# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Custom Resource: CloudWatch Transaction Search enablement.

Switches X-Ray trace segment ingestion to CloudWatch Logs (the `aws/spans`
log group), enabling GenAI Observability span queries — e.g. per-user token
usage via `attributes.user.id` × `attributes.gen_ai.usage.*`.

This is an account-level setting (one per region) with no CloudFormation
native resource. Behavior:
- Create/Update: skipped if Transaction Search is already enabled (idempotent).
  The default trace-summary indexing rule (1%) is left untouched — span
  ingestion into `aws/spans` is always 100%, so measurement accuracy is
  unaffected.
- Delete: intentionally NOT reverted to avoid disrupting other services.
"""

import json
import logging
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context: object) -> dict:
    """CloudFormation Custom Resource handler.

    Args:
        event: CloudFormation Custom Resource event (Create/Update/Delete).
        context: Lambda context object.

    Returns:
        CloudFormation response dict.
    """
    request_type = event["RequestType"]
    props = event["ResourceProperties"]

    try:
        if request_type in ("Create", "Update"):
            _enable_transaction_search(props)
        # Delete: intentionally no-op (account-level setting, don't disrupt other services)

        _send_response(event, "SUCCESS")
    except Exception as e:
        logger.exception("Custom resource failed")
        _send_response(event, "FAILED", reason=str(e))

    return {}


def _enable_transaction_search(props: dict) -> None:
    """Enable Transaction Search: X-Ray trace segments → CloudWatch Logs.

    Follows the documented API sequence (AgentCore Observability getting
    started): logs resource policy for X-Ray span delivery, then switch the
    trace segment destination to CloudWatchLogs.

    Args:
        props: Resource properties containing AccountId, Region, Partition.
    """
    xray = boto3.client("xray")
    logs_client = boto3.client("logs")

    # Idempotency: skip if already enabled (matches "skipped if already
    # configured" semantics — never clobber an existing account setup).
    current = xray.get_trace_segment_destination()
    if current.get("Destination") == "CloudWatchLogs":
        logger.info(
            "Transaction Search already enabled (status=%s) — skipping",
            current.get("Status"),
        )
        return

    account_id = props["AccountId"]
    region = props["Region"]
    partition = props.get("Partition", "aws")

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TransactionSearchXRayAccess",
                "Effect": "Allow",
                "Principal": {"Service": "xray.amazonaws.com"},
                "Action": "logs:PutLogEvents",
                "Resource": [
                    f"arn:{partition}:logs:{region}:{account_id}:log-group:aws/spans:*",
                    f"arn:{partition}:logs:{region}:{account_id}:log-group:/aws/application-signals/data:*",
                ],
                "Condition": {
                    "ArnLike": {"aws:SourceArn": f"arn:{partition}:xray:{region}:{account_id}:*"},
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            }
        ],
    }
    logs_client.put_resource_policy(
        policyName="SdpmTransactionSearchXRayAccess",
        policyDocument=json.dumps(policy),
    )
    xray.update_trace_segment_destination(Destination="CloudWatchLogs")
    logger.info("Transaction Search enabled: trace segment destination → CloudWatch Logs")


def _send_response(event: dict, status: str, reason: str = "") -> None:
    """Send response to CloudFormation.

    Args:
        event: Original CloudFormation event.
        status: SUCCESS or FAILED.
        reason: Failure reason (empty for success).
    """
    body = json.dumps({
        "Status": status,
        "Reason": reason or "See CloudWatch logs",
        "PhysicalResourceId": event.get("PhysicalResourceId", "transaction-search-config"),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
    }).encode("utf-8")

    req = urllib.request.Request(
        url=event["ResponseURL"],
        data=body,
        headers={"Content-Type": ""},
        method="PUT",
    )
    urllib.request.urlopen(req)  # nosec B310
