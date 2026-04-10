# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Agent tools for reading uploaded files.

Uploaded files are stored in S3 with server-side encryption and scoped per user.
Presigned URLs provide time-limited access.

Agent tools for reading uploaded files and listing uploads in a session."""

import json
import os

import boto3
from strands import tool


def _get_table():
    """Get the DynamoDB Table resource for decks.

    Returns:
        boto3 DynamoDB Table resource.

    Raises:
        ValueError: If DECKS_TABLE environment variable is not set.
    """
    table_name = os.environ.get("DECKS_TABLE")
    if not table_name:
        raise ValueError("DECKS_TABLE environment variable is not set")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


@tool
def read_uploaded_file(upload_id: str) -> str:
    """Read the extracted text content from an uploaded file.

    Use this when the user has attached a file and you need to read its contents.
    For images (PNG), this returns a presigned URL for Bedrock Vision analysis.

    Args:
        upload_id: The upload identifier provided in the [Attached: ...] message.

    Returns:
        Extracted text content, or an error/status message.
    """
    # Get user_id from module-level state (set by basic_agent.py)
    from tools.deck_tools import _current_user_id

    table = _get_table()
    resp = table.get_item(Key={"PK": f"USER#{_current_user_id}", "SK": f"UPLOAD#{upload_id}"})
    item = resp.get("Item")

    if not item:
        return f"Error: Upload {upload_id} not found."

    status = item.get("status", "unknown")
    if status == "processing":
        return "File is still being processed. Please wait a moment and try again."
    if status == "failed":
        return "File processing failed. The user may need to re-upload."
    if status == "uploading":
        return "File is still uploading."

    # Return inline extracted text if available
    # For PPTX uploads, prefer slide JSON structure over plain text
    slide_json_key = item.get("slideJsonS3Key")
    if slide_json_key:
        try:
            bucket = os.environ.get("PPTX_BUCKET")
            region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
            s3_client = boto3.client("s3", region_name=region)
            obj = s3_client.get_object(Bucket=bucket, Key=slide_json_key)
            slide_json = obj["Body"].read().decode("utf-8")
            file_name = item.get("fileName", "unknown")
            return f"## Slide JSON of {file_name}\n\n{slide_json}"
        except Exception:
            pass  # Fall through to text extraction

    extracted_text = item.get("extractedText")
    if extracted_text:
        file_name = item.get("fileName", "unknown")
        return f"## Content of {file_name}\n\n{extracted_text}"

    # For images, return presigned URL
    file_type = item.get("fileType", "")
    if file_type.startswith("image/") or file_type in (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/pdf",
    ):
        s3_key = item.get("s3KeyRaw")
        if s3_key:
            bucket = os.environ.get("PPTX_BUCKET")
            region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
            s3_client = boto3.client("s3", region_name=region)
            url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": s3_key},
                ExpiresIn=900,
            )
            file_name = item.get("fileName", "unknown")
            if file_type.startswith("image/"):
                return f"Image file: {file_name}. Presigned URL: {url}"
            return f"Binary file: {file_name} ({file_type}). Use init_deck with this presigned URL to convert: {url}"

    # Try reading from S3 extracted key
    s3_key_extracted = item.get("s3KeyExtracted")
    if s3_key_extracted:
        bucket = os.environ.get("PPTX_BUCKET")
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        s3_client = boto3.client("s3", region_name=region)
        obj = s3_client.get_object(Bucket=bucket, Key=s3_key_extracted)
        text = obj["Body"].read().decode("utf-8")
        file_name = item.get("fileName", "unknown")
        return f"## Content of {file_name}\n\n{text}"

    return f"No extracted content available for upload {upload_id}."


@tool
def list_uploads(session_id: str) -> str:
    """List all uploaded files in the current chat session.

    Use this to see what files the user has uploaded in this conversation.

    Args:
        session_id: The current chat session ID.

    Returns:
        JSON list of uploads with their status and file names.
    """
    from tools.deck_tools import _current_user_id

    table = _get_table()

    # Query all uploads for this user and filter by sessionId
    resp = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{_current_user_id}",
            ":prefix": "UPLOAD#",
        },
    )

    uploads = []
    for item in resp.get("Items", []):
        if item.get("sessionId") == session_id:
            uploads.append({
                "uploadId": item["SK"].replace("UPLOAD#", ""),
                "fileName": item.get("fileName", ""),
                "fileType": item.get("fileType", ""),
                "status": item.get("status", "unknown"),
            })

    if not uploads:
        return "No files have been uploaded in this session."

    return json.dumps(uploads, ensure_ascii=False)
