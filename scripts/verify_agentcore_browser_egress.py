# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Egress canary for the HTML browser check on AgentCore Browser.

AgentCore Browser has internet access, so the check fails every http(s) / ws(s) request
through the Fetch domain and removes WebRTC before deck code runs. This script runs the
same check the remote server runs (``tools.agentcore_browser.make_source`` registered as
the browser source, ``sdpm.api.refresh_html``) on a canary deck whose slides try to get
out:

- ``rtc``: looks for ``RTCPeerConnection`` in the top window, a fresh iframe
  (``window[n]`` and ``contentWindow``) and a srcdoc iframe, and starts ICE gathering
  against a public STUN server, reporting any ``srflx`` candidate (a reflexive address
  means a UDP packet left the browser);
- ``net``: an image and a fetch to https://example.com;
- ``dns`` (with ``--dns-domain D``): ``dns-prefetch`` / ``preconnect`` hints to a
  one-off ``<nonce>.D``; look the nonce up in that domain's query log afterwards.

Exit 0 only when the check reports ``network_blocked: true``, the ``rtc`` slide ran and
no window exposed WebRTC and no ``srflx`` candidate appeared. Without ``--dns-domain``
DNS egress is not verified.

Run (dev account credentials in the environment):
    AWS_DEFAULT_REGION=ap-northeast-1 uv run python scripts/verify_agentcore_browser_egress.py --region ap-northeast-1
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "servers" / "remote"), str(ROOT / "sdpm")]

from sdpm import api  # noqa: E402
from sdpm.engine.html.browser import register_browser_source  # noqa: E402
from tools.agentcore_browser import make_source  # noqa: E402

STUN = "stun:stun.l.google.com:19302"

RTC_SLIDE = """<section data-layout="Title Only"><h1 data-ph="title">WebRTC</h1>
<script>
(function(){
var n = 0;
function check(w, where){ n++;
  if (w && typeof w.RTCPeerConnection !== 'undefined') console.error('sdpm slide rtc: available ' + where); }
check(window, 'top');
var f = document.createElement('iframe'); document.body.appendChild(f);
check(window[window.length - 1], 'window[n]');
check(f.contentWindow, 'iframe');
var s = document.createElement('iframe'); document.body.appendChild(s);
s.onload = function(){ check(window[window.length - 1], 'srcdoc window[n]'); check(s.contentWindow, 'srcdoc');
  console.error('sdpm slide rtc: probed ' + n); };
s.srcdoc = '<p>x</p>';
try {
  var pc = new RTCPeerConnection({iceServers: [{urls: '%(stun)s'}]});
  pc.createDataChannel('x');
  pc.onicecandidate = function(e){
    if (e.candidate && / srflx /.test(e.candidate.candidate)) console.error('sdpm slide rtc: srflx ' + e.candidate.candidate); };
  pc.createOffer().then(function(o){ return pc.setLocalDescription(o); });
  console.error('sdpm slide rtc: available constructor');
} catch (e) { /* RTCPeerConnection removed: expected */ }
})();
</script></section>
""" % {"stun": STUN}

NET_SLIDE = """<section data-layout="Title Only"><h1 data-ph="title">Network</h1>
<script>
new Image().src = 'https://example.com/sdpm-canary.png';
fetch('https://example.com/sdpm-canary').catch(function(){});
</script></section>
"""

DNS_SLIDE = """<section data-layout="Title Only"><h1 data-ph="title">DNS</h1>
<link rel="dns-prefetch" href="//%(host)s">
<link rel="preconnect" href="https://%(host)s">
</section>
"""


def _build(deck: Path, dns_host: str | None) -> list[str]:
    api.init("egress-canary", output_dir=deck, output_format="html")
    styled = api.apply_style(deck, style="typographic", template="blank-dark")
    if styled.get("status") != "ok":
        raise SystemExit(f"apply_style failed: {styled}")
    slides = {"rtc": RTC_SLIDE, "net": NET_SLIDE}
    if dns_host:
        slides["dns"] = DNS_SLIDE % {"host": dns_host}
    outline = "# Egress canary\n\n" + "".join(f"- [{slug}] {slug}\n" for slug in slides)
    (deck / "specs" / "outline.md").write_text(outline, encoding="utf-8")
    for slug, text in slides.items():
        (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    return list(slides)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1"))
    parser.add_argument("--dns-domain", help="a domain whose DNS query log you can read")
    args = parser.parse_args()

    os.environ.pop("SDPM_BROWSER", None)  # SDPM_BROWSER=none would turn the check off
    register_browser_source(make_source(args.region))
    nonce = secrets.token_hex(8)
    dns_host = f"{nonce}.{args.dns_domain.strip('.')}" if args.dns_domain else None

    with tempfile.TemporaryDirectory(prefix="sdpm-egress-") as tmp:
        deck = Path(tmp) / "deck"
        slugs = _build(deck, dns_host)
        result = api.refresh_html(deck, measure_slides=slugs)

    check = result.get("browser_check") or {}
    print("browser_check:", json.dumps({k: check.get(k) for k in
                                        ("status", "browser", "slides", "network_blocked", "blocked_requests",
                                         "seconds", "note")}, ensure_ascii=False))
    js_errors = [w for w in result.get("warnings", []) if ": JS error" in w]
    print(f"js errors ({len(js_errors)}):")
    for line in js_errors:
        print("  " + line[:300])
    if dns_host:
        print(f"DNS egress: look up {dns_host} in the query log of {args.dns_domain} "
              "(a query means the hints left the browser)")
    else:
        print("DNS egress: not verified (pass --dns-domain to test dns-prefetch / preconnect)")

    rtc = [w for w in js_errors if w.startswith("rtc: ")]
    leaked = [w for w in rtc if "sdpm slide rtc: available" in w or "sdpm slide rtc: srflx" in w]
    probed = any("sdpm slide rtc: probed" in w for w in rtc)
    ok = check.get("network_blocked") is True and probed and not leaked
    if not probed:
        print("FAIL: the rtc slide did not report (it did not run or its srcdoc frame did not load)")
    if leaked:
        print("FAIL: WebRTC reachable:", *leaked, sep="\n  ")
    if check.get("network_blocked") is not True:
        print("FAIL: network_blocked is not true")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
