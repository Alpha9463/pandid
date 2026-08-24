"""Single source of truth for unit sizing and port geometry.

Layout, routing, and rendering all resolve a unit's size and its port
positions *here*, so the drawn diagram and the routed paths can never
disagree: the renderer cannot forget a mirror flip the router applied
and leave a mirrored unit's streams visually disconnected.

:func:`resolve_port` is the single authority on where a port is: it
answers the port's drawn point, its routing anchor and its face
together, and :func:`port_point`, :func:`port_anchor` and
:func:`port_offset` are wrappers over it. The rest are its peers, not
its wrappers -- sizing, the symbol-to-box transform, the ink box, the
face a coordinate comes out of -- and are what it is built from.
Deriving a port's point, anchor or face anywhere else is the bug. Which
of a port's declared faces it puts the ink on comes from
:func:`chosen_face`, so there is one precedence (the author's, then the
engine's, then the symbol's) and one place stating it.

The placement is a parameter rather than something read off the unit, so
these work during layout (on a ``_Slot``) and afterwards (on a
``Frame``) alike. Where it is optional -- :func:`port_faces`,
:func:`resolve_size`, :func:`port_offset` -- it falls back to the unit's
own pin, then its frame; a caller about to change either must pass its
candidate, since the committed one describes a sheet on its way out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from pandid.units import Unit


def _sym(unit: "Unit"):
    from pandid.render.symbols import default_registry
    return default_registry.for_unit(unit)


def _anchor(unit: "Unit", port_name: str) -> str:
    """The name the unit's *symbol* anchors ``port_name`` under.

    Almost always the port's own name: a symbol is authored against the
    class that draws it, so the two vocabularies are one. A class that
    renames a nozzle its drawing already ships under says so in
    :attr:`pandid.units.Unit.PORT_ANCHORS`, and this is the single place
    the rename is applied -- everything here that asks the artwork about
    a port asks through it, so a renamed nozzle lands on the ink the
    original does rather than on the box-centre fallback a name the
    symbol never heard of gets.

    Asked of the *unit* rather than read off its class, because the one
    class whose nozzle names are not all known when it is written
    (:class:`~pandid.units.Instrument`, which mints a signal connection
    per line) has to answer by rule instead of from a dict. See
    :meth:`pandid.units.Unit._symbol_anchor`.
    """
    return unit._symbol_anchor(port_name)


def _xform(frame) -> tuple[int, bool, bool]:
    """Read (orientation, mirror_x, mirror_y) off a Frame or _Slot."""
    return (int(getattr(frame, "orientation", 0) or 0),
            bool(getattr(frame, "mirrored", False)),
            bool(getattr(frame, "mirror_y", False)))


def symbol_to_box(px: float, py: float, sw: float, sh: float,
                  rot: int = 0, mirror_x: bool = False, mirror_y: bool = False
                  ) -> tuple[float, float, float, float]:
    """Map a point from a symbol's coordinates into its placed box.

    Mirroring is applied first (in the symbol's frame), then the
    clockwise quarter turn, the same order the renderer's SVG transform
    composes in, so ports and artwork can never drift apart. Returns
    ``(x, y, box_w, box_h)``; a quarter turn swaps the box's width and
    height.
    """
    if mirror_x:
        px = sw - px
    if mirror_y:
        py = sh - py
    if rot == 90:
        return sh - py, px, sh, sw
    if rot == 180:
        return sw - px, sh - py, sw, sh
    if rot == 270:
        return py, sw - px, sh, sw
    return px, py, sw, sh


def ink_box(bw: float, bh: float, w: float, h: float, stretchable: bool = True
            ) -> tuple[float, float, float, float]:
    """Where a symbol's artwork lands inside a ``w`` x ``h`` placed box.

    Returns ``(x, y, width, height)`` relative to the box's top-left.
    ``bw`` x ``bh`` is the symbol's own box, already turned by
    :func:`symbol_to_box` if the placement turns it.

    A stretchable symbol fills the box, so the whole of it is ink and
    the mapping is the plain linear one. A symbol that may not be
    distorted keeps its aspect and is centred, exactly as an SVG
    ``<symbol>`` does under its default
    ``preserveAspectRatio="xMidYMid meet"``, which leaves whitespace
    along one axis that the box edge is on and the drawing is not.
    Resolving a port against the *box* there is the bug this exists to
    prevent: the nozzle lands out in the letterbox and its stream stops
    short of the equipment.
    """
    if stretchable:
        return 0.0, 0.0, w, h
    scale = min(w / bw, h / bh)
    iw, ih = bw * scale, bh * scale
    return (w - iw) / 2, (h - ih) / 2, iw, ih


def port_faces(unit: "Unit", port_name: str, placed=None) -> list[str]:
    """Faces this port may be piped from as drawn, best first.

    The symbol authors an exact coordinate per face, so an alternate
    placement still lands on drawn ink. Answers in the same frame of
    reference as :meth:`pandid.units.Unit.nozzle` takes its argument,
    which is why it has to apply the mirror the way :func:`resolve_port`
    does rather than report the symbol's own faces.

    ``placed`` is the placement to answer for: a
    :class:`~pandid.geometry.Pin` or :class:`~pandid.geometry.Frame`. It
    defaults to the unit's own, preferring the *pin* over the frame: the
    transform is intent, which layout copies onto the frame, so a
    ``pin()`` already made describes the sheet that is coming rather
    than the one it replaces. A caller about to change the pin must pass
    its candidate, since answering from the committed one answers about
    a sheet that is on its way out.

    A port the symbol never anchored answers with the one face its
    box-centre fallback comes out of, not with nothing:
    :func:`resolve_port` places it and gives it a face, and an answer of
    "nowhere" here would be a claim about the engine that the engine
    does not honour. See :func:`is_anchored`.
    """
    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mx, my = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    return list(_drawn_placements(unit, port_name, w, h, rot, mx, my))


def unreachable_face(unit: "Unit", port_name: str, face: str,
                     options: list[str]) -> ValueError:
    """The error for a face this port cannot take as transformed.

    Built here so the message :meth:`pandid.units.Unit.nozzle` raises up
    front and the one the resolver raises later are the same sentence
    about the same rule.
    """
    # Every port resolves *somewhere*, so the list is never empty and
    # there is no "nowhere" case to word.
    offered = " or ".join(filter(None, [", ".join(options[:-1]), *options[-1:]]))
    return ValueError(
        f"{unit.name}.{port_name} can be piped from {offered} as drawn; "
        f"you asked for {face!r}"
    )


def _drawn_placements(unit: "Unit", port_name: str, w: float, h: float,
                      rot: int, mirrored: bool, mirror_y: bool
                      ) -> dict[str, tuple[float, float]]:
    """Every declared placement of a port, keyed by drawn face.

    The menu is authored in the symbol's own frame; mapping it through
    the placement transform *here* is what lets a caller name a face on
    the finished sheet without redoing the mirror arithmetic.
    Coordinates come back relative to the unit's top-left, in resolved
    pixels. Two placements can collapse onto one face after a quarter
    turn, in which case the more-preferred one wins.

    :func:`outward_dir` is asked about the *anchor* rather than the port
    name, because it holds the one rule that is stated per name -- a
    flag's pennant points east on a feed and west on a product whatever
    its coordinate says -- and a name the drawing does not know cannot
    be matched against it. A boundary flag carrying several runs spells
    its second one ``outlet_2``, which resolves to the ``outlet``
    anchor; without this it would take the plain nearest-edge answer
    and the run would be drawn leaving the flag through its top.

    The map onto the box goes through :func:`ink_box`, so a symbol that
    keeps its aspect puts its ports on the artwork rather than on the
    box edge the artwork no longer reaches. The face each lands on is
    read in the artwork's own rectangle for the same reason: a balloon's
    west tap is on the west of the *circle*, whatever the box around it
    is shaped like.
    """
    sym = _sym(unit)
    anchor = _anchor(unit, port_name)
    menu = (getattr(sym, "port_faces", None) or {}).get(anchor)
    if menu:
        coords = list(menu.values())
    elif (placed := _series_point(unit, sym, port_name)) is not None:
        coords = [placed]
    else:
        # A port the symbol does not anchor falls back to the centre of
        # the box.
        coords = [sym.ports.get(anchor, (sym.width / 2, sym.height / 2))]
    out: dict[str, tuple[float, float]] = {}
    for px, py in coords:
        if unit.kind in ("feed", "product"):
            # Boundary flags are drawn directly, not from the symbol
            # box, but the flag is still a placed box with a height of
            # its own -- :func:`~pandid.render.svg.boundary_flag` insets
            # its pennant off *that*, not off the symbol's fallback
            # 50-unit fixture, so the port has to come off the same
            # height. The horizontal convention is not this: a Feed's
            # port stays a fixed lead off its own frame origin however
            # wide the flag grows (see :func:`unit_box`), so ``px`` is
            # left as the symbol read it.
            lx, ly = (sym.width - px if mirrored else px), py / sym.height * h
            face = outward_dir(lx, ly, w, h, unit.kind, anchor, mirrored)
        else:
            bx, by, bw, bh = symbol_to_box(px, py, sym.width, sym.height,
                                           rot, mirrored, mirror_y)
            ox, oy, iw, ih = ink_box(bw, bh, w, h, getattr(sym, "stretchable", True))
            lx, ly = ox + bx * iw / bw, oy + by * ih / bh
            face = outward_dir(lx - ox, ly - oy, iw, ih, unit.kind, anchor, mirrored)
        out.setdefault(face, (lx, ly))
    return out


def _series_point(unit: "Unit", sym, port_name: str
                  ) -> tuple[float, float] | None:
    """Symbol-space coordinate of a port placed by a port series.

    The count is the unit's, not the symbol's (that is the whole point
    of a series), so this is where the two meet. Members are ordered by
    the unit's port order rather than by the number in the name, so the
    drawn top-to-bottom order is the order they were declared in.

    ``port_name`` is canonicalised against the *unit* before it is
    matched against ``members``: the symbol's series is still authored
    with ``singular="feed"`` (so ``series_for`` finds it from either
    spelling), but a live alias like ``Reactor.feed``/``Column.feed``
    is a plain attribute and never a key of ``unit.ports`` (see
    :meth:`~pandid.units.Unit._canonical_port_name`), so matching the
    raw alias against the *unit's* own members would always miss and
    fall through to the box-centre fallback -- moving every nozzle an
    author reaches with ``port_offset(unit, "feed")`` or
    ``pinned_y(unit, "feed")`` to the middle of the shell.
    """
    series = sym.series_for(port_name) if hasattr(sym, "series_for") else None
    if series is None:
        return None
    # Canonicalise first, then ask the cache: the alias has to become the
    # real name before it is looked up, and the cache is keyed by the real
    # names ``ports`` holds.
    port_name = unit._canonical_port_name(port_name)
    members = unit._series_members(series)
    index = members.get(port_name)
    if index is None:
        return None
    return series.placement(index, len(members), sym.width, sym.height,
                            pin=unit._series_pin(port_name),
                            band=sym.bands.get(series.face))


def is_anchored(unit: "Unit", port_name: str) -> bool:
    """True when the symbol places this port, rather than falling back.

    A port that is neither anchored nor a member of one of the symbol's
    port series falls back to the centre of the box, so any two of them
    land on the same point by construction. That is a gap in the symbol
    rather than a placement, and callers that police collisions have to
    tell the two apart.
    """
    sym = _sym(unit)
    return (_anchor(unit, port_name) in sym.ports
            or _series_point(unit, sym, port_name) is not None)


def unit_box(unit: "Unit", frame) -> tuple[float, float, float, float]:
    """True drawn bounding box (x_min, y_min, x_max, y_max) of a unit.

    A non-mirrored Feed keeps its port at ``frame.x + 50`` with the box
    extending left from there; everything else spans
    ``frame.x .. frame.x + w``.
    """
    if unit.kind == "feed" and not frame.mirrored:
        return (frame.x + 50.0 - frame.w, frame.y, frame.x + 50.0, frame.y + frame.h)
    return (frame.x, frame.y, frame.x + frame.w, frame.y + frame.h)


def face_point(unit: "Unit", frame, face: str) -> tuple[tuple[float, float],
                                                        tuple[float, float]]:
    """Midpoint of one face of a unit's box, and its outward normal.

    The tap point for an instrument mounted on equipment. Read off the
    same :func:`unit_box` the router treats as the obstacle, so a bubble
    hung on the east face sits against the same edge a stream would
    leave from.
    """
    x0, y0, x1, y1 = unit_box(unit, frame)
    return {
        "N": (((x0 + x1) / 2, y0), (0.0, -1.0)),
        "S": (((x0 + x1) / 2, y1), (0.0, 1.0)),
        "W": ((x0, (y0 + y1) / 2), (-1.0, 0.0)),
        "E": ((x1, (y0 + y1) / 2), (1.0, 0.0)),
    }[face.upper()]


def resolve_size(unit: "Unit", placed=None) -> tuple[float, float]:
    """Intrinsic (w, h) of a unit's placed box.

    Explicit ``width``/``height`` win and are taken as the *final* box,
    so a caller who sizes a rotated unit gets exactly what they asked
    for. Symbol defaults are swapped by a quarter turn. Feed/Product get
    a dynamic width sized to their label text.

    ``placed`` names the placement whose quarter turn decides that swap,
    and defaults to the unit's pin; a caller weighing a placement it has
    not committed passes the candidate.
    """
    sym = _sym(unit)
    if unit.kind in ("feed", "product"):
        # Boundary flag: size to the wider of the label or the off-page
        # reference (drawn as the connector's second line), so neither
        # overflows the flag. The label is the tag, not the name: every
        # tap of one header is drawn at the same size, however the
        # flowsheet tells the taps apart.
        #
        # `label_span` per string rather than a shared length fed
        # through one formula: a CJK tag and a Latin reference (or the
        # reverse) need different rates, and taking the max of the two
        # spans is the same answer taking the max of the two lengths
        # first would give when both strings are the one script this
        # used to assume.
        from pandid.render.symbols import label_span
        w = unit.width if unit.width is not None else max(
            80.0, label_span(unit.tag), label_span(getattr(unit, "reference", "") or ""))
        return w, unit.height if unit.height is not None else sym.height

    sym_w, sym_h = sym.width, sym.height
    turn = placed if placed is not None else getattr(unit, "pin_", None)
    if turn is not None and int(getattr(turn, "orientation", 0) or 0) in (90, 270):
        sym_w, sym_h = sym_h, sym_w
    w = unit.width if unit.width is not None else sym_w
    h = unit.height if unit.height is not None else sym_h
    return w, h


def outward_dir(px: float, py: float, w: float, h: float,
                kind: str = "", port_name: str = "", mirrored: bool = False) -> str:
    """Outward normal for a port at local (px, py) in a w by h box."""
    if kind == "product" and port_name == "inlet":
        return "E" if mirrored else "W"
    if kind == "feed" and port_name == "outlet":
        return "W" if mirrored else "E"
    dist_N, dist_S, dist_W, dist_E = py, h - py, px, w - px
    m = min(dist_N, dist_S, dist_W, dist_E)
    if m == dist_N:
        return "N"
    if m == dist_S:
        return "S"
    if m == dist_W:
        return "W"
    return "E"


def chosen_face(unit: "Unit", placed, port_name: str) -> str | None:
    """The face this port is piped from, ``None`` for the symbol's.

    An explicit :meth:`pandid.units.Unit.nozzle` beats the face the
    layout engine picked: naming a face is how a drawing convention is
    stated, and a convention the geometry may overrule is not one. The
    engine's own answer rides on the resolved
    :class:`~pandid.geometry.Frame` rather than on the unit, which is
    what keeps it a *result*: recomputed from scratch by every layout
    run, and invisible to the solver's ``_Slot``, which has no such
    field.

    Both dicts are keyed by the name :attr:`~pandid.units.Unit.ports`
    holds, so the alias a caller may have written -- ``sep.feed`` for
    ``feed_1`` -- has to become that first. Without it a face named
    through the alias is filed under the real name by
    :meth:`~pandid.units.Unit.nozzle` and then looked for under the
    alias here, and the nozzle silently stays where the symbol drew it.
    """
    port_name = unit._canonical_port_name(port_name)
    explicit = (getattr(unit, "_port_faces", None) or {}).get(port_name)
    if explicit is not None:
        return explicit
    return (getattr(placed, "port_faces", None) or {}).get(port_name)


def _local_port(unit: "Unit", port_name: str, w: float, h: float,
                mirrored: bool, mirror_y: bool, rot: int, want: str | None
                ) -> tuple[str, tuple[float, float]]:
    """The face a port leaves, and its offset from the top-left.

    Both together, in resolved pixels: the menu is keyed by face, so the
    face is something the placement is *looked up by* rather than
    something to be read back off the coordinate afterwards. Deriving it
    a second time from the point is how the two come to disagree: an
    artwork that keeps its aspect puts the nozzle on the drawing, which
    is not necessarily nearest the box edge of the same name.

    Takes the placement on the face ``want`` names, else the symbol's
    own nozzle, which is the menu's first entry, since the whole point
    of folding the home in is that there is no second place to look.

    A face that *was* chosen and this transform cannot reach raises
    rather than falling back to the home nozzle, which would move the
    stream to the far side of the unit without saying so: every guard
    upstream of here can be outrun by a later ``pin()``, and this is the
    call that decides where the ink goes.
    """
    placements = _drawn_placements(unit, port_name, w, h, rot, mirrored, mirror_y)
    if want is None:
        return next(iter(placements.items()))
    if want not in placements:
        raise unreachable_face(unit, port_name, want, list(placements))
    return want, placements[want]


class ResolvedPort(NamedTuple):
    """Where a port is drawn, where a path meets it, its face."""
    point: tuple[float, float]
    anchor: tuple[float, float]
    face: str


def resolve_port(unit: "Unit", frame, port_name: str) -> ResolvedPort:
    """Resolve a port's geometry: nozzle, routing anchor and face.

    All three together, because deriving one of them somewhere else is
    what lets the renderer and the router disagree. The anchor is the
    point projected onto the bounding-box edge the port faces (the full
    placed box, which is what :func:`unit_box` hands the router as the
    obstacle), so a symbol drawn smaller than its box is still left by
    way of the box it occupies. Feed/Product use their arrow-tip
    convention for both (the port sits at the tip, whichever way it
    points): ``py`` already comes out scaled to the placed ``h`` (see
    :func:`_drawn_placements`), so a taller flag centres its nozzle
    rather than leaving it at a fraction of the symbol's own 50-unit
    fixture. ``rot`` and ``mirror_y`` are read above and go unused on
    this path -- deliberately, not an oversight: the pennant *is* the
    statement of direction (east out of a Feed, west into a Product,
    the other way where ``mirrored`` flips it), so a turn or a vertical
    flip has nothing to add to it and is silently a no-op rather than
    a second, competing way to say which way the flag points.
    """
    w, h = frame.w, frame.h
    rot, mirrored, mirror_y = _xform(frame)
    want = chosen_face(unit, frame, port_name)
    d, (px, py) = _local_port(unit, port_name, w, h, mirrored, mirror_y, rot, want)

    if unit.kind in ("feed", "product"):
        # The horizontal lead is a fixed 50 units off the frame's own
        # origin, not ``w``: a Feed's box grows to the *left* as its
        # label does, so widening it never moves the nozzle the sheet
        # already routed a stream to. See :func:`unit_box`, which uses
        # the same fixed lead for the same reason, and
        # ``test_a_flag_is_drawn_across_its_own_box``, which pins the
        # two agreeing.
        if unit.kind == "feed":
            ax = frame.x if mirrored else frame.x + 50.0
        else:
            ax = frame.x + w if mirrored else frame.x
        tip = (ax, frame.y + py)
        return ResolvedPort(tip, tip, d)

    point = (frame.x + px, frame.y + py)
    ax, ay = point
    if d == "N":
        ay = frame.y
    elif d == "S":
        ay = frame.y + h
    elif d == "W":
        ax = frame.x
    elif d == "E":
        ax = frame.x + w
    return ResolvedPort(point, (ax, ay), d)


def port_point(unit: "Unit", frame, port_name: str) -> tuple[float, float]:
    """Absolute (x, y) where a stream attaches to the nozzle.

    This is the endpoint the renderer draws to.
    """
    return resolve_port(unit, frame, port_name).point


def port_anchor(unit: "Unit", frame, port_name: str) -> tuple[float, float, str]:
    """Absolute routing anchor for a port: (x, y, outward_dir)."""
    _, (ax, ay), d = resolve_port(unit, frame, port_name)
    return ax, ay, d


def port_offset(unit: "Unit", port_name: str, placed=None) -> tuple[float, float]:
    """Where a port sits relative to the unit's own top-left corner.

    Asked of the symbol rather than written down as a pair of numbers. A
    hand-measured offset is only true of the artwork it was measured
    off, so a run pinned against one drifts off its nozzles the moment
    the symbol is redrawn or the unit is given a size of its own; asked,
    it cannot.

    This is what puts a device *on* a run: a valve whose inlet has to
    land on a line at ``y`` is pinned at
    ``y - port_offset(valve, "inlet")[1]``, which is
    :meth:`pandid.units.Unit.pin`'s ``port=`` argument, and it is how an
    author finds the elevation of a nozzle to run a spine at -- though
    :func:`pinned_y` is the spelling for that, this being the offset
    alone and the two being easy to add up wrongly::

        feed_y = pinned_y(column, "feed")

    ``placed`` is the placement to answer for and defaults to the unit's
    own, preferring the *pin* over the frame for the reason
    :func:`port_faces` does: a ``pin()`` already made describes the
    sheet that is coming. The offset is measured in the placed box, so a
    quarter turn or a mirror moves it.
    """
    from pandid.geometry import Frame

    if placed is None:
        placed = unit.pin_ if unit.pin_ is not None else unit.frame
    rot, mirror_x, mirror_y = _xform(placed) if placed is not None else (0, False, False)
    w, h = resolve_size(unit, placed)
    probe = Frame(x=0.0, y=0.0, w=w, h=h, orientation=rot,
                  mirrored=mirror_x, mirror_y=mirror_y)
    return port_point(unit, probe, port_name)


def _pinned(unit: "Unit", axis: str, port_name: str | None) -> float:
    """One axis of a pinned unit's corner, or of one of its nozzles.

    The shared half of :func:`pinned_x` and :func:`pinned_y`; see either
    for what it is for.
    """
    pin = unit.pin_
    if pin is None:
        raise ValueError(
            f"{unit.name} has not been pinned, so it has no {axis} to read. "
            f"pin() it first, or ask its frame after the sheet is laid out "
            f"(port_point(unit, unit.frame, ...))."
        )
    corner = getattr(pin, axis)
    if corner is None:
        placed = "col/row" if (pin.col is not None or pin.row is not None) else "nothing"
        raise ValueError(
            f"{unit.name} is pinned by {placed} and not by an absolute {axis}, so "
            f"there is no coordinate to read: the solver decides it, and it is not "
            f"decided until the sheet is laid out. Pin it with {axis}=, or read "
            f"unit.frame.{axis} afterwards."
        )
    if port_name is None:
        return corner
    return corner + port_offset(unit, port_name)[0 if axis == "x" else 1]


def pinned_x(unit: "Unit", port_name: str | None = None) -> float:
    """The absolute ``x`` a pinned unit -- or one of its nozzles -- sits at.

    The safe spelling of ``unit.pin_.x + port_offset(unit, port)[0]``,
    and the one to reach for. That expression is wrong in two ways a
    reader does not see: ``pin_`` is ``None`` until the unit is pinned
    and ``pin_.x`` is ``None`` when it is pinned by ``col``/``row``, so
    it raises ``TypeError`` from inside an arithmetic expression; and
    the ``[0]`` has to be matched to the ``.x`` by hand, so an ``.x``
    paired with a ``[1]`` reads fine and silently draws a run at the
    wrong elevation.

    This returns a ``float`` or raises saying which of the two is
    wrong::

        spine_y = pinned_y(column, "feed")     # the nozzle's elevation
        centre_x = pinned_x(tee) + tee_w / 2   # the unit's own corner

    Answers about the **pin** and so about the sheet that is coming,
    which is what an author placing the next unit is asking. After a
    layout, :func:`port_point` against the unit's frame is the same
    question about the sheet that exists.

    Raises :class:`ValueError` if the unit is unpinned, or pinned on the
    other axis only.
    """
    return _pinned(unit, "x", port_name)


def pinned_y(unit: "Unit", port_name: str | None = None) -> float:
    """The absolute ``y`` a pinned unit -- or one of its nozzles -- sits at.

    :func:`pinned_x` down the other axis; see it.
    """
    return _pinned(unit, "y", port_name)


def pin_intent(unit: "Unit") -> dict[str, tuple[str | None, float]]:
    """What the author asked for, per axis: ``{"y": ("inlet", 440.0)}``.

    The coordinate each pinned axis was given, and the nozzle it was
    measured to where one was named -- ``None`` for a plain corner. The
    two are different statements: *this nozzle sits at 440* survives a
    later turn, mirror, resize or :meth:`~pandid.units.Unit.nozzle`
    call, and *this corner sits at 432.5* is only the same drawing until
    one of those happens.

    The one place both halves of :meth:`~pandid.units.Unit.pin`'s record
    are read together, so the callers that hold a drawing to what was
    asked for -- :func:`pandid.validate.geometry_issues`, and
    :func:`pandid.layout.faces.select_faces`, which must leave a pinned
    nozzle's face alone -- do not reach into the unit for them. An axis
    left to the solver (``col``/``row``, or not pinned at all) is absent
    rather than ``None``: there is no coordinate to hold anything to.
    """
    pin = getattr(unit, "_pin", None)
    if pin is None:
        return {}
    ports = getattr(unit, "_pin_ports", None) or {}
    return {axis: (ports.get(axis), value)
            for axis in ("x", "y")
            if (value := getattr(pin, axis)) is not None}


def port_refusal(port_name: "str | None", axes: "Sequence[str]",
                 measured: "Collection[str]", ranks: "Collection[str]",
                 drop: str) -> str | None:
    """Why a nozzle named on a pin locates nothing, or ``None``.

    One rule, asked the same way at both doors into a placement --
    :meth:`pandid.units.Unit.pin` and ``pin:`` in :mod:`pandid.spec`:
    **a named nozzle must be what some stated coordinate is measured
    to.** ``axes`` is the coordinates the nozzle is offered for and
    ``measured`` the ones that are in fact measured to it, so the
    refusal is simply that the two do not meet.

    ``ranks`` is the grid lines the pin names. It changes no verdict --
    a cell and a nozzle sit together perfectly well, and ``pin(col=1,
    x=5, port="inlet")`` means x locates the inlet and the column is
    superseded there, exactly as a pin mixing grid and absolute always
    has. What it changes is the *sentence*: an author who wrote
    ``pin(col=1, port="inlet")`` gave a placement and no coordinate, and
    is better told why a cell is not one than told they stated nothing.

    That is why this is one rule and not two. Refusing a rank *beside* a
    nozzle was a second rule, and it made a placement the call accepted
    and the file rejected -- ``pin(port="inlet", y=440)`` then
    ``pin(col=1)``, or a boundary flag's ``pin(x=…, y=…, col=…)`` in a
    single call -- so ``to_dict`` wrote sheets that would not read back.

    **Ask this of the pin the unit will have, not of the call in front
    of you.** A rule read off one call's arguments is one you defeat by
    writing two calls, which is how the accumulated placement above got
    past it.

    ``drop`` is what the author strikes to keep the rest of the
    placement -- ``port`` for a whole ``port=`` or ``port:``, ``port.x``
    for one axis of the axis-by-axis mapping. It is the only thing here
    a caller supplies, and so the only reason two doors could word this
    differently; for the shape both doors can write, both pass ``port``
    and the sentence is the same to the byte.
    """
    if not axes or set(axes) & set(measured):
        return None
    subject = " or ".join(axes)
    said = (f"port {port_name!r} is the nozzle {subject} "
            f"{'are' if len(axes) > 1 else 'is'} measured to, and this pin states "
            f"{'neither' if len(axes) > 1 else f'no {axes[0]}'}")
    if ranks:
        named = " and ".join(sorted(ranks))
        said += (f": {named} {'name' if len(ranks) > 1 else 'names'} a grid cell, "
                 f"which has no nozzle in it")
    return f"{said}. Give {subject}, or drop {drop}"
