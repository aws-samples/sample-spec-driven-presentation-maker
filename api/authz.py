# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""API authorization — enforces resource-level access control.

All API operations are authorized based on resource ownership and role.
See shared/authz.py for the RBAC implementation.

API authorization — re-exports from shared.authz.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

This module exists for backward compatibility. All authorization logic
lives in shared/authz.py.
"""

from shared.authz import AccessDecision, authorize, resolve_role, check_permission  # noqa: F401

__all__ = ["AccessDecision", "authorize", "resolve_role", "check_permission"]
