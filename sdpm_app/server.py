"""FastAPI server: serves static web-ui + /acp WebSocket proxy to kiro-cli."""
from __future__ import annotations

import asyncio
import json
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def create_app() -> FastAPI:
    app = FastAPI(title="SDPM")

    # ACP WebSocket proxy — browser ↔ kiro-cli acp (stdin/stdout)
    @app.websocket("/acp")
    async def acp_ws(ws: WebSocket):
        await ws.accept()
        # Config sent from client as first message: {cmd, args, env}
        cfg_raw = await ws.receive_text()
        cfg = json.loads(cfg_raw)
        cmd = cfg.get("cmd", "kiro-cli")
        args = cfg.get("args", ["acp", "--agent", "sdpm-spec"])
        env = {**__import__("os").environ, **(cfg.get("env") or {})}

        proc = await asyncio.create_subprocess_exec(
            cmd, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        async def pump_stdout():
            assert proc.stdout
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    await ws.send_text(line.decode().rstrip("\n"))
                except Exception:
                    break

        async def pump_stdin():
            try:
                while True:
                    msg = await ws.receive_text()
                    assert proc.stdin
                    proc.stdin.write((msg + "\n").encode())
                    await proc.stdin.drain()
            except WebSocketDisconnect:
                pass

        try:
            await asyncio.gather(pump_stdout(), pump_stdin())
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    proc.kill()

    # Serve static web-ui (bundled at build time into sdpm_app/web/)
    try:
        web_dir = Path(files("sdpm_app").joinpath("web"))
    except Exception:
        web_dir = Path(__file__).parent / "web"

    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    else:
        @app.get("/")
        async def missing_web():
            return {"error": f"web UI not bundled at {web_dir}. Run web-ui build first."}

    return app
