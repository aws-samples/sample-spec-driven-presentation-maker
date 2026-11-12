# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent's web_fetch applies the MCP fetcher's URL check (review finding F4).

DNS and HTTP are faked at the fetcher's socket / HTTPConnection seams, so the tests run
the real check, redirect handling and IP pinning without touching the network. IP
literals go through the real getaddrinfo, which parses them without a lookup.
"""

import importlib.util
import io
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_WEB_TOOLS = Path(__file__).resolve().parents[1] / "agent" / "tools" / "web_tools.py"
_PUBLIC_IP = "93.184.216.34"
_REAL_GETADDRINFO = socket.getaddrinfo


@pytest.fixture(scope="module")
def web_fetch():
    # Loaded by path: agent/tools would shadow servers/remote's top-level tools package.
    spec = importlib.util.spec_from_file_location("agent_web_tools", _WEB_TOOLS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.web_fetch


class _Response:
    def __init__(self, status, headers, body=b""):
        self.status = status
        self._headers = headers
        self._body = io.BytesIO(body)

    def getheaders(self):
        return list(self._headers.items())

    def getheader(self, name, default=None):
        return next((v for k, v in self._headers.items() if k.lower() == name.lower()), default)

    def read(self, size):
        return self._body.read(size)

    def isclosed(self):
        return False


class _Network:
    """Fake DNS (hostname -> list of answers, consumed in order) and HTTP (by Host, path)."""

    def __init__(self, dns=None, routes=None):
        self.dns = {host: list(answers) for host, answers in (dns or {}).items()}
        self.routes = routes or {}
        self.connections = []
        self.requests = []

    def getaddrinfo(self, host, *args, **kwargs):
        if host not in self.dns:
            return _REAL_GETADDRINFO(host, *args, **kwargs)
        answers = self.dns[host]
        ips = answers.pop(0) if len(answers) > 1 else answers[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips.split(",")]

    def connection(self, ip, port, timeout=None):
        network = self

        class _Connection:
            sock = MagicMock()

            def connect(self):
                network.connections.append((ip, port))

            def request(self, method, path, headers):
                self.key = (headers["Host"], path)
                network.requests.append((ip, path, headers))

            def getresponse(self):
                return _Response(*network.routes[self.key])

            def close(self):
                pass

        return _Connection()

    def __enter__(self):
        self._patches = [
            patch("socket.getaddrinfo", side_effect=self.getaddrinfo),
            patch("sdpm.tools.attachment.fetcher.HTTPConnection", side_effect=self.connection),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _text(result):
    assert isinstance(result, dict) and result["status"] == "error", result
    return result["content"][0]["text"]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://[::1]/",
    "http://2130706433/",                     # 127.0.0.1 as a decimal literal
    "http://169.254.169.254/latest/meta-data/",  # instance metadata (IPv4)
    "http://[fd00:ec2::254]/latest/meta-data/",  # instance metadata (IPv6)
    "http://10.1.2.3/",
    "http://192.168.0.1/",
    "http://[::ffff:127.0.0.1]/",
])
def test_blocks_non_public_ip_literals(web_fetch, url):
    with _Network() as net:
        text = _text(web_fetch(url=url))
    assert text.startswith(f"Blocked {url}:")
    assert net.connections == []


@pytest.mark.parametrize("url, reason", [
    ("file:///etc/passwd", "Unsupported URL scheme: file"),
    ("ftp://example.com/file", "Unsupported URL scheme: ftp"),
    ("http://example.com:8080/", "Only ports 80/443 allowed"),
])
def test_rejects_unsafe_schemes_and_ports(web_fetch, url, reason):
    with _Network(dns={"example.com": [_PUBLIC_IP]}) as net:
        text = _text(web_fetch(url=url))
    assert text.startswith(f"Could not fetch {url}: {reason}")
    assert net.connections == []


@pytest.mark.parametrize("answer", ["10.0.0.5", "169.254.169.254", "127.0.0.1", f"{_PUBLIC_IP},127.0.0.1"])
def test_blocks_hostnames_resolving_to_private_addresses(web_fetch, answer):
    with _Network(dns={"internal.example.com": [answer]}) as net:
        text = _text(web_fetch(url="http://internal.example.com/"))
    assert text.startswith("Blocked http://internal.example.com/:")
    assert net.connections == []


@pytest.mark.parametrize("location", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1/",
    "http://internal.example.com/admin",
])
def test_blocks_redirects_to_private_targets(web_fetch, location):
    dns = {"example.com": [_PUBLIC_IP], "internal.example.com": ["10.0.0.5"]}
    routes = {("example.com", "/"): (302, {"Location": location})}
    with _Network(dns=dns, routes=routes) as net:
        text = _text(web_fetch(url="http://example.com/"))
    assert text.startswith("Blocked http://example.com/:")
    assert net.connections == [(_PUBLIC_IP, 80)]


def test_fetches_public_url(web_fetch):
    body = "<h1>こんにちは</h1><p>public page</p>".encode()
    routes = {("example.com", "/page"): (200, {"Content-Type": "text/html; charset=utf-8"}, body)}
    with _Network(dns={"example.com": [_PUBLIC_IP]}, routes=routes) as net:
        result = web_fetch(url="http://example.com/page#section")
    assert isinstance(result, str)
    assert "# こんにちは" in result and "public page" in result
    assert net.connections == [(_PUBLIC_IP, 80)]
    ip, path, headers = net.requests[0]
    assert path == "/page"  # the fragment stays on the client
    assert headers["User-Agent"] == "Mozilla/5.0 (compatible; sdpm-agent/1.0)"


def test_follows_redirect_between_public_urls_and_detects_charset(web_fetch):
    body = "<p>日本語のページです。文字コードの宣言がありません。</p>".encode()
    routes = {
        ("example.com", "/old"): (301, {"Location": "/new"}),
        ("example.com", "/new"): (200, {"Content-Type": "text/html"}, body),
    }
    with _Network(dns={"example.com": [_PUBLIC_IP]}, routes=routes):
        result = web_fetch(url="http://example.com/old")
    assert "日本語のページです。" in result


def test_connection_is_pinned_to_the_checked_address(web_fetch):
    """A second DNS answer (rebinding to loopback) never reaches the connection."""
    routes = {("rebind.example.com", "/"): (200, {"Content-Type": "text/html"}, b"<p>ok</p>")}
    with _Network(dns={"rebind.example.com": [_PUBLIC_IP, "127.0.0.1"]}, routes=routes) as net:
        result = web_fetch(url="http://rebind.example.com/")
    assert "ok" in result
    assert net.connections == [(_PUBLIC_IP, 80)]
