---
description: "Area chart JSON structure and style overrides — read when slide contains area or stacked area chart"
tags: [composer-pptx]
---

Area charts for volume over time and stacked share of a total.

## Use cases
- Cumulative or stacked volume over time (requests, active users, cost by service)
- Part-to-whole trends across time periods
- Emphasizing magnitude of change alongside trend direction

## Design points
- `stacked: false` (default) for overlapping areas; `stacked: true` for stacked area charts
- Use `stacked: true` when showing how components add up to a total
- Keep series ordered with the largest or most stable component at the bottom

**Constraints:**
- You SHOULD keep to 2–5 series because stacked layers become hard to compare past 5
- You SHOULD NOT use unstacked areas with more than 2 series because front series hide back series

## Style-adjustable properties
- `gridlineColor`, `gridlineWidth`, `gridlineDash`: gridlines
- `axisColor`, `axisWidth`: axis lines
- `fontColor`, `fontSize`: text
- `legendPosition`: legend position (bottom/right/left/top)

These can be set as a `style` object:
```json
"style": {
  "gridlineColor": "#E0E0E0", "gridlineWidth": 0.25, "gridlineDash": "dash",
  "fontColor": "#333333", "fontSize": 10, "legendPosition": "bottom"
}
```

## Axis control

```json
"valueAxis": {"min": 0, "max": 500, "majorUnit": 100, "gridlines": true, "line": "none", "tickMark": "none"},
"categoryAxis": {"tickMark": "none"}
```

## Additional properties

- `title`: chart title text
- `titleFontSize`: title font size (default: 14)
- `titleFontColor`: title color
- `numberFormat`: data label format (e.g. `"#,##0"`)

## JSON: Stacked area chart

(Example coordinates assume 16:9 canvas H=1080. Adjust y/height for other ratios.)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Monthly Compute Usage",
      "elements": [
        {
          "type": "chart",
          "chartType": "area",
          "stacked": true,
          "x": 192, "y": 216, "width": 1536, "height": 700,
          "categories": ["Jan", "Feb", "Mar", "Apr"],
          "series": [
            {"name": "Lambda", "values": [120, 150, 180, 210], "color": "#FF9900"},
            {"name": "ECS", "values": [80, 95, 90, 130], "color": "#41B3FF"}
          ],
          "legend": true,
          "dataLabels": false
        }
      ]
    }
  ]
}
```
