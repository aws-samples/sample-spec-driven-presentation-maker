---
description: "Pie/donut chart JSON structure and style overrides — read when slide contains pie/donut chart"
---

Pie/donut charts for proportions and breakdowns.

## Use cases
- Cost breakdown
- Resource allocation
- Category-level proportions

## Design points
- Percentage display by default (`numberFormat: "0%"`)
- Use `numberFormat: "#,##0"` for absolute values
- Legend is auto-placed at the bottom

**Constraints:**
- You SHOULD keep categories to 6 or fewer because small slices become unreadable

## Style-adjustable properties
- `fontColor`, `fontSize`: text
- `legendPosition`: legend position (bottom/right/left/top)

These can be set as a `style` object:
```json
"style": {"fontColor": "#333", "fontSize": 10, "legendPosition": "bottom"}
```

## Additional properties

- `title`: chart title text
- `titleFontSize`: title font size (default: 14)
- `titleFontColor`: title color
- `holeSize`: donut hole size in % (donut only)

## JSON: Cost breakdown

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Cost Distribution",
      "elements": [
        {
          "type": "chart",
          "chartType": "pie",
          "x": 300, "y": 173, "width": 1320, "height": 750,
          "categories": ["Compute", "Storage", "Network", "Other"],
          "series": [
            {"name": "Cost", "values": [45, 25, 20, 10]}
          ],
          "dataLabels": true
        }
      ]
    }
  ]
}
```

## JSON: Custom colors

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Resource Allocation",
      "elements": [
        {
          "type": "chart",
          "chartType": "pie",
          "x": 300, "y": 173, "width": 1320, "height": 750,
          "categories": ["CPU", "Memory", "Disk"],
          "series": [
            {
              "name": "Usage",
              "values": [60, 25, 15],
              "colors": ["#FF9900", "#41B3FF", "#AD5CFF"]
            }
          ],
          "dataLabels": true,
          "numberFormat": "#,##0 GB"
        }
      ]
    }
  ]
}
```

## JSON: Donut (center area can hold a total or label)

```json
{
  "slides": [
    {
      "layout": "content",
      "title": "Monthly Cost Breakdown",
      "elements": [
        {
          "type": "chart",
          "chartType": "donut",
          "x": 300, "y": 173, "width": 1320, "height": 750,
          "categories": ["Compute", "Storage", "Network", "Database", "Other"],
          "series": [
            {"name": "Cost", "values": [45, 25, 15, 10, 5]}
          ],
          "dataLabels": true
        }
      ]
    }
  ]
}
```
- `donut` is a variant of `pie`. Overlaying a text element on the center hole to show a total is an effective technique.
