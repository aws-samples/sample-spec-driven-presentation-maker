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

def _refresh_autofit_pptx(pptx_path):
    """Re-save PPTX with autofit applied via detected presentation backend."""
    from sdpm.preview import refresh_autofit_for_convert
    return refresh_autofit_for_convert(pptx_path)

def pptx_to_json(pptx_path: Path, output_dir: Path = None, no_autofit: bool = False, use_layout_names: bool = True, minimal: bool = False):
    """Convert PPTX to JSON. Output is a project folder with slides.json + images/."""
    # Refresh autofit via PowerPoint (temp copy → extract → cleanup)
    tmp_pptx = None
    if not no_autofit:
        tmp_pptx = _refresh_autofit_pptx(pptx_path)
        if tmp_pptx:
            print("Autofit refreshed via presentation backend")
    
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
