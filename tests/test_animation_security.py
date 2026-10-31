# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hostile-input contract for animation/transition import (REQ-5.3, REQ-5.3a).

A PPTX is external input. Parsing it must stay offline and non-executing, and
the resource boundaries have to hold on the *uncompressed* XML before any
sidecar is written. The sentinels below replace the network, external
filesystem and process-launch entry points with fail-fast stand-ins and the
tests require **zero** calls through them during a successful import — plus a
positive control proving the sentinels would actually catch one.
"""

from __future__ import annotations

import builtins
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.converter.pipeline import pptx_to_json
from sdpm.engine.timing.raw import (
    RawManifestError,
    resolve_within,
    safe_bundle_path,
)
from sdpm.engine.timing.reader import (
    IMPORT_LIMIT_CODE,
    MAX_TIMING_XML_DEPTH,
    MAX_TIMING_XML_ELEMENTS,
    ImportLimitExceeded,
    enforce_xml_limits,
)
from sdpm.tools.attachment.pipeline import import_attachment_core

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


class Denied(AssertionError):
    """Raised by a sentinel: the import reached outside its sandbox."""


class Sentinels:
    """Fail-fast stand-ins for every way out of the process.

    The filesystem sentinel is a *scope* check rather than a blanket denial:
    reading the package and writing the bundle is the job, so the rule is that
    nothing outside the declared roots (the fixture directory, this checkout
    and the interpreter's own installation) may be opened.
    """

    def __init__(self, *allowed_roots: Path) -> None:
        self.allowed = [Path(root).resolve() for root in allowed_roots]
        self.calls: list[str] = []
        self._restore: list[tuple[object, str, object]] = []

    # -- plumbing -----------------------------------------------------
    def _patch(self, owner: object, name: str, replacement: object) -> None:
        self._restore.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def _deny(self, label: str):
        def fail(*args, **kwargs):
            self.calls.append(f"{label}{args[:1]}")
            raise Denied(f"import attempted {label}")

        return fail

    def _guarded_open(self, real):
        def guarded(file, *args, **kwargs):
            try:
                target = Path(os.fspath(file)).resolve()
            except TypeError:  # a file descriptor, not a path
                return real(file, *args, **kwargs)
            if not any(target == root or root in target.parents for root in self.allowed):
                self.calls.append(f"open({target})")
                raise Denied(f"import opened {target}, which is outside its sandbox")
            return real(file, *args, **kwargs)

        return guarded

    def __enter__(self) -> "Sentinels":
        for owner, name in (
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (urllib.request, "urlopen"),
            (subprocess, "Popen"),
            (subprocess, "run"),
            (os, "system"),
            (os, "popen"),
            (os, "posix_spawn"),
            (os, "execv"),
            (http.client.HTTPConnection, "connect"),
        ):
            self._patch(owner, name, self._deny(f"{getattr(owner, '__name__', owner)}.{name}"))
        real_open = builtins.open
        self._patch(builtins, "open", self._guarded_open(real_open))
        self._patch(io, "open", self._guarded_open(real_open))
        return self

    def __exit__(self, *exc) -> None:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()


def _sandbox(tmp_path: Path) -> Sentinels:
    return Sentinels(
        tmp_path,
        REPO_ROOT,
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(tempfile.gettempdir()),
    )


def _package(tmp_path, *, animations=True, name="deck.pptx"):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=tmp_path,
        animations_enabled=animations,
        transitions_enabled=True,
    )
    builder.add_slide({
        "id": "animated",
        "layout": "Blank",
        "elements": [{"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
                      "width": 300, "height": 60}],
        "animations": {
            "mainSequence": [{
                "id": "fx", "target": {"element": "hero"},
                "preset": {"category": "entrance", "effect": "fade", "variant": None},
                "start": {"type": "onPageClick", "delayMs": 0},
                "timing": {"durationMs": 500},
                "afterEffect": {"type": "none"}, "sound": None,
            }],
            "interactiveSequences": [],
        },
        "transition": {"effect": "wipe", "parameters": {}, "durationMs": 1000,
                       "advance": {"onClick": True, "afterMs": None}, "sound": None},
    })
    out = tmp_path / name
    builder.save(out)
    return out


def _inject_timing(path, xml):
    presentation = Presentation(str(path))
    slide = list(presentation.slides)[0]
    for node in slide._element.findall("{%s}timing" % P):
        slide._element.remove(node)
    slide._element.append(etree.fromstring(xml) if isinstance(xml, str) else xml)
    presentation.save(str(path))
    return path


# --- zero outbound activity ------------------------------------------------


class TestNonExecution:
    def test_a_successful_import_makes_no_outbound_call(self, tmp_path):
        package = _package(tmp_path)
        with _sandbox(tmp_path) as sentinels:
            pptx_to_json(package, tmp_path / "out")
        assert sentinels.calls == []
        slide = json.loads((tmp_path / "out" / "slides" / "slide-001.json").read_text())
        assert slide["animations"]["mainSequence"][0]["id"] == "fx", (
            "the import really ran inside the sandbox"
        )

    def test_importing_hostile_unknown_timing_makes_no_outbound_call(self, tmp_path):
        """A fragment full of references PowerPoint would resolve must be
        stored as bytes, not dereferenced."""
        package = _package(tmp_path, animations=False)
        slide = list(Presentation(str(package)).slides)[0]
        spid = slide.shapes[0].shape_id
        hostile = (
            '<p:timing xmlns:p="%s"><p:tnLst><p:par>'
            '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">'
            '<p:childTnLst><p:seq><p:cTn id="2" nodeType="mainSeq"><p:childTnLst>'
            '<p:par><p:cTn id="3" futureThing="https://example.invalid/payload">'
            '<p:tgtEl><p:spTgt spid="%s"/></p:tgtEl>'
            '<p:script src="file:///etc/passwd"/>'
            "</p:cTn></p:par></p:childTnLst></p:cTn></p:seq>"
            "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>" % (P, spid)
        )
        _inject_timing(package, hostile)
        with _sandbox(tmp_path) as sentinels:
            pptx_to_json(package, tmp_path / "out")
        assert sentinels.calls == []
        sidecar = next((tmp_path / "out" / "animations").glob("*-timing.xml"))
        assert b"example.invalid" in sidecar.read_bytes(), "preserved verbatim, never fetched"

    def test_the_sentinels_would_catch_a_real_attempt(self, tmp_path):
        """Positive control: without it, "zero calls" could be vacuous."""
        with _sandbox(tmp_path) as sentinels:
            with pytest.raises(Denied):
                socket.socket()
            with pytest.raises(Denied):
                subprocess.run(["/bin/echo", "hi"])
            with pytest.raises(Denied):
                builtins.open(Path.home() / ".ssh" / "id_rsa")
        assert len(sentinels.calls) == 3


# --- DTD and entities ------------------------------------------------------


class TestDtdAndEntities:
    @pytest.mark.parametrize(
        "xml",
        [
            b'<!DOCTYPE timing [<!ENTITY payload SYSTEM "file:///etc/passwd">]>'
            b"<p:timing xmlns:p=\"%s\">&payload;</p:timing>" % P.encode(),
            b'<!DOCTYPE timing SYSTEM "http://example.invalid/timing.dtd"><p:timing/>',
            b'<!ENTITY payload "x"><p:timing/>',
        ],
    )
    def test_a_dtd_or_entity_declaration_is_refused(self, xml):
        with pytest.raises(ImportLimitExceeded) as error:
            enforce_xml_limits(xml, what="hostile fixture")
        assert error.value.code == IMPORT_LIMIT_CODE
        assert "forbidden" in str(error.value)


# --- resource limits ------------------------------------------------------


class TestResourceLimits:
    def test_the_boundaries_are_the_spec_values(self):
        assert MAX_TIMING_XML_DEPTH == 256
        assert MAX_TIMING_XML_ELEMENTS == 100_000

    def test_the_element_count_boundary_is_inclusive(self):
        def tree(count):
            root = etree.Element("timing")
            for _ in range(count - 1):
                etree.SubElement(root, "node")
            return etree.tostring(root)

        enforce_xml_limits(tree(MAX_TIMING_XML_ELEMENTS), what="at the boundary")
        with pytest.raises(ImportLimitExceeded) as error:
            enforce_xml_limits(tree(MAX_TIMING_XML_ELEMENTS + 1), what="over the boundary")
        assert error.value.code == IMPORT_LIMIT_CODE

    def test_the_depth_boundary_is_inclusive(self):
        def nest(depth):
            root = etree.Element("timing")
            node = root
            for _ in range(depth - 1):
                node = etree.SubElement(node, "node")
            return etree.tostring(root)

        enforce_xml_limits(nest(MAX_TIMING_XML_DEPTH), what="at the boundary",
                           max_depth=MAX_TIMING_XML_DEPTH)
        with pytest.raises(ImportLimitExceeded) as error:
            enforce_xml_limits(nest(MAX_TIMING_XML_DEPTH + 1), what="over the boundary",
                               max_depth=MAX_TIMING_XML_DEPTH)
        assert error.value.code == IMPORT_LIMIT_CODE

    def test_an_over_limit_slide_tree_stops_the_converter(self, tmp_path):
        package = _package(tmp_path, animations=False)
        timing = etree.Element("{%s}timing" % P, nsmap={"p": P})
        for _ in range(MAX_TIMING_XML_ELEMENTS + 1):
            etree.SubElement(timing, "{%s}node" % P)
        _inject_timing(package, timing)
        with pytest.raises(ImportLimitExceeded) as error:
            pptx_to_json(package, tmp_path / "out")
        assert error.value.code == IMPORT_LIMIT_CODE

    def test_the_attachment_pipeline_reports_the_structured_code(self, tmp_path):
        import random

        package = _package(tmp_path, animations=False)
        # Incompressible payload on purpose: a tree of identical nodes trips the
        # pre-existing 100:1 ZIP ratio limit first, and this test is about the
        # timing element-count limit reaching the caller with its own code.
        noise = random.Random(0)
        timing = etree.Element("{%s}timing" % P, nsmap={"p": P})
        for index in range(MAX_TIMING_XML_ELEMENTS + 1):
            etree.SubElement(
                timing, "{%s}node" % P, id=f"n{index}",
                seed=f"{noise.getrandbits(128):032x}",
            )
        _inject_timing(package, timing)
        result = import_attachment_core(
            package, source=str(package), deck_dir=tmp_path / "deck", filename="deck.pptx",
        )
        assert result["code"] == IMPORT_LIMIT_CODE
        assert not (tmp_path / "deck" / "attachments" / "imports").exists() or not list(
            (tmp_path / "deck" / "attachments" / "imports").iterdir()
        ), "nothing is published when a limit is exceeded"

    def test_the_existing_attachment_limits_are_untouched(self):
        from sdpm.tools.attachment.limits import (
            MAX_RAW_SIZE_BYTES,
            MAX_ZIP_COMPRESSION_RATIO,
            MAX_ZIP_ENTRIES,
            MAX_ZIP_SINGLE_ENTRY,
            MAX_ZIP_TOTAL_UNCOMPRESSED,
        )

        assert MAX_RAW_SIZE_BYTES == 100 * 1024 * 1024
        assert MAX_ZIP_ENTRIES == 10_000
        assert MAX_ZIP_TOTAL_UNCOMPRESSED == 500 * 1024 * 1024
        assert MAX_ZIP_SINGLE_ENTRY == 100 * 1024 * 1024
        assert MAX_ZIP_COMPRESSION_RATIO == 100


# --- path containment -----------------------------------------------------


class TestPathContainment:
    @pytest.mark.parametrize(
        "path",
        ["../outside.xml", "animations/../../outside.xml", "/absolute.xml",
         "animations/./same.xml", "a\\b.xml"],
    )
    def test_a_path_leaving_the_bundle_is_refused(self, path, tmp_path):
        with pytest.raises(RawManifestError):
            safe_bundle_path(path, what="sidecar path")
        with pytest.raises(RawManifestError):
            resolve_within(tmp_path, path, what="sidecar path")

    def test_a_symlink_out_of_the_bundle_is_refused(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "bundle"
        (root / "animations").mkdir(parents=True)
        (root / "animations" / "escape").symlink_to(outside, target_is_directory=True)
        with pytest.raises(RawManifestError, match="escapes the bundle root"):
            resolve_within(root, "animations/escape/payload.xml", what="sidecar path")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
