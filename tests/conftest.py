"""Shared fixtures."""

import pytest

from pandid import Flowsheet, units as U

from _render_cases import gallery


@pytest.fixture(scope="session")
def settled_gallery() -> dict[str, tuple[Flowsheet, dict]]:
    """Build every gallery flowsheet and settle its geometry once per test run.

    Returns
    -------
    dict
        Routed flowsheets and render options keyed by gallery example name.

    Notes
    -----
    Consumers copy a case before rendering or mutating it. The fixture owns
    cold layout and routing; each test owns its output and mutations.
    """
    cases = {}
    for stem in gallery.sheets():
        fs, kwargs = gallery.flowsheet(stem)
        fs.layout()
        fs.route()
        cases[stem] = fs, kwargs
    return cases


@pytest.fixture
def gapped_kind():
    """Provide a unit type with two unanchored ports.

    Yields
    ------
    type[U.Unit]
        Test-only unit class with anchored inlet/outlet and unanchored spares.
    """
    from pandid.render.symbols import Symbol, default_registry

    class Gapped(U.Unit):
        """Test unit that exercises fallback placement for unanchored ports."""

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
