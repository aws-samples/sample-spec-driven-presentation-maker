# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The runtimes' random-module values do not repeat across V2 restores (shared/snapshot_random.py).

A restore is simulated by putting the module's hidden generator back to a saved state:
every restored microVM starts from the same one.
"""

import random
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

from shared import snapshot_random

_SERVER = Path(__file__).resolve().parents[1] / "servers" / "remote" / "server.py"


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


def test_installed_jitter_differs_after_the_same_restore(installed):
    first, second = _restore_twice(lambda: [random.uniform(0, 1) for _ in range(4)])
    assert first != second


def test_install_is_idempotent_and_keeps_the_seed_functions(installed):
    seed, getstate = random.seed, random.getstate
    snapshot_random.install()
    assert random.seed is seed and random.getstate is getstate
    assert random.getrandbits.__self__.__class__ is random.SystemRandom


def test_the_mcp_server_installs_it_before_uvicorn_starts():
    main = _SERVER.read_text().split('if __name__ == "__main__":', 1)[1]
    assert main.index("snapshot_random.install()") < main.index("uvicorn.run(")
