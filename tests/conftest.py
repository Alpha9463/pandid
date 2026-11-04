"""Shared fixtures."""

import os
from collections.abc import Callable

import pytest

from pandid import Flowsheet, units as U

from _render_cases import copy_settled_case, gallery


@pytest.fixture(scope="session")
def settled_gallery() -> dict[str, tuple[Flowsheet, dict]]:
    """Build every gallery flowsheet and settle its geometry once per test run.

    Returns
    -------
    dict
        Routed flowsheets and render options keyed by gallery example name.

    Notes
    -----
    Copy a case with ``copy_settled_case`` before rendering or mutating it.
    """
    cases = gallery.captures()
    for fs, _kwargs in cases.values():
        fs.layout()
        fs.route()
    return cases


@pytest.fixture(scope="session")
def corpus_svg(settled_gallery) -> dict[str, tuple[Flowsheet, dict, str]]:
    """Render every line-number corpus sheet once with the options it ships with.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict]]
        Routed gallery flowsheets and render options.

    Returns
    -------
    dict[str, tuple[Flowsheet, dict, str]]
        Flowsheet, render options and SVG keyed by corpus name.

    Notes
    -----
    The label, halo and debug-overlay checks share these flowsheets; read them, never change them.
    """
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
    """Record what ``show()`` hands the preview instead of opening a window.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces ``pandid.render.preview.preview`` with a recorder.

    Returns
    -------
    dict[str, str]
        The ``svg`` and ``title`` of the last call; empty if nothing was shown.
    """
    from pandid.render import preview as P

    seen: dict[str, str] = {}

    def fake(svg: str, *, title: str = "") -> str:
        """Record one preview call.

        Parameters
        ----------
        svg : str
            Rendered SVG markup.
        title : str, default=""
            Flowsheet title.

        Returns
        -------
        str
            ``"window"``, as a successful preview returns.
        """
        seen["svg"], seen["title"] = svg, title
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    return seen


@pytest.fixture
def same_file() -> Callable[[str], str]:
    """Provide a function that returns a path as the file system resolves and compares it.

    Returns
    -------
    Callable[[str], str]
        Path normaliser for comparing a warning's file with ``__file__``.
    """
    return lambda path: os.path.normcase(os.path.realpath(path))


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
