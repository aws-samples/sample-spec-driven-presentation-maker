# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Preview: autofit refresh, PNG generation, layout imbalance check."""

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.
import subprocess
import sys
import tempfile
from pathlib import Path

from pptx import Presentation


def _is_wsl():
    return Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower()


def _mac_open_pptx_background(pptx_path):
    """Open PPTX in PowerPoint without stealing fullscreen space. Returns restore info."""
    script = '''
    tell application "System Events"
        tell application process "Microsoft PowerPoint"
            set fsName to ""
            set topName to ""
            if (count of windows) > 0 then
                set topName to name of window 1
            end if
            repeat with w in windows
                if value of attribute "AXFullScreen" of w is true then
                    set fsName to name of w
                    set value of attribute "AXFullScreen" of w to false
                    exit repeat
                end if
            end repeat
        end tell
    end tell
    do shell script "open -gF -a 'Microsoft PowerPoint' " & quoted form of "%s"
    return fsName & "|" & topName
    ''' % str(pptx_path)
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    return result.stdout.strip() if result.returncode == 0 else "|"


def _mac_restore_pptx_focus(restore_info):
    """Restore PowerPoint window focus after background open."""
    parts = restore_info.split("|", 1)
    fs_name = parts[0] if len(parts) > 0 else ""
    top_name = parts[1] if len(parts) > 1 else ""
    script = _mac_restore_applescript(fs_name, top_name)
    if script:
        subprocess.run(["osascript", "-e", script], capture_output=True)  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit


def _mac_restore_pptx_focus_async(restore_info):
    """Restore PowerPoint window focus asynchronously (non-blocking)."""
    parts = restore_info.split("|", 1)
    fs_name = parts[0] if len(parts) > 0 else ""
    top_name = parts[1] if len(parts) > 1 else ""
    script = _mac_restore_applescript(fs_name, top_name)
    if script:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit


def _mac_restore_applescript(fs_name, top_name):
    """Return AppleScript snippet to restore PowerPoint window focus."""
    if fs_name:
        return f'''
        tell application "System Events"
            tell application process "Microsoft PowerPoint"
                repeat with w in windows
                    if name of w is "{fs_name}" then
                        set value of attribute "AXFullScreen" of w to true
                        exit repeat
                    end if
                end repeat
            end tell
        end tell
        tell application "Microsoft PowerPoint" to activate
        '''
    elif top_name:
        return f'''
        tell application "System Events"
            tell application process "Microsoft PowerPoint"
                repeat with w in windows
                    if name of w is "{top_name}" then
                        perform action "AXRaise" of w
                        exit repeat
                    end if
                end repeat
            end tell
        end tell
        '''
    return ""


def refresh_autofit(pptx_path, pdf_path=None):
    """Refresh autofit by opening in PowerPoint and nudging a shape."""
    if sys.platform == "darwin":
        pdf_lines = ""
        if pdf_path:
            pdf_lines = f'''
                set outPath to (POSIX file "{pdf_path}") as text
                save pres in outPath as save as PDF
            '''
        pptx_name = Path(pptx_path).name
        restore_info = _mac_open_pptx_background(pptx_path)
        _mac_restore_pptx_focus_async(restore_info)
        import time
        time.sleep(2)
        script = f'''
            tell application "Microsoft PowerPoint"
                set pres to presentation "{pptx_name}"
                set slideCount to count of slides of pres
                if (count of shapes of slide 1 of pres) > 0 then
                    set sh to shape 1 of slide 1 of pres
                    set w to width of sh
                    set width of sh to w + 1
                    set width of sh to w
                end if
                set waitTime to 1 + slideCount * 0.3
                delay waitTime
                save pres
                {pdf_lines}
                close pres
            end tell
        '''
        cmd = ["osascript", "-e", script]
    elif sys.platform == "win32":
        pdf_line = ""
        if pdf_path:
            pdf_line = f"$prs.SaveAs('{pdf_path}', 32); "
        ps_cmd = (
            f"$app = New-Object -ComObject PowerPoint.Application; "
            f"$prs = $app.Presentations.Open('{pptx_path}'); "
            f"$s = $prs.Slides[1]; "
            f"if ($s.Shapes.Count -gt 0) {{ $sh = $s.Shapes[1]; $w = $sh.Width; $sh.Width = $w + 1; $sh.Width = $w }}; "
            f"$prs.Save(); {pdf_line}$prs.Close(); $app.Quit()"
        )
        cmd = ["powershell.exe", "-Command", ps_cmd]
    elif _is_wsl():
        win_path = subprocess.run(["wslpath", "-w", str(pptx_path)], capture_output=True, text=True).stdout.strip()  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        pdf_line = ""
        if pdf_path:
            win_pdf = subprocess.run(["wslpath", "-w", str(pdf_path)], capture_output=True, text=True).stdout.strip()  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            pdf_line = f"$prs.SaveAs('{win_pdf}', 32); "
        ps_cmd = (
            f"$app = New-Object -ComObject PowerPoint.Application; "
            f"$prs = $app.Presentations.Open('{win_path}'); "
            f"$s = $prs.Slides[1]; "
            f"if ($s.Shapes.Count -gt 0) {{ $sh = $s.Shapes[1]; $w = $sh.Width; $sh.Width = $w + 1; $sh.Width = $w }}; "
            f"$prs.Save(); {pdf_line}$prs.Close(); $app.Quit()"
        )
        cmd = ["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", ps_cmd]
    else:
        print("Warning: Autofit refresh skipped (unsupported platform)", file=sys.stderr)
        return False
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        if result.returncode == 0:
            return True
        else:
            encoding = "cp932" if _is_wsl() else "utf-8"
            stderr = result.stderr.decode(encoding, errors="replace").strip()
            print(f"Warning: Autofit refresh failed: {stderr}", file=sys.stderr)
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, UnicodeDecodeError):
        print("Warning: Autofit refresh skipped (PowerPoint not available)", file=sys.stderr)
        return False


def check_layout_imbalance(pptx_path, slide_defs=None):
    """Detect slides where bbox centroid deviates from content area center and print results."""
    alerts = check_layout_imbalance_data(pptx_path, slide_defs)
    if alerts:
        print(f"⚠️  Layout bias detected ({len(alerts)} slides):")
        for a in alerts:
            print(f"  page{a['slide']:02d} ({a['layout']}) | {a['bbox']} | centroid offset: {a['offset']} ({a['direction']})")
        print("  → MUST FIX unless the layout type is intentionally asymmetric (e.g. title, section, agenda, thankyou).")
        print("  → Action: Increase element heights, expand spacing between elements, or add content to fill the empty area. Fix one slide at a time. Do NOT batch-fix.")


def check_layout_imbalance_data(pptx_path, slide_defs=None):
    """Detect slides where bbox centroid deviates from content area center.

    Args:
        pptx_path: Path to the PPTX file.
        slide_defs: Optional list of slide definition dicts with 'layout' key.

    Returns:
        List of dicts with keys: slide, layout, bbox, offset, direction.
    """
    _THRESHOLD = 0.03
    prs = Presentation(str(pptx_path))
    _SW = int(prs.slide_width / 6350)
    _SH = int(prs.slide_height / 6350)
    emu = 6350
    _TITLE_BOTTOM = int(_SH * 0.13)
    _CONTENT_BOTTOM = int(_SH * 0.88)
    _CY = (_TITLE_BOTTOM + _CONTENT_BOTTOM) / 2
    _CA_H = _CONTENT_BOTTOM - _TITLE_BOTTOM
    alerts = []
    for slide_idx, slide in enumerate(prs.slides, 1):
        layout = "content"
        if slide_defs and slide_idx <= len(slide_defs):
            layout = slide_defs[slide_idx - 1].get("layout", "content")
        min_x, min_y, max_x, max_y = _SW, _SH, 0, 0
        has_elem = False
        for shape in slide.shapes:
            if shape.is_placeholder:
                continue
            x = int(shape.left / emu)
            y = int(shape.top / emu)
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x + int(shape.width / emu)), max(max_y, y + int(shape.height / emu))
            has_elem = True
        if not has_elem:
            continue
        cy = (min_y + max_y) / 2
        dy = (cy - _CY) / _CA_H
        if abs(dy) > _THRESHOLD:
            alerts.append({
                "slide": slide_idx,
                "layout": layout,
                "bbox": f"x={min_x}..{max_x} y={min_y}..{max_y} (of {_SW}x{_SH})",
                "offset": f"{dy:+.1%}",
                "direction": "bottom-heavy" if dy > 0 else "top-heavy",
            })
    return alerts


def unlock_height_constraints(pptx_path):
    """Replace normAutofit with noAutofit and warn on text overflow."""
    from lxml import etree
    prs = Presentation(str(pptx_path))
    nsmap = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    changed = False
    warnings = []
    for slide_idx, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            body_pr = shape.text_frame._txBody.find('.//a:bodyPr', nsmap)
            if body_pr is None:
                continue
            norm = body_pr.find('a:normAutofit', nsmap)
            if norm is None:
                continue
            font_scale = int(norm.get('fontScale', '100000')) / 100000.0
            # Collect warning for any font shrink
            if font_scale < 1.0:
                text_preview = shape.text_frame.text[:40].replace('\n', ' ')
                warnings.append(f"  page{slide_idx:02d} | \"{text_preview}\" | would need fontSize {font_scale:.0%} to fit")
            # Replace normAutofit with noAutofit (no font size bake)
            body_pr.remove(norm)
            etree.SubElement(body_pr, f'{{{nsmap["a"]}}}noAutofit')
            changed = True
    if warnings:
        print(f"⚠️  Text may not fit ({len(warnings)} shapes) — would need fontSize reduction to fit within shape bounds:")
        for line in warnings:
            print(line)
        print("  fontSize reduction also changes text wrapping — exact cause of overflow varies.")
        print("  Check preview for: text overflowing shape bounds, unintended wrapping, overlap with nearby elements.")
        print("  If no visible problem, no action needed.")
        print("  If text overflows, adjust layout (width/height) or content (text length).")
        print("  fontSize has recommended minimums — prefer layout/content adjustments over reducing fontSize.")
        print("  Review surrounding layout together — don't fix in isolation.")
    if changed:
        prs.save(str(pptx_path))


def get_tmp_project_dir(input_json_path):
    """Derive temp pptx-maker/{project_name}/ from input JSON path."""
    p = Path(input_json_path).resolve().parent
    project_name = p.name
    tmp_dir = Path(tempfile.gettempdir()) / "pptx-maker" / project_name
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir
