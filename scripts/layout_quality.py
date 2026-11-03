"""Build a gallery example with its placement stripped, for the layout tests."""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import gallery  # noqa: E402

import pandid.portgeom as portgeom_mod  # noqa: E402
import pandid.streams as streams_mod  # noqa: E402
import pandid.units as units_mod  # noqa: E402
from pandid.flowsheet import Flowsheet  # noqa: E402


@contextlib.contextmanager
def strip_placement():
    """Strip placement from every example built inside the ``with`` block.

    ``pin()`` keeps ``orientation=`` and ``mirrored=`` and drops ``col``,
    ``row``, ``x``, ``y`` and ``port``. ``Stream.via()`` does nothing, and
    ``pinned_x()``/``pinned_y()`` return ``0.0``. Restore all four on exit.
    """
    original_pin = units_mod.Unit.pin
    original_via = streams_mod.Stream.via
    original_pinned_x = portgeom_mod.pinned_x
    original_pinned_y = portgeom_mod.pinned_y

    _UNCHANGED = units_mod._UNCHANGED
    _UNSTATED = units_mod._UNSTATED

    def stripped_pin(self, *, col=None, row=None, x=None, y=None,
                      orientation=_UNCHANGED, mirrored=_UNCHANGED, port=_UNSTATED):
        return original_pin(self, col=None, row=None, x=None, y=None,
                             orientation=orientation, mirrored=mirrored, port=None)

    def stripped_via(self, waypoints):
        return self

    def dummy_axis(unit, port_name=None):
        return 0.0

    units_mod.Unit.pin = stripped_pin
    streams_mod.Stream.via = stripped_via
    portgeom_mod.pinned_x = dummy_axis
    portgeom_mod.pinned_y = dummy_axis
    try:
        yield
    finally:
        units_mod.Unit.pin = original_pin
        streams_mod.Stream.via = original_via
        portgeom_mod.pinned_x = original_pinned_x
        portgeom_mod.pinned_y = original_pinned_y


def build(stem: str, auto: bool) -> tuple[Flowsheet, dict]:
    """Build the gallery sheet *stem* afresh, with its placement stripped if *auto*.

    Parameters
    ----------
    stem : str
        Gallery sheet name.
    auto : bool
        Strip placement while the example builds.

    Returns
    -------
    tuple[Flowsheet, dict]
        The flowsheet and its render options.
    """
    if auto:
        with strip_placement():
            with contextlib.redirect_stdout(io.StringIO()):
                return gallery.flowsheet(stem)
    with contextlib.redirect_stdout(io.StringIO()):
        return gallery.flowsheet(stem)
