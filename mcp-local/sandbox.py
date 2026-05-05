"""Sandbox for run_python: AST inspection + runner template generation."""

from __future__ import annotations

import ast


# --- Layer 1: AST inspection ---

_BLOCKED_NAMES = frozenset({
    "exec", "eval", "compile", "open", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir", "breakpoint", "__import__",
})


def check_code(code: str) -> list[str]:
    """Parse *code* and return a list of violations (empty = OK)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Line {e.lineno}: SyntaxError: {e.msg}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            violations.append(f"Line {line}: import statement is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                violations.append(
                    f"Line {line}: dunder access '{node.attr}' is not allowed"
                )
        elif isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            violations.append(
                f"Line {line}: '{node.id}' is not allowed in sandbox"
            )
    return violations


# --- Layer 2+3: Runner template ---

_RUNNER_WITH_DECK = '''\
import json, os, sys
from pathlib import Path

deck_dir = Path(sys.argv[1]).resolve()

def _resolve(rel_path):
    resolved = (deck_dir / rel_path).resolve()
    prefix = str(deck_dir) + os.sep
    if not (str(resolved).startswith(prefix) or resolved == deck_dir):
        raise PermissionError(f"Access denied: {rel_path}")
    return resolved

def read_json(path):
    p = _resolve(path)
    return json.loads(p.read_text(encoding="utf-8"))

def write_json(path, data):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")

def read_text(path):
    return _resolve(path).read_text(encoding="utf-8")

def write_text(path, text):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def list_files(subdir="."):
    d = _resolve(subdir)
    if not d.is_dir():
        raise FileNotFoundError(f"Not a directory: {subdir}")
    return sorted(f.name for f in d.iterdir() if f.is_file())

_safe_builtins = {
    "print": print, "len": len, "range": range, "enumerate": enumerate,
    "sorted": sorted, "isinstance": isinstance, "type": type,
    "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "any": any, "all": all, "zip": zip, "map": map, "filter": filter,
    "reversed": reversed, "True": True, "False": False, "None": None,
}

code = sys.stdin.read()
exec(code, {"__builtins__": _safe_builtins,
     "read_json": read_json, "write_json": write_json,
     "read_text": read_text, "write_text": write_text,
     "list_files": list_files})
'''

_RUNNER_NO_DECK = '''\
import sys

_safe_builtins = {
    "print": print, "len": len, "range": range, "enumerate": enumerate,
    "sorted": sorted, "isinstance": isinstance, "type": type,
    "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "any": any, "all": all, "zip": zip, "map": map, "filter": filter,
    "reversed": reversed, "True": True, "False": False, "None": None,
}

code = sys.stdin.read()
exec(code, {"__builtins__": _safe_builtins})
'''


def make_runner(deck_id: str) -> str:
    """Return the runner script. Static template — code comes via stdin."""
    return _RUNNER_WITH_DECK if deck_id else _RUNNER_NO_DECK


# --- Style runner ---

_RUNNER_STYLE = '''\
import json, os, sys
from pathlib import Path

style_dir = Path(sys.argv[1]).resolve()
styles_dirs = json.loads(sys.argv[2])

def _resolve(rel_path):
    resolved = (style_dir / rel_path).resolve()
    prefix = str(style_dir) + os.sep
    if not (str(resolved).startswith(prefix) or resolved == style_dir):
        raise PermissionError(f"Access denied: {rel_path}")
    return resolved

def read_text(path):
    return _resolve(path).read_text(encoding="utf-8")

def write_text(path, text):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def read_json(path):
    p = _resolve(path)
    return json.loads(p.read_text(encoding="utf-8"))

def write_json(path, data):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")

def list_files(subdir="."):
    d = _resolve(subdir)
    if not d.is_dir():
        raise FileNotFoundError(f"Not a directory: {subdir}")
    return sorted(f.name for f in d.iterdir() if f.is_file())

def read_style(name):
    """Read an existing style HTML by name (read-only, searches all style dirs)."""
    filename = name + ".html" if not name.endswith(".html") else name
    for d in styles_dirs:
        p = Path(d) / filename
        if p.exists():
            return p.read_text(encoding="utf-8")
    available = []
    for d in styles_dirs:
        dp = Path(d)
        if dp.is_dir():
            available.extend(f.stem for f in dp.iterdir() if f.suffix == ".html")
    raise FileNotFoundError(f"Style not found: {name}. Available: {sorted(set(available))}")

_safe_builtins = {
    "print": print, "len": len, "range": range, "enumerate": enumerate,
    "sorted": sorted, "isinstance": isinstance, "type": type,
    "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "any": any, "all": all, "zip": zip, "map": map, "filter": filter,
    "reversed": reversed, "True": True, "False": False, "None": None,
}

code = sys.stdin.read()
exec(code, {"__builtins__": _safe_builtins,
     "read_text": read_text, "write_text": write_text,
     "read_json": read_json, "write_json": write_json,
     "list_files": list_files, "read_style": read_style})
'''


def make_style_runner() -> str:
    """Return the style runner script. Expects sys.argv[1]=style_dir, sys.argv[2]=styles_dirs JSON."""
    return _RUNNER_STYLE
