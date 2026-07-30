# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Server authorization — re-exports from shared.authz.

This module exists for backward compatibility. All authorization logic
lives in shared/authz.py.
"""

from shared.authz import AccessDecision, authorize, resolve_role, check_permission  # noqa: F401

__all__ = ["AccessDecision", "authorize", "resolve_role", "check_permission"]
