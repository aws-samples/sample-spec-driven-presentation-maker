# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Draw the ``random`` module's values from the kernel, so V2 restores do not repeat them.

AgentCore Runtime platform V2 restores every microVM from one snapshot taken after
startup. The ``random`` module is seeded at import, so without this every restored
instance would produce the same sequence. Libraries in the runtime processes call its
module-level functions at use time: OpenTelemetry's trace and span id generators
(``random.getrandbits``, including the X-Ray id generator) and botocore's retry
jitter. Rebinding those functions to a ``random.SystemRandom`` reads ``os.urandom`` on
every call, which is fresh after a restore
([Optimize for V2](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-v2-optimize.html)).

Call install() from the process entry point, before the server starts (and so before
the snapshot); importing this module changes nothing, so tests that import a server
module keep the seeded ``random``.

``random.seed`` / ``getstate`` / ``setstate`` and ``random.Random`` instances are left
alone. A module that bound a function by name before install() (``from random import
randrange``, as OpenTelemetry's metric exemplar reservoir does) keeps the seeded one;
none of those produce ids.
"""

import random

_SYSTEM = random.SystemRandom()

# The module-level functions that are bound methods of random's hidden Random instance.
_FUNCTIONS = (
    "random", "uniform", "triangular", "randint", "randrange", "choice", "choices",
    "shuffle", "sample", "getrandbits", "randbytes", "binomialvariate", "normalvariate",
    "lognormvariate", "expovariate", "vonmisesvariate", "gammavariate", "gauss",
    "betavariate", "paretovariate", "weibullvariate",
)


def install() -> None:
    """Rebind the ``random`` module's functions to the kernel-backed generator (idempotent)."""
    for name in _FUNCTIONS:
        if hasattr(random, name):
            setattr(random, name, getattr(_SYSTEM, name))
