# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Secure URL fetcher with DNS rebinding / SSRF protection (Phase 0-6 / R4b).

Security contract:
- Resolve all A/AAAA records; reject if ANY is private/loopback/link-local/reserved
- Pin validated public IP for the actual connection (no re-resolve)
- TLS SNI and hostname verification use the original hostname
- Each redirect hop re-resolves and re-validates (no downgrade HTTPS→HTTP)
- No cookies/auth forwarded between hops
- Stream with body size limits and timeouts
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPResponse
from typing import BinaryIO
from urllib.parse import urlparse

from sdpm.tools.attachment.errors import SourceLimitExceeded, SourceValidationError, SSRFBlocked
from sdpm.tools.attachment.limits import (
    CONNECT_TIMEOUT_S,
    IDLE_READ_TIMEOUT_S,
    MAX_BODY_BYTES,
    MAX_REDIRECTS,
    MAX_RESPONSE_HEADER_BYTES,
    TOTAL_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

# Private/reserved IP ranges to block
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),        # "This" network
    ipaddress.ip_network("10.0.0.0/8"),        # Private
    ipaddress.ip_network("100.64.0.0/10"),     # Carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / IMDS
    ipaddress.ip_network("172.16.0.0/12"),     # Private
    ipaddress.ip_network("192.0.0.0/24"),      # IETF Protocol
    ipaddress.ip_network("192.0.2.0/24"),      # Documentation
    ipaddress.ip_network("192.88.99.0/24"),    # 6to4 Relay
    ipaddress.ip_network("192.168.0.0/16"),    # Private
    ipaddress.ip_network("198.18.0.0/15"),     # Benchmark
    ipaddress.ip_network("198.51.100.0/24"),   # Documentation
    ipaddress.ip_network("203.0.113.0/24"),    # Documentation
    ipaddress.ip_network("224.0.0.0/4"),       # Multicast
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
    # IPv6
    ipaddress.ip_network("::1/128"),           # Loopback
    ipaddress.ip_network("fc00::/7"),          # ULA
    ipaddress.ip_network("fe80::/10"),         # Link-local
    ipaddress.ip_network("ff00::/8"),          # Multicast
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped (check inner)
    ipaddress.ip_network("2001:db8::/32"),     # Documentation
]


@dataclass
class FetchResult:
    """Result of a secure URL fetch."""

    data: bytes
    final_url: str
    content_type: str | None = None
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    filename_from_header: str | None = None
    not_modified: bool = False


@dataclass
class FetchRequest:
    """Parameters for a URL fetch."""

    url: str
    max_bytes: int = MAX_BODY_BYTES
    stream_to: BinaryIO | None = None  # If provided, stream to this instead of memory


def _is_private_ip(addr: str) -> bool:
    """Check if an IP address is in a blocked/private range."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # Invalid = blocked

    # Check IPv4-mapped IPv6 addresses
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    for network in _BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


def _resolve_and_validate(hostname: str) -> list[str]:
    """Resolve hostname and validate all IPs are public.

    Returns list of validated public IP addresses.
    Raises SSRFBlocked if any resolved IP is private/reserved.
    """
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SourceValidationError(f"DNS resolution failed for {hostname}: {e}")

    if not addrinfos:
        raise SourceValidationError(f"No DNS records for {hostname}")

    ips: list[str] = []
    for family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            raise SSRFBlocked(
                f"DNS for {hostname} resolved to private/reserved IP {ip}"
            )
        ips.append(ip)

    return ips


def _validate_url(url: str) -> tuple[str, str, int, str]:
    """Validate URL scheme, port, and structure.

    Returns (scheme, hostname, port, path).
    """
    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        raise SourceValidationError(f"Unsupported URL scheme: {parsed.scheme}")

    # No credentials
    if parsed.username or parsed.password:
        raise SourceValidationError("URLs with credentials are not allowed")

    # No fragment
    if parsed.fragment:
        raise SourceValidationError("URLs with fragments are not allowed")

    # Control chars / NUL
    if any(ord(c) < 0x20 or c == "\x7f" for c in url):
        raise SourceValidationError("URL contains control characters")

    hostname = parsed.hostname
    if not hostname:
        raise SourceValidationError("URL has no hostname")

    # Port check: only 80/443
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if port not in (80, 443):
        raise SourceValidationError(f"Only ports 80/443 allowed, got {port}")

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    return parsed.scheme, hostname, port, path


def _extract_filename_from_headers(response: HTTPResponse) -> str | None:
    """Extract filename from Content-Disposition header (RFC 5987)."""
    cd = response.getheader("Content-Disposition")
    if not cd:
        return None

    # Try filename* first (RFC 5987)
    import re
    match = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)?''(.+?)(?:;|$)", cd)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))

    # Try quoted filename
    match = re.search(r'filename\s*=\s*"([^"]+)"', cd)
    if match:
        return match.group(1)

    # Try unquoted filename
    match = re.search(r'filename\s*=\s*([^\s;]+)', cd)
    if match:
        return match.group(1)

    return None


def fetch_url(
    url: str,
    *,
    max_bytes: int = MAX_BODY_BYTES,
    etag: str | None = None,
    last_modified: str | None = None,
) -> FetchResult:
    """Securely fetch a URL with full SSRF protection.

    Args:
        url: The URL to fetch.
        max_bytes: Maximum response body size.

    Returns:
        FetchResult with data and metadata.

    Raises:
        SSRFBlocked: If URL targets private/reserved IP.
        SourceValidationError: On invalid URL or network errors.
        SourceLimitExceeded: If response exceeds max_bytes.
    """
    for validator in (etag, last_modified):
        if validator is not None and (len(validator) > 1024 or "\r" in validator or "\n" in validator):
            raise SourceValidationError("Invalid conditional URL validator")

    start_time = time.monotonic()
    current_url = url
    visited: set[str] = set()

    for redirect_count in range(MAX_REDIRECTS + 1):
        elapsed = time.monotonic() - start_time
        if elapsed >= TOTAL_TIMEOUT_S:
            raise SourceValidationError(f"Total timeout ({TOTAL_TIMEOUT_S}s) exceeded")

        if current_url in visited:
            raise SourceValidationError(f"Redirect loop detected: {current_url}")
        visited.add(current_url)

        scheme, hostname, port, path = _validate_url(current_url)

        # Resolve and validate all IPs
        valid_ips = _resolve_and_validate(hostname)
        # Pick first valid IP for connection
        target_ip = valid_ips[0]

        remaining_timeout = TOTAL_TIMEOUT_S - (time.monotonic() - start_time)
        connect_timeout = min(CONNECT_TIMEOUT_S, remaining_timeout)

        try:
            if scheme == "https":
                # Create SSL context with hostname verification
                ctx = ssl.create_default_context()
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                # HTTPConnection supplies HTTP framing; the socket is explicitly
                # pinned and TLS-wrapped here so DNS cannot be resolved again.
                conn = HTTPConnection(target_ip, port, timeout=connect_timeout)
                import socket as _socket
                raw_sock = _socket.create_connection(
                    (target_ip, port), timeout=connect_timeout
                )
                conn.sock = ctx.wrap_socket(raw_sock, server_hostname=hostname)
            else:
                conn = HTTPConnection(target_ip, port, timeout=connect_timeout)
                conn.connect()

            # Send request with original Host header
            headers = {
                "Host": hostname,
                "Accept-Encoding": "identity",
                "User-Agent": "sdpm-attachment-fetcher/1.0",
                "Connection": "close",
            }
            if redirect_count == 0:
                if etag:
                    headers["If-None-Match"] = etag
                if last_modified:
                    headers["If-Modified-Since"] = last_modified
            conn.request("GET", path, headers=headers)

            read_timeout = min(IDLE_READ_TIMEOUT_S, TOTAL_TIMEOUT_S - (time.monotonic() - start_time))
            conn.sock.settimeout(read_timeout)  # type: ignore[union-attr]

            response = conn.getresponse()
            header_bytes = sum(
                len(name.encode("latin-1")) + len(value.encode("latin-1")) + 4
                for name, value in response.getheaders()
            )
            if header_bytes > MAX_RESPONSE_HEADER_BYTES:
                conn.close()
                raise SourceLimitExceeded(
                    f"Response headers exceed {MAX_RESPONSE_HEADER_BYTES} bytes"
                )

        except (OSError, ssl.SSLError, TimeoutError) as e:
            raise SourceValidationError(f"Connection failed to {hostname}: {e}")

        if response.status == 304 and redirect_count == 0 and (etag or last_modified):
            conn.close()
            return FetchResult(
                data=b"",
                final_url=current_url,
                etag=response.getheader("ETag") or etag,
                last_modified=response.getheader("Last-Modified") or last_modified,
                not_modified=True,
            )

        # Handle redirects
        if response.status in (301, 302, 303, 307, 308):
            if redirect_count >= MAX_REDIRECTS:
                raise SourceValidationError(f"Too many redirects (max {MAX_REDIRECTS})")

            location = response.getheader("Location")
            if not location:
                raise SourceValidationError("Redirect without Location header")

            # Resolve relative URLs using urljoin (handles both absolute and relative)
            from urllib.parse import urljoin
            location = urljoin(current_url, location)

            # Check HTTPS downgrade
            new_scheme = urlparse(location).scheme
            if scheme == "https" and new_scheme == "http":
                raise SourceValidationError("HTTPS to HTTP downgrade not allowed")

            current_url = location
            conn.close()
            continue

        # Check response status
        if response.status != 200:
            conn.close()
            raise SourceValidationError(f"HTTP {response.status} from {hostname}")

        # Check Content-Length before downloading
        content_length_str = response.getheader("Content-Length")
        content_length: int | None = None
        if content_length_str:
            try:
                content_length = int(content_length_str)
            except ValueError:
                pass
            if content_length is not None and content_length > max_bytes:
                conn.close()
                raise SourceLimitExceeded(
                    f"Content-Length {content_length} exceeds limit {max_bytes}"
                )

        # Stream body with size limit
        chunks: list[bytes] = []
        total_read = 0
        while True:
            remaining = TOTAL_TIMEOUT_S - (time.monotonic() - start_time)
            if remaining <= 0:
                conn.close()
                raise SourceValidationError(f"Total timeout ({TOTAL_TIMEOUT_S}s) exceeded during read")

            conn.sock.settimeout(min(IDLE_READ_TIMEOUT_S, remaining))  # type: ignore[union-attr]
            chunk = response.read(65536)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > max_bytes:
                conn.close()
                raise SourceLimitExceeded(
                    f"Response body exceeds limit {max_bytes} bytes"
                )
            chunks.append(chunk)

        conn.close()
        data = b"".join(chunks)

        # Extract metadata
        content_type = response.getheader("Content-Type")
        if content_type:
            content_type = content_type.split(";")[0].strip()

        return FetchResult(
            data=data,
            final_url=current_url,
            content_type=content_type,
            content_length=len(data),
            etag=response.getheader("ETag"),
            last_modified=response.getheader("Last-Modified"),
            filename_from_header=_extract_filename_from_headers(response),
        )

    raise SourceValidationError(f"Too many redirects (max {MAX_REDIRECTS})")
