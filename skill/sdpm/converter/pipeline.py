# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PPTX to JSON conversion pipeline."""
import argparse
import sys
from pathlib import Path

from pptx import Presentation

from .color import extract_theme_colors_and_mapping
from .slide import extract_slide
from sdpm.utils.io import write_json
from sdpm.schema.defaults import sort_element_keys

def _is_wsl():
    try:
        return 'microsoft' in open('/proc/version').read().lower()
    except Exception:
        return False

def _refresh_autofit_pptx(pptx_path):
    """Open PPTX in PowerPoint, apply 'resize shape to fit text' on spAutoFit textboxes, return temp path."""
    import shutil
    import subprocess
    import tempfile
    from pptx import Presentation as _Prs
    from pptx.oxml.ns import qn as _qn
    
    # Find textboxes (txBox="1") to apply resize
    prs = _Prs(str(pptx_path))
    targets = []  # list of (slide_idx_1based, shape_idx_1based)
    for si, slide in enumerate(prs.slides, 1):
        for shi, shape in enumerate(slide.shapes, 1):
            sp = shape._element
            nvSpPr = sp.find(_qn('p:nvSpPr'))
            if nvSpPr is None:
                continue
            cNvSpPr = nvSpPr.find(_qn('p:cNvSpPr'))
            if cNvSpPr is None or cNvSpPr.get('txBox') != '1':
                continue
            targets.append((si, shi))
    
    if not targets:
        return None  # nothing to refresh
    
    tmp_dir = tempfile.mkdtemp()
    tmp_pptx = Path(tmp_dir) / pptx_path.name
    shutil.copy2(pptx_path, tmp_pptx)
    
    if sys.platform == "darwin":
        from sdpm.preview import _mac_open_pptx_background, _mac_restore_pptx_focus_async
        # Build AppleScript lines for each target shape
        resize_lines = "\n".join(
            f'                try\n'
            f'                    tell text frame of shape {shi} of slide {si} of pres\n'
            f'                        set auto size to shape to fit text\n'
            f'                    end tell\n'
            f'                end try'
            for si, shi in targets
        )
        pptx_name = tmp_pptx.name
        restore_info = _mac_open_pptx_background(tmp_pptx)
        _mac_restore_pptx_focus_async(restore_info)
        import time
        time.sleep(2)
        script = f'''
    tell application "Microsoft PowerPoint"
        set pres to presentation "{pptx_name}"
{resize_lines}
        delay 1
        save pres
        close pres
    end tell
'''
        cmd = ["osascript", "-e", script]
    elif sys.platform == "win32" or _is_wsl():
        # PowerShell COM: TextFrame.AutoSize = 1 (ppAutoSizeShapeToFitText)
        # targets is list of (slide_1based, shape_1based)
        resize_lines = "; ".join(
            f"$prs.Slides[{si}].Shapes[{shi}].TextFrame.AutoSize = 1"
            for si, shi in targets
        )
        ps_cmd = (
            f"$app = New-Object -ComObject PowerPoint.Application; "
            f"$prs = $app.Presentations.Open('{tmp_pptx}'); "
            f"{resize_lines}; "
            f"$prs.Save(); $prs.Close(); $app.Quit()"
        )
        if _is_wsl():
            win_path = subprocess.run(["wslpath", "-w", str(tmp_pptx)], capture_output=True, text=True).stdout.strip()  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ps_cmd = ps_cmd.replace(str(tmp_pptx), win_path)
            cmd = ["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", ps_cmd]
        else:
            cmd = ["powershell.exe", "-Command", ps_cmd]
    else:
        shutil.rmtree(tmp_dir)
        return None
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        if result.returncode == 0:
            return tmp_pptx
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    shutil.rmtree(tmp_dir)
    return None

def pptx_to_json(pptx_path: Path, output_dir: Path = None, no_autofit: bool = False, use_layout_names: bool = True, minimal: bool = False):
    """Convert PPTX to JSON. Output is a project folder with slides.json + images/."""
    # Refresh autofit via PowerPoint (temp copy → extract → cleanup)
    tmp_pptx = None
    if not no_autofit:
        tmp_pptx = _refresh_autofit_pptx(pptx_path)
        if tmp_pptx:
            print("Autofit refreshed via PowerPoint")
    
    actual_path = tmp_pptx or pptx_path
    prs = Presentation(str(actual_path))

    # Set EMU_PER_PX based on actual slide size
    from .constants import set_emu_per_px
    set_emu_per_px(int(prs.slide_width))
    
    # Create output directory
    if output_dir is None:
        output_dir = pptx_path.with_suffix('')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    result = {
        "slides": []
    }
    
    # Extract fonts from template
    try:
        from sdpm.analyzer import extract_fonts
        result["fonts"] = extract_fonts(actual_path)
    except Exception:
        pass
    
    # Compute builder's default text color (from slide_masters[0])
    builder_text_color = None
    try:
        tc0, cm0, _ = extract_theme_colors_and_mapping(actual_path, 0)
        tx1_ref = cm0.get('tx1', 'dk1')
        builder_text_color = tc0.get(tx1_ref)
    except Exception:
        pass

    for slide_idx, slide in enumerate(prs.slides):
        # Get slide master index
        slide_master = slide.slide_layout.slide_master
        master_idx = list(prs.slide_masters).index(slide_master)
        
        # Extract theme colors and mapping for this master
        theme_colors, color_mapping, theme_styles = extract_theme_colors_and_mapping(actual_path, master_idx)
        
        slide_dict = extract_slide(slide, theme_colors, color_mapping, theme_styles, master_idx, output_dir, slide_idx, pptx_path=actual_path, use_layout_names=use_layout_names, builder_text_color=builder_text_color)
        slide_dict["elements"] = [sort_element_keys(e) for e in slide_dict.get("elements", [])]
        if minimal:
            from sdpm.schema.minimal import minimize
            slide_dict["elements"] = minimize(slide_dict["elements"])
        result["slides"].append(slide_dict)
    
    # Output
    json_path = output_dir / "slides.json"
    write_json(json_path, result)
    
    # Cleanup temp copy
    if tmp_pptx:
        import shutil
        shutil.rmtree(tmp_pptx.parent)
    print(f"Converted: {output_dir}/")
    print(f"  {json_path}")
    images_dir = output_dir / "images"
    if images_dir.exists():
        count = len(list(images_dir.iterdir()))
        print(f"  {images_dir}/ ({count} files)")
    
    return result

def main():
    parser = argparse.ArgumentParser(description="Convert PPTX to JSON")
    parser.add_argument("input", help="Input PPTX file")
    parser.add_argument("-o", "--output", help="Output directory (default: input filename without extension)")
    parser.add_argument("--no-autofit", action="store_true", help="Skip PowerPoint autofit refresh")
    parser.add_argument("--minimal", action="store_true", help="Strip defaults, internal keys, and font tags for clean output")
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    output_dir = Path(args.output) if args.output else None
    pptx_to_json(input_path, output_dir, no_autofit=args.no_autofit, minimal=args.minimal)

if __name__ == "__main__":
    main()
