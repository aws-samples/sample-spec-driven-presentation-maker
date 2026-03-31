# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Custom Resource: Bedrock Model Invocation Logging.

Configures Model Invocation Logging → CloudWatch Logs + S3.
This is an API-only operation with no CloudFormation native resource.

NOTE: This is an account-level setting (one per region). On stack deletion,
logging is intentionally NOT disabled to avoid disrupting other services.
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
            _enable_model_invocation_logging(props)
        # Delete: intentionally no-op (account-level setting, don't disrupt other services)

        _send_response(event, "SUCCESS")
    except Exception as e:
        logger.exception("Custom resource failed")
        _send_response(event, "FAILED", reason=str(e))

    return {}


def _enable_model_invocation_logging(props: dict) -> None:
    """Enable Bedrock Model Invocation Logging to CloudWatch Logs and S3.

    Args:
        props: Resource properties containing LogGroupName, S3BucketName,
               S3Prefix, and BedrockRoleArn.
    """
    client = boto3.client("bedrock")

    log_group_name = props["LogGroupName"]
    s3_bucket = props["S3BucketName"]
    s3_prefix = props.get("S3Prefix", "bedrock-logs")
    role_arn = props["BedrockRoleArn"]

    config = {
        "cloudWatchConfig": {
            "logGroupName": log_group_name,
            "roleArn": role_arn,
            "largeDataDeliveryS3Config": {
                "bucketName": s3_bucket,
                "keyPrefix": f"{s3_prefix}/large-data",
            },
        },
        "s3Config": {
            "bucketName": s3_bucket,
            "keyPrefix": s3_prefix,
        },
        "textDataDeliveryEnabled": True,
        "imageDataDeliveryEnabled": False,
        "embeddingDataDeliveryEnabled": False,
    }

    client.put_model_invocation_logging_configuration(loggingConfig=config)
    logger.info("Model invocation logging enabled: log_group=%s s3=%s/%s", log_group_name, s3_bucket, s3_prefix)


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
        "PhysicalResourceId": event.get("PhysicalResourceId", "bedrock-logging-config"),
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
