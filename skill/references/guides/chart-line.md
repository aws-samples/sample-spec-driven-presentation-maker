---
description: "Line chart JSON structure and style overrides — read when slide contains line/trend chart"
---

Line charts for time-series and trend data.

## Use cases
- Throughput/latency trends during load tests
- Time-series performance data
- Trend comparison

## Design points
- Markers are shown by default (data points are clear)
- `smooth: true` for smooth curves (good for trend display)

**Constraints:**
- You SHOULD NOT put two series with vastly different scales on the same chart because the smaller series gets crushed

## Style-adjustable properties
- `lineWidth`: line thickness (default: 2.5pt)
- `markerSize`: marker size (default: 8)
- `gridlineColor`, `gridlineWidth`, `gridlineDash`: gridlines
- `fontColor`, `fontSize`: text
- `legendPosition`: legend position (bottom/right/left/top)

These can be set as a `style` object:
```json
"style": {
  "lineWidth": 2.5, "markerSize": 8, "gridlineColor": "#E0E0E0",
  "gridlineWidth": 0.25, "gridlineDash": "dash",
  "fontColor": "#333", "fontSize": 10, "legendPosition": "bottom"
}
```

## Axis control

```json
"valueAxis": {"min": 0, "max": 1000, "majorUnit": 200, "gridlines": true, "line": "none", "tickMark": "none"},
"categoryAxis": {"tickMark": "none"}
```

## Additional properties

- `title`: chart title text
- `titleFontSize`: title font size (default: 14)
- `titleFontColor`: title color

## JSON: Load test trend

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Load Test Results",
      "elements": [
        {
          "type": "chart",
          "chartType": "line",
          "x": 58, "y": 173, "width": 1804, "height": 750,
          "categories": ["0s", "10s", "20s", "30s", "40s", "50s", "60s"],
          "series": [
            {"name": "Throughput (req/s)", "values": [100, 450, 800, 1200, 1150, 1180, 1200], "color": "#FF9900"},
            {"name": "Latency (ms)", "values": [5, 8, 12, 15, 14, 15, 15], "color": "#41B3FF"}
          ]
        }
      ]
    }
  ]
}
```

## JSON: No markers, smooth curve

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Growth Trend",
      "elements": [
        {
          "type": "chart",
          "chartType": "line",
          "markers": false,
          "smooth": true,
          "x": 58, "y": 173, "width": 1804, "height": 750,
          "categories": ["Q1", "Q2", "Q3", "Q4"],
          "series": [
            {"name": "Revenue", "values": [100, 150, 180, 250], "color": "#FF9900"}
          ],
          "dataLabels": true
        }
      ]
    }
  ]
}
```
