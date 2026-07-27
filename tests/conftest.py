"""Shared fixtures."""

import pytest

from pfd import units as U


@pytest.fixture
def gapped_kind():
    """A unit kind whose symbol forgets two of the unit's ports.

    No shipped symbol has this gap: every port a built-in unit declares is
    either anchored or placed by a :class:`~pfd.render.symbols.PortSeries`. The
    centre-of-the-box fallback is still reachable, though — it is what any
    symbol registered from outside this package gets when it anchors fewer
    ports than its unit declares. Tests covering that fallback build their own
    specimen here rather than leaning on a gap in the shipped registry, which
    would leave them silently exercising nothing once it was closed.

    ``spare_a`` and ``spare_b`` are the unanchored pair; ``inlet``/``outlet``
    are anchored, so a test can tell the two cases apart on one unit.
    """
    from pfd.render.symbols import Symbol, default_registry

    class Gapped(U.Unit):
        kind = "gapped_test_unit"
        PORTS = [
            ("inlet", "inlet", "process"),
            ("outlet", "outlet", "process"),
            ("spare_a", "inlet", "process"),
            ("spare_b", "inlet", "process"),
        ]

    default_registry.register(
        Gapped.kind,
        Symbol(
            svg=(
                '<g id="sym_gapped_test_unit"><rect x="0" y="0" width="50" '
                'height="50" fill="none" stroke="black" stroke-width="2"/></g>'
            ),
            width=50.0,
            height=50.0,
            ports={"inlet": (0.0, 25.0), "outlet": (50.0, 25.0)},
        ),
    )
    yield Gapped
    default_registry._symbols.pop((Gapped.kind, "default"), None)
