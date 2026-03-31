# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Group and arch-group elements."""
from sdpm.builder.constants import ARCH_GROUP_DEFS


class GroupMixin:
    """Mixin providing group element methods."""

    def _add_group(self, slide, elem):
        """Add group element to slide (flatten sub-elements, or inject raw XML)."""
        # If raw group XML is available, inject directly for lossless roundtrip
        group_xml = elem.get("_groupXml")
        if group_xml:
            from lxml import etree
            from pptx.oxml.ns import qn
            grp_el = etree.fromstring(group_xml)
            spTree = slide._element.find(qn('p:cSld')).find(qn('p:spTree'))
            spTree.append(grp_el)
            return
        for sub_elem in elem.get("elements", []):
            sub_type = sub_elem.get("type")
            if sub_type == "group":
                self._add_group(slide, sub_elem)
            elif sub_type == "arch-group":
                self._add_arch_group(slide, sub_elem)
            elif sub_type == "textbox":
                self._add_textbox(slide, sub_elem)
            elif sub_type == "image":
                self._add_image(slide, sub_elem)
            elif sub_type == "shape":
                self._add_shape(slide, sub_elem)
            elif sub_type == "freeform":
                self._add_freeform_shape(slide, sub_elem)
            elif sub_type == "line":
                self._add_line(slide, sub_elem)
            elif sub_type == "chart":
                self._add_chart(slide, sub_elem)
    
    def _add_arch_group(self, slide, elem):
        """Add AWS architecture group with predefined styling."""
        group_type = elem.get("groupType", "generic")
        x = elem.get("x", 0)
        y = elem.get("y", 0)
        w = elem.get("width", 300)
        h = elem.get("height", 200)
        label = elem.get("label", "")
        icon_size = elem.get("iconSize", 60)
    
        if group_type == "custom":
            color = elem.get("color", "#7D8998")
            dash = elem.get("dashStyle")
            icon_src = elem.get("icon")
            icon_pos = "top-left" if icon_src else None
            label_align = "left" if icon_src else "center"
        else:
            defn = ARCH_GROUP_DEFS.get(group_type, ARCH_GROUP_DEFS["generic"])
            color, dash, icon_src, icon_pos, label_align = defn
            # Theme-aware border color for aws-cloud
            if group_type == "aws-cloud" and not self.is_dark:
                color = "#232F3E"
    
        # Theme-aware label color
        label_color = self.theme_colors["text"]
    
        # Build shape element for the border
        shape_elem = {
            "type": "shape", "shape": "rectangle",
            "x": x, "y": y, "width": w, "height": h,
            "fill": "none", "line": color, "lineWidth": 1.2,
        }
        if dash:
            shape_elem["dashStyle"] = dash
    
        # Add label as shape text
        if label:
            styled_label = f"{{{{{label_color}:{label}}}}}"
            shape_elem["text"] = styled_label
            shape_elem["fontSize"] = 12
            shape_elem["verticalAlign"] = "top"
            # Scale marginLeft proportionally to icon size (px)
            icon_margin = round(79.2 * icon_size / 60)
            if label_align == "left":
                shape_elem["align"] = "left"
                shape_elem["marginLeft"] = icon_margin
                shape_elem["marginTop"] = 14
            elif label_align == "left-no-icon":
                shape_elem["align"] = "left"
                shape_elem["marginTop"] = 14
            elif label_align == "center" and icon_pos == "top-center":
                shape_elem["align"] = "center"
                shape_elem["marginTop"] = icon_margin
            else:
                shape_elem["align"] = "center"
                shape_elem["marginTop"] = 14
    
        self._add_shape(slide, shape_elem)
    
        # Add icon
        if icon_src and icon_pos:
            icon_elem = {"type": "image", "src": icon_src, "width": icon_size, "height": icon_size}
            if icon_pos == "top-left":
                icon_elem["x"] = x + 1
                icon_elem["y"] = y + 1
            elif icon_pos == "top-center":
                icon_elem["x"] = x + (w - icon_size) / 2
                icon_elem["y"] = y + 1
            self._add_image(slide, icon_elem)
    

