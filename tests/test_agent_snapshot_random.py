# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent installs shared/snapshot_random.py before it serves, and its ids then differ
across V2 restores.

A restore is simulated by putting the random module's hidden generator back to a saved
state: every restored microVM starts from the same one.
"""

import random
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

from shared import snapshot_random

_AGENT = Path(__file__).resolve().parents[1] / "agent"


@pytest.fixture
def installed():
    saved = {name: getattr(random, name) for name in dir(random) if callable(getattr(random, name))}
    snapshot_random.install()
    yield
    for name, value in saved.items():
        setattr(random, name, value)


def _restore_twice(draw):
    state = random.getstate()
    first = draw()
    random.setstate(state)
    second = draw()
    return first, second


def test_without_install_a_restored_state_repeats_the_ids():
    ids = RandomIdGenerator()
    first, second = _restore_twice(lambda: (ids.generate_trace_id(), ids.generate_span_id()))
    assert first == second


def test_installed_trace_and_span_ids_differ_after_the_same_restore(installed):
    ids = RandomIdGenerator()
    first, second = _restore_twice(lambda: (ids.generate_trace_id(), ids.generate_span_id()))
    assert first[0] != second[0]
    assert first[1] != second[1]


def test_the_agent_installs_it_before_the_server_starts():
    source = (_AGENT / "basic_agent.py").read_text()
    main = source.split("def main(", 1)[1]
    assert main.index("snapshot_random.install()") < main.index("app.run(")


def test_the_agent_image_copies_the_shared_module():
    dockerfile = (_AGENT / "Dockerfile").read_text()
    assert "shared/snapshot_random.py" in dockerfile
