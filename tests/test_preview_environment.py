# SPDX-License-Identifier: MIT-0
"""Previews are optional: a missing LibreOffice/poppler is reported at the point of need."""

from __future__ import annotations

from sdpm.engine.preview import environment as env


def _no_tools(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda _n: None)
    monkeypatch.setattr(env, "_SOFFICE_CANDIDATES", ())


def test_all_present(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert env.preview_environment("darwin") == {"available": True, "missing": [], "install": ""}
    assert env.preview_unavailable("darwin") is None


def test_missing_both_with_os_specific_install_line(monkeypatch):
    _no_tools(monkeypatch)
    mac = env.preview_environment("darwin")
    assert mac["missing"] == ["libreoffice", "poppler"]
    assert mac["install"] == "brew install --cask libreoffice && brew install poppler"
    assert "apt-get" in env.preview_environment("linux")["install"]
    assert "winget" in env.preview_environment("win32")["install"]
    assert env.preview_environment("freebsd")["install"].startswith("install LibreOffice")


def test_only_poppler_missing(monkeypatch):
    monkeypatch.setattr(env.shutil, "which", lambda n: "/usr/bin/soffice" if n == "soffice" else None)
    result = env.preview_unavailable("linux")
    assert result["status"] == "unavailable"
    assert result["missing"] == ["poppler"]
    assert result["install"] == "sudo apt-get install -y poppler-utils"
    assert "Slides were built" in result["note"]


def test_app_bundle_counts_as_present(monkeypatch, tmp_path):
    fake = tmp_path / "soffice"
    fake.write_text("")
    monkeypatch.setattr(env.shutil, "which", lambda n: "/usr/bin/pdftoppm" if n == "pdftoppm" else None)
    monkeypatch.setattr(env, "_SOFFICE_CANDIDATES", (fake,))
    assert env.soffice_path() == str(fake)
    assert env.preview_environment("darwin")["available"] is True
