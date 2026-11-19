---
description: "Scatter chart JSON structure and style overrides — read when slide contains XY scatter plot"
---

Scatter charts for plotting two numeric variables against each other.

## Use cases
- Latency vs. payload size or memory configuration
- Cost vs. throughput trade-off curves
- Before/after or multi-variant benchmark comparisons

## Design points
- Each series uses `points` (a list of `[x, y]` numeric pairs) instead of `values`, and no `categories` key is needed
- Series `color` sets the marker color; markers are shown without connecting lines
- Set `valueAxis` (`min` / `max` / `majorUnit` / `gridlines`) to control the Y axis

**Constraints:**
- You SHOULD keep to 2–4 series with distinct colors so overlapping clusters stay legible
- You SHOULD include axis units in the chart title or subtitle because X and Y are both numeric

## Style-adjustable properties
- `markerSize`: marker size (default: 8)
- `gridlineColor`, `gridlineWidth`, `gridlineDash`: Y-axis gridlines
- `axisColor`, `axisWidth`: axis lines
- `fontColor`, `fontSize`: text
- `legendPosition`: legend position (bottom/right/left/top)

These can be set as a `style` object:
```json
"style": {
  "markerSize": 8, "gridlineColor": "#E0E0E0",
  "gridlineWidth": 0.25, "gridlineDash": "dash",
  "fontColor": "#333333", "fontSize": 10, "legendPosition": "bottom"
}
```

## Axis control

```json
"valueAxis": {"min": 0, "max": 100, "majorUnit": 20, "gridlines": true}
```

## Additional properties

- `title`: chart title text
- `titleFontSize`: title font size (default: 14)
- `titleFontColor`: title color

## JSON: Latency vs. memory

(Example coordinates assume 16:9 canvas H=1080. Adjust y/height for other ratios.)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Latency by Memory Allocation",
      "elements": [
        {
          "type": "chart",
          "chartType": "scatter",
          "x": 192, "y": 216, "width": 1536, "height": 700,
          "series": [
            {"name": "Lambda", "points": [[128, 45], [256, 30], [512, 22], [1024, 18]], "color": "#FF9900"},
            {"name": "Fargate", "points": [[128, 60], [512, 35], [1024, 25]], "color": "#41B3FF"}
          ],
          "legend": true,
          "valueAxis": {"min": 0},
          "title": "Latency (ms) by memory (MB)"
        }
      ]
    }
  ]
}
```
