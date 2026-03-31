# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Custom Resource Lambda — provisions Bedrock KB with S3 Vectors.

Creates: S3 Vector Bucket → Vector Index → Bedrock KB → S3 DataSource → SSM Parameter.
Deletes in reverse order.
"""

import json
import os
import time
import urllib.request

import boto3

bedrock = boto3.client("bedrock-agent")
s3vectors = boto3.client("s3vectors")
ssm = boto3.client("ssm")


def send_response(event: dict, context: object, status: str,
                  data: dict | None = None, reason: str = "") -> None:
    """Send CloudFormation custom resource response.

    Args:
        event: CFn custom resource event.
        context: Lambda context.
        status: SUCCESS or FAILED.
        data: Optional response data dict.
        reason: Failure reason string.
    """
    physical_id = (data or {}).get(
        "KnowledgeBaseId", event.get("PhysicalResourceId", "none"),
    )
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch: {context.log_stream_name}",
        "PhysicalResourceId": physical_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }).encode("utf-8")

    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT")
    req.add_header("Content-Type", "")
    urllib.request.urlopen(req)  # nosec B310


def _create(props: dict) -> str:
    """Create S3 Vector Bucket, Index, KB, DataSource, and SSM param.

    Args:
        props: ResourceProperties from CloudFormation event.

    Returns:
        Knowledge Base ID.
    """
    vb_name = props["VectorBucketName"]
    region = props["Region"]
    dimension = int(props.get("EmbeddingDimension", "1024"))

    # Step 1: Get or create vector bucket
    try:
        vb_resp = s3vectors.get_vector_bucket(vectorBucketName=vb_name)
        print(f"get_vector_bucket response: {json.dumps(vb_resp, default=str)}")
        vb_arn = vb_resp.get("vectorBucket", {}).get("vectorBucketArn", "")
    except Exception:
        vb_resp = s3vectors.create_vector_bucket(vectorBucketName=vb_name)
        print(f"create_vector_bucket response: {json.dumps(vb_resp, default=str)}")
        vb_arn = vb_resp.get("vectorBucketArn", "")

    # Fallback: construct ARN if API didn't return it (boto3 version issue)
    if not vb_arn:
        account = boto3.client("sts").get_caller_identity()["Account"]
        vb_arn = f"arn:aws:s3vectors:{region}:{account}:bucket/{vb_name}"
        print(f"Constructed ARN fallback: {vb_arn}")

    if not vb_arn:
        raise ValueError(f"Could not get vectorBucketArn: {json.dumps(vb_resp, default=str)}")

    # Step 2: Create vector index
    index_name = f"{props['KbName']}-index"
    try:
        s3vectors.create_index(
            vectorBucketName=vb_name,
            indexName=index_name,
            dataType="float32",
            dimension=dimension,
            distanceMetric="cosine",
            metadataConfiguration={
                "nonFilterableMetadataKeys": [
                    "AMAZON_BEDROCK_TEXT",
                    "AMAZON_BEDROCK_METADATA",
                ],
            },
        )
    except Exception as e:
        if "already exists" not in str(e).lower() and "Conflict" not in str(e):
            raise

    # Step 3: Create Knowledge Base
    kb_resp = bedrock.create_knowledge_base(
        name=props["KbName"],
        roleArn=props["RoleArn"],
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": (
                    f"arn:aws:bedrock:{region}::foundation-model/"
                    "amazon.titan-embed-text-v2:0"
                ),
            },
        },
        storageConfiguration={
            "type": "S3_VECTORS",
            "s3VectorsConfiguration": {
                "vectorBucketArn": vb_arn,
                "indexName": index_name,
            },
        },
    )
    kb_id = kb_resp["knowledgeBase"]["knowledgeBaseId"]

    # Wait for KB ACTIVE
    for _ in range(30):
        status = bedrock.get_knowledge_base(
            knowledgeBaseId=kb_id,
        )["knowledgeBase"]["status"]
        if status == "ACTIVE":
            break
        time.sleep(2)

    # Step 4: Create S3 Data Source
    bedrock.create_data_source(
        knowledgeBaseId=kb_id,
        name=f"{props['KbName']}-ds",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": props["DataSourceBucketArn"],
                "inclusionPrefixes": ["kb-source/"],
            },
        },
    )

    # Step 5: SSM Parameter
    ssm_param = os.environ.get("SSM_KB_ID_PARAM", "")
    if ssm_param:
        ssm.put_parameter(
            Name=ssm_param, Value=kb_id, Type="String", Overwrite=True,
        )

    return kb_id


def _delete(props: dict, kb_id: str) -> None:
    """Delete DataSource, KB, Vector Index, and Vector Bucket.

    Args:
        props: ResourceProperties from CloudFormation event.
        kb_id: Knowledge Base ID to delete.
    """
    if not kb_id or kb_id == "none":
        return

    # Delete data sources
    try:
        ds_resp = bedrock.list_data_sources(knowledgeBaseId=kb_id)
        for ds in ds_resp.get("dataSourceSummaries", []):
            bedrock.delete_data_source(
                knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"],
            )
    except Exception:
        pass

    try:
        bedrock.delete_knowledge_base(knowledgeBaseId=kb_id)
    except Exception:
        pass

    vb_name = props.get("VectorBucketName", "")
    if vb_name:
        try:
            s3vectors.delete_index(
                vectorBucketName=vb_name,
                indexName=f"{props['KbName']}-index",
            )
        except Exception:
            pass
        try:
            s3vectors.delete_vector_bucket(vectorBucketName=vb_name)
        except Exception:
            pass


def handler(event: dict, context: object) -> None:
    """Handle Create/Update/Delete for Bedrock KB with S3 Vectors.

    ResourceProperties:
        KbName: Knowledge base name.
        RoleArn: KB execution role ARN.
        VectorBucketName: S3 Vector Bucket name.
        DataSourceBucketArn: Regular S3 bucket ARN for data source.
        Region: AWS region.
        EmbeddingDimension: Embedding vector dimension (default 1024).

    Args:
        event: CloudFormation custom resource event.
        context: Lambda context.
    """
    request_type = event["RequestType"]
    props = event["ResourceProperties"]
    print(f"RequestType={request_type}, Props={json.dumps(props)}")

    try:
        if request_type == "Create":
            kb_id = _create(props)
            send_response(event, context, "SUCCESS", {"KnowledgeBaseId": kb_id})

        elif request_type == "Update":
            kb_id = event["PhysicalResourceId"]
            ssm_param = os.environ.get("SSM_KB_ID_PARAM", "")
            if ssm_param and kb_id and kb_id != "none":
                ssm.put_parameter(
                    Name=ssm_param, Value=kb_id, Type="String", Overwrite=True,
                )
            send_response(event, context, "SUCCESS", {"KnowledgeBaseId": kb_id})

        elif request_type == "Delete":
            _delete(props, event["PhysicalResourceId"])
            send_response(event, context, "SUCCESS")

    except Exception as e:
        print(f"Error: {e}")
        send_response(event, context, "FAILED", reason=str(e))
