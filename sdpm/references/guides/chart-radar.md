---
description: "Radar chart JSON structure and style overrides — read when slide contains radar/spider chart"
---

Radar (spider) charts for comparing a few options across several criteria.

## Use cases
- Vendor or option evaluation across criteria
- Skill maps
- Well-Architected pillar scores

## Design points
- Markers are shown by default (`markers: false` for plain lines)
- Each category is one spoke; each series is one closed line
- Set `valueAxis` `min` / `max` / `majorUnit` so the rings match the scoring scale

**Constraints:**
- You SHOULD keep to 3–8 categories on the same scale because spokes get crowded and mixed scales distort the shape
- You SHOULD keep to 2–3 series because overlapping outlines become unreadable

## Style-adjustable properties
- `lineWidth`: line thickness (default: 2.5pt)
- `markerSize`: marker size (default: 8)
- `gridlineColor`, `gridlineWidth`, `gridlineDash`: rings
- `fontColor`, `fontSize`: text
- `legendPosition`: legend position (bottom/right/left/top)

These can be set as a `style` object:
```json
"style": {
  "lineWidth": 2.5, "markerSize": 8, "gridlineColor": "#E0E0E0",
  "fontColor": "#333", "fontSize": 10, "legendPosition": "bottom"
}
```

## Axis control

```json
"valueAxis": {"min": 0, "max": 5, "majorUnit": 1, "gridlines": true}
```

## Additional properties

- `title`: chart title text
- `titleFontSize`: title font size (default: 14)
- `titleFontColor`: title color

## JSON: Option comparison

(Example coordinates assume 16:9 canvas H=1080. Adjust y/height for other ratios.)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Option Comparison",
      "elements": [
        {
          "type": "chart",
          "chartType": "radar",
          "x": 460, "y": 173, "width": 1000, "height": 750,
          "categories": ["Cost", "Performance", "Security", "Reliability", "Operations"],
          "series": [
            {"name": "Option A", "values": [4, 3, 5, 4, 2], "color": "#FF9900"},
            {"name": "Option B", "values": [2, 5, 3, 3, 4], "color": "#41B3FF"}
          ],
          "legend": true,
          "valueAxis": {"min": 0, "max": 5, "majorUnit": 1}
        }
      ]
    }
  ]
}
```
