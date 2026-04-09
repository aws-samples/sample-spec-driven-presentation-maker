---
description: "Bar chart JSON structure and style overrides — read when slide contains bar/column chart"
---

Bar charts (vertical, horizontal, stacked) for comparison data.

## Use cases
- Latency/cost comparison across services
- Before/after improvement effects
- Component-level breakdown (stacked)

## Design points
- Single series: legend is auto-hidden (category axis is sufficient)
- `numberFormat` controls data label format (`"$#,##0"`, `"#,##0"`, etc.)

**Constraints:**
- You SHOULD set `dataLabels: false` for stacked bars with small segments (<10% of total) because labels overlap and become unreadable

## Variations
- `stacked: true` → stacked bar
- `horizontal: true` → horizontal bar
- Both → horizontal stacked bar

## Style-adjustable properties
- `gapWidth`: gap between bars (default: clustered=80, stacked=60)
- `overlap`: overlap between clustered bars (default: -10, negative=gap, positive=overlap)
- `gridlineColor`, `gridlineWidth`, `gridlineDash`: gridlines
- `axisColor`, `axisWidth`: axis lines
- `fontColor`, `fontSize`: text
- `legendPosition`: legend position (bottom/right/left/top)

These can be set either as top-level `style` object or individually:
```json
"style": {
  "gapWidth": 80, "gridlineColor": "#E0E0E0", "gridlineWidth": 0.25,
  "gridlineDash": "dash", "axisColor": "#CCC", "axisWidth": 0.5,
  "fontColor": "#333", "fontSize": 10, "legendPosition": "bottom"
}
```

## Axis control

```json
"valueAxis": {"min": 0, "max": 100, "majorUnit": 20, "gridlines": true, "line": "none", "tickMark": "none"},
"categoryAxis": {"tickMark": "none"}
```

- `gridlines: false` removes gridlines entirely
- `line: "none"` hides the axis line
- `tickMark: "none"` hides tick marks

## Additional properties

- `title`: chart title text
- `titleFontSize`: title font size (default: 14)
- `titleFontColor`: title color
- `pointColors`: per-bar colors `{"0": "#FF0000", "2": "#00FF00"}` (index → color)

## JSON: Vertical bar (comparison)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Latency Comparison",
      "elements": [
        {
          "type": "chart",
          "chartType": "bar",
          "x": 58, "y": 173, "width": 1804, "height": 750,
          "categories": ["Lambda", "ECS", "EC2"],
          "series": [
            {"name": "p50 (ms)", "values": [12, 45, 89], "color": "#FF9900"},
            {"name": "p99 (ms)", "values": [34, 120, 250], "color": "#41B3FF"}
          ],
          "dataLabels": true,
          "numberFormat": "#,##0"
        }
      ]
    }
  ]
}
```

## JSON: Horizontal bar (cost comparison)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Monthly Cost",
      "elements": [
        {
          "type": "chart",
          "chartType": "bar",
          "horizontal": true,
          "x": 58, "y": 173, "width": 1804, "height": 750,
          "categories": ["Lambda", "ECS", "EC2"],
          "series": [
            {"name": "Cost ($/month)", "values": [120, 450, 890]}
          ],
          "dataLabels": true,
          "numberFormat": "$#,##0"
        }
      ]
    }
  ]
}
```

## JSON: Stacked bar (breakdown)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Cost Breakdown",
      "elements": [
        {
          "type": "chart",
          "chartType": "bar",
          "stacked": true,
          "x": 58, "y": 173, "width": 1804, "height": 750,
          "categories": ["Lambda", "ECS", "EC2"],
          "series": [
            {"name": "Compute", "values": [80, 300, 600]},
            {"name": "Storage", "values": [20, 80, 150]},
            {"name": "Network", "values": [20, 70, 140]}
          ]
        }
      ]
    }
  ]
}
```
