# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""schedule_webp_background must work from a worker thread (no event loop)."""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers" / "remote"))

import server_utils  # noqa: E402


class _Storage:
    pptx_bucket = "b"

    def __init__(self):
        self.uploads = {}
        self.updates = []
        self._s3 = type("S3", (), {"delete_object": lambda self, **k: None})()

    def list_files(self, prefix, bucket=None):
        return [k for k in self.uploads if k.startswith(prefix)]

    def upload_file(self, key, data, content_type=""):
        self.uploads[key] = data

    def update_deck(self, deck_id, user_id, updates):
        self.updates.append(updates)


def test_webp_background_runs_without_event_loop(tmp_path, monkeypatch):
    from PIL import Image
    import tools.generate as gen

    def fake_previews(pptx_path, out_dir):
        files = []
        for i in range(2):
            p = Path(out_dir) / f"slide-{i + 1}.webp"
            Image.new("RGB", (64, 36), "white").save(p, "WEBP")
            files.append(p)
        return files

    monkeypatch.setattr(gen, "generate_previews", fake_previews)
    storage = _Storage()
    workdir = tmp_path / "work"
    workdir.mkdir()
    pptx = workdir / "out.pptx"
    pptx.write_bytes(b"")

    def from_worker():
        # Tools run via asyncio.to_thread → no running loop in this thread.
        server_utils.schedule_webp_background("d1", pptx, workdir, storage, ["a", "b"], user_id="u1")

    t = threading.Thread(target=from_worker)
    t.start()
    t.join()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not storage.updates:
        time.sleep(0.05)

    keys = sorted(storage.uploads)
    assert any(k.startswith("previews/d1/a_") for k in keys)
    assert any(k.startswith("previews/d1/b_") for k in keys)
    assert any(k.startswith("previews/d1/thumbnail_") for k in keys)
    assert storage.updates and "thumbnailS3Key" in storage.updates[0]
    assert not workdir.exists()  # task owns tmpdir cleanup
