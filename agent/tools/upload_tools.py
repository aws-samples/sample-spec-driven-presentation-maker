# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Agent tools for listing uploads in a session.

File reading is handled by the MCP server's read_uploaded_file tool,
which supports multimodal responses (ImageContent for images/PDFs)."""

import json
import os

import boto3
from strands import tool

# Module-level state — set by basic_agent.py before tool invocation
_current_user_id: str = ""


def _get_table():
    """Get the DynamoDB Table resource for decks."""
    table_name = os.environ.get("DECKS_TABLE")
    if not table_name:
        raise ValueError("DECKS_TABLE environment variable is not set")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


@tool
def list_uploads(session_id: str) -> str:
    """List all uploaded files in the current chat session.

    Use this to see what files the user has uploaded in this conversation.

    Args:
        session_id: The current chat session ID.

    Returns:
        JSON list of uploads with their status and file names.
    """
    table = _get_table()

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
