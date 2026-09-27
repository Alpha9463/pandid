"""Settle derived faces, controls, labels, and routes on proposed frames."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.routing import Router


def geometry_state(fs: Flowsheet) -> tuple:
    """Capture geometry that can change face and control placement.

    Parameters
    ----------
    fs : Flowsheet
        Drawing after a settlement pass.

    Returns
    -------
    tuple
        Frames, selected faces, labels, and control taps in unit order.
    """
    return tuple(
        None
        if unit.frame is None
        else (
            unit.frame.x,
            unit.frame.y,
            unit.frame.w,
            unit.frame.h,
            unit.frame.label_pos,
            tuple(sorted(unit.frame.port_faces.items())),
            getattr(unit, "tap", None),
        )
        for unit in fs.units
    )


def settle(
    fs: Flowsheet,
    router: Router | None = None,
    *,
    face_choices: tuple[tuple[int, str, str], ...] = (),
) -> None:
    """Resolve proposed frames to a completed, final-box route drawing.

    Parameters
    ----------
    fs : Flowsheet
        Detached drawing with its proposed frames installed.
    router : Router or None, optional
        Router used on every settlement pass.
    face_choices : tuple[tuple[int, str, str], ...], optional
        Trial-only automatic face preferences.

    Returns
    -------
    None
        Settled geometry and route status are stored on ``fs``.
    """
    from pandid.layout.attach import MAX_PLACEMENT_PASSES
    from pandid.layout.control import place_control
    from pandid.layout.coordinates import assign_labels
    from pandid.layout.faces import select_faces
    from pandid.routing import DefaultRouter

    active_router = DefaultRouter() if router is None else router
    preferred = {(index, port): face for index, port, face in face_choices}
    fs.route_converged = False
    for _ in range(MAX_PLACEMENT_PASSES):
        select_faces(fs, preferred)
        assign_labels(fs)
        before = geometry_state(fs)
        active_router.route(fs)
        moved = place_control(fs)
        if not moved and geometry_state(fs) == before:
            fs.route_converged = True
            fs._route_stale = False
            return

    # The cap leaves a coherent route against the final boxes even when
    # attached controls do not reach a fixed point.
    select_faces(fs, preferred)
    assign_labels(fs)
    active_router.route(fs)
    fs._route_stale = False
