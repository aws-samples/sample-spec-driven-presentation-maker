# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A two-slide deck in LibreOffice's SVG shape and its compose payloads, for the deck viewer tests.

The shape follows a real export: top-level ``<defs>`` for clip paths, slide metadata, bullet
glyphs and the master page (whose background objects hold a large image, as a logo or photo
in a template does); each slide's own background; a cover with a title and an embedded image;
a body slide with an inline gradient and a bulleted line. The images are made at test time
from seeded noise, so their base64 is long, does not compress, and is not in the repository.
"""

from __future__ import annotations

import base64
import io
import json
import random

from lxml import etree
from PIL import Image

from sdpm.engine.preview.compose import extract_optimized_defs, mark_changed, split_slide_components

SLUGS = ("cover", "points")
BULLET = "bullet-char-template-8226"
UNUSED_BULLET = "bullet-char-template-8211"
MASTER_IMAGE_ID = "master-photo"

_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" xmlns:ooo="http://xml.openoffice.org/svg/export"
     xmlns:xlink="http://www.w3.org/1999/xlink" version="1.2" viewBox="0 0 33867 19050"
     fill-rule="evenodd" stroke-width="28.222" stroke-linejoin="round">
 <defs class="ClipPathGroup">
  <clipPath id="presentation_clip_path" clipPathUnits="userSpaceOnUse">
   <rect x="0" y="0" width="33867" height="19050"/>
  </clipPath>
 </defs>
 <defs>
  <g id="ooo:meta_slides" ooo:number-of-slides="2">
   <g id="ooo:meta_slide_0" ooo:slide="id1" ooo:master="id2"/>
   <g id="ooo:meta_slide_1" ooo:slide="id3" ooo:master="id2"/>
  </g>
 </defs>
 <defs class="EmbeddedBulletChars">
  <g id="bullet-char-template-8226" transform="scale(0.00048828125,-0.00048828125)">
   <path d="M 346,457 C 273,457 209,483 155,535 101,586 74,649 74,723 74,796 101,859 155,911 Z"/>
  </g>
  <g id="bullet-char-template-8211" transform="scale(0.00048828125,-0.00048828125)">
   <path d="M -4,459 L 1135,459 1135,606 -4,606 -4,459 Z"/>
  </g>
 </defs>
 <defs>
  <g id="id2" ooo:name="Title" class="Master_Slide">
   <g id="bg-id2" class="Background">
    <path fill="rgb(255,255,255)" stroke="none" d="M 0,0 L 33867,0 33867,19050 0,19050 Z"/>
   </g>
   <g id="bo-id2" class="BackgroundObjects">
    <g class="Graphic">
     <g id="master-photo">
      <rect class="BoundingBox" stroke="none" fill="none" x="0" y="0" width="33867" height="19050"/>
      <image x="0" y="0" width="33867" height="19050" preserveAspectRatio="none" xlink:href="data:image/png;base64,{master}"/>
     </g>
    </g>
   </g>
  </g>
 </defs>
 <g class="SlideGroup">
  <g class="Slide"><g class="Page"/></g>
  <g class="Slide" id="id1">
   <g class="Page">
    <defs class="SlideBackground">
     <g class="Background"><path fill="rgb(20,30,40)" stroke="none" d="M 0,0 L 33867,0 33867,19050 0,19050 Z"/></g>
    </defs>
    <g class="com.sun.star.drawing.CustomShape">
     <g id="id11">
      <rect class="BoundingBox" stroke="none" fill="none" x="1693" y="5000" width="20000" height="3000"/>
      <text class="SVGTextShape"><tspan class="TextParagraph"><tspan class="TextPosition" x="1693" y="7000"><tspan font-family="Amazon Ember" font-size="1129px" font-weight="700" fill="rgb(255,255,255)" stroke="none" textLength="9000" lengthAdjust="spacingAndGlyphs" style="white-space: pre">Compose preview fixture</tspan></tspan></tspan></text>
     </g>
    </g>
    <g class="Graphic">
     <g id="id12">
      <rect class="BoundingBox" stroke="none" fill="none" x="26000" y="2000" width="5000" height="5000"/>
      <image x="26000" y="2000" width="5000" height="5000" preserveAspectRatio="none" xlink:href="data:image/png;base64,{logo}"/>
     </g>
    </g>
   </g>
  </g>
  <g class="Slide" id="id3">
   <g class="Page">
    <defs class="SlideBackground">
     <g class="Background"><path fill="rgb(250,250,250)" stroke="none" d="M 0,0 L 33867,0 33867,19050 0,19050 Z"/></g>
    </defs>
    <g class="com.sun.star.drawing.CustomShape">
     <g id="id21">
      <rect class="BoundingBox" stroke="none" fill="none" x="2000" y="3000" width="10000" height="6000"/>
      <defs>
       <linearGradient id="gradient1" x1="2000" y1="3000" x2="12000" y2="9000" gradientUnits="userSpaceOnUse">
        <stop offset="0" style="stop-color:rgb(255,153,0)"/><stop offset="1" style="stop-color:rgb(35,47,62)"/>
       </linearGradient>
      </defs>
      <path fill="url(#gradient1)" stroke="none" d="M 2000,3000 L 12000,3000 12000,9000 2000,9000 Z"/>
     </g>
    </g>
    <g class="TextShape">
     <g id="id22">
      <rect class="BoundingBox" stroke="none" fill="none" x="13500" y="4000" width="18000" height="1500"/>
      <text class="SVGTextShape"><tspan class="TextParagraph"><tspan class="TextPosition" x="14200" y="5000"><tspan font-family="Amazon Ember" font-size="706px" fill="rgb(21,29,37)" stroke="none" style="white-space: pre">One agent per slide</tspan></tspan></tspan></text>
      <g class="BulletChars"><g><use transform="translate(13600,4700) scale(423,423)" xlink:href="#bullet-char-template-8226"/></g></g>
     </g>
    </g>
   </g>
  </g>
 </g>
</svg>
"""


def noise_png(width: int, height: int, seed: int) -> bytes:
    pixels = random.Random(seed).randbytes(width * height * 3)
    out = io.BytesIO()
    Image.frombytes("RGB", (width, height), pixels).save(out, format="PNG")
    return out.getvalue()


def svg_text() -> str:
    b64 = lambda data: base64.b64encode(data).decode("ascii")  # noqa: E731
    return _SVG.format(master=b64(noise_png(160, 90, 1)), logo=b64(noise_png(48, 48, 2)))


def compose_files(epoch: int = 100) -> dict[str, bytes]:
    """``{file name: bytes}`` as the servers write them: ``<slug>_<epoch>.json`` per slide of
    ``SLUGS`` and ``defs_<epoch>.json``."""
    tree = etree.fromstring(svg_text().encode()).getroottree()
    files = {f"defs_{epoch}.json": json.dumps(extract_optimized_defs(tree), ensure_ascii=False).encode()}
    for number, slug in enumerate(SLUGS, start=1):
        payload = split_slide_components(tree, number)
        mark_changed(payload["components"], None)
        payload["regions"] = []
        files[f"{slug}_{epoch}.json"] = json.dumps(payload, ensure_ascii=False).encode()
    return files
