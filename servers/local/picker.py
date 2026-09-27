# SPDX-License-Identifier: MIT-0
"""A checkbox picker for the terminal — no dependencies, macOS / Linux / Windows.

    ❯ [x] Kiro CLI            creates agent `sdpm`
      [ ] Cursor              opens an Install link
          Claude Desktop      not here — use sdpm.mcpb          (disabled row)

↑/↓ (or j/k) move, space toggles, `a` toggles all, enter confirms, q / esc cancels.
Without a TTY (CI, `--yes`, pipes) callers fall back to line input or the defaults —
this module never blocks on a non-interactive stream.

The picker writes to and reads from the controlling terminal (/dev/tty on POSIX, the
console on Windows), so it works under `curl … | bash` where stdin is the script.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class Option:
    key: str
    label: str
    hint: str = ""
    checked: bool = True
    enabled: bool = True   # disabled rows are shown, never selectable


def _tty_available() -> bool:
    if sys.platform == "win32":
        return sys.stdout.isatty()
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    os.close(fd)
    return True


# --- key reading -----------------------------------------------------------------------


def _read_key_posix(fd: int) -> str:
    """Read one key from a terminal already in raw mode (see `_raw_mode`)."""
    import select

    ch = os.read(fd, 1)
    if ch == b"\x1b":
        # CSI sequences may arrive byte by byte (ptys, slow terminals): collect for a moment.
        seq = b""
        while len(seq) < 2 and select.select([fd], [], [], 0.05)[0]:
            seq += os.read(fd, 1)
        return {b"[A": "up", b"[B": "down"}.get(seq, "esc")
    return {b"\r": "enter", b"\n": "enter", b" ": "space", b"\x03": "ctrl-c", b"q": "esc",
            b"k": "up", b"j": "down", b"a": "all"}.get(ch, ch.decode(errors="ignore"))


class _raw_mode:
    """Raw terminal for the duration of the picker; one mode switch, no per-key flushes."""

    def __init__(self, fd: int) -> None:
        self.fd = fd

    def __enter__(self) -> None:
        import termios
        import tty

        self.old = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)

    def __exit__(self, *exc) -> None:
        import termios

        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def _read_key_windows() -> str:
    import msvcrt

    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
    return {"\r": "enter", " ": "space", "\x03": "ctrl-c", "\x1b": "esc", "q": "esc",
            "k": "up", "j": "down", "a": "all"}.get(ch, ch)


# --- rendering -------------------------------------------------------------------------


def _render(options: list[Option], cursor: int, title: str, help_line: str) -> str:
    lines = [f"  {title}   \x1b[2m{help_line}\x1b[0m", ""]
    width = max(len(o.label) for o in options) + 2
    for i, o in enumerate(options):
        pointer = "\x1b[36m❯\x1b[0m" if i == cursor else " "
        if not o.enabled:
            lines.append(f"  {pointer}     \x1b[2m{o.label:<{width}}{o.hint}\x1b[0m")
            continue
        box = "\x1b[32m[x]\x1b[0m" if o.checked else "[ ]"
        label = f"\x1b[1m{o.label:<{width}}\x1b[0m" if i == cursor else f"{o.label:<{width}}"
        lines.append(f"  {pointer} {box} {label}\x1b[2m{o.hint}\x1b[0m")
    return "\r\n".join(lines) + "\r\n"


def pick(options: list[Option], *, title: str = "Select", out=None) -> Optional[list[str]]:
    """Interactive multi-select. Returns the checked keys, or None if cancelled.

    Falls back to `pick_line` when no terminal is available.
    """
    if not _tty_available():
        return pick_line(options, title=title)
    enabled_idx = [i for i, o in enumerate(options) if o.enabled]
    if not enabled_idx:
        return []
    help_line = "↑↓ move · space toggle · a all · enter confirm · q cancel"
    cursor = enabled_idx[0]
    height = len(options) + 2

    if sys.platform == "win32":
        write = lambda s: (sys.stdout.write(s), sys.stdout.flush())  # noqa: E731
        read_key = _read_key_windows
        tty_file = None
        raw = None
    else:
        tty_file = open("/dev/tty", "r+b", buffering=0)
        write = lambda s: (tty_file.write(s.encode()), tty_file.flush())  # noqa: E731
        fd = tty_file.fileno()
        read_key = lambda: _read_key_posix(fd)  # noqa: E731
        raw = _raw_mode(fd)
        raw.__enter__()

    try:
        write("\x1b[?25l")  # hide cursor
        write(_render(options, cursor, title, help_line))
        while True:
            key = read_key()
            if key == "up":
                cursor = enabled_idx[(enabled_idx.index(cursor) - 1) % len(enabled_idx)]
            elif key == "down":
                cursor = enabled_idx[(enabled_idx.index(cursor) + 1) % len(enabled_idx)]
            elif key == "space":
                options[cursor].checked = not options[cursor].checked
            elif key == "all":
                target = not all(o.checked for o in options if o.enabled)
                for o in options:
                    if o.enabled:
                        o.checked = target
            elif key == "enter":
                break
            elif key in ("esc", "ctrl-c"):
                write(f"\x1b[{height}A\x1b[J")
                return None
            write(f"\x1b[{height}A\x1b[J")  # redraw in place
            write(_render(options, cursor, title, help_line))
        # Leave a compact summary in the scrollback instead of the widget.
        write(f"\x1b[{height}A\x1b[J")
        chosen = [o for o in options if o.enabled and o.checked]
        write(f"  {title}: " + (", ".join(o.label for o in chosen) if chosen else "none") + "\r\n\r\n")
        return [o.key for o in chosen]
    finally:
        write("\x1b[?25h")
        if raw is not None:
            raw.__exit__(None, None, None)
        if tty_file is not None:
            tty_file.close()


def pick_line(options: list[Option], *, title: str = "Select") -> Optional[list[str]]:
    """Line-input fallback: numbered list, answer `1,3`, `all`, or `none` (Enter = defaults)."""
    enabled = [o for o in options if o.enabled]
    if not enabled:
        return []
    print(f"  {title}")
    for i, o in enumerate(enabled, 1):
        mark = "x" if o.checked else " "
        print(f"    {i}. [{mark}] {o.label:<22} {o.hint}")
    for o in options:
        if not o.enabled:
            print(f"       {o.label:<22} {o.hint}")
    default = ",".join(str(i) for i, o in enumerate(enabled, 1) if o.checked) or "none"
    try:
        answer = input(f"  Which? [numbers / all / none] ({default}) ").strip().lower()
    except (EOFError, OSError):
        answer = ""
    if answer in ("", "default"):
        return [o.key for o in enabled if o.checked]
    if answer == "all":
        return [o.key for o in enabled]
    if answer == "none":
        return []
    keys = []
    for part in answer.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= len(enabled):
            keys.append(enabled[int(part) - 1].key)
    return keys
