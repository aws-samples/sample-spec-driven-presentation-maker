"""CLI entrypoint: sdpm start / install-shortcut."""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import sys
import webbrowser
from pathlib import Path


def cmd_start(args: argparse.Namespace) -> int:
    """Start FastAPI server + open browser."""
    import uvicorn
    from sdpm_app.server import create_app

    host = args.host
    port = args.port
    app = create_app()

    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
    print(f"[sdpm] Starting at {url}")
    if not args.no_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def cmd_install_shortcut(args: argparse.Namespace) -> int:
    """Create a double-clickable app shortcut in ~/Applications (macOS only)."""
    if sys.platform != "darwin":
        print("install-shortcut currently supports macOS only.", file=sys.stderr)
        return 1

    sdpm_bin = shutil.which("sdpm") or sys.argv[0]
    if not Path(sdpm_bin).exists():
        print(f"sdpm executable not found at {sdpm_bin}", file=sys.stderr)
        return 1

    app_dir = Path.home() / "Applications" / "SDPM.app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    (app_dir / "Contents" / "MacOS").mkdir(parents=True)
    (app_dir / "Contents" / "Resources").mkdir()

    # Launcher shell script
    launcher = app_dir / "Contents" / "MacOS" / "SDPM"
    launcher.write_text(f"""#!/bin/bash
exec {sdpm_bin} start
""")
    launcher.chmod(0o755)

    # Info.plist
    plistlib.dump({
        "CFBundleExecutable": "SDPM",
        "CFBundleIdentifier": "com.sdpm.app",
        "CFBundleName": "SDPM",
        "CFBundleDisplayName": "SDPM",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundlePackageType": "APPL",
        "LSUIElement": False,
    }, (app_dir / "Contents" / "Info.plist").open("wb"))

    print(f"[sdpm] Created {app_dir}")
    print("Open Finder → Applications → SDPM to launch.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sdpm", description="SDPM local app")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start server + open browser")
    p_start.add_argument("--host", default="127.0.0.1")
    p_start.add_argument("--port", type=int, default=8765)
    p_start.add_argument("--no-browser", action="store_true")
    p_start.set_defaults(func=cmd_start)

    p_inst = sub.add_parser("install-shortcut", help="Create macOS .app shortcut")
    p_inst.set_defaults(func=cmd_install_shortcut)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
