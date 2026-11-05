---
description: "AWS-specific design conventions — read when building AWS service content"
---

# AWS Design Guide

Design guide for AWS architecture diagrams and AWS service introduction slides.

## Icon selection

- General concepts → `search-assets --type general`
- Actual AWS services → `search-assets -s aws` to find the corresponding AWS icon

## AWS service category colors

Official colors for representing services by category. Used for group borders, card borders, section color-coding, etc.
The bundled `aws-light` / `aws-dark` styles carry the same values as `--cat-<category>` tokens (plus a per-background `--cat-<category>-tint` for filled areas) — when one of them is the deck's style, use the tokens rather than this table.

| Color | Code | Category |
|-------|------|----------|
| Purple | #8C4FFF | Analytics, Games, Networking Content Delivery, Serverless |
| Pink | #E7157B | Application Integration, Management & Governance |
| Green | #7AA116 | Cloud Financial Management, Internet of Things, Storage |
| Teal | #01A88D | Artificial Intelligence, End User Computing, Migration & Modernization |
| Orange | #ED7100 | Blockchain, Compute, Containers, Media Services, Quantum Technologies |
| Red | #DD344C | Business Applications, Contact Center, Front End Web & Mobile, Robotics, Security Identity & Compliance |
| Magenta | #C925D1 | Customer Enablement, Databases, Developer Tools, Satellite |

Identify the category from the `[category/service]` display in `search-assets`, then look up the color in this table.
