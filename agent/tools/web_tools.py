# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent tool for fetching web pages as clean Markdown."""

import html2text
import requests
from strands import tool


@tool
def web_fetch(url: str, max_chars: int = 20000, start: int = 0) -> str:
    """Fetch a web page and return its content as clean Markdown.

    Use this tool when you need to read the contents of a specific URL.
    For long pages, use 'start' to paginate through the content.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return (default 20000).
        start: Character offset to start from, for reading continuation.

    Returns:
        Markdown-formatted page content, with a truncation notice if applicable.
    """
    response = requests.get(
        url=url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; sdpm-agent/1.0)"},
    )
    response.raise_for_status()

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0  # no line wrapping
    markdown = h.handle(response.text)

    total = len(markdown)
    chunk = markdown[start : start + max_chars]
    end = start + len(chunk)

    if end < total:
        chunk += f"\n\n---\n[Truncated: showing chars {start}-{end} of {total}. Use start={end} to continue.]"

    return chunk
