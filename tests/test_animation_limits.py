# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Resource boundaries for untrusted animation/transition XML."""

import pytest

from sdpm.engine.timing import (
    MAX_TIMING_XML_DEPTH,
    MAX_TIMING_XML_ELEMENTS,
    TimingXmlLimitError,
    validate_xml_resource_limits,
)
from sdpm.tools.attachment.limits import (
    MAX_RAW_SIZE_BYTES,
    MAX_ZIP_COMPRESSION_RATIO,
    MAX_ZIP_ENTRIES,
    MAX_ZIP_SINGLE_ENTRY,
    MAX_ZIP_TOTAL_UNCOMPRESSED,
)


def test_motion_limits_match_spec_and_existing_attachment_contract():
    assert MAX_RAW_SIZE_BYTES == 100 * 1024 * 1024
    assert MAX_ZIP_ENTRIES == 10_000
    assert MAX_ZIP_TOTAL_UNCOMPRESSED == 500 * 1024 * 1024
    assert MAX_ZIP_SINGLE_ENTRY == 100 * 1024 * 1024
    assert MAX_ZIP_COMPRESSION_RATIO == 100
    assert MAX_TIMING_XML_DEPTH == 256
    assert MAX_TIMING_XML_ELEMENTS == 100_000


def test_xml_limit_accepts_values_at_boundary():
    validate_xml_resource_limits(b"<a><b><c/></b></a>", max_depth=3, max_elements=3)


def test_xml_limit_rejects_depth_above_boundary():
    with pytest.raises(TimingXmlLimitError, match="depth 2"):
        validate_xml_resource_limits(b"<a><b><c/></b></a>", max_depth=2, max_elements=10)


def test_xml_limit_rejects_element_count_above_boundary():
    with pytest.raises(TimingXmlLimitError, match="2 elements"):
        validate_xml_resource_limits(b"<a><b/><c/></a>", max_depth=3, max_elements=2)


@pytest.mark.parametrize(
    "xml",
    [
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>',
        b'<!ENTITY e "x"><x/>',
    ],
)
def test_xml_limit_rejects_dtd_and_entity_declarations(xml):
    with pytest.raises(TimingXmlLimitError, match="forbidden"):
        validate_xml_resource_limits(xml)


def test_xml_limit_rejects_invalid_xml():
    with pytest.raises(TimingXmlLimitError, match="invalid"):
        validate_xml_resource_limits(b"<timing>")
