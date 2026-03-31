# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared constants for builder modules.

Contains tool-default design tokens (not brand-specific).
Brand-specific values (fonts, theme colors) are supplied via presentation.json.
"""

# Night Owl syntax highlighting colors
# Based on Night Owl theme by Sarah Drasner (MIT License)
# https://github.com/sdras/night-owl-vscode-theme
CODE_COLORS = {
    "dark": {
        "background": "#011627",
        "keyword": "#c792ea",
        "string": "#ecc48d",
        "number": "#F78C6C",
        "comment": "#637777",
        "function": "#82AAFF",
        "class": "#ffcb8b",
        "variable": "#d6deeb",
        "operator": "#7fdbca",
        "boolean": "#ff5874",
        "property": "#7fdbca",
        "decorator": "#c5e478",
    },
    "light": {
        "background": "#FBFBFB",
        "keyword": "#994cc3",
        "string": "#c96765",
        "number": "#aa0982",
        "comment": "#989fb1",
        "function": "#4876d6",
        "class": "#111111",
        "variable": "#403f53",
        "operator": "#0c969b",
        "boolean": "#bc5454",
        "property": "#0c969b",
        "decorator": "#4876d6",
    }
}

# AWS Architecture diagram group definitions
# Colors follow official AWS Architecture Icon guidelines
ARCH_GROUP_DEFS = {
    "aws-cloud":                ("#FFFFFF", None,      "icons:AWS-Cloud-logo_32",                "top-left",   "left"),
    "region":                   ("#00A4A6", "sysDash", "icons:Region_32",                        "top-left",   "left"),
    "az":                       ("#00A4A6", "dash",    None,                                     None,         "center"),
    "vpc":                      ("#8C4FFF", None,      "icons:Virtual-private-cloud-VPC_32",     "top-left",   "left"),
    "private-subnet":           ("#00A4A6", None,      "icons:Private-subnet_32",                "top-left",   "left"),
    "public-subnet":            ("#7AA116", None,      "icons:Public-subnet_32",                 "top-left",   "left"),
    "security-group":           ("#DD344C", None,      None,                                     None,         "left-no-icon"),
    "auto-scaling":             ("#ED7100", "dash",    "icons:Auto-Scaling-group_32",            "top-center", "center"),
    "account":                  ("#E7157B", None,      "icons:AWS-Account_32",                   "top-left",   "left"),
    "corporate-datacenter":     ("#7D8998", None,      "icons:Corporate-data-center_32",         "top-left",   "left"),
    "server-contents":          ("#7D8998", None,      "icons:Server-contents_32",               "top-left",   "left"),
    "ec2-instance":             ("#ED7100", None,      "icons:EC2-instance-contents_32",         "top-left",   "left"),
    "spot-fleet":               ("#ED7100", None,      "icons:Spot-Fleet_32",                    "top-left",   "left"),
    "ebs-container":            ("#ED7100", None,      "icons:Arch_AWS-Elastic-Beanstalk_48",   "top-left",   "left"),
    "step-functions":           ("#E7157B", None,      "icons:Arch_AWS-Step-Functions_48",       "top-left",   "left"),
    "iot-greengrass":           ("#7AA116", None,      "icons:Arch_AWS-IoT-Greengrass_48",      "top-left",   "left"),
    "iot-greengrass-deployment":("#7AA116", None,      "icons:AWS-IoT-Greengrass-Deployment_32","top-left",   "left"),
    "generic":                  ("#7D8998", None,      None,                                     None,         "center"),
    "generic-dashed":           ("#7D8998", "dash",    None,                                     None,         "center"),
}
