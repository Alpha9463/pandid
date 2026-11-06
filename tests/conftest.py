"""Shared fixtures."""

import os
from collections.abc import Callable

import pytest

from pandid import Flowsheet, units as U

from _render_cases import copy_settled_case, gallery


@pytest.fixture(scope="session")
def settled_gallery() -> dict[str, tuple[Flowsheet, dict]]:
    """Build every gallery flowsheet and settle its geometry once per test run."""
    cases = gallery.captures()
    for fs, _kwargs in cases.values():
        fs.layout()
        fs.route()
    return cases


@pytest.fixture(scope="session")
def corpus_svg(settled_gallery) -> dict[str, tuple[Flowsheet, dict, str]]:
    """Render every line-number corpus sheet once with the options it ships with."""
    from test_label_invariants import _RENDER_OPTS, CORPUS

    out = {}
    for name, build in CORPUS.items():
        fs, kwargs = (
            copy_settled_case(settled_gallery, name) if name in settled_gallery else build()
        )
        options = {k: v for k, v in kwargs.items() if k in _RENDER_OPTS}
        out[name] = fs, options, fs.to_svg(**options)
    return out


@pytest.fixture
def caught(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Record what ``show()`` hands the preview instead of opening a window."""
    from pandid.render import preview as P

    seen: dict[str, str] = {}

    def fake(svg: str, *, title: str = "") -> str:
        """Record one preview call."""
        seen["svg"], seen["title"] = svg, title
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    return seen


@pytest.fixture
def same_file() -> Callable[[str], str]:
    """Provide a function that returns a path as the file system resolves and compares it."""
    return lambda path: os.path.normcase(os.path.realpath(path))


@pytest.fixture
def gapped_kind():
    """Provide a unit type with two unanchored ports."""
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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep the tests that share a module fixture on one xdist worker."""
    for item in items:
        defs = getattr(item, "_fixtureinfo").name2fixturedefs.values()
        if any(d[-1].scope == "module" for d in defs):
            item.add_marker(pytest.mark.xdist_group(item.module.__name__))
