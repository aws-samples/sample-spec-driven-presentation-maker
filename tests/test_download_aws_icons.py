# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for scripts.download_aws_icons — ZIP filtering and classification."""

from scripts.download_aws_icons import _classify_type, _is_target_entry


class TestIsTargetEntry:
    def test_service_48_extracted(self):
        assert _is_target_entry("Architecture-Service-Icons_01302026/Arch_Compute/48/Arch_AWS-Lambda_48.svg")

    def test_resource_48_extracted(self):
        assert _is_target_entry("Resource-Icons_01302026/Res_Compute/Res_AWS-Lambda_48_Light.svg")

    def test_category_48_extracted(self):
        assert _is_target_entry("Architecture-Category-Icons_01302026/Arch-Category_Compute_48.svg")

    def test_group_32_extracted(self):
        assert _is_target_entry("Architecture-Group-Icons_01302026/AWS-Cloud-logo_32.svg")

    def test_group_32_dark_variant_extracted(self):
        assert _is_target_entry("Architecture-Group-Icons_01302026/AWS-Cloud-logo_32_Dark.svg")

    def test_group_48_not_extracted(self):
        # Group icons live at 32px only; reject any stray 48 in the group dir.
        assert not _is_target_entry("Architecture-Group-Icons_01302026/AWS-Cloud-logo_48.svg")

    def test_service_32_not_extracted(self):
        # Service icons live at 48px in this script; reject 32 in non-group dirs.
        assert not _is_target_entry("Architecture-Service-Icons_01302026/Arch_Compute/32/Arch_AWS-Lambda_32.svg")

    def test_non_svg_not_extracted(self):
        assert not _is_target_entry("Architecture-Group-Icons_01302026/AWS-Cloud-logo_32.png")


class TestClassifyType:
    def test_group_path_classified_as_group(self):
        result = _classify_type(
            "AWS-Cloud-logo_32.svg",
            "Architecture-Group-Icons_01302026/AWS-Cloud-logo_32.svg",
        )
        assert result == "group"

    def test_service_classified_as_service(self):
        result = _classify_type(
            "Arch_AWS-Lambda_48.svg",
            "Architecture-Service-Icons_01302026/Arch_Compute/48/Arch_AWS-Lambda_48.svg",
        )
        assert result == "service"

    def test_resource_classified_as_resource(self):
        result = _classify_type(
            "Res_AWS-Lambda_48_Light.svg",
            "Resource-Icons_01302026/Res_Compute/Res_AWS-Lambda_48_Light.svg",
        )
        assert result == "resource"

    def test_category_classified_as_category(self):
        result = _classify_type(
            "Arch-Category_Compute_48.svg",
            "Architecture-Category-Icons_01302026/Arch-Category_Compute_48.svg",
        )
        assert result == "category"
