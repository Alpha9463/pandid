"""Define the unit classes: equipment, flags, fittings and instruments.

Each class declares its ports in ``PORTS`` as ``(name, direction, role)``
tuples, or adds them in ``__init__`` when the caller chooses how many.
Ports are reachable as ``unit.ports["name"]``, ``unit.port("name")`` and
as attributes (``pump.suction``), which each class annotates for type
checkers. A family whose size the caller chooses is also a tuple in
declaration order: ``mixer.inlets``, ``splitter.outlets``,
``block.inlets``/``block.outlets`` and ``column.feeds``/``reactor.feeds``.

This module is the public ``units`` namespace (``from pandid import
units``).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

from pandid._checks import check_real, check_whole, is_whole
from pandid.deprecation import Deprecation
from pandid.geometry import Frame, Pin, _Slot
from pandid.ports import Port

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.render.symbols import PortSeries, Symbol
    from pandid.streams import Stream

__all__ = [
    "Unit",
    "Feed",
    "Product",
    "Pump",
    "Compressor",
    "Blower",
    "Valve",
    "Vessel",
    "Tank",
    "HeatExchanger",
    "Heater",
    "Cooler",
    "CoolingTower",
    "Evaporator",
    "Reactor",
    "Separator",
    "Thickener",
    "Absorber",
    "Stripper",
    "DistillationColumn",
    "Column",
    "Mixer",
    "Splitter",
    "Tee",
    "Reducer",
    "Fitting",
    "Ejector",
    "Vent",
    "Funnel",
    "Furnace",
    "Boiler",
    "Stack",
    "Flare",
    "Turbine",
    "Filter",
    "Dryer",
    "Kiln",
    "CrushingMachine",
    "Crusher",
    "Mill",
    "Centrifuge",
    "Conveyor",
    "Elevator",
    "Feeder",
    "SprayNozzle",
    "ScreeningDevice",
    "Kneader",
    "Instrument",
    "Block",
]

# Port roles. Signal ports carry signal lines and all others carry fluid;
# Flowsheet.connect enforces this. "draw" is a column side draw, like
# "feed" in that it states no phase.
_VALID_ROLES = {
    "process",
    "feed",
    "product",
    "energy",
    "utility",
    "vapor",
    "liquid",
    "signal",
    "draw",
}

# label_pos side names mapped to compass faces.
_FACE_OF_SIDE = {"top": "N", "bottom": "S", "left": "W", "right": "E"}

# Sentinel for pin() arguments whose falsy values are meaningful
# (``orientation=0`` and ``mirrored=False`` reset the transform).
_UNCHANGED: Any = object()

#: Sentinel for "not given", distinct from ``None``. ``Reactor()`` gets
#: its default agitator; ``Reactor(agitator=None)`` gets none. Also used
#: by :meth:`Unit.pin`'s ``port``.
_UNSTATED: Any = object()

# Lets chainable methods return the subclass they were called on.
_UnitT = TypeVar("_UnitT", bound="Unit")

# Attributes layout and routing read. Assigning one marks the sheet's
# cached geometry stale (see Unit.__setattr__), which also catches plain
# assignments such as ``pump.width = 90``. Private names back properties
# that change the resolved symbol (Block width, Conveyor length and
# diameter, Reducer large_end, normal_position). ``name`` is included
# because the drawn tag is a routing obstacle. Lettering the renderer lays
# out afresh (description, reference, quadrants) and the engine's own
# output (frame, _slot) are excluded.
_LAYOUT_INPUTS = frozenset(
    {
        "name",
        "variant",
        "label_pos",
        # Pin intent; ``pin_`` is derived from these and is not listed.
        "_pin",
        "_pin_ports",
        "width",
        "height",
        "_width",
        "_height",
        "_length",
        "_diameter",
        "_large_end",
        "_normal_position",
    }
)


class Unit:
    """A piece of equipment, flag, fitting or instrument on a flowsheet.

    Parameters
    ----------
    name : str
        Tag, unique on the sheet except for repeatable symbols.
    variant : str, default="default"
        Drawing variant; must be in :attr:`VARIANTS` when that is set.
    width, height : float or None, optional
        Explicit box size, positive and finite; ``None`` uses the symbol's.
    label_pos : str or None, optional
        Tag position: ``"top"``, ``"bottom"``, ``"left"`` or ``"right"``.
    description : str, default=""
        Text for the equipment list.
    reference : str, default=""
        Off-page drawing reference; only for a Feed or Product.

    Attributes
    ----------
    kind : str
        Equipment type: the symbol registry key and the spec's ``kind``.
    PORTS : list[tuple[str, str, str]]
        Declared ports as ``(name, direction, role)``. The nearest class in
        the hierarchy that declares it supplies the whole list.
    VARIANTS : tuple[str, ...]
        Variants this class draws, class-local names first. Empty means any
        registered variant of :attr:`kind`. A class that lists variants but
        not ``"default"`` cannot be built without one.
    VARIANT_ALIASES : dict[str, str]
        Class-local variant name to registry name. ``variant`` stores the
        registry name, so list both in :attr:`VARIANTS` if the class-local
        name must survive a spec round trip.
    PORT_ANCHORS : dict[str, str]
        Port name to the name the symbol anchors it under, for a renamed
        nozzle. Read through :meth:`_symbol_anchor`.
    LAYOUT_CONFIDENCE : float
        Weight of this class's placement claims (stiffness in the
        least-squares fit, at both ends): 8 for columns and reactors, 4 for
        vessels, tanks and separators, 2 for exchangers, pumps, compressors
        and filters, 1 by default, and 0 for inline valves, fittings,
        reducers and tees, whose claims are dropped. See
        :mod:`pandid.layout.claims`.
    PLACES : dict[str, str | tuple[str, float] | None]
        Port or port-family name to where the connected unit is drawn: a
        compass point, or ``(point, weight)``. Written in the symbol's
        frame and turned with the unit. ``None`` declines a direction for a
        service connection (steam, fuel, regenerant), so its header is
        placed by the rest of the sheet. A missing entry falls back to the
        port's fixed face. A subclass's dict replaces its base's.
    ONE_NOZZLE_MANY_RUNS : bool
        Whether several streams may meet at one point on purpose. Only
        boundary flags set it; elsewhere coincident ports are an error.
    COMPOSITION : dict[str, Any]
        Composition keywords (ISO 10628-2 supplementary parts) and their
        defaults. The constructor and both directions of :mod:`pandid.spec`
        read this one declaration. :data:`_UNSTATED` means the default
        depends on the body; see :meth:`composition_defaults`.
    COMPOSITION_VARIANT : str
        Composition keyword this class folds into :attr:`variant`, so a
        serializer writes the keyword rather than the deprecated variant.
    name : str
        Tag.
    variant : str
        Registry variant name.
    ports : dict[str, Port]
        Ports by name.
    flowsheet : Flowsheet or None
        Sheet the unit is on.
    frame : Frame or None
        Resolved geometry, written only by layout.
    balloon : Instrument or None
        Balloon carrying this unit's tag, set by
        :meth:`~pandid.flowsheet.Flowsheet.add_balloon`.

    Raises
    ------
    ValueError
        If the name is empty, the variant is not drawn by this class, a size
        is not positive and finite, or ``reference`` is given on equipment.
    """

    kind: str = "unit"
    PORTS: list[tuple[str, str, str]] = []

    VARIANTS: tuple[str, ...] = ()
    VARIANT_ALIASES: dict[str, str] = {}

    PORT_ANCHORS: dict[str, str] = {}

    LAYOUT_CONFIDENCE: float = 1

    PLACES: dict[str, "str | tuple[str, float] | None"] = {}

    ONE_NOZZLE_MANY_RUNS = False

    # Retired port name -> (direction, role, Deprecation). __getattr__ adds
    # the port on first access and warns. Subclasses that never had it
    # reset this to {}.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {}

    # Renamed port name -> (new name, Deprecation); resolves to the same Port.
    _RETIRED_PORT_ALIASES: dict[str, tuple[str, Deprecation]] = {}

    # Attributes read once in __init__ to build ports and artwork (such as a
    # column's internals or a reactor's agitator); __setattr__ refuses a
    # later assignment.
    _FIXED_AT_CONSTRUCTION: frozenset[str] = frozenset()

    COMPOSITION: dict[str, Any] = {}

    COMPOSITION_VARIANT: str = ""

    # Layout solver state, seeded by pandid.layout._seed_slots; absent until
    # the first layout.
    _slot: _Slot | None

    # Backing store for pin_. The class default keeps a unit mid-__init__
    # reading as unpinned.
    _pin: "Pin | None" = None

    # Subclasses annotate their ports (``suction: Port``) so type checkers
    # see what _add_port creates; tests/test_port_annotations.py keeps the
    # annotations and PORTS in step.

    @classmethod
    def _declared_ports(cls) -> list[tuple[str, str, str]]:
        """Return the ports this class declares.

        Returns
        -------
        list[tuple[str, str, str]]
            :attr:`PORTS` from the nearest class in the MRO that declares
            it.
        """
        for klass in cls.__mro__:
            if "PORTS" in klass.__dict__:
                return list(klass.__dict__["PORTS"])
        return []

    @classmethod
    def composition_defaults(
        cls, variant: str, stated: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return each composition keyword's default for a variant.

        The constructor and the spec serializer both ask here, so the rule
        is written once. A class whose defaults depend on the body or on
        other keywords overrides this; for example, a reactor with internals
        defaults to no agitator.

        Parameters
        ----------
        variant : str
            Body variant.
        stated : Mapping[str, Any] or None, optional
            Current value of every composition keyword.

        Returns
        -------
        dict[str, Any]
            Default per keyword, never :data:`_UNSTATED`.
        """
        return dict(cls.COMPOSITION)

    @classmethod
    def _generic_class(cls) -> type["Unit"] | None:
        """Return the ancestor that draws every variant of this class's kind.

        Returns
        -------
        type[Unit] or None
            Nearest ancestor with an empty :attr:`VARIANTS` and the same
            :attr:`kind`, named in errors as the generic form.
        """
        for klass in cls.__mro__:
            if issubclass(klass, Unit) and not klass.VARIANTS and klass.kind == cls.kind:
                return klass
        return None

    @classmethod
    def _unknown_variant(cls, name: str, variant: str) -> ValueError:
        """Build the error for a variant this class does not draw.

        Returned rather than raised, so the traceback starts at the
        constructor. The message names the generic class that does draw it.

        Parameters
        ----------
        name : str
            Unit name.
        variant : str
            Requested variant.

        Returns
        -------
        ValueError
            The error to raise.
        """
        close = get_close_matches(variant, cls.VARIANTS, n=1, cutoff=0.6)
        suggestion = f" (did you mean {close[0]!r}?)" if close else ""
        generic = cls._generic_class()
        escape = (
            ""
            if generic is None
            else (
                f" The generic form is {generic.__name__}(variant={variant!r}), which "
                f"takes any variant registered for a {cls.kind}."
            )
        )
        return ValueError(
            f"{name}: {cls.__name__} draws "
            f"{', '.join(repr(v) for v in cls.VARIANTS)}, not {variant!r}{suggestion}. "
            f"A different device is a different class, so {variant!r} belongs to "
            f"whichever class draws it.{escape}"
        )

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        if not name:
            raise ValueError("Unit name cannot be empty")
        self.name = name
        if self.VARIANTS and variant not in self.VARIANTS:
            raise self._unknown_variant(name, variant)
        # Store the registry spelling; see VARIANT_ALIASES.
        self.variant = self.VARIANT_ALIASES.get(variant, variant)
        # SVG draws nothing for a zero or negative size, so refuse it here.
        for dim, value in (("width", width), ("height", height)):
            if value is not None and not (math.isfinite(value) and value > 0):
                raise ValueError(
                    f"{name}: {dim}={value!r} is not a usable size; a symbol is "
                    f"drawn into a box with a positive, finite {dim}, or "
                    f"{dim}=None to size itself"
                )
        self.width = width
        self.height = height
        self.label_pos = label_pos
        self.description = description
        if reference and self.kind not in ("feed", "product"):
            raise ValueError(
                f"{name}: reference= names the drawing an off-page connector "
                f"continues onto, and a {type(self).__name__} is drawn as equipment. "
                f"Put it on the Feed or Product where the line crosses the sheet edge."
            )
        self.reference = reference
        self.balloon: "Instrument | None" = None
        self.flowsheet: Flowsheet | None = None
        self.ports: dict[str, Port] = {}
        self.params: dict = {}
        self._new_line_number = False
        self._pin: Pin | None = None  # intent; set only via pin()
        # Axes pinned to a port rather than the corner: {"y": "inlet"}.
        self._pin_ports: dict[str, str] = {}
        self.frame: Frame | None = None  # resolved; set only by layout
        self._port_faces: dict[str, str] = {}  # port name -> face
        for spec in self._declared_ports():
            self._add_port(*spec)

    def _invalidate_layout(self) -> None:
        """Mark the sheet's cached geometry stale, if the unit is on one.

        A unit not yet on a sheet needs nothing: adding it marks the sheet
        stale. Uses ``getattr`` because :meth:`__setattr__` calls this
        before ``flowsheet`` exists.
        """
        fs = getattr(self, "flowsheet", None)
        if fs is not None:
            fs._invalidate_layout()

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute, invalidating layout for one layout reads.

        Attributes in :data:`_LAYOUT_INPUTS` mark the sheet stale. An
        attribute fixed at construction can be set once and is refused
        afterwards.

        Parameters
        ----------
        name : str
            Attribute name.
        value : Any
            New value.

        Raises
        ------
        AttributeError
            If the attribute is fixed at construction and already set.
        TypeError
            If ``width`` or ``height`` is not a number or ``None``.
        """
        if name in ("width", "height") and value is not None:
            check_real(value, f"{self.__dict__.get('name', '?')}: {name}")
        if name in self._FIXED_AT_CONSTRUCTION and name in self.__dict__:
            raise AttributeError(
                f"{self.name}: {name} is read-only. It is read once, in "
                f"__init__, to build the nozzles and artwork that describe "
                f"what this {type(self).__name__} is; reassigning it would "
                f"leave the drawing disagreeing with the object. Build a new "
                f"{type(self).__name__} with {name}={value!r} instead."
            )
        super().__setattr__(name, value)
        if name in _LAYOUT_INPUTS:
            self._invalidate_layout()

    @property
    def tag(self) -> str:
        """Return the tag drawn beside this unit.

        For equipment this is the name. It is empty once a balloon carries
        the tag. Repeatable symbols override it; see :attr:`Instrument.tag`
        and :attr:`_Boundary.tag`.

        Returns
        -------
        str
            Drawn tag.
        """
        return "" if self.balloon is not None else self.name

    def repeats(self, other: "Unit") -> bool:
        """Return whether this unit is another drawing of ``other``.

        ``False`` for equipment. Overridden by repeatable symbols
        (:meth:`Instrument.repeats`, :meth:`_Boundary.repeats`) and by
        :meth:`Tee.repeats`.

        Parameters
        ----------
        other : Unit
            Unit with the same name.

        Returns
        -------
        bool
            Whether the two may share a tag.
        """
        return False

    @property
    def new_line_number(self) -> bool:
        """Return whether the line number breaks at this inline unit.

        On a valve, reducer, fitting or tee, ``True`` starts a new stream or
        line number after the unit, such as at a piping spec break. Setting
        it renumbers the sheet.

        Returns
        -------
        bool
            Current setting.
        """
        return self._new_line_number

    @new_line_number.setter
    def new_line_number(self, value: bool) -> None:
        """Set the line-number break and renumber the sheet.

        Parameters
        ----------
        value : bool
            New setting.
        """
        self._new_line_number = value
        if self.flowsheet is not None:
            # New names change label sizes, so layout is stale too.
            self.flowsheet._invalidate_layout()
            self.flowsheet.renumber_streams()

    @property
    def pin_(self) -> Pin | None:
        """Return the placement intent with ``x`` and ``y`` as the corner.

        An axis pinned to a port (``valve.pin(port="inlet", y=440)``) is
        stored as that relation and converted to a corner on every read, so
        a later turn, mirror, resize or :meth:`nozzle` call keeps the port on
        its coordinate. Layout's own face selection leaves a pinned port's
        face alone (:func:`pandid.layout.faces.select_faces`).

        Returns
        -------
        Pin or None
            Placement with corner coordinates, or ``None`` when unpinned.
        """
        pin = self._pin
        if pin is None or not self._pin_ports:
            return pin
        from dataclasses import replace

        from pandid.portgeom import port_offset

        corners = {}
        for axis, port_name in self._pin_ports.items():
            # Only the pin's transform is used for the offset.
            offset = port_offset(self, port_name, pin)[0 if axis == "x" else 1]
            corners[axis] = getattr(pin, axis) - offset
        return replace(pin, **corners)

    @pin_.setter
    def pin_(self, value: Pin | None) -> None:
        """Replace the placement with corner coordinates.

        Any port relation is dropped. Use this to restore a placement read
        from :attr:`pin_`; :meth:`pin` keeps port relations.

        Parameters
        ----------
        value : Pin or None
            Placement, or ``None`` to unpin.
        """
        self._pin_ports = {}
        self._pin = value

    def pin(
        self: _UnitT,
        *,
        col: int | None = None,
        row: int | None = None,
        x: float | None = None,
        y: float | None = None,
        orientation: float = _UNCHANGED,
        mirrored: bool | str = _UNCHANGED,
        port: str | None = _UNSTATED,
    ) -> _UnitT:
        """Record placement intent for the unit.

        Layout honours pinned axes exactly. Omitted arguments keep their
        current value, so a second ``pin(y=...)`` keeps an earlier turn;
        pass ``orientation=0`` or ``mirrored=False`` to clear them.

        With ``port``, ``x`` and ``y`` in this call place that port rather
        than the corner, so ``valve.pin(port="inlet", y=run_y)`` puts a
        valve on a run. The named port must locate a coordinate in the
        resulting pin; a grid cell alone has no port in it. On a
        :class:`Feed` or :class:`Product`, ``x`` and ``y`` place the flag's
        tip by default; ``port=None`` places the corner instead. On an
        attached :class:`Instrument`, ``x`` and ``y`` replace the standoff on
        their axes, while ``col`` and ``row`` are reported as
        ``pin-not-honored``.

        Parameters
        ----------
        col, row : int or None, optional
            Grid column and row.
        x, y : float or None, optional
            Pixel coordinate of the corner, or of ``port``.
        orientation : float, optional
            Clockwise quarter turn: 0, 90, 180 or 270. A quarter turn swaps
            width and height.
        mirrored : bool or str, optional
            ``True`` or ``"x"`` flips left to right (E and W faces), ``"y"``
            top to bottom, ``"xy"`` both.
        port : str or None, optional
            Port that ``x`` and ``y`` locate.

        Returns
        -------
        Unit
            This unit.

        Raises
        ------
        KeyError
            If ``port`` is not a port of this unit.
        TypeError
            If ``x`` or ``y`` is not a number, or ``col`` or ``row`` not a
            whole number.
        ValueError
            If the named port locates no coordinate, or a face set with
            :meth:`nozzle` cannot be reached under the new transform.
        """
        from dataclasses import replace

        for axis, value in (("x", x), ("y", y)):
            if value is not None:
                check_real(value, f"{self.name}: pin {axis}")
        for axis, value in (("col", col), ("row", row)):
            if value is not None:
                check_whole(value, f"{self.name}: pin {axis}")

        from pandid.geometry import normalize_mirror, normalize_orientation

        # Build from the stored intent, not pin_, so port relations survive.
        # Pin is frozen, so collect the changes and apply one replace().
        fields: dict[str, Any] = {axis: value
                                  for axis, value in (("col", col), ("row", row),
                                                      ("x", x), ("y", y))
                                  if value is not None}
        ports = dict(self._pin_ports)
        if orientation is not _UNCHANGED:
            fields["orientation"] = normalize_orientation(orientation)
        if mirrored is not _UNCHANGED:
            fields["mirrored"], fields["mirror_y"] = normalize_mirror(mirrored)
        candidate = replace(self._pin if self._pin is not None else Pin(), **fields)
        # Keep the port the caller named; the flag default below fills one in.
        named_port: str | None = None if port is _UNSTATED else port
        if port is _UNSTATED:
            # A flag's coordinates place its only port by default.
            port = next(iter(self.ports)) if isinstance(self, _Boundary) else None
        # Check the port name first, even with no coordinate.
        nozzle = self._pin_port(port) if port is not None else None
        # Record per axis which port the coordinate locates.
        for axis, value in (("x", x), ("y", y)):
            if value is None:
                continue
            if nozzle is None:
                ports.pop(axis, None)
            else:
                ports[axis] = nozzle
        if named_port is not None:
            # Check the resulting pin, not this call alone, so splitting
            # arguments across calls cannot get past the rule.
            from pandid.portgeom import port_refusal

            complaint = port_refusal(
                named_port, ("x", "y"),
                {axis for axis, name in ports.items() if name == nozzle},
                {r for r, v in (("col", candidate.col), ("row", candidate.row))
                 if v is not None},
                "port")
            if complaint is not None:
                raise ValueError(f"{self.name}: {complaint}")
        # Check chosen faces against the candidate before committing.
        if self._port_faces:
            from pandid.portgeom import port_faces

            for port_name, face in self._port_faces.items():
                self._check_face(port_name, face, port_faces(self, port_name, candidate))
        # Set the port relations before the pin, so the pair is never
        # inconsistent.
        self._pin_ports = ports
        self._pin = candidate
        return self

    def _pin_port(self, port_name: str) -> str:
        """Return the real port name for a name given to :meth:`pin`.

        Parameters
        ----------
        port_name : str
            Port name or alias.

        Returns
        -------
        str
            Key in :attr:`ports`.

        Raises
        ------
        KeyError
            If the unit has no such port.
        """
        canonical = self._canonical_port_name(port_name)
        if canonical not in self.ports:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no port {canonical!r} to "
                f"pin by; available ports: {sorted(self.ports)}"
            )
        return canonical

    def nozzle(self: _UnitT, port_name: str, face: str) -> _UnitT:
        """Fix the face a port is drawn on, overriding automatic selection.

        The face is as drawn on the sheet, so a mirrored unit takes the face
        the reader sees. A later :meth:`pin` that turns or mirrors the unit
        re-checks the choice.

        Parameters
        ----------
        port_name : str
            Port name.
        face : str
            ``"N"``, ``"S"``, ``"E"`` or ``"W"``, or ``"top"``, ``"bottom"``,
            ``"left"`` or ``"right"``.

        Returns
        -------
        Unit
            This unit.

        Raises
        ------
        KeyError
            If the port does not exist.
        ValueError
            If the symbol offers no placement on that face.
        """
        from pandid.portgeom import port_faces

        port_name = self._canonical_port_name(port_name)
        if port_name not in self.ports:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no port {port_name!r}; "
                f"available ports: {sorted(self.ports)}"
            )
        face = _FACE_OF_SIDE.get(face.strip().lower(), face.strip().upper())
        self._check_face(port_name, face, port_faces(self, port_name))
        # Mutating the dict bypasses __setattr__, so invalidate explicitly.
        self._port_faces[port_name] = face
        self._invalidate_layout()
        return self

    def _check_face(self, port_name: str, face: str, options: list[str]) -> None:
        """Check that a face is one a port can be drawn on.

        Parameters
        ----------
        port_name : str
            Port name.
        face : str
            Requested face.
        options : list[str]
            Faces available.

        Raises
        ------
        ValueError
            The same error :mod:`pandid.portgeom` raises at resolve time.
        """
        if face not in options:
            from pandid.portgeom import unreachable_face

            raise unreachable_face(self, port_name, face, options)

    def _add_port(self, name: str, direction: str, role: str, side: str | None = None) -> Port:
        """Create a port and expose it as an attribute.

        Parameters
        ----------
        name : str
            Port name.
        direction : str
            ``"inlet"`` or ``"outlet"``.
        role : str
            One of :data:`_VALID_ROLES`.
        side : str or None, optional
            Reserved.

        Returns
        -------
        Port
            The new port.

        Raises
        ------
        ValueError
            If the name exists or the role is invalid.
        """
        if name in self.ports:
            raise ValueError(f"{type(self).__name__!r} already has a port named {name!r}")
        if role not in _VALID_ROLES:
            raise ValueError(
                f"Invalid role {role!r} for port {name!r}. Allowed roles are: {_VALID_ROLES}"
            )
        port = Port(name=name, owner=self, direction=direction, role=role, side=side)
        self.ports[name] = port
        setattr(self, name, port)
        # A new port can join a series, so drop the cached membership.
        self.__dict__.pop("_series_members_cache", None)
        return port

    def has_another_port(self, port: "Port") -> bool:
        """Return whether a connected port can take another stream.

        ``False`` for equipment, where a second pipe needs a :class:`Tee`.
        :class:`Instrument` signal pools and :class:`_Boundary` flags
        override it. Asked separately from :meth:`another_port` so
        :meth:`~pandid.flowsheet.Flowsheet.connect` can check both ends
        before adding a port to either.

        Parameters
        ----------
        port : Port
            Connected port.

        Returns
        -------
        bool
            Whether :meth:`another_port` can supply a free equivalent.
        """
        return False

    def another_port(self, port: "Port") -> "Port":
        """Return a free port equivalent to ``port``, adding one if needed.

        Called only where :meth:`has_another_port` is true.

        Parameters
        ----------
        port : Port
            Connected port.

        Returns
        -------
        Port
            ``port`` itself on this base class.
        """
        return port

    def _next_member(self, base: str, direction: str, role: str) -> "Port":
        """Return a free member of a port pool, adding one if all are used.

        Shared by :class:`Instrument` and :class:`_Boundary`, so pools number
        alike. The new member takes the next unused number, so after
        ``sig_out_2`` and ``sig_out_4`` the next is ``sig_out_5``.

        Parameters
        ----------
        base : str
            Pool name, such as ``"sig_out"``.
        direction : str
            Direction of a new member.
        role : str
            Role of a new member.

        Returns
        -------
        Port
            Free member.
        """
        members = self._pool_members(base)
        for member in members:
            if member.stream is None:
                return member
        n = len(members) + 1
        while f"{base}_{n}" in self.ports:
            n += 1
        return self._add_port(f"{base}_{n}", direction, role)

    def _pool_members(self, base: str) -> list["Port"]:
        """Return the ports in a pool, in port order.

        Parameters
        ----------
        base : str
            Pool name.

        Returns
        -------
        list[Port]
            Members; empty on classes without pools.
        """
        return []

    def _mint_port(self, name: str) -> "Port | None":
        """Create a pool member by name, for the spec reader.

        A spec may name a pool member such as ``sig_out_3`` before its
        stream exists (:func:`pandid.spec._find_port`).

        Parameters
        ----------
        name : str
            Port name.

        Returns
        -------
        Port or None
            The port, or ``None`` when this class has no such pool.
        """
        return None

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the name the symbol anchors a port under.

        Uses :attr:`PORT_ANCHORS`; :class:`Instrument` overrides it. An
        unknown name falls back to the box centre in :mod:`pandid.portgeom`.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str
            Anchor name.
        """
        return type(self).PORT_ANCHORS.get(port_name, port_name)

    def _series_pin(self, port_name: str) -> float | None:
        """Return a fixed position for a port within its port series.

        ``None`` lets the series spread its members evenly. :class:`Column`
        overrides it to place feeds and draws on their stages.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        float or None
            Fraction along the series face, or ``None``.
        """
        return None

    def _series_members(self, series: "PortSeries") -> dict[str, int]:
        """Return the ports in a port series and their order.

        Cached per series, so placing a large family is linear;
        :meth:`_add_port` clears the cache.

        Parameters
        ----------
        series : PortSeries
            Symbol's port series.

        Returns
        -------
        dict[str, int]
            Port name to index among the members, in port order.
        """
        cache = self.__dict__.setdefault("_series_members_cache", {})
        members = cache.get(id(series))
        if members is None:
            members = {n: i for i, n in enumerate(n for n in self.ports if series.matches(n))}
            cache[id(series)] = members
        return members

    def _canonical_port_name(self, name: str) -> str:
        """Return the real port name for a name or alias.

        ``Reactor.feed`` and ``Column.feed`` with one feed are attribute
        aliases of ``feed_1`` and not keys of :attr:`ports`. Call this wherever
        a caller's name is used as a key or passed to :mod:`pandid.portgeom`.
        An attribute that is not a port (such as ``width``) is returned
        unchanged.

        Parameters
        ----------
        name : str
            Port name or alias.

        Returns
        -------
        str
            Real port name, or ``name`` unchanged.
        """
        if name in self.ports:
            return name
        aliased = getattr(self, name, None)
        return aliased.name if isinstance(aliased, Port) and aliased.name in self.ports else name

    def port(self, name: str) -> Port:
        """Return a port by name or alias.

        Parameters
        ----------
        name : str
            Port name.

        Returns
        -------
        Port
            The port.

        Raises
        ------
        KeyError
            If the unit has no such port.
        """
        name = self._canonical_port_name(name)
        if name in self.ports:
            return self.ports[name]
        raise KeyError(
            f"{type(self).__name__!r} has no port named {name!r}; "
            f"available ports: {sorted(self.ports)}"
        )

    def __repr__(self) -> str:
        """Return ``ClassName('tag')``."""
        return f"{type(self).__name__}({self.name!r})"

    # Hidden from type checkers, which would otherwise accept any attribute.
    # Families declare their numbered ports through typed __new__ overloads
    # instead; Block alone keeps a visible __getattr__ (see
    # tests/test_port_annotations.py).
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            """Resolve retired port names and explain unknown attributes.

            Called only when normal lookup fails.

            Parameters
            ----------
            name : str
                Attribute name.

            Returns
            -------
            Any
                A renamed or retired port, after a deprecation warning.

            Raises
            ------
            AttributeError
                Listing the unit's ports when the name is unknown.
            """
            ports = self.__dict__.get("ports")
            if ports is not None and not name.startswith("_"):
                where = self.__dict__.get("name", "?")
                alias = type(self)._RETIRED_PORT_ALIASES.get(name)
                if alias is not None:
                    target, dep = alias
                    dep.warn(self, where=where)
                    return getattr(self, target)
                retired = type(self)._RETIRED_PORTS.get(name)
                if retired is not None:
                    direction, role, dep = retired
                    dep.warn(self, where=where)
                    return self._add_port(name, direction, role)
                raise AttributeError(
                    f"{type(self).__name__} {where!r} has no "
                    f"attribute or port {name!r}; available ports: {sorted(ports)}"
                )
            raise AttributeError(name)


# ----------------------------------------------------------------
# Fixed-port unit types
# ----------------------------------------------------------------


class _Boundary(Unit):
    """Base class for the off-page flags :class:`Feed` and :class:`Product`.

    A flag marks a line crossing the sheet edge; its label names the
    service and ``reference`` the drawing the line continues on.
    ``pin(x=..., y=...)`` places the flag's port, not its corner (see
    :meth:`Unit.pin`).

    A flag's port takes any number of streams, all drawn from the flag's
    tip, so one header can serve several users from one flag. Each stream
    keeps its own number, route and stream-table column. The port works as
    a pool, like :class:`Instrument`'s signal ports, but its members share
    one point (see :attr:`Unit.ONE_NOZZLE_MANY_RUNS`). Real equipment keeps
    one stream per port; a branch needs a :class:`Tee`.

    Parameters
    ----------
    name, variant, width, height, label_pos, description, reference
        As for :class:`Unit`.
    header : bool, default=False
        Mark the flag as a utility header (cooling water, steam, flare,
        plant air) that may be drawn at several taps with one label; see
        :meth:`repeats`.

    Attributes
    ----------
    header : bool
        Whether the flag is a repeatable utility header.
    """

    # A flag's face is artwork, not a direction, so it states no claims.
    LAYOUT_CONFIDENCE = 0

    ONE_NOZZLE_MANY_RUNS = True

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        header: bool = False,
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self.header = bool(header)
        # Drawn label; a repeated header gets a distinct name but keeps this.
        self._tag = name

    @property
    def tag(self) -> str:
        """Return the service label drawn on the flag, such as ``"CWSH"``.

        A repeated header keeps this label while each tap has its own name
        (``CWSH``, ``CWSH (2)``).

        Returns
        -------
        str
            Label.
        """
        return self._tag

    @property
    def connection(self) -> Port:
        """Return the flag's declared port.

        Returns
        -------
        Port
            ``outlet`` on a feed, ``inlet`` on a product.
        """
        return next(iter(self.ports.values()))

    def _pool_base(self, port_name: str) -> str | None:
        """Return the pool a port name belongs to.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str or None
            The flag's port name for it or a numbered member, else ``None``.
        """
        base = self.connection.name
        if port_name == base:
            return base
        head, _, tail = port_name.rpartition("_")
        return base if head == base and tail.isdigit() else None

    def _pool_members(self, base: str) -> list[Port]:
        """Return the members of the flag's port pool.

        Parameters
        ----------
        base : str
            Pool name.

        Returns
        -------
        list[Port]
            Members in port order.
        """
        return [p for name, p in self.ports.items() if self._pool_base(name) == base]

    def has_another_port(self, port: Port) -> bool:
        """Return whether the port is the flag's port or a member of it.

        Parameters
        ----------
        port : Port
            Connected port.

        Returns
        -------
        bool
            ``True`` for the flag's own pool.
        """
        return self._pool_base(port.name) is not None

    def another_port(self, port: Port) -> Port:
        """Return a free member of the flag's port, adding one if needed.

        Members share the first port's direction and role.

        Parameters
        ----------
        port : Port
            Connected port.

        Returns
        -------
        Port
            Free member.
        """
        base = self._pool_base(port.name)
        if base is None:
            return port
        return self._next_member(base, port.direction, port.role)

    def _mint_port(self, name: str) -> Port | None:
        """Create a named member of the flag's port for the spec reader.

        Parameters
        ----------
        name : str
            Port name such as ``outlet_2``.

        Returns
        -------
        Port or None
            The new port, or ``None`` if the name is not in the pool.
        """
        if self._pool_base(name) is None:
            return None
        first = self.connection
        return self._add_port(name, first.direction, first.role)

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the anchor name, mapping every pool member to the flag's port.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str
            Anchor name.
        """
        return self._pool_base(port_name) or super()._symbol_anchor(port_name)

    def repeats(self, other: "Unit") -> bool:
        """Return whether this flag is another tap of the same header.

        Both flags must be headers of the same class, label, variant and
        reference, so a supply and a return with one label still clash.

        Parameters
        ----------
        other : Unit
            Unit with the same name.

        Returns
        -------
        bool
            Whether the two may share the tag.
        """
        return (
            self.header
            and isinstance(other, _Boundary)
            and type(other) is type(self)
            and other.header
            and other.tag == self.tag
            and other.variant == self.variant
            and other.reference == self.reference
        )


class Feed(_Boundary):
    """Off-page flag where material enters the sheet.

    With ``header=True`` it is a utility supply header that may be drawn at
    several taps; see :class:`_Boundary`.
    """

    outlet: Port

    kind = "feed"
    PORTS = [("outlet", "outlet", "feed")]


class Product(_Boundary):
    """Off-page flag where material leaves the sheet.

    With ``header=True`` it is a return or collection header that may be
    drawn at several taps; see :class:`_Boundary`.
    """

    inlet: Port

    kind = "product"
    PORTS = [("inlet", "inlet", "product")]


class Pump(Unit):
    """Centrifugal or positive-displacement pump."""

    suction: Port
    discharge: Port

    kind = "pump"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]
    LAYOUT_CONFIDENCE = 2
    PLACES = {"suction": "W", "discharge": "E"}


class Compressor(Unit):
    """Gas compressor."""

    suction: Port
    discharge: Port

    kind = "compressor"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]
    LAYOUT_CONFIDENCE = 2
    PLACES = {"suction": "W", "discharge": "E"}


class _NormallyPositioned(Unit):
    """Base class for units with a normal position: Valve and Fitting.

    How a closed position is drawn differs: a valve body is darkened, a
    blind uses its closed shape. Each subclass refuses variants that cannot
    be shown closed by overriding :meth:`_refuse_closed`;
    :func:`pandid.render.symbols.closed_marking` draws the mark.

    Parameters
    ----------
    name, variant, width, height, label_pos, description, reference
        As for :class:`Unit`.
    normal_position : str, default="open"
        One of :data:`NORMAL_POSITIONS`: where the device sits in normal
        operation.
    """

    # Inline devices state no placement claims.
    LAYOUT_CONFIDENCE = 0

    #: Normal positions a device may declare.
    NORMAL_POSITIONS = ("open", "closed")

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        normal_position: str = "open",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._normal_position = "open"
        self.normal_position = normal_position

    @property
    def normal_position(self) -> str:
        """Return where the device sits in normal operation.

        Returns
        -------
        str
            ``"open"`` or ``"closed"``.
        """
        return self._normal_position

    @normal_position.setter
    def normal_position(self, value: str) -> None:
        """Set the normal position.

        Parameters
        ----------
        value : str
            ``"open"`` or ``"closed"``.

        Raises
        ------
        ValueError
            If the value is unknown or this variant cannot be shown closed.
        """
        if value not in self.NORMAL_POSITIONS:
            raise ValueError(
                f"{self.name}: normal_position is "
                f"{' or '.join(repr(p) for p in self.NORMAL_POSITIONS)}, got {value!r}"
            )
        if value == "closed":
            self._refuse_closed()
        self._normal_position = value

    def _refuse_closed(self) -> None:
        """Raise if this variant cannot be shown normally closed.

        Raises
        ------
        ValueError
            In subclasses, for a variant that cannot be shown closed.
        """


class Valve(_NormallyPositioned):
    """Valve: a body, optionally stroked by an actuator.

    ``variant`` is the body (``"globe"``, ``"ball"``, ``"butterfly"``,
    ``"gate"`` and others); ``actuator`` is what strokes it.
    ``variant="control"`` is a general body with a diaphragm actuator::

        units.Valve("HV-101", variant="globe")       # plain globe valve
        units.Valve("CV-303", variant="control")     # control valve
        units.Valve("CV-303", variant="gate", actuator="diaphragm")
        units.Valve("XV-201", variant="butterfly", actuator="diaphragm")
        units.Valve("SV-401", variant="solenoid")

    The stencils draw fused body-and-actuator shapes, so only the pairings
    in :data:`pandid.render.symbols.ACTUATED` exist; the resolved variant
    is stored. An actuator that contradicts a variant's own raises.

    A closed valve's body is darkened (PIP PIC001 4.2.2.7); variants whose
    fill would hide the symbol write ``NC`` instead (4.2.2.8; see
    :data:`pandid.render.symbols.NC_DARKENS`). Control, regulator and
    relief valves may not be shown closed (4.2.2.10). ISA-5.1 requires a
    legend entry for this extension (clauses 2.8.1(b)(1), 2.8.2, 5.2.5);
    :func:`pandid.document.legend` builds the box but does not add it.

    ``variant="three_way"`` adds a ``branch`` outlet. It is not annotated
    on the class, since other variants lack it; reach it through
    :class:`~pandid.devices.ThreeWayValve` or ``port("branch")``.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body or body-and-actuator variant.
    actuator : str, default=""
        ``"diaphragm"``, ``"motor"``, ``"solenoid"``, ``"hydraulic"`` or
        ``"handwheel"``; empty when not stated.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    normal_position : str, default="open"
        ``"open"`` or ``"closed"``; see above.
    fail : str, default=""
        Position on loss of actuating energy; see :attr:`fail`.

    Raises
    ------
    ValueError
        If the actuator is unknown or contradicts the variant, the pairing
        is not drawn, the variant cannot be shown closed, or ``fail`` is
        invalid for it.
    """

    inlet: Port
    outlet: Port
    actuator: Port

    kind = "valve"
    # Ports depend on the variant, so __init__ adds them from _VARIANT_PORTS.
    PORTS: list[tuple[str, str, str]] = []
    #: Ports of every variant except ``three_way``.
    _BASE = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("actuator", "inlet", "signal"),
    ]
    #: Ports by variant, defaulting to :data:`_BASE`.
    _VARIANT_PORTS = {"three_way": [*_BASE, ("branch", "outlet", "process")]}

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return the ports a variant adds.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs, or none when the class declares :attr:`PORTS`.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._BASE)

    def __init__(
        self,
        name: str,
        variant: str = "default",
        *,
        actuator: str = "",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        normal_position: str = "open",
        fail: str = "",
    ):
        variant = self._resolve(name, variant, actuator)
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
            normal_position=normal_position,
        )
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        self._fail = ""
        self.fail = fail

    def _resolve(self, name: str, variant: str, actuator: str) -> str:
        """Return the variant that draws a body with an actuator.

        Only the resolved variant is stored, so renderers and the spec read
        one value.

        Parameters
        ----------
        name : str
            Tag, for messages.
        variant : str
            Body or pairing variant.
        actuator : str
            Actuator, or empty.

        Returns
        -------
        str
            Resolved variant.

        Raises
        ------
        ValueError
            If the actuator is unknown or contradicts the variant.
        """
        from pandid.render.symbols import ACTUATED, ACTUATORS, actuated_variant

        if not actuator:
            return variant
        if actuator not in ACTUATORS:
            raise ValueError(
                f"{name}: actuator is one of "
                f"{', '.join(repr(a) for a in ACTUATORS)}, got {actuator!r}. It is "
                f"what strokes the valve; what the valve *is* -- the body -- is "
                f"variant."
            )
        # A variant that already includes an actuator accepts only that one.
        fitted = {a for (_, a), drawn in ACTUATED.items() if drawn == variant}
        if fitted:
            if actuator in fitted:
                return variant
            raise ValueError(
                f"{name}: variant {variant!r} already draws a valve with a "
                f"{', '.join(repr(a) for a in sorted(fitted))} operator on it, so it "
                f"cannot also take actuator={actuator!r} -- one drawing, two "
                f"operators. Name the body and the actuator (variant='gate', "
                f"actuator={actuator!r}), or the pairing on its own "
                f"(variant={variant!r})."
            )
        return actuated_variant(variant, actuator)

    @property
    def fail(self) -> str:
        """Return where the valve goes on loss of actuating energy.

        Independent of :attr:`~_NormallyPositioned.normal_position`, which
        is where it sits in normal operation. Drawn as ISA-5.1 letters
        beside the valve (PIP PIC001 4.5.3.2):

        ===================  =========  =============================
        ``fail``             drawn      ANSI/ISA-5.1-2009 Table 5.4.4
        ===================  =========  =============================
        ``"open"``           ``FO``     fail open
        ``"closed"``         ``FC``     fail closed
        ``"last"``           ``FL``     fail last, holding position
        ``"drift_open"``     ``FL/DO``  fail last, then drifting open
        ``"drift_closed"``   ``FL/DC``  fail last, then drifting shut
        ``"indeterminate"``  ``FI``     fail indeterminate
        ===================  =========  =============================

        Only actuated variants (:data:`pandid.render.symbols.FAIL_ACTUATED`)
        may declare one. Where signal and motive-power failure differ, set
        the motive-power position and add a note (PIP PIC001 4.5.3.2(3)).

        Returns
        -------
        str
            Fail position, or ``""`` when unset.
        """
        return self._fail

    @fail.setter
    def fail(self, value: str) -> None:
        """Set the fail position.

        Parameters
        ----------
        value : str
            Fail position, or ``""`` to clear it.

        Raises
        ------
        ValueError
            If the value is unknown or the variant has no actuator.
        """
        from pandid.render.symbols import FAIL_ACTUATED, FAIL_POSITIONS

        if not value:
            self._fail = ""
            return
        if value not in FAIL_POSITIONS:
            raise ValueError(
                f"{self.name}: fail is one of "
                f"{', '.join(repr(p) for p in FAIL_POSITIONS)}, got {value!r}. "
                f"It is where the valve goes when its actuating energy is lost. "
                f"Where it sits in normal operation is normal_position."
            )
        if self.variant not in FAIL_ACTUATED:
            raise ValueError(
                f"{self.name}: variant {self.variant!r} has no actuator, so it has "
                f"no fail position. ANSI/ISA-5.1 note 5.3.4(10) scopes the failure "
                f"symbols to control valves and actuators: a handwheel loses no air, "
                f"and a regulator or a relief valve is worked by the process itself. "
                f"The variants that take one are: "
                f"{', '.join(sorted(FAIL_ACTUATED))}. If you meant where the valve "
                f"sits with the plant running, that is normal_position."
            )
        self._fail = value

    def _refuse_closed(self) -> None:
        """Refuse a closed control, regulator or relief valve.

        Raises
        ------
        ValueError
            If the variant is in :data:`pandid.render.symbols.NC_FORBIDDEN`.
        """
        from pandid.render.symbols import NC_FORBIDDEN

        if self.variant in NC_FORBIDDEN:
            raise ValueError(
                f"{self.name}: PIP PIC001 clause 4.2.2.10 bars a control valve and "
                f"a relief valve from being shown NC, and variant "
                f"{self.variant!r} draws one. A darkened control valve on an issued "
                f"sheet reads as a block valve someone has closed. Say where the "
                f"valve fails instead (fail='closed'), or put the normally closed "
                f"mark on the hand valve that actually isolates the line."
            )


def _compose_onto(unit, *groups) -> None:
    """Set a unit's overlays from its composition keywords.

    Nothing is set when no part was asked for, so the unit draws exactly as
    one that cannot compose.

    Parameters
    ----------
    unit : Unit
        Unit to compose onto.
    *groups : Iterable
        Overlay groups in the order requested.
    """
    overlays = tuple(overlay for group in groups for overlay in group)
    if overlays:
        unit.overlays = overlays


#: Deprecated vessel variants that drew a support into the shell artwork.
#: ``supports=`` draws the ISO group-26 support under the standard shell
#: instead, which changes the drawing, so each declaration carries a note.
#: Declared as module constants so :func:`pandid.deprecation.declarations`
#: finds them.
VESSEL_VARIANT_LEGS = Deprecation(
    what="Vessel(variant='legs')",
    instead="Vessel(supports='leg')",
    removed_in="0.2.0",
    note="the drawing changes -- a pair of ISO item 26.1 C2005 legs under the "
    "standard vessel shell, where this one has its own drawn in",
)
VESSEL_VARIANT_SKIRTED = Deprecation(
    what="Vessel(variant='skirted')",
    instead="Vessel(supports='skirt')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 26.3 C2007's skirt under the standard "
    "vessel shell, where this one has its own drawn in",
)

_VESSEL_SUPPORT_VARIANTS = {
    "legs": VESSEL_VARIANT_LEGS,
    "skirted": VESSEL_VARIANT_SKIRTED,
}


# Self type for _MultiPortVessel methods, so their bodies see the vessel's
# own attributes and callers get their subclass back.
_MultiPortVesselT = TypeVar("_MultiPortVesselT", bound="_MultiPortVessel")


class _MultiPortVessel(Unit):
    """Base class for the :class:`Tank` and :class:`Vessel` port families.

    Inlets and outlets are families spread over the vessel's faces, as on
    :class:`Block`, but drawn on the vendored artwork: a crowded face
    squeezes its ports rather than growing the box, and only faces the
    artwork anchors for a role are allowed. ``vent``, ``relief`` and
    ``drain`` are single fixed ports moved only through
    :meth:`Unit.nozzle`.

    When the caller names no face, a connection uses, in rising priority:

    1. the face the artwork anchors (:meth:`_home_face`);
    2. :attr:`DEFAULT_INPUT_FACE` or :attr:`DEFAULT_OUTPUT_FACE`, which a
       subclass may set;
    3. the ``inputs=`` or ``outputs=`` argument.

    Attributes
    ----------
    DEFAULT_INPUT_FACE, DEFAULT_OUTPUT_FACE : str or None
        Class-wide default faces; ``None`` on Tank and Vessel.
    inlets, outlets : tuple[Port, ...]
        Port families in declaration order.
    """

    DEFAULT_INPUT_FACE: str | None = None
    DEFAULT_OUTPUT_FACE: str | None = None

    LAYOUT_CONFIDENCE = 4
    # Inlets come from upstream and outlets go downstream, whatever face
    # they use. Vent, relief and drain restate their faces at vessel weight.
    PLACES = {"in": "W", "out": "E", "vent": "N", "relief": "N", "drain": "S"}

    # Family port name -> face, in port order; the symbol is built from it.
    _faces: dict[str, str]

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the anchor name, resolving the ``inlet``/``outlet`` aliases.

        Parameters
        ----------
        port_name : str
            Port name or alias.

        Returns
        -------
        str
            Anchor name in the symbol.
        """
        return super()._symbol_anchor(self._canonical_port_name(port_name))

    def _registry_symbol(self):
        """Return the registered symbol for this unit's variant.

        An unknown variant returns ``None`` so that, as for every other
        class, the error is raised at render time.

        Returns
        -------
        Symbol or None
            Vendored symbol.
        """
        from pandid.render.symbols import default_registry

        try:
            return default_registry.get(self.kind, self.variant)
        except ValueError:
            return None

    def _home_face(self, role: str) -> str:
        """Return the face the artwork draws a role's port on.

        Parameters
        ----------
        role : str
            ``"inlet"`` or ``"outlet"``.

        Returns
        -------
        str
            Face; a placeholder for an unknown variant, which fails at
            render.
        """
        sym = self._registry_symbol()
        if sym is None:
            return "W" if role == "inlet" else "E"
        from pandid.portgeom import outward_dir

        x, y = sym.ports[role]
        return outward_dir(x, y, sym.width, sym.height)

    def _legal_faces(self, role: str) -> "dict[str, tuple[float, float]] | None":
        """Return the faces the artwork allows for a role.

        Parameters
        ----------
        role : str
            ``"inlet"`` or ``"outlet"``.

        Returns
        -------
        dict[str, tuple[float, float]] or None
            Face to symbol point, always including the home face; ``None``
            for an unknown variant.
        """
        sym = self._registry_symbol()
        if sym is None:
            return None
        return dict(sym.port_faces.get(role, {}))

    def _validate_face(self, role: str, port_name: str, face: str) -> None:
        """Check that a family port may be drawn on a face.

        Parameters
        ----------
        role : str
            ``"inlet"`` or ``"outlet"``.
        port_name : str
            Port name.
        face : str
            Requested face.

        Raises
        ------
        ValueError
            If the artwork has no anchor for the role on that face, or the
            face has no room for another port.
        """
        options = self._legal_faces(role)
        if options is None:
            # Unknown variant: leave the error to render time.
            return
        if face not in options:
            from pandid.portgeom import unreachable_face

            raise unreachable_face(self, port_name, face, list(options))
        self._check_face_room(role, port_name, face)

    def _check_face_room(self, role: str, port_name: str, face: str) -> None:
        """Refuse a second port on a face that meets the box at one point.

        A dished roof, cone apex or dished head has a band of zero length,
        so two ports there would coincide. Inlets and outlets count
        together. Checking here names the author's call in the error;
        :func:`~pandid.render.symbols.vessel_symbol` checks again when
        drawing.

        Parameters
        ----------
        role : str
            ``"inlet"`` or ``"outlet"``.
        port_name : str
            Port being placed.
        face : str
            Its face.

        Raises
        ------
        ValueError
            If another port already uses the zero-length face.
        """
        from pandid.render.symbols import bandless_face, walled_faces

        sym = self._registry_symbol()
        if sym is None:
            return
        band = sym.bands.get(face)
        if band is None or band[0] < band[1]:
            return
        others = [name for name, on in self._faces.items()
                  if on == face and name != port_name]
        if not others:
            return
        raise bandless_face(self.name, face, band[0], [*others, port_name],
                            walled_faces(sym, role))

    def default_input_face(self) -> str:
        """Return the face an inlet uses when none is named.

        :func:`~pandid.spec.to_dict` uses it to omit default faces.

        Returns
        -------
        str
            :attr:`DEFAULT_INPUT_FACE`, else the artwork's inlet face.
        """
        return self.DEFAULT_INPUT_FACE or self._home_face("inlet")

    def default_output_face(self) -> str:
        """Return the face an outlet uses when none is named.

        Returns
        -------
        str
            :attr:`DEFAULT_OUTPUT_FACE`, else the artwork's outlet face.
        """
        return self.DEFAULT_OUTPUT_FACE or self._home_face("outlet")

    def _init_connections(
        self, inputs: "int | Sequence[str]", outputs: "int | Sequence[str]"
    ) -> None:
        """Create the inlet and outlet families.

        With one inlet or outlet, ``inlet`` or ``outlet`` is an attribute
        alias for ``in_1`` or ``out_1``.

        Parameters
        ----------
        inputs, outputs : int or Sequence[str]
            Count, or one face per port.

        Raises
        ------
        ValueError
            If a face is invalid or not offered by the artwork.
        """
        in_faces = _block_faces(inputs, self.default_input_face(), self.name, "inputs")
        out_faces = _block_faces(outputs, self.default_output_face(), self.name, "outputs")
        self._faces = {}
        self.inlets = tuple(
            self._connect(f"in_{i}", "inlet", "inlet", face)
            for i, face in enumerate(in_faces, start=1)
        )
        self.outlets = tuple(
            self._connect(f"out_{i}", "outlet", "outlet", face)
            for i, face in enumerate(out_faces, start=1)
        )
        if len(self.inlets) == 1:
            # An alias, not a second port; larger families have no bare name.
            self.inlet = self.inlets[0]
        if len(self.outlets) == 1:
            self.outlet = self.outlets[0]

    def _connect(self, name: str, direction: str, role: str, face: str) -> Port:
        """Check a family port's face, then create the port.

        Parameters
        ----------
        name : str
            Port name.
        direction : str
            ``"inlet"`` or ``"outlet"``.
        role : str
            Symbol role used for the face check.
        face : str
            Face.

        Returns
        -------
        Port
            The new port.
        """
        self._validate_face(role, name, face)
        port = self._add_port(name, direction, "process")
        self._faces[name] = face
        return port

    def nozzle(self: _MultiPortVesselT, port_name: str, face: str) -> _MultiPortVesselT:
        """Move a port to a named face.

        An inlet or outlet moves to any face the artwork offers for its
        role, and the symbol is rebuilt. The choice is also stored in
        ``_port_faces`` so automatic face selection does not override it.
        ``vent``, ``relief`` and ``drain`` use :meth:`Unit.nozzle`.

        Parameters
        ----------
        port_name : str
            Port name or alias.
        face : str
            Compass face or side name.

        Returns
        -------
        _MultiPortVessel
            This unit.

        Raises
        ------
        ValueError
            If the artwork offers no such face for the port.
        """
        canonical = self._canonical_port_name(port_name)
        if canonical not in self._faces:
            return super().nozzle(port_name, face)
        role = "inlet" if canonical.startswith("in_") else "outlet"
        resolved = _block_face(face, self.name)
        # Validate before recording, so a refusal leaves the unit unchanged.
        self._validate_face(role, canonical, resolved)
        self._faces[canonical] = resolved
        self._port_faces[canonical] = resolved
        self._invalidate_layout()
        return self

    def face(self, port_name: str) -> str:
        """Return the face an inlet or outlet is on.

        Parameters
        ----------
        port_name : str
            Inlet or outlet name or alias.

        Returns
        -------
        str
            Face.

        Raises
        ------
        KeyError
            If the port is not an inlet or outlet.
        """
        canonical = self._canonical_port_name(port_name)
        try:
            return self._faces[canonical]
        except KeyError:
            raise KeyError(
                f"{type(self).__name__} {self.name!r} has no inlet or outlet "
                f"named {port_name!r}; available: {sorted(self._faces)}"
            ) from None

    def ports_on(self, face: str) -> tuple[Port, ...]:
        """Return the inlets and outlets on one face, in drawn order.

        Parameters
        ----------
        face : str
            Compass face or side name.

        Returns
        -------
        tuple[Port, ...]
            Family ports on that face; fixed ports are excluded.
        """
        wanted = _block_face(face, self.name)
        return tuple(self.ports[name] for name, on in self._faces.items() if on == wanted)

    def order_on(self: _MultiPortVesselT, face: str, ports: "Sequence[Port]") -> _MultiPortVesselT:
        """Set the drawn order of the inlets and outlets on one face.

        Parameters
        ----------
        face : str
            Compass face or side name.
        ports : Sequence[Port]
            Every port :meth:`ports_on` reports for the face, first to last.

        Returns
        -------
        _MultiPortVessel
            This unit.

        Raises
        ------
        TypeError
            If an item is not a Port.
        ValueError
            If a port belongs to another unit or face, is repeated, or a
            port on the face is missing.
        """
        wanted = _block_face(face, self.name)
        on_face = [name for name, on in self._faces.items() if on == wanted]
        named: list[str] = []
        for port in ports:
            if not isinstance(port, Port):
                raise TypeError(
                    f"{self.name}: order_on() takes the connections themselves and "
                    f"not their names, so a checker can see a typo -- "
                    f"order_on({wanted!r}, [v.out_2, v.in_2]), or v.outlets[1] / "
                    f"v.port('out_2') where the name is computed. "
                    f"Got {port!r}."
                )
            if self.ports.get(port.name) is not port:
                raise ValueError(
                    f"{self.name}: {port.name!r} is a connection of "
                    f"{port.owner.name!r}, not of this unit, so it is not on any "
                    f"face of it. order_on() orders one unit's own wall; "
                    f"the {wanted} face carries "
                    f"{', '.join(on_face) if on_face else 'nothing'}."
                )
            if self._faces.get(port.name) != wanted:
                raise ValueError(
                    f"{self.name}: {port.name!r} is on the "
                    f"{self._faces.get(port.name)} face, not the {wanted}. "
                    f"order_on() orders what is already on a side; move it first "
                    f"with nozzle({port.name!r}, {wanted!r})."
                )
            if port.name in named:
                raise ValueError(
                    f"{self.name}: order_on({wanted!r}, ...) names {port.name!r} "
                    f"twice, so it asks for one connection in two places. Name "
                    f"each of the {wanted} face's connections once: "
                    f"{', '.join(on_face)}."
                )
            named.append(port.name)
        missing = [name for name in on_face if name not in named]
        if missing:
            raise ValueError(
                f"{self.name}: order_on({wanted!r}, ...) names {len(named)} of the "
                f"{len(on_face)} connections on the {wanted} face and leaves "
                f"{', '.join(missing)} unplaced. Name every one, first to last "
                f"along the face; it currently carries {', '.join(on_face)}."
            )
        replacement = iter(named)
        self._faces = {
            (next(replacement) if on == wanted else name): on for name, on in self._faces.items()
        }
        self._invalidate_layout()
        return self

    @property
    def input_faces(self) -> tuple[str, ...]:
        """Return each inlet's face, in port order."""
        return tuple(self._faces[port.name] for port in self.inlets)

    @property
    def output_faces(self) -> tuple[str, ...]:
        """Return each outlet's face, in port order."""
        return tuple(self._faces[port.name] for port in self.outlets)

    def symbol(self) -> "Symbol":
        """Return this unit's symbol with its current port faces.

        Called by :meth:`~pandid.render.symbols.SymbolRegistry.for_unit` on
        every port resolution. Overlays such as a vessel's supports are
        included.

        Returns
        -------
        Symbol
            Vendored artwork with the inlet and outlet families placed.
        """
        from pandid.render.symbols import vessel_symbol

        overlays = tuple(getattr(self, "overlays", ()) or ())
        return vessel_symbol(self.kind, self.variant, tuple(self._faces.items()), overlays)


class Vessel(_MultiPortVessel):
    """Pressure vessel for holdup rather than phase separation.

    ``"default"`` and ``"dished"`` stand upright; ``"horizontal"`` is a
    lying drum (reflux drum, accumulator, knock-out pot). Use that variant
    rather than turning an upright vessel: supports and shell bands do not
    survive a quarter turn, and :meth:`~pandid.flowsheet.Flowsheet.validate`
    reports a turned vessel as ``gravity-turned`` (ISO 15519-1 11.4.2). Use
    :class:`Separator` when the vessel separates phases into named
    products.

    Besides its inlets and outlets, a vessel has ``vent`` (top head),
    ``relief`` (where the protective device sits, at the top per CHEE4001
    p.7) and ``drain`` (low point). These are named rather than counted
    because each has its own duty. Every vessel and tank variant anchors
    all five (``scripts/vendor_symbols.py``), so a second relief needs new
    artwork. ``nozzle-unconnected`` checks only numbered nozzles, so these
    three are never reported. :class:`Tank` has the same five ports.

    ``inputs`` and ``outputs`` make families as on :class:`Block`: a count
    (all on the default face) or one face per port, such as
    ``inputs=["W", "W", "N"]``. With one of each, ``inlet`` and ``outlet``
    name them; above one, use ``in_1``, ``in_2``, ... or :attr:`inlets`.
    See :class:`_MultiPortVessel` for face defaults and
    :meth:`~_MultiPortVessel.nozzle` for moving a port.

    ``supports`` draws an ISO 10628-2 group-26 support under or against
    any variant::

        Vessel("D-301", supports="skirt")     # 26.3 C2007
        Vessel("D-302", supports="leg")       # 26.1 C2005, a pair
        Vessel("D-303", supports="bracket")   # 26.2 C2006, a pair
        Vessel("D-304", supports="ring")      # 26.4 C2008, a pair

    Parameters
    ----------
    name : str
        Tag.
    inputs, outputs : int or Sequence[str], default=1
        Number of inlets or outlets, or one face per port.
    variant : str, default="default"
        Shell drawing. ``"legs"`` and ``"skirted"`` are deprecated in
        favour of ``supports``.
    supports : str, optional
        ``"skirt"``, ``"leg"``, ``"bracket"`` or ``"ring"``. Fixed at
        construction.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]
    # Aliases for in_1 and out_1 when there is one of each.
    inlet: Port
    outlet: Port
    vent: Port
    # Where the relief device sits, so the relief path is drawn from the
    # vessel. Role "process": a relief passes whatever the vessel holds.
    relief: Port
    # Low-point liquid draw; most variants put outlet on the shell wall.
    drain: Port

    # A literal inputs= count, or a tuple of faces, returns a typed view
    # declaring in_1 to in_n (Vessel1 to Vessel8), so a type checker
    # accepts ``Vessel("V-1", inputs=3).in_3``. A computed count or a list
    # gets Vessel; use ``inlets[i]`` or ``port(...)``. outputs= has no
    # typed family; use ``outlets[i]``.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, inputs: Literal[1] = 1, *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel1": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel1": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[2], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel2": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel2": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[3], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel3": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel3": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[4], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel4": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel4": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[5], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel5": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel5": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[6], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel6": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel6": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[7], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel7": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel7": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[8], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Vessel8": ...

        @overload
        def __new__(
            cls, name: str, inputs: tuple[str, str, str, str, str, str, str, str], *args: Any,
            outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any
        ) -> "Vessel8": ...

        @overload
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Vessel": ...
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Vessel": ...

    kind = "vessel"
    PORTS = [
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    # No support unless ``supports`` names one; any variant takes one.
    COMPOSITION = {"supports": None}
    # The supports overlay is composed in __init__.
    _FIXED_AT_CONSTRUCTION = frozenset({"supports"})

    def __init__(
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        supports: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._init_connections(inputs, outputs)
        # Check the variant the author typed, not the alias it resolved to.
        if variant in _VESSEL_SUPPORT_VARIANTS:
            _VESSEL_SUPPORT_VARIANTS[variant].warn(self, where=name)
        self.supports = supports
        from pandid.render.iso_parts import support_overlays

        _compose_onto(self, () if supports is None else support_overlays(supports))


if TYPE_CHECKING:
    # Typed views for the overloads above, written out so a checker can
    # read them; never built at run time.

    class Vessel1(Vessel):
        """Vessel declaring ``in_1`` for type checkers."""

        in_1: Port

    class Vessel2(Vessel):
        """Vessel declaring ``in_1`` to ``in_2`` for type checkers."""

        in_1: Port
        in_2: Port

    class Vessel3(Vessel):
        """Vessel declaring ``in_1`` to ``in_3`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port

    class Vessel4(Vessel):
        """Vessel declaring ``in_1`` to ``in_4`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port

    class Vessel5(Vessel):
        """Vessel declaring ``in_1`` to ``in_5`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port

    class Vessel6(Vessel):
        """Vessel declaring ``in_1`` to ``in_6`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port

    class Vessel7(Vessel):
        """Vessel declaring ``in_1`` to ``in_7`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port

    class Vessel8(Vessel):
        """Vessel declaring ``in_1`` to ``in_8`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port
        in_8: Port


class Tank(_MultiPortVessel):
    """Storage tank.

    Variants are ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``, ``"conical_bottom"``,
    ``"conical_ends"`` and ``"dished_roof_conical_bottom"``.

    A tank has :class:`Vessel`'s five ports. ``vent`` is the conservation
    vent a fixed-roof tank breathes through. ``relief`` is the fire-case
    relief (CHEE4001 p.8), separate from the vent because it passes nothing
    until the design case. A declared port need not be piped.

    The inlet face is a menu. Flat-floored variants (``default``,
    ``conical``, ``floating_roof``, ``sphere``) fill low on the shell, since
    splash filling a flammable liquid generates static; hopper-bottomed
    variants fill at the crown. Every variant except ``floating_roof``,
    whose roof rides on the liquid, offers both::

        tk = Tank("TK-602")          # fills low on the shell
        tk.nozzle("inlet", "N")      # ...through a crown downcomer

    Without a ``nozzle()`` call, layout chooses the face from where the peer
    lands (:mod:`pandid.layout.faces`).

    Several feeds use ``inputs``, as on :class:`Vessel`::

        tk = Tank("TK-901", inputs=["W", "W", "N"])
        tk.in_1, tk.in_2, tk.in_3   # west, west, crown; in declared order

    Parameters
    ----------
    name : str
        Tag.
    inputs, outputs : int or Sequence[str], default=1
        Number of inlets or outlets, or one face per port.
    variant : str, default="default"
        Tank drawing.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]
    inlet: Port
    outlet: Port
    # As on Vessel.
    vent: Port
    relief: Port
    drain: Port

    # Typed overloads, as on Vessel.
    if TYPE_CHECKING:

        @overload
        def __new__(cls, name: str, inputs: Literal[1] = 1, *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank1": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank1": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[2], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank2": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank2": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[3], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank3": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank3": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[4], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank4": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank4": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[5], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank5": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank5": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[6], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank6": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank6": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[7], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank7": ...

        @overload
        def __new__(cls, name: str, inputs: tuple[str, str, str, str, str, str, str], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank7": ...

        @overload
        def __new__(cls, name: str, inputs: Literal[8], *args: Any,
                    outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any) -> "Tank8": ...

        @overload
        def __new__(
            cls, name: str, inputs: tuple[str, str, str, str, str, str, str, str], *args: Any,
            outputs: "Literal[1] | tuple[str]" = 1, **kwargs: Any
        ) -> "Tank8": ...

        @overload
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Tank": ...
        def __new__(cls, name: str, inputs: "int | Sequence[str]" = 1, *args: Any,
                    outputs: "int | Sequence[str]" = 1, **kwargs: Any) -> "Tank": ...

    kind = "tank"
    # Keep the inherited ``out: "E"`` claim although the artwork puts the
    # outlet on the floor: the outlet pipe turns toward a peer drawn
    # alongside. Claiming S or SE measured worse on the example corpus.

    PORTS = [
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    def __init__(
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._init_connections(inputs, outputs)


if TYPE_CHECKING:
    # Typed views for the overloads above; never built at run time.

    class Tank1(Tank):
        """Tank declaring ``in_1`` for type checkers."""

        in_1: Port

    class Tank2(Tank):
        """Tank declaring ``in_1`` to ``in_2`` for type checkers."""

        in_1: Port
        in_2: Port

    class Tank3(Tank):
        """Tank declaring ``in_1`` to ``in_3`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port

    class Tank4(Tank):
        """Tank declaring ``in_1`` to ``in_4`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port

    class Tank5(Tank):
        """Tank declaring ``in_1`` to ``in_5`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port

    class Tank6(Tank):
        """Tank declaring ``in_1`` to ``in_6`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port

    class Tank7(Tank):
        """Tank declaring ``in_1`` to ``in_7`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port

    class Tank8(Tank):
        """Tank declaring ``in_1`` to ``in_8`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port
        in_8: Port


class Blower(Unit):
    """Fan or blower."""

    suction: Port
    discharge: Port

    kind = "blower"
    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process")]
    LAYOUT_CONFIDENCE = 2
    PLACES = {"suction": "W", "discharge": "E"}


class Reducer(Unit):
    """Reducer or expander: the fitting that changes a line's size.

    ``"concentric"`` (also ``"default"``) is symmetric about the run's
    centreline. ``"eccentric"`` is drawn flat on top, the pump suction
    arrangement that leaves no vapour pocket; ``pin(mirrored="y")`` puts
    the flat side at the bottom for a line that must drain, with both
    ports kept on their faces.

    ``large_end`` names the port on the wide face:

    =====================  ========================================
    ``large_end``          what the fitting does
    =====================  ========================================
    ``"inlet"`` (default)  a **reduction**: the run enters wide
                           and leaves narrow, going into a valve
    ``"outlet"``           an **expansion**: the run enters narrow
                           and leaves wide, coming back out of one
    =====================  ========================================

    The run always goes ``inlet`` to ``outlet``, so a station reads

    .. code-block:: python

        fs.connect(hv.outlet, rd.inlet)   # Reducer("RD-306A")
        fs.connect(rd.outlet, cv.inlet)   # the control valve
        fs.connect(cv.outlet, ex.inlet)   # ...large_end="outlet"

    ``pin(mirrored="x")`` is different: it turns the drawing and its ports
    together, so the line runs backwards through the fitting.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body style.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    large_end : {"inlet", "outlet"}, default="inlet"
        Port on the wide face.

    Attributes
    ----------
    LARGE_ENDS : tuple[str, ...]
        Allowed ``large_end`` values.

    Raises
    ------
    ValueError
        If ``large_end`` is not in :attr:`LARGE_ENDS`.
    """

    inlet: Port
    outlet: Port

    kind = "reducer"
    LAYOUT_CONFIDENCE = 0
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    LARGE_ENDS = ("inlet", "outlet")

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        large_end: str = "inlet",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._large_end = "inlet"
        self.large_end = large_end

    @property
    def large_end(self) -> str:
        """Return ``"inlet"`` for a reduction, ``"outlet"`` for expansion."""
        return self._large_end

    @large_end.setter
    def large_end(self, value: str) -> None:
        """Set the port on the wide face.

        Parameters
        ----------
        value : {"inlet", "outlet"}
            Port name.

        Raises
        ------
        ValueError
            If ``value`` is not in :attr:`LARGE_ENDS`.
        """
        if value not in self.LARGE_ENDS:
            raise ValueError(
                f"{self.name}: large_end names the nozzle on the wide face and is "
                f"{' or '.join(repr(end) for end in self.LARGE_ENDS)}, got {value!r}"
            )
        self._large_end = value


class Tee(Unit):
    """Pipe tee: the junction where a line branches.

    Used for a bypass leg, drain, vent, sample point or PSV takeoff. It is a
    piping fitting, not a unit operation such as :class:`Mixer` or
    :class:`Splitter`.

    A tee is drawn as three lines meeting: the run passes straight through
    with ``inlet`` and ``outlet`` on one centreline, and the branch leaves
    at a right angle. A line ending at a tee has no arrowhead, so none lands
    mid-run.

    A tee has no tag and is not in the equipment list. ``name`` defaults to
    :data:`DEFAULT_NAME`, tees may share it (:meth:`repeats`), and
    :meth:`~pandid.flowsheet.Flowsheet.add` renames them ``TEE (2)``,
    ``TEE (3)``.

    The branch leaves the south face as drawn; place it with
    :meth:`~Unit.pin`:

    ===================  ================
    ``pin(...)``         run, branch
    ===================  ================
    (nothing)            W to E, branch S
    ``mirrored="y"``     W to E, branch N
    ``orientation=90``   N to S, branch W
    ``orientation=270``  S to N, branch E
    ===================  ================

    The run keeps its line number through the tee and the branch starts its
    own. Set ``new_line_number`` to break the run's number where the piping
    class changes.

    Parameters
    ----------
    name : str, default=""
        Flowsheet name; :data:`DEFAULT_NAME` when empty.
    branch : {"outlet", "inlet"}, default="outlet"
        ``"outlet"`` takes flow off the run; ``"inlet"`` returns flow to it.
    variant : str, default="default"
        Drawing variant.
    width, height, description, reference
        As for :class:`Unit`.

    Attributes
    ----------
    DEFAULT_NAME : str
        Name used when none is given.
    BRANCH_DIRECTIONS : tuple[str, ...]
        Allowed ``branch`` values.

    Raises
    ------
    ValueError
        If ``branch`` is not in :attr:`BRANCH_DIRECTIONS`.
    """

    inlet: Port
    outlet: Port
    # Added in __init__, since its direction is the branch= argument.
    branch: Port

    kind = "tee"
    LAYOUT_CONFIDENCE = 0
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    DEFAULT_NAME = "TEE"

    BRANCH_DIRECTIONS = ("outlet", "inlet")

    def __init__(
        self,
        name: str = "",
        branch: str = "outlet",
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        description: str = "",
        reference: str = "",
    ):
        if branch not in self.BRANCH_DIRECTIONS:
            raise ValueError(
                f"{name or self.DEFAULT_NAME}: branch= is "
                f"{' or '.join(repr(d) for d in self.BRANCH_DIRECTIONS)}, whether "
                f"the third connection takes flow off the run or returns it; got "
                f"{branch!r}"
            )
        super().__init__(
            name or self.DEFAULT_NAME,
            variant=variant,
            width=width,
            height=height,
            description=description,
            reference=reference,
        )
        self._add_port("branch", branch, "process")

    @property
    def branch_direction(self) -> str:
        """Return ``"outlet"`` for a takeoff or ``"inlet"`` for a return.

        Read from the branch port, so the spec writer and the router see
        one fact.
        """
        return self.ports["branch"].direction

    @branch_direction.setter
    def branch_direction(self, value: str) -> None:
        """Refuse to change the branch direction after construction.

        Raises
        ------
        AttributeError
            Always; build a new tee with the wanted ``branch``.
        """
        raise AttributeError(
            f"{self.name}: branch_direction is read-only. The branch nozzle is "
            f"already built and may already have a line on it, so turning one "
            f"direction into the other would leave that line running the wrong "
            f"way with nothing said about it. Build the tee you want: "
            f"Tee({self.name!r}, branch={value!r})"
        )

    @property
    def tag(self) -> str:
        """Return ``""``; a tee is never labelled."""
        return ""

    def repeats(self, other: "Unit") -> bool:
        """Return whether ``other`` is a tee, which may share this name.

        Parameters
        ----------
        other : Unit
            Unit with the same name.

        Returns
        -------
        bool
            True for another tee.
        """
        return isinstance(other, Tee)


class Fitting(_NormallyPositioned):
    """In-line pipe device other than a valve.

    The variant picks the device: ``strainer``, ``strainer_cone``,
    ``strainer_y``, ``strainer_basket``, ``strainer_duplex``, ``orifice``,
    ``rotameter``, ``rupture_disc``, ``sight_glass``, ``sight_glass_lit``,
    ``silencer``, ``expansion_joint``, ``bellows``, ``blind``, ``damper``,
    ``spool``, ``static_mixer`` (ISO 10628-2 item 12.2 X2673),
    ``rotary_mixer`` (item 12.1 X2672), ``mixing_path`` (item 12.3 X8184),
    ``steam_trap`` (item 24.15, registered 2181), ``hose``, ``coupling``,
    ``clamped_coupling``, ``flange`` (the default), and the flame arrestors
    (``flame_arrestor`` plus ``_explosion_proof`` / ``_detonation_proof``
    / ``_fire_resistant``).

    Primary flow elements are variants too: ``venturi``, ``flow_nozzle``,
    ``coriolis``, ``vortex``, ``ultrasonic``, ``turbine_meter``,
    ``positive_displacement``, ``v_cone``, ``wedge``, ``target``,
    ``pitot`` and ``averaging_pitot``. Attach the FE balloon with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument`.

    A stream keeps its line number through a fitting unless
    ``new_line_number`` is set.

    ``blind`` is the spectacle (figure-8) blind and the only fitting with a
    ``normal_position``:

    - ``"open"`` (the default) draws the bored disc in the line: the line
      is through.
    - ``"closed"`` draws the solid disc in the line: the line is blanked.

    Every other variant raises :class:`ValueError` for ``"closed"``.
    Parameters are those of :class:`_NormallyPositioned`.
    """

    inlet: Port
    outlet: Port

    kind = "fitting"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    def _refuse_closed(self) -> None:
        """Raise unless this variant has a normally closed drawing.

        Raises
        ------
        ValueError
            If the variant is drawn in one position only.
        """
        from pandid.render.symbols import default_registry

        if default_registry.closed_symbol(self.kind, self.variant) is None:
            drawn = default_registry.closed_variants(self.kind)
            raise ValueError(
                f"{self.name}: variant {self.variant!r} is drawn one way, so it has "
                f"no normally closed position to state; the fittings drawn in two "
                f"positions are: {', '.join(drawn)}. Use a valve if what closes the "
                f"line is a valve."
            )


class Ejector(Unit):
    """Steam or gas ejector, or eductor.

    ``motive`` drives the nozzle, ``suction`` is the entrained stream, and
    ``discharge`` leaves the diffuser.
    """

    motive: Port
    suction: Port
    discharge: Port

    kind = "ejector"
    PORTS = [
        ("motive", "inlet", "utility"),
        ("suction", "inlet", "process"),
        ("discharge", "outlet", "process"),
    ]


class Vent(Unit):
    """Open end to atmosphere.

    A boundary like :class:`Product`, drawn as piping rather than an
    off-page flag, for a PSV tailpipe or tank breather. Variants are
    ``"default"`` (stack with a weather cap), ``"exhaust_head"`` (silencing
    hood) and ``"breather"`` (tank conservation vent); each has one inlet
    piped from below.
    """

    inlet: Port

    kind = "vent"
    PORTS = [("inlet", "inlet", "vapor")]


class Funnel(Unit):
    """Open charging funnel: a manual addition point feeding a line.

    Its single port is an outlet: the cone is open to the room and the stem
    feeds the process.
    """

    outlet: Port

    kind = "funnel"
    PORTS = [("outlet", "outlet", "feed")]


class Furnace(Unit):
    """Fired heater or furnace: a stream heated by burning fuel."""

    inlet: Port
    outlet: Port
    fuel: Port

    kind = "furnace"
    # Vessel rank: the train is drawn through it, not around it.
    LAYOUT_CONFIDENCE = 4
    # The fuel header is a utility; do not hang it below the furnace.
    PLACES = {"fuel": None}
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("fuel", "inlet", "feed"),
    ]


class Boiler(Unit):
    """Steam boiler: feedwater in, steam out. ISO 10628-2 item 4.1, 2532.

    ``feedwater`` is on the west wall and ``steam`` leaves the dome's apex.
    ISO draws no fuel or flue connection, so a separately fired boiler is a
    :class:`Furnace` upstream on the sheet.
    """

    feedwater: Port
    steam: Port

    kind = "boiler"
    # Vessel rank, as for Furnace.
    LAYOUT_CONFIDENCE = 4
    # Steam leaves the apex but its consumers are downstream, so claim east.
    PLACES = {"steam": "E"}
    PORTS = [("feedwater", "inlet", "process"), ("steam", "outlet", "process")]


class Stack(Unit):
    """Exhaust stack or chimney. ISO 10628-2 item 4.7, 2041.

    Tagged equipment for furnace or boiler flue gas, unlike :class:`Vent`,
    which is bulk piping. One inlet low on the shaft; nothing leaves it.
    """

    inlet: Port

    kind = "stack"
    PORTS = [("inlet", "inlet", "vapor")]


class Flare(Unit):
    """Flare stack: waste gas burned off at the tip. ISO 10628-2 item 4.8, 2591.

    One inlet low on the shaft, as on :class:`Stack`. To name a flare header
    without drawing the stack, use ``Product(header=True)``.
    """

    inlet: Port

    kind = "flare"
    PORTS = [("inlet", "inlet", "vapor")]


class Turbine(Unit):
    """Steam or gas turbine, or expander."""

    inlet: Port
    outlet: Port

    kind = "turbine"
    # Machine rank, as for Compressor and Pump.
    LAYOUT_CONFIDENCE = 2
    # No PLACES: the symbol fixes inlet west and outlet east, and a stated
    # face would ignore mirroring.

    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Filter(Unit):
    """Liquid or gas filter, with one of three port sets.

    **Clarifying** (one in, one out) holds the solids in the medium, which
    is cleaned offline. Variants: ``default`` (bag, candle or cartridge),
    ``fixed_bed``, ``gas``, ``gas_fixed_bed`` and ``gas_belt``.

    **Cake-forming** separates a slurry into filtrate and cake, with a
    displacement wash that pushes mother liquor out of the cake. Variants:
    ``press``, ``belt``, ``rotary`` and ``rotary_scraper``::

        Filter("F-101", variant="press")
          .inlet      slurry in
          .wash_in    wash water in
          .outlet     filtrate out
          .cake       cake out

    **Regenerated** (``ion_exchange``) has ``regenerant_in`` (acid, caustic
    or brine) and ``spent_regenerant`` instead, so the line list names the
    right fluid.

    The extra ports are optional to pipe;
    :meth:`~pandid.flowsheet.Flowsheet.validate` reports only numbered
    ports left unconnected.

    Parameters
    ----------
    name, variant, width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    # Only the ports every variant has, so ``f.cake`` does not type-check
    # on a bag filter. The generated device classes
    # (:class:`~pandid.devices.FilterPress` and others) declare the rest;
    # otherwise use ``f.port("cake")``.
    inlet: Port
    outlet: Port

    kind = "filter"
    LAYOUT_CONFIDENCE = 2
    # Regenerant lines run to day tanks and effluent headers; do not let
    # them place those above the filter. wash_in keeps its artwork claim:
    # silencing it costs crossings on the alumina example until the
    # fallback for silent ports improves.
    PLACES = {"regenerant_in": None, "spent_regenerant": None}
    # Ports depend on the variant; __init__ adds _VARIANT_PORTS.
    PORTS: list[tuple[str, str, str]] = []
    # One in, one out; the default.
    _CLARIFYING = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
    ]
    # The wash is a utility supplied to the machine; it stays a material
    # stream, since a line is an energy stream only when both ends are.
    # Cake is wet solids, which has no role of its own, so it is process.
    _CAKE_FORMING = [
        ("inlet", "inlet", "process"),
        ("wash_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("cake", "outlet", "process"),
    ]
    # Named for the fluid, not the side: regenerant is acid, caustic or brine.
    _REGENERATED = [
        ("inlet", "inlet", "process"),
        ("regenerant_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("spent_regenerant", "outlet", "process"),
    ]
    # Variant -> port set; absent variants clarify.
    _VARIANT_PORTS = {
        "press": _CAKE_FORMING,
        "belt": _CAKE_FORMING,
        "rotary": _CAKE_FORMING,
        "rotary_scraper": _CAKE_FORMING,
        "ion_exchange": _REGENERATED,
    }

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return the ports a variant adds.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs, or none when the class declares :attr:`PORTS`.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._CLARIFYING)

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


class Centrifuge(Unit):
    """Centrifuge, ISO 10628-2 group 9.

    ``overflow`` is drawn high on the shell and ``underflow`` low, where
    the solids discharge. The ports are named by position, as on
    :class:`Separator`, because either may be the product::

        Centrifuge("CF-101")                             # 9.6  X8082  decanter
        Centrifuge("CF-102", variant="disc")              # 9.4  X8036
        Centrifuge("CF-103", variant="high_speed")        # 9.1  X2619
        Centrifuge("CF-104", variant="perforated_shell")  # 9.2  X2614
        Centrifuge("CF-105", variant="solid_shell")       # 9.3  X8035
        Centrifuge("CF-106", variant="screw_perforated")  # 9.5  X8037
        Centrifuge("CF-107", variant="pusher")            # 9.7  X8038
        Centrifuge("CF-108", variant="skimmer")           # 9.8  X8039

    The default is the decanter (9.6 X8082): group 9 has no general
    centrifuge, and the decanter is the commonest solid-liquid duty. Every
    variant has the same three ports.

    Separation is by rotation, not gravity, so a centrifuge may be turned
    or mirrored (ISO 15519-1 11.4.2).
    """

    feed: Port
    overflow: Port
    underflow: Port

    kind = "centrifuge"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]


class Dryer(Unit):
    """Dryer: removes moisture from a solid or slurry.

    ``feed`` and ``product`` carry the solid; ``heating_in`` and ``vent``
    carry the drying gas in and out. ISO 10628-2 group 10 draws only the
    solid pair, so the gas ports are this library's addition, on the
    casing wall.

    Parameters
    ----------
    name, variant, width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    feed: Port
    product: Port
    heating_in: Port
    vent: Port

    kind = "dryer"
    # heating_in is a utility from a header; do not place the header below.
    PLACES = {"heating_in": None}
    # Ports depend on the variant; all variants are gas swept today.
    PORTS: list[tuple[str, str, str]] = []
    _GAS_SWEPT = [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("heating_in", "inlet", "utility"),
        ("vent", "outlet", "vapor"),
    ]
    _VARIANT_PORTS: dict[str, list[tuple[str, str, str]]] = {}

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return the ports a variant adds.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs, or none when the class declares :attr:`PORTS`.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._GAS_SWEPT)

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


class Kiln(Unit):
    """Kiln or calciner: solids heated and reacted in the combustion chamber.

    Unlike :class:`Furnace`, the solids meet the fire and the off-gas is a
    plant stream; unlike :class:`Dryer`, the solids react. The ports are::

        kiln.feed      the raw solids
        kiln.product   the calcined solids
        kiln.offgas    the spent combustion gas
        kiln.fuel      fuel to the burner
        kiln.air       combustion or fluidising air

    Variants::

        Kiln("K-101")                            # rotary kiln
        Kiln("CA-901", variant="fluidized_bed")  # fluidised-bed calciner
        Kiln("K-301", variant="shaft")           # vertical shaft kiln

    Riding rings, drive and hood are part of each body, not overlays.
    Every variant is gravity-fixed and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).
    """

    feed: Port
    product: Port
    offgas: Port
    fuel: Port
    air: Port

    kind = "kiln"
    # Vessel rank, as for Furnace.
    LAYOUT_CONFIDENCE = 4
    # Off-gas leaves the train up and away, like Separator.overflow. Fuel
    # and air are utilities; do not let them place their headers. Feed and
    # product keep the artwork's faces, which follow mirroring.
    PLACES = {"offgas": "NE", "fuel": None, "air": None}
    PORTS = [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("offgas", "outlet", "vapor"),
        ("fuel", "inlet", "feed"),
        ("air", "inlet", "utility"),
    ]


class Feeder(Unit):
    """Proportional or metering feeder, ISO 10628-2 group 19.

    Solids enter at ``feed`` and leave metered at ``discharge``::

        Feeder("FD-101")                          # 19.1  C2056  general
        Feeder("FD-102", variant="rotary_valve")  # 19.2  X8067
        Feeder("FD-103", variant="rotary_table")  # 19.3  C0074
        Feeder("FD-104", variant="metering")      # 19.4  C0035

    The default is the general feeder (19.1), for a duty sized before its
    mechanism is chosen. A rotary valve feeds solids into a pressurised
    system; a metering feeder is drawn as a balance. Every variant is
    gravity-fixed and reported as ``gravity-turned`` if turned (ISO
    15519-1 11.4.2).
    """

    feed: Port
    discharge: Port

    kind = "feeder"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]


class SprayNozzle(Unit):
    """Spray nozzle, ISO 10628-2 item 19.5 2037.

    A terminal fitting drawn as a fan opening downward. Its one port,
    ``inlet``, is offered on the west and east faces, since ISO draws the
    header passing through the apex.
    """

    inlet: Port

    kind = "spray_nozzle"
    PORTS = [("inlet", "inlet", "process")]


class ScreeningDevice(Unit):
    """Screening device: sieve, strainer or rake, ISO 10628-2 group 7.

    Named for the ISO group; :class:`~pandid.devices.Screen` is the
    separate ``Separator(variant="sifter")`` drawing. Feed enters from
    above, ``oversize`` leaves a side wall and ``undersize`` leaves the apex
    below. The ports are named by position, as on :class:`Separator`,
    because either may be the product::

        ScreeningDevice("SC-101")                             # 7.1  X8123  general
        ScreeningDevice("SC-102", variant="coarse_rake")      # 7.2  X8026
        ScreeningDevice("SC-103", variant="fine_rake")        # 7.3  X8027
        ScreeningDevice("SC-104", variant="coarse_and_fine")  # 7.4  X8028
        ScreeningDevice("SC-105", variant="vibrating")        # 7.5  X2605
        ScreeningDevice("SC-106", variant="rotating_drum")    # 7.6  X8029
        ScreeningDevice("SC-107", variant="basket_reel")      # 7.7  X8030

    Every variant has the same three ports. Drawn one way up and
    reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).
    """

    feed: Port
    oversize: Port
    undersize: Port

    # Not "screen": pandid.spec aliases class names and kinds in one table,
    # and "screen" would collide with the Screen device class.
    kind = "screening_device"
    # The artwork feeds through the roof, but upstream is drawn west, not
    # above. Undersize goes south-east, like Separator.underflow, so the
    # two products get a lane each; oversize keeps the artwork's east face.
    PLACES = {"feed": "W", "undersize": "SE"}
    PORTS = [
        ("feed", "inlet", "feed"),
        ("oversize", "outlet", "process"),
        ("undersize", "outlet", "process"),
    ]


class Kneader(Unit):
    """Kneader for paste, dough or rubber, ISO 10628-2 item 12.4 X8134.

    Tagged equipment, unlike the in-line ``rotary_mixer`` and
    ``mixing_path`` :class:`Fitting` variants. Drawn one way up and
    reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).
    """

    inlet: Port
    outlet: Port

    kind = "kneader"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class CrushingMachine(Unit):
    """Size-reduction machine, type not yet chosen: ISO 10628-2 item 11.1 X8084.

    For an early PFD that has sized a crushing or grinding duty before
    choosing the machine::

        CrushingMachine("SZ-101")            # 11.1  X8084  general

    Use :class:`Crusher` or :class:`Mill` once the machine is chosen; both
    take the same arguments.

    ``feed`` enters the top and ``discharge`` leaves the bottom, using
    :class:`Conveyor`'s names. There is no ``drive`` port because ISO draws
    none for group 11; draw the motor as its own unit if needed.
    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).
    """

    feed: Port
    discharge: Port

    kind = "crushing_machine"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]


class Crusher(CrushingMachine):
    """Crusher: coarse size reduction, ISO 10628-2 item 11.2 X8085.

    ``variant`` names the ISO group-29 characteristic::

        Crusher("CR-101")                    # 11.2  X8085  general
        Crusher("CR-102", variant="jaw")     # 11.5  X8047
        Crusher("CR-103", variant="cone")    # 11.7  X8049
        Crusher("CR-104", variant="hammer")  # 11.3  X8045
        Crusher("CR-105", variant="impact")  # 11.4  X8046
        Crusher("CR-106", variant="roller")  # 11.6  X8048

    ``vibration`` is a mill characteristic (11.12) and is refused.
    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).
    """

    kind = "crusher"


class Mill(CrushingMachine):
    """Mill or pulveriser: fine grinding, ISO 10628-2 item 11.8 X8086.

    ``variant`` names the ISO group-29 characteristic::

        Mill("ML-101")                       # 11.8   X8086  general
        Mill("ML-102", variant="hammer")     # 11.9   X8050
        Mill("ML-103", variant="impact")     # 11.10  X8051
        Mill("ML-104", variant="roller")     # 11.11  X8053
        Mill("ML-105", variant="vibration")  # 11.12  X8054

    ISO has no ball or rod mill, so draw one as the general mill and say
    so in ``description``. ``jaw`` and ``cone`` are crusher
    characteristics and are refused. Drawn one way up and reported as
    ``gravity-turned`` by :meth:`~pandid.flowsheet.Flowsheet.validate`
    if turned (ISO 15519-1 11.4.2).
    """

    kind = "mill"


class Conveyor(Unit):
    """Conveyor: bulk solids carried from tail end to head end.

    ``"default"`` is the belt (ISO 10628-2 item 18.2, 3821) and
    ``"screw"`` the enclosed screw (item 18.5 X8063)::

        Conveyor("CV-101")                                # belt
        Conveyor("CV-102", variant="screw", length=140)   # screw
        Conveyor("CV-103", length=300, diameter=40)       # big rollers

    The symbol is built to ``length`` and ``diameter`` rather than scaled,
    so rollers stay round and a longer screw gets more turns at the same
    pitch. ``width`` and ``height`` are refused because a quarter turn
    swaps them.

    A belt's ``feed`` is the tail roller and ``discharge`` the head, each
    also offered on the chute face. A screw is fed through a top spout near
    the tail and discharges through a bottom spout near the head, with the
    ends offered instead.

    Parameters
    ----------
    name : str
        Tag.
    length : float, optional
        Run from tail to head, in drawn units; the symbol default when
        omitted.
    diameter : float, optional
        Belt roller or screw bore; :meth:`default_diameter` when omitted.
    variant : str, default="default"
        ``"default"`` (belt) or ``"screw"``.
    width, height : None
        Refused; use ``length`` and ``diameter``.
    label_pos, description, reference
        As for :class:`Unit`.

    Raises
    ------
    ValueError
        If ``width`` or ``height`` is given, or the size is too small to
        draw.
    """

    feed: Port
    discharge: Port

    kind = "conveyor"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]

    _length: float
    _diameter: float

    def __init__(
        self,
        name: str,
        length: float | None = None,
        diameter: float | None = None,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        from pandid.render.symbols import CONVEYOR_LENGTH

        if width is not None or height is not None:
            # Suggest the keyword the given number belongs on.
            given = width if width is not None else height
            instead = "length" if width is not None else "diameter"
            raise ValueError(
                f"{name}: a Conveyor is sized by length=, the run between its "
                f"two ends, and diameter=, the roller a belt runs on or the "
                f"bore a screw turns in. Those are the machine; width= and "
                f"height= size the drawn box instead, which a quarter turn "
                f"swaps and which would stretch a belt's rollers out of round "
                f"and a screw's flight off its pitch. Pass {instead}={given!r}."
            )
        super().__init__(
            name, variant=variant, label_pos=label_pos, description=description, reference=reference
        )
        # Set diameter first: the minimum length depends on it.
        self.diameter = self.default_diameter() if diameter is None else diameter
        self.length = CONVEYOR_LENGTH if length is None else length

    def default_diameter(self) -> float:
        """Return the default roller or bore diameter for this variant.

        Returns
        -------
        float
            Diameter in drawn units.
        """
        from pandid.render.symbols import CONVEYOR_DIAMETER, SCREW_HEIGHT

        return SCREW_HEIGHT if self.variant == "screw" else CONVEYOR_DIAMETER

    @property
    def length(self) -> float:
        """Return the run from tail to head, in drawn units."""
        return self._length

    @length.setter
    def length(self, value: float) -> None:
        """Set the run length.

        Parameters
        ----------
        value : float
            Length in drawn units.

        Raises
        ------
        ValueError
            If a belt is shorter than its two rollers, or a screw shorter
            than one flight turn.
        """
        from pandid.render.symbols import (
            SCREW_MIN_LENGTH,
            conveyor_min_length,
            conveyor_too_short,
            screw_too_short,
        )

        if self.variant == "screw":
            if value < SCREW_MIN_LENGTH:
                raise screw_too_short(value, self.name)
        elif value < conveyor_min_length(self.diameter):
            raise conveyor_too_short(value, self.name, self.diameter)
        self._length = float(value)

    @property
    def diameter(self) -> float:
        """Return the belt roller or screw bore, in drawn units.

        It is also the drawn depth of the symbol.
        """
        return self._diameter

    @diameter.setter
    def diameter(self, value: float) -> None:
        """Set the roller or bore diameter.

        Parameters
        ----------
        value : float
            Diameter in drawn units.

        Raises
        ------
        ValueError
            If ``value`` is not positive, or a belt's current length is too
            short for rollers of this size.
        """
        from pandid.render.symbols import (
            conveyor_bad_diameter,
            conveyor_min_length,
            conveyor_too_short,
            screw_bad_diameter,
        )

        if value <= 0:
            raise (screw_bad_diameter if self.variant == "screw" else conveyor_bad_diameter)(
                value, self.name
            )
        value = float(value)
        length = getattr(self, "_length", None)
        if self.variant != "screw" and length is not None and length < conveyor_min_length(value):
            raise conveyor_too_short(length, self.name, value)
        self._diameter = value


class Elevator(Unit):
    """Bucket elevator: solids lifted in buckets on a belt.

    ISO 10628-2 item 18.7 X8065; ``"z_form"`` is item 18.8 X8066, with a
    horizontal run at each end::

        Elevator("BE-301")
        Elevator("BE-302", variant="z_form")

    ``feed`` is the boot (low) and ``discharge`` the head (high). The
    straight elevator also offers north and south chute faces. There is no
    ``length``: the lift follows from the elevations it connects.
    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).
    """

    feed: Port
    discharge: Port

    kind = "elevator"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process")]


def split_tag(type: str, number: str | int = "") -> tuple[str, str]:
    """Split an instrument tag into its letters and loop number.

    ``("FT", 101)``, ``"FT-101"`` and ``"FT101"`` all give
    ``("FT", "101")``.

    Parameters
    ----------
    type : str
        Letters, or a whole tag when ``number`` is empty.
    number : str or int, default=""
        Loop number.

    Returns
    -------
    tuple[str, str]
        Letters and loop number.

    Raises
    ------
    TypeError
        If ``number`` is neither text nor a whole number, so a float such
        as ``101.0`` does not draw as ``LIC-101.0``.
    """
    if number is not None and not (isinstance(number, str) or is_whole(number)):
        raise TypeError(
            f"an instrument's loop number is text or a whole number (an int), got {number!r}"
        )
    if number != "" and number is not None:
        return type.strip(), str(number).strip()
    tag = type.strip()
    if "-" in tag:
        letters, num = tag.split("-", 1)
        return letters, num
    i = 0
    while i < len(tag) and not tag[i].isdigit():
        i += 1
    return tag[:i], tag[i:]


# Extra signal port name; the first member of each pool is bare (sig_out),
# the rest are numbered from 2 (sig_out_2).
_POOL_MEMBER = re.compile(r"(sig_in|sig_out)_\d+")

#: Where a balloon's reading is available (ISO 15519-2:2015 Table 1): no
#: bar for field, one bar for the central control system, two for a
#: subsidiary one.
DISPLAYS = ("field", "central", "subsidiary")

#: How a balloon relates to its host. ``"sensing"`` and ``"acting_on"``
#: draw a line; ``"near"`` only places the balloon.
RELATIONS = ("sensing", "acting_on", "near")

# (symbol type, display) -> registered variant. Pairs not listed use the
# symbol type unchanged, so a new balloon shape needs no entry.
_BALLOON_SYMBOLS = {
    ("default", "field"): "default",
    ("default", "central"): "panel",
    ("default", "subsidiary"): "aux",
    ("shared", "central"): "shared",
}

# Registered variant -> symbol type, for writing the two axes back out.
_BALLOON_SHAPES = {drawn: shape for (shape, _display), drawn in _BALLOON_SYMBOLS.items()}

# Display implied by a symbol type: a shared (circle-in-square) balloon
# is in the central system (CHEE4001 p.13).
_IMPLIED_DISPLAY = {"shared": "central"}

# Removed variant spellings and the display each meant. Refused by name,
# since the registry would otherwise draw the bar while display stayed
# "field".
_DISPLAY_VARIANTS = {"panel": "central", "aux": "subsidiary"}


class Instrument(Unit):
    """ISA-5.1 instrument balloon.

    The balloon draws the function letters over the bare loop number;
    ``name`` is the full tag (``"FT-101"``). ``Instrument("FT-101")``,
    ``Instrument("FT101")`` and ``Instrument("FT", 101)`` are the same.

    ``pv`` taps the process; ``sig_in`` and ``sig_out`` carry signals. All
    three are signal ports. ``sig_in`` and ``sig_out`` are pools: a
    connection to a used member gets a new one, so a balloon takes as many
    signal lines as the loop needs::

        fs.connect(pic301.sig_out, cv1.actuator, kind="pneumatic")
        fs.connect(pic301.sig_out, cv2.actuator, kind="pneumatic")

    Connecting units instead lets the engine pick both ends:
    ``fs.connect(ft305, fic305, kind="electric")``.

    ``variant`` is the symbol type: ``"default"`` (circle), ``"shared"``
    (circle in a square), ``"computer"`` (hexagon), ``"sis"`` or
    ``"logic"`` (diamond in a square, ANSI/ISA-5.1-2009 Table 5.1.1 column
    B) and ``"interlock"`` (diamond, Table 5.1.2 items 3-5). ``display`` is
    where the reading is available (:data:`DISPLAYS`). Only registered
    pairs are drawn; ``"shared"`` implies ``"central"``.

    Place a balloon on what it measures with :meth:`attach` or
    :meth:`pandid.flowsheet.Flowsheet.add_instrument`.

    Parameters
    ----------
    type : str
        Function letters, or the whole tag when ``number`` is empty.
    number : str or int, default=""
        Loop number.
    variant : str, default="default"
        Symbol type.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    display : str, optional
        One of :data:`DISPLAYS`; implied by ``variant`` when omitted, else
        ``"field"``.

    Attributes
    ----------
    type, number : str
        Function letters and loop number.
    display : str
        Where the reading is available.
    symbol_type : str
        Symbol type as the author gave it, without the display folded in.
    host : Stream, Unit or None
        What :meth:`attach` placed the balloon on.
    at, offset, angle, relation
        Attachment set by :meth:`attach`.
    quadrants : dict[str, tuple[str, ...]]
        Letter codes outside the symbol, set by :meth:`annotate`.
    tap : tuple[float, float] or None
        Resolved tap point, set by layout.

    Raises
    ------
    ValueError
        If ``display`` is unknown, ``variant`` is a removed display
        spelling, or the pair has no drawing.
    """

    pv: Port
    sig_in: Port
    sig_out: Port

    kind = "instrument"
    # Balloons are placed after the process units and make no claims.
    LAYOUT_CONFIDENCE = 0
    # Declared up front, not created on first use, so face selection sees
    # them in a fixed order whatever order the author connects them in.
    PORTS = [
        ("pv", "inlet", "signal"),
        ("sig_in", "inlet", "signal"),
        ("sig_out", "outlet", "signal"),
    ]

    # Pool names, which are also the first member of each pool.
    _SIGNAL_POOLS = ("sig_in", "sig_out")

    # Logic-function symbols, which may be drawn several times under one tag.
    _REPEATABLE_VARIANTS = frozenset({"sis", "logic", "interlock"})

    def __init__(
        self,
        type: str,
        number: str | int = "",
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
        display: str | None = None,
    ):
        letters, num = split_tag(type, number)
        # Build the name from the split, so every spelling gives one tag.
        name = f"{letters}-{num}" if letters and num else letters + num
        # _resolved_variant sets the final display.
        self.display = "field"
        variant = self._resolved_variant(name, variant, display)
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self.type = letters
        self.number = num
        # Written by to_dict, so a sheet read back names an accepted variant.
        self.symbol_type = _BALLOON_SHAPES.get(variant, variant)
        # Kept apart from name: a repeated square needs a distinct name.
        self._tag = name
        # Attachment intent (set only via attach()); the layout engine
        # resolves it into a frame, as Pin -> Frame for equipment.
        self.host: "Stream | Unit | None" = None
        self.at: float | str | None = None
        self.offset: float = 45.0
        self.angle: float = 90.0
        # One of RELATIONS; decides whether a tap line is drawn.
        self.relation: str = "sensing"
        # Primary element whose tag this balloon shares (add_balloon).
        self._marks: "Unit | None" = None
        # Letter codes written outside the symbol, keyed by quadrant;
        # see :meth:`annotate`.
        self.quadrants: dict[str, tuple[str, ...]] = {}
        # Resolved tap point; set only by layout.
        self.tap: tuple[float, float] | None = None

    def _resolved_variant(self, name: str, variant: str, display: str | None) -> str:
        """Return the registered variant for a symbol type and display.

        Sets :attr:`display` as a side effect.

        Parameters
        ----------
        name : str
            Tag, for error messages.
        variant : str
            Symbol type (ANSI/ISA-5.1 5.1.1).
        display : str or None
            Display (ISO 15519-2 Table 1); implied when ``None``.

        Returns
        -------
        str
            Registered variant.

        Raises
        ------
        ValueError
            If ``variant`` is a removed display spelling, ``display`` is
            unknown, or the pair has no drawing.
        """
        meant = _DISPLAY_VARIANTS.get(variant)
        if meant is not None:
            raise ValueError(
                f"{name}: variant={variant!r} says where the information is "
                f"available, which is the display= axis: write "
                f"display={meant!r}. What the instrument *does* is variant="
            )
        if display is None:
            display = _IMPLIED_DISPLAY.get(variant, "field")
        if display not in DISPLAYS:
            raise ValueError(
                f"{name}: display= is where the information this balloon shows is "
                f"available, one of {', '.join(repr(d) for d in DISPLAYS)}, got "
                f"{display!r}. It is ISO 15519-2 Table 1's additional graphic: no bar "
                f"in the field, one for the central control system, two for a "
                f"subsidiary one. What the instrument *does* is variant="
            )
        self.display = display
        pair = _BALLOON_SYMBOLS.get((variant, display))
        if pair is not None:
            return pair
        if display == "field":
            return variant  # an unregistered shape is the registry's to refuse
        drawn = ", ".join(
            f"variant={v!r} display={d!r}" for (v, d) in _BALLOON_SYMBOLS if d != "field"
        )
        raise ValueError(
            f"{name}: no balloon is drawn for variant={variant!r} with "
            f"display={display!r}. A location bar is registered artwork rather than "
            f"a stripe laid over any outline, and the pairs drawn today are {drawn}. "
            f"Ask for display='field', or for one of those"
        )

    # ------------------------------------------------------------------
    # Signal pools.
    #
    # sig_in and sig_out stay plain attributes naming the first member:
    # ``inst.sig_out.stream`` must read back the first line rather than
    # create a new port. Flowsheet.connect asks for another member when the
    # one given is wired. pv is not a pool; a differential instrument needs
    # named high and low taps instead.
    # ------------------------------------------------------------------

    def has_another_port(self, port: Port) -> bool:
        """Return whether ``port`` is in a signal pool.

        Parameters
        ----------
        port : Port
            Port of this balloon.

        Returns
        -------
        bool
            True for ``sig_in``/``sig_out`` members, false for ``pv``.
        """
        return self._pool_of(port.name) is not None

    def another_port(self, port: Port) -> Port:
        """Return a free member of ``port``'s pool, creating one if needed.

        Called by :meth:`pandid.flowsheet.Flowsheet.connect` when ``port``
        is already connected.

        Parameters
        ----------
        port : Port
            Pool member already in use.

        Returns
        -------
        Port
            Free member, or ``port`` itself when it is not in a pool.
        """
        base = self._pool_of(port.name)
        if base is None:
            return port
        # New members take the first member's direction.
        return self._next_member(base, self._pool_members(base)[0].direction, "signal")

    def _pool_members(self, base: str) -> list[Port]:
        """Return the members of a pool, in creation order.

        Parameters
        ----------
        base : str
            Pool name.

        Returns
        -------
        list[Port]
            Members.
        """
        return [p for name, p in self.ports.items() if self._pool_of(name) == base]

    def signal_port(self, name: str) -> Port:
        """Return a port by name, creating a missing pool member.

        Used by :func:`pandid.spec.from_dict` to rebuild pool members, as in
        ``pic.signal_port("sig_out_2")``.

        Parameters
        ----------
        name : str
            Port name.

        Returns
        -------
        Port
            Existing port, or a new pool member.

        Raises
        ------
        KeyError
            If ``name`` is neither a port nor a pool member name.
        """
        if name in self.ports:
            return self.ports[name]
        member = _POOL_MEMBER.fullmatch(name)
        if member is None:
            raise KeyError(
                f"{type(self).__name__!r} has no port named {name!r} and mints none "
                f"under that name; its signal pools are "
                f"{', '.join(f'{base}, {base}_2, {base}_3' for base in self._SIGNAL_POOLS)}"
            )
        return self._add_port(name, self.ports[member.group(1)].direction, "signal")

    def _mint_port(self, name: str) -> Port | None:
        """Return :meth:`signal_port`, or ``None`` instead of raising.

        Lets :func:`pandid.spec._find_port` report the error itself.

        Parameters
        ----------
        name : str
            Port name.

        Returns
        -------
        Port or None
            The port, or ``None`` if the name cannot be created.
        """
        try:
            return self.signal_port(name)
        except KeyError:
            return None

    @classmethod
    def _pool_of(cls, port_name: str) -> str | None:
        """Return the pool a port belongs to.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str or None
            ``"sig_in"`` or ``"sig_out"``, or ``None`` for ``pv``.
        """
        if port_name in cls._SIGNAL_POOLS:
            return port_name
        member = _POOL_MEMBER.fullmatch(port_name)
        return member.group(1) if member else None

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the anchor name, mapping pool members to their pool.

        Signal ports share one menu of four faces
        (:attr:`pandid.render.symbols.Symbol.faceless_ports`);
        :mod:`pandid.layout.faces` picks a face per port.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str
            Anchor name in the symbol.
        """
        return self._pool_of(port_name) or super()._symbol_anchor(port_name)

    @property
    def tag(self) -> str:
        """Return the ISA tag drawn in the symbol.

        Equal to :attr:`~Unit.name` except for a repeated logic square,
        whose names differ (``I-1``, ``I-1 (2)``) while the tag is shared.
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Return whether this balloon may share ``other``'s tag.

        True for the same logic symbol drawn again (``"sis"`` and
        ``"logic"`` count as one; an interlock diamond and a diamond in a
        square do not), or for the primary element this balloon was built
        for by :meth:`pandid.flowsheet.Flowsheet.add_balloon`.

        Parameters
        ----------
        other : Unit
            Unit with the same tag.

        Returns
        -------
        bool
            Whether the shared tag is allowed.
        """

        def symbol(variant: object) -> object:
            """Return the symbol a variant draws, folding ``logic`` into ``sis``."""
            return "sis" if variant == "logic" else variant

        if other is self._marks:
            return True
        return (
            isinstance(other, Instrument)
            and other.tag == self.tag
            and self.variant in self._REPEATABLE_VARIANTS
            and symbol(self.variant) == symbol(other.variant)
        )

    def annotate(
        self,
        *,
        high: "str | Sequence[str] | None" = None,
        low: "str | Sequence[str] | None" = None,
        safety: "str | Sequence[str] | None" = None,
        variable: "str | Sequence[str] | None" = None,
    ) -> "Instrument":
        """Write letter codes in the quadrants around this symbol.

        ISO 15519-2 5.2.5 puts letter codes with modifiers H or L outside
        the symbol, ordered A, S then Z outward; no line is drawn. The
        quadrants are the corners (5.1.3, Figure 8), so no face is used.
        Codes in one quadrant are sorted into that order::

            lic304.annotate(high="LAH", low="LAL")
            lsh611.annotate(high=("LAHH", "LSHH"))
            ai301.annotate(variable="pH", safety="SIL 2")

        An omitted argument leaves its quadrant unchanged; an empty
        sequence clears it.

        Parameters
        ----------
        high : str or Sequence[str], optional
            Quadrant (c): high functions such as alarms or switches.
        low : str or Sequence[str], optional
            Quadrant (d): low functions.
        safety : str or Sequence[str], optional
            Quadrant (a): typical-diagram reference or safety information
            such as a SIL or SIF identifier.
        variable : str or Sequence[str], optional
            Quadrant (b): the variable meant by letter code U, such as pH.

        Returns
        -------
        Instrument
            This balloon.

        Raises
        ------
        ValueError
            If a code is empty.
        """
        for name, codes in (("a", safety), ("b", variable), ("c", high), ("d", low)):
            if codes is None:
                continue
            written = _quadrant_codes(self.name, name, codes)
            if written:
                self.quadrants[name] = written
            else:
                self.quadrants.pop(name, None)
        return self

    def attach(
        self,
        on: "Stream | Unit",
        *,
        at: float | str | None = None,
        offset: float = 45.0,
        angle: float = 90.0,
        relation: str = "sensing",
    ) -> "Instrument":
        """Anchor this balloon to a process line or to equipment.

        An attached balloon is placed from its host, not by flow order. An
        absolute :meth:`~Unit.pin` overrides the standoff on the axis it
        names; the tap point is kept.

        Parameters
        ----------
        on : Stream or Unit
            Host line or equipment.
        at : float or str, optional
            Fraction 0 to 1 along a stream's routed path (default 0.5), or
            a face ``"N"``, ``"S"``, ``"E"`` or ``"W"`` of a unit (default
            ``"E"``).
        offset : float, default=45.0
            Distance from tap to balloon centre in pixels; 0 draws an
            in-line element on the line.
        angle : float, default=90.0
            Branch direction in degrees, counter-clockwise from the flow
            direction at the tap (or the face tangent on a unit).
        relation : str, default="sensing"
            One of :data:`RELATIONS`; ``"near"`` draws no tap line.

        Returns
        -------
        Instrument
            This balloon.

        Raises
        ------
        TypeError
            If ``on`` is not a Stream or Unit.
        ValueError
            If ``on`` is this balloon, or ``at``, ``offset`` or
            ``relation`` is invalid.
        """
        from pandid.streams import Stream

        if not isinstance(on, (Stream, Unit)):
            raise TypeError(
                f"{self.name}: attach(on=...) takes a Stream or a Unit, got {type(on).__name__}"
            )
        if isinstance(on, Unit) and on is self:
            raise ValueError(f"{self.name} cannot be attached to itself")
        if isinstance(on, Stream):
            if at is None:
                at = 0.5
            if isinstance(at, str):
                raise ValueError(
                    f"{self.name}: at= on a stream is a fraction 0..1 along its "
                    f"routed path, got {at!r}"
                )
            if not 0.0 <= float(at) <= 1.0:
                raise ValueError(f"{self.name}: at= must be within 0..1, got {at!r}")
            at = float(at)
        else:
            if at is None:
                at = "E"
            if not isinstance(at, str) or at.upper() not in ("N", "S", "E", "W"):
                raise ValueError(
                    f"{self.name}: at= on a unit host is a face 'N'/'S'/'E'/'W', got {at!r}"
                )
            at = at.upper()
        if offset < 0:
            raise ValueError(f"{self.name}: offset= must not be negative, got {offset!r}")
        if relation not in RELATIONS:
            raise ValueError(
                f"{self.name}: relation= is what this balloon has to do with "
                f"{getattr(on, 'name', on)!r}, one of "
                f"{', '.join(repr(r) for r in RELATIONS)}, got {relation!r}"
            )
        self.host = on
        self.at = at
        self.offset = float(offset)
        self.angle = float(angle)
        self.relation = relation
        # Placement is resolved in route(), so re-anchoring needs a re-route.
        self._invalidate_layout()
        return self


def _quadrant_codes(where: str, quadrant: str, codes: "str | Sequence[str]") -> tuple[str, ...]:
    """Return one quadrant's letter codes in ISO 15519-2 5.2.5 order.

    Codes are sorted A, S then Z outward by their function letter; codes
    with none of these follow in the given order.

    Parameters
    ----------
    where : str
        Tag, for error messages.
    quadrant : str
        Quadrant letter, for error messages.
    codes : str or Sequence[str]
        Codes; an empty string or sequence clears the quadrant.

    Returns
    -------
    tuple[str, ...]
        Sorted codes.

    Raises
    ------
    ValueError
        If a code is empty.
    """
    if isinstance(codes, str):
        codes = (codes,) if codes else ()
    out = [str(code).strip() for code in codes]
    for code in out:
        if not code:
            raise ValueError(
                f"{where}: quadrant {quadrant!r} was given an empty letter code. A "
                f"quadrant holds the codes written outside the symbol, e.g. "
                f"high='LAH'; leave the argument out to write nothing there"
            )

    def rank(code: str) -> int:
        """Return a code's sort rank from its function letter.

        The function letter follows the measured variable: ``LAH``
        alarms, ``LSHH`` switches, ``LZHH`` trips.
        """
        return next((" ASZ".index(c) for c in code[1:] if c in "ASZ"), 4)

    return tuple(sorted(out, key=rank))


def _side_ports(*sides: str) -> list[tuple[str, str, str]]:
    """Return an inlet and an outlet spec for each named side.

    Parameters
    ----------
    *sides : str
        Side names, such as ``"shell"`` and ``"tube"``.

    Returns
    -------
    list[tuple[str, str, str]]
        ``(name, direction, role)`` port specs.
    """
    return [
        (f"{side}_{end}", direction, "process")
        for side in sides
        for end, direction in (("in", "inlet"), ("out", "outlet"))
    ]


class HeatExchanger(Unit):
    """Heat exchanger with an inlet and outlet on each of its two sides.

    Ports are named for the side of the equipment, not the duty: which
    fluid goes shell side is a design decision the drawing records, and
    which side is hot can change between operating cases.

    Most variants are shell and tube. ``air_cooled`` has ``tube`` and
    ``air`` sides, ``plate`` and ``spiral`` have ``side_a`` and ``side_b``,
    and ``thin_film`` has ``jacket`` and ``product`` sides. ``kettle`` adds
    ``bottoms``, the liquid draw at the weir end of the shell.

    Parameters
    ----------
    name, variant, width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    # Only the shell-and-tube ports, so ``hx.bottoms`` does not type-check
    # on every exchanger; use ``hx.port("bottoms")`` for the others.
    shell_in: Port
    shell_out: Port
    tube_in: Port
    tube_out: Port

    kind = "hex"
    # No PLACES: which side is the process depends on the service, so a
    # class-wide claim would misplace either condensers or interchangers.
    LAYOUT_CONFIDENCE = 2
    # Ports depend on the variant; __init__ adds _VARIANT_PORTS.
    PORTS: list[tuple[str, str, str]] = []
    # Default port set.
    _SHELL_AND_TUBE = _side_ports("shell", "tube")
    # Variant -> port set; absent variants are shell and tube.
    _VARIANT_PORTS = {
        "kettle": [*_SHELL_AND_TUBE, ("bottoms", "outlet", "liquid")],
        "air_cooled": _side_ports("tube", "air"),
        "plate": _side_ports("side_a", "side_b"),
        "spiral": _side_ports("side_a", "side_b"),
        "thin_film": _side_ports("jacket", "product"),
    }

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return the ports a variant adds.

        A subclass that declares :attr:`~Unit.PORTS` gets none, so a
        per-variant subclass does not add its ports twice.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._SHELL_AND_TUBE)

    def __init__(
        self,
        name: str,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


class Heater(Unit):
    """Single-stream heater with a utility heating medium.

    ``utility_in`` is the heating medium's connection.
    """

    inlet: Port
    outlet: Port
    utility_in: Port

    kind = "heater"
    LAYOUT_CONFIDENCE = 2
    # The utility header is placed by the sheet, not hung below each heater.
    # inlet and outlet are not restated: their artwork faces follow
    # mirroring, and a PLACES entry would not.
    PLACES = {"utility_in": None}
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("utility_in", "inlet", "energy"),
    ]


class Cooler(Unit):
    """Single-stream cooler with a utility cooling medium.

    ``utility_out`` is the cooling medium's connection.
    """

    inlet: Port
    outlet: Port
    utility_out: Port

    kind = "cooler"
    LAYOUT_CONFIDENCE = 2
    # As for Heater: do not lift the return header above every cooler.
    PLACES = {"utility_out": None}
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("utility_out", "outlet", "energy"),
    ]


class CoolingTower(Unit):
    """Evaporative cooling tower.

    ``"default"`` and ``"induced_draft"`` draw the fan on a stack over the
    fill; ``"forced_draft"`` draws fans at the foot of each side. Both have
    the same six ports.

    Ports are named for the side, as on :class:`HeatExchanger`: ``water``
    for the circulating loop and ``air`` for the draught. ``makeup``
    replaces evaporation and drift losses, and ``blowdown`` bleeds off
    dissolved solids; both are on the basin. The air ports are usually left
    unpiped.
    """

    water_in: Port
    water_out: Port
    air_in: Port
    air_out: Port
    # Makeup is a utility supplied to the tower; blowdown is water leaving.
    makeup: Port
    blowdown: Port

    kind = "cooling_tower"
    # Vessel rank: coolers on the sheet are piped back to it.
    LAYOUT_CONFIDENCE = 4
    # Cold water leaves the basin but the loop runs on east. Makeup,
    # blowdown and air intake run to headers or ambient, so they place
    # nothing. air_out keeps its north face: exhaust is drawn leaving up.
    PLACES = {"water_out": "E", "air_in": None, "makeup": None, "blowdown": None}
    PORTS = [
        *_side_ports("water", "air"),
        ("makeup", "inlet", "utility"),
        ("blowdown", "outlet", "liquid"),
    ]


class Evaporator(Unit):
    """Evaporator: liquor concentrated by boiling off water.

    Unlike :class:`HeatExchanger`, the vapour is a plant stream piped to the
    next effect or a condenser. ``feed``, ``vapor`` (crown) and
    ``concentrate`` (bottom) are the process; ``heating_in`` and
    ``condensate`` are the steam chest. The chest is fed from the west and
    drained to the east, so one effect's vapour reaches the next effect's
    ``heating_in`` in a left-to-right train.

    Variants::

        Evaporator("EV-101")                            # element unspecified
        Evaporator("EV-102", variant="calandria")       # short-tube
        Evaporator("EV-103", variant="falling_film")
        Evaporator("EV-104", variant="climbing_film")
        Evaporator("EV-105", variant="plate")

    ``default`` draws an unspecified element for an early PFD. The falling-
    and climbing-film bodies differ in where the liquor enters, and only
    the falling-film body has a distributor. Draw forced circulation as
    this body, a circulating heater and a pump.

    ``supports`` draws an ISO group-26 support under the shell, as on
    :class:`Vessel`::

        Evaporator("EV-101", variant="falling_film", supports="skirt")

    The heating element is the variant, not an overlay, because ISO
    groups 26 to 29 draw no tube bundle or plate pack. Drawn one way up
    and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Heating element.
    supports : str, optional
        ``"leg"``, ``"bracket"``, ``"skirt"`` or ``"ring"``. Fixed at
        construction.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    feed: Port
    vapor: Port
    concentrate: Port
    heating_in: Port
    condensate: Port

    kind = "evaporator"
    # Vessel rank, as for Separator.
    LAYOUT_CONFIDENCE = 4
    # Vapour goes to the next unit along, not above, or a train climbs into
    # a staircase. Concentrate goes down and on, clear of the vapour. The
    # steam chest runs to utility headers and places nothing. feed keeps
    # its artwork face, which follows mirroring.
    PLACES = {"vapor": "E", "concentrate": "SE",
              "heating_in": None, "condensate": None}
    PORTS = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("concentrate", "outlet", "liquid"),
        ("heating_in", "inlet", "utility"),
        ("condensate", "outlet", "utility"),
    ]
    # No support unless ``supports`` names one.
    COMPOSITION = {"supports": None}
    # The supports overlay is composed in __init__.
    _FIXED_AT_CONSTRUCTION = frozenset({"supports"})

    def __init__(
        self,
        name: str,
        variant: str = "default",
        supports: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        from pandid.render.iso_parts import support_overlays

        self.supports = supports
        _compose_onto(self, () if supports is None else support_overlays(supports))


#: Default thickener rake: ISO 10628-2 item 28.4 C2021, the cross-beam
#: stirrer, the nearest group-28 form to a rake.
DEFAULT_RAKE = "cross_beam"


class Thickener(Unit):
    """Thickener or clarifier: solids settled out of a slurry by gravity.

    A thickener is bought for the underflow and a clarifier for the
    overflow; the drawing is the same, so there is one class::

        thickener.feed        the slurry, into a launder at the rim
        thickener.overflow    the clarified liquor, over the weir
        thickener.underflow   the thickened solids, out of the cone

    The draws are named by position, as on :class:`Separator`. This is not
    ``Separator(characteristic="gravity")`` (ISO item 8.3 X8031), which is
    a tall hopper-bottomed drum with no rake.

    ``rake`` names the ISO group-28 stirrer on the central shaft::

        Thickener("TH-101")                     # raked, 28.4's cross-beam
        Thickener("TH-102", rake="gate_paddle")
        Thickener("TH-103", rake=None)          # a plain settling tank

    The rake drive is not drawn, because ISO draws a motor inside an
    apparatus only for item 1.27; draw a tagged drive beside the thickener
    if needed (see :func:`~pandid.render.iso_parts.rake_overlays`).
    Drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body drawing.
    rake : str or None, default=DEFAULT_RAKE
        Group-28 stirrer, or ``None`` for none. Fixed at construction.
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    feed: Port
    overflow: Port
    underflow: Port

    kind = "thickener"
    # Vessel rank, as for Separator.
    LAYOUT_CONFIDENCE = 4
    # As Separator: overflow up and away, underflow down and on, so the two
    # draws never share a cell. feed keeps its artwork face.
    PLACES = {"overflow": "NE", "underflow": "SE"}
    PORTS = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    # Raked unless rake=None.
    COMPOSITION = {"rake": DEFAULT_RAKE}
    _FIXED_AT_CONSTRUCTION = frozenset({"rake"})

    def __init__(
        self,
        name: str,
        variant: str = "default",
        rake: str | None = DEFAULT_RAKE,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        from pandid.render.iso_parts import rake_overlays

        self.rake = rake
        _compose_onto(self, () if rake is None else rake_overlays(rake))


def _feed_names(n_feeds: int, owner: str) -> list[str]:
    """Return feed port names ``feed_1`` to ``feed_n``.

    Numbered from one at every count; the caller adds the bare ``feed``
    alias when there is one feed. ``unit.feeds[0]`` is ``feed_1``.

    Parameters
    ----------
    n_feeds : int
        Number of feeds.
    owner : str
        Unit name, for error messages.

    Returns
    -------
    list[str]
        Port names.

    Raises
    ------
    ValueError
        If ``n_feeds`` is less than 1.
    """
    if n_feeds < 1:
        raise ValueError(f"{owner} requires at least 1 feed, got {n_feeds}")
    return [f"feed_{i}" for i in range(1, n_feeds + 1)]


def _draw_names(n_draws: int, owner: str) -> list[str]:
    """Return a column's side-draw port names.

    Parameters
    ----------
    n_draws : int
        Number of draws; may be 0.
    owner : str
        Unit name, for error messages.

    Returns
    -------
    list[str]
        ``[]``, ``["draw"]``, or ``draw_1`` to ``draw_n``.

    Raises
    ------
    ValueError
        If ``n_draws`` is negative.
    """
    if n_draws < 0:
        raise ValueError(f"{owner} cannot take a negative number of draws, got {n_draws}")
    if n_draws == 0:
        return []
    return ["draw"] if n_draws == 1 else [f"draw_{i}" for i in range(1, n_draws + 1)]


def _stage_fractions(
    name: str,
    internals: str | None,
    trays: int,
    stages: list[int | None] | None,
    names: list[str],
    keyword: str,
    noun: str,
) -> dict[str, float]:
    """Return the shell fraction for each port given a stage.

    Shared by a column's ``feed_stages`` and ``draw_stages`` so both are
    checked alike. Ports without a stage keep the even spread of
    :class:`~pandid.render.symbols.PortSeries`.

    Parameters
    ----------
    name : str
        Unit name, for error messages.
    internals : str or None
        Column internals; ``None`` draws no stages.
    trays : int
        Drawn stage count.
    stages : list[int or None] or None
        One stage per port in declaration order, ``None`` for a port that
        keeps the even spread; ``None`` for all.
    names : list[str]
        Port names.
    keyword : str
        Argument name, for error messages.
    noun : str
        ``"feed"`` or ``"draw"``, for error messages.

    Returns
    -------
    dict[str, float]
        Port name to fraction of the shell, for ports given a stage.

    Raises
    ------
    ValueError
        If the list length differs from ``names``, a stage is named with no
        internals, or a stage is out of range.
    """
    if stages is None:
        return {}
    if len(stages) != len(names):
        raise ValueError(
            f"{name} has {len(names)} {noun}{'s' if len(names) != 1 else ''} "
            f"({', '.join(names)}) but {keyword} names {len(stages)}; "
            f"give one entry per {noun}, in the same order, and null for a {noun} "
            f"that keeps the even spread"
        )
    if internals is None:
        if any(stage is not None for stage in stages):
            raise ValueError(
                f"{name}: {keyword} names a stage, and this column draws no "
                f"stages to put one on -- internals is None, so there is nothing on "
                f"the shell for a reader to count against. Give internals= a deck or "
                f"a bed, or drop {keyword} and let n_{noun}s spread the {noun}s evenly"
            )
        return {}
    from pandid.render.iso_parts import stage_fraction

    fractions = {}
    for one_name, stage in zip(names, stages):
        if stage is None:
            continue
        try:
            fractions[one_name] = stage_fraction(internals, stage, trays)
        except ValueError as e:
            raise ValueError(f"{name}.{one_name}: {e}") from None
    return fractions


#: Deprecation of ``Reactor(variant="plain")``. Its hatched bed is not an
#: ISO mark; ``internals="packing"`` draws item 27.8 X8141 on the standard
#: vessel shell, so the drawing and its size change.
REACTOR_VARIANT_PLAIN = Deprecation(
    what="Reactor(variant='plain')",
    instead="Reactor(internals='packing')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 27.8 X8141's crossed bed on the "
    "standard vessel shell, in place of this one's diagonal hatch",
)


#: Deprecation of ``Reactor(variant="mixing")``, a cone-bottomed body with
#: the stirrer and motor drawn in. ISO draws an agitated vessel only as item
#: 1.27 X8006 (dished ends), and the drawn motor had no ``drive`` port.
#: ``agitator="disc"`` (item 28.9 C2026, nearest to the drawn plates)
#: replaces it.
REACTOR_VARIANT_MIXING = Deprecation(
    what="Reactor(variant='mixing')",
    instead="Reactor(agitator='disc')",
    removed_in="0.2.0",
    note="the drawing changes -- ISO item 1.27 X8006's dished-end shell with a "
    "group-28 stirrer and the motor that turns it, in place of this one's "
    "cone-bottomed box and the capsule on top of it; the cone goes, and "
    "the stirrer becomes one you can choose and route a drive to",
)


class Reactor(Unit):
    """Reactor: CSTR, PFR, packed bed or fluidised bed.

    ISO 10628-2 has no reactor symbol, so a reactor is a vessel body
    (``variant``) with ISO parts inside (``agitator`` and ``internals``)::

        Reactor("R-101")                              # a CSTR
        Reactor("R-102", agitator="turbine")
        Reactor("R-103", variant="jacketed")          # jacketed CSTR
        Reactor("R-201", internals="packing")         # a PBR
        Reactor("R-202", internals="fluidised_bed")   # a FBR
        Reactor("R-301", variant="tubular")           # a PFR

    ``variant`` is ``"default"`` (dished-end stirred tank), ``"jacketed"``
    or ``"tubular"`` (horizontal plug-flow shell). ``"plain"`` and
    ``"mixing"`` are deprecated.

    ``agitator`` is one of the ten ISO group-28 stirrers: ``"agitator"``
    (general), ``"turbine"``, ``"propeller"``, ``"anchor"``,
    ``"helical"``, ``"flat_blade"``, ``"gate_paddle"``, ``"cross_beam"``,
    ``"impeller"`` or ``"disc"``. It is drawn with its drive motor (ISO
    item 20.6 C0082, as in item 1.27 X8006), which carries the ``drive``
    port. ``internals`` is one of the eight ISO group-27 internals, such as
    ``"packing"`` or ``"fluidised_bed"``. Either may be ``None``.

    When ``agitator`` is not given, the default and jacketed bodies get the
    general agitator unless ``internals`` is named; name both for a stirred
    slurry bed, such as
    ``Reactor("R-203", agitator="turbine", internals="packing")``.

    ``vent`` is the off-gas port at the top (absent on ``tubular``) and
    ``duty`` the jacket or coil connection. ``n_feeds`` adds ``feed_1`` to
    ``feed_n`` down the shell, top to bottom; with one, ``feed`` is an
    alias for ``feed_1``.

    Parameters
    ----------
    name : str
        Tag.
    n_feeds : int, default=1
        Number of feed ports.
    variant : str, default="default"
        Body.
    agitator : str or None, optional
        Group-28 stirrer, or ``None`` for none. Defaults from the body and
        internals. Fixed at construction.
    internals : str or None, default=None
        Group-27 internals. Fixed at construction.
    width, height, label_pos, description, reference
        As for :class:`Unit`.

    Raises
    ------
    ValueError
        If ``n_feeds`` is less than 1.
    """

    outlet: Port
    vent: Port
    duty: Port
    # Present only with an agitator; declared for type checkers.
    drive: Port
    # feed_1 to feed_n, top to bottom down the shell.
    feeds: tuple[Port, ...]
    # Alias for feed_1 when there is one feed.
    feed: Port

    # A literal n_feeds returns a typed view declaring feed_1 to feed_n
    # (Reactor1 to Reactor8); a computed count gets Reactor and
    # ``reactor.feeds[i]``. scripts/gen_devices.py gives each generated
    # subclass its own overloads so it stays assignable to its own type.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Reactor1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Reactor2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Reactor3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Reactor4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Reactor5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Reactor6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Reactor7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Reactor8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Reactor": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Reactor": ...

    kind = "reactor"
    # Column rank: the sheet is drawn around the reactor.
    LAYOUT_CONFIDENCE = 8
    # The outlet is on the floor, but what it feeds is the next unit along,
    # so claim east and let the pipe turn. Claiming SE at this weight steps
    # a reactor train into a staircase and measured worse on the corpus.
    # Feed restates its west face at reactor weight.
    PLACES = {"feed": "W", "outlet": "E", "vent": "N"}
    # Ports depend on the variant; __init__ adds _VARIANT_PORTS.
    PORTS: list[tuple[str, str, str]] = []
    # Default port set: product, off-gas and jacket or coil duty.
    _VESSEL = [
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("duty", "inlet", "energy"),
    ]
    # Variant -> port set; absent variants use _VESSEL.
    _VARIANT_PORTS: dict[str, list[tuple[str, str, str]]] = {
        # No vapour space, so no vent.
        "tubular": [
            ("outlet", "outlet", "process"),
            ("duty", "inlet", "energy"),
        ],
    }

    # Bodies that get an agitator by default. "mixing" draws its own, and
    # tubular and plain bodies are not stirred.
    _STIRRED = ("default", "jacketed")

    # The agitator default depends on body and internals.
    COMPOSITION = {"agitator": _UNSTATED, "internals": None}
    # Both choose overlays, and agitator the drive port, in __init__.
    _FIXED_AT_CONSTRUCTION = frozenset({"agitator", "internals"})

    @classmethod
    def composition_defaults(
        cls, variant: str, stated: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return composition defaults for a body and stated parts.

        A stirred body (:attr:`_STIRRED`) gets the general agitator (ISO
        item 28.1) unless internals are stated; other bodies get none. A
        stated agitator always wins.

        Parameters
        ----------
        variant : str
            Resolved body.
        stated : Mapping[str, Any], optional
            Parts the author stated.

        Returns
        -------
        dict[str, Any]
            Default for each composition keyword.
        """
        return {
            **super().composition_defaults(variant, stated),
            "agitator": "agitator"
            if variant in cls._STIRRED and (stated or {}).get("internals") is None
            else None,
        }

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return the ports a variant adds.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs, or none when the class declares :attr:`PORTS`.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._VESSEL)

    def __init__(
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        agitator: str | None = _UNSTATED,
        internals: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        names = _feed_names(n_feeds, "Reactor")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Check the variant the author typed, not the alias it resolved to.
        if variant == "plain":
            REACTOR_VARIANT_PLAIN.warn(self, where=name)
        elif variant == "mixing":
            REACTOR_VARIANT_MIXING.warn(self, where=name)
        if agitator is _UNSTATED:
            agitator = self.composition_defaults(self.variant, {"internals": internals})["agitator"]
        self.agitator = agitator
        self.internals = internals
        # Add before the feeds to keep port order: product, off-gas, duty,
        # then feeds. Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        # Draw the bed first so the stirrer shaft is drawn over it.
        from pandid.render.iso_parts import agitator_overlays, internals_overlays

        _compose_onto(
            self,
            () if internals is None else internals_overlays(internals),
            () if agitator is None else agitator_overlays(agitator, self.kind, self.variant),
        )
        # The agitator brings the motor and its drive port.
        if agitator is not None:
            self.drive = self._add_port("drive", "inlet", "energy")
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        if n_feeds == 1:
            # An alias, not a second port, so the feed series has one member.
            self.feed = self.feeds[0]


if TYPE_CHECKING:
    # Typed views for the overloads above; never built at run time. The
    # base class declares the ``feed`` alias.

    class Reactor1(Reactor):
        """Reactor declaring ``feed_1`` for type checkers."""

        feed_1: Port

    class Reactor2(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_2`` for type checkers."""

        feed_1: Port
        feed_2: Port

    class Reactor3(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_3`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Reactor4(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_4`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Reactor5(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_5`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Reactor6(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_6`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Reactor7(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_7`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Reactor8(Reactor):
        """Reactor declaring ``feed_1`` to ``feed_8`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


#: Deprecations of the Separator variants that are now ``characteristic``
#: values, one constant each so :func:`pandid.deprecation.declarations`
#: finds them. ``variant="cyclone"`` is not deprecated: ISO 14617-1 4.5
#: registers X2618 as a symbol of its own, and the same holds for the
#: sifter, impact separator, permanent magnet and scrubber.
SEPARATOR_VARIANT_GRAVITY = Deprecation(
    what="Separator(variant='gravity')",
    instead="Separator(characteristic='gravity')",
    removed_in="0.2.0",
)
SEPARATOR_VARIANT_ELECTROSTATIC = Deprecation(
    what="Separator(variant='electrostatic')",
    instead="Separator(characteristic='electrostatic')",
    removed_in="0.2.0",
)
SEPARATOR_VARIANT_ELECTROMAGNETIC = Deprecation(
    what="Separator(variant='electromagnetic')",
    instead="Separator(characteristic='electromagnetic')",
    removed_in="0.2.0",
)

_SEPARATOR_CHARACTERISTIC_VARIANTS = {
    "gravity": SEPARATOR_VARIANT_GRAVITY,
    "electrostatic": SEPARATOR_VARIANT_ELECTROSTATIC,
    "electromagnetic": SEPARATOR_VARIANT_ELECTROMAGNETIC,
}


class Separator(Unit):
    """Flash drum or other separator.

    ``"default"`` is the upright dished-head drum and ``"horizontal"`` the
    lying drum; use the variant rather than turning the upright one.
    ``"knockout"`` draws a demister pad and level gauge into the drum; the
    gauge is artwork, so a level instrument added separately draws its own
    balloon.

    The draws are named for what leaves:

    - ``vapor`` and ``liquid`` on the phase separators: ``"default"``,
      ``"horizontal"``, ``"knockout"`` and ``"scrubber"``;
    - ``overflow`` (high) and ``underflow`` (apex) on the mechanical
      separators (``"sifter"``, ``"impact"``, ``"permanent_magnet"``,
      ``"electromagnetic"``) and the dust collectors (``"cyclone"``,
      ``"gravity"``, ``"electrostatic"``). They name positions, because
      either may be the product.

    ``characteristic`` names one of three ISO 10628-2 group-29 marks
    drawn in the separating vessel::

        Separator("V-201", characteristic="gravity")          # 8.3 X8031
        Separator("V-202", characteristic="electrostatic")    # 8.6 X8125
        Separator("V-203", characteristic="electromagnetic")  # 8.8 X8126

    The cyclone (X2618), sifter, impact separator, permanent magnet and
    scrubber are registered symbols of their own and stay variants.

    ``n_feeds`` adds ``feed_1`` to ``feed_n`` down the wall, ``feed_1``
    highest; with one, ``feed`` is an alias for ``feed_1``. On
    hopper-bottomed bodies the family grows downward from the single-feed
    position, so adding a feed does not move the first
    (:data:`pandid.render.symbols.FROM_START`)::

        Separator("V-401", n_feeds=2, characteristic="gravity")

    ``"horizontal"`` takes one feed only (:attr:`_ONE_FEED_VARIANTS`).
    Every variant is drawn one way up and reported as ``gravity-turned`` by
    :meth:`~pandid.flowsheet.Flowsheet.validate` if turned (ISO 15519-1
    11.4.2).

    Parameters
    ----------
    name : str
        Tag.
    n_feeds : int, default=1
        Number of feed ports.
    variant : str, default="default"
        Body. ``"gravity"``, ``"electrostatic"`` and ``"electromagnetic"``
        are deprecated in favour of ``characteristic``.
    characteristic : str, optional
        Group-29 mark; replaces ``variant``.
    width, height, label_pos, description, reference
        As for :class:`Unit`.

    Raises
    ------
    ValueError
        If ``characteristic`` is unknown or given with a non-default
        ``variant``, ``n_feeds`` is less than 1, or the variant takes one
        feed only.
    """

    # Only the phase draws, so ``sep.overflow`` does not type-check on a
    # flash drum. The pandid.devices classes declare the others; otherwise
    # use ``sep.port("overflow")``.
    vapor: Port
    liquid: Port
    # feed_1 to feed_n, top to bottom down the wall.
    feeds: tuple[Port, ...]
    # Alias for feed_1 when there is one feed.
    feed: Port

    # Typed overloads for a literal n_feeds, as on Reactor.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Separator1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Separator2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Separator3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Separator4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Separator5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Separator6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Separator7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Separator8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Separator": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Separator": ...

    kind = "separator"
    LAYOUT_CONFIDENCE = 4
    # Bottom draws go south-east so the two draws never share a cell.
    # Vapour goes east, not north-east: it feeds the next unit along, and
    # lifting it turns a train into a staircase. Overflow goes north-east:
    # a collector's clean gas leaves the train.
    PLACES = {
        "feed": "W",
        "vapor": "E", "liquid": "SE",
        "overflow": "NE", "underflow": "SE",
    }
    # Ports depend on the variant; __init__ adds feeds, then _VARIANT_PORTS.
    PORTS: list[tuple[str, str, str]] = []
    # Default draws. Feeds are a family added in __init__.
    _PHASES = [
        ("vapor", "outlet", "vapor"),
        ("liquid", "outlet", "liquid"),
    ]
    # A high draw and a low draw, named by position. Role "process": dust,
    # tramp metal or a size fraction have no role of their own.
    _OVER_AND_UNDER = [
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    # Variant -> draws; absent variants are phase separators.
    _VARIANT_PORTS = {
        "cyclone": _OVER_AND_UNDER,
        "gravity": _OVER_AND_UNDER,
        "electrostatic": _OVER_AND_UNDER,
        "sifter": _OVER_AND_UNDER,
        "impact": _OVER_AND_UNDER,
        "permanent_magnet": _OVER_AND_UNDER,
        "electromagnetic": _OVER_AND_UNDER,
    }
    # Variant -> {port: artwork anchor} where the artwork uses another name.
    # Per variant, since most drawings anchor the port names directly.
    _VARIANT_ANCHORS = {
        "cyclone": {"overflow": "vapor", "underflow": "liquid"},
        "gravity": {"overflow": "vapor", "underflow": "liquid"},
        "electrostatic": {"overflow": "vapor", "underflow": "liquid"},
        # Composed on the same separating vessel as gravity and electrostatic.
        "electromagnetic": {"overflow": "vapor", "underflow": "liquid"},
        # The artwork names its single feed "feed", with a three-face menu.
        "horizontal": {"feed_1": "feed"},
    }

    # Values of ``characteristic``; see
    # SymbolRegistry._register_composed.
    _CHARACTERISTICS = ("gravity", "electrostatic", "electromagnetic")

    # Variant -> advice, for variants that take one feed. The horizontal
    # drum offers its feed on three faces, and a Symbol cannot carry both a
    # face menu and a port family for one port; its 30-unit head also has
    # no room for two.
    _ONE_FEED_VARIANTS = {
        "horizontal": "Separator(variant='default'), the upright drum, takes as many as "
                      "you like, and a Mixer ahead of the drum draws the junction where "
                      "two feeds really do combine before they enter",
    }

    # No mark unless characteristic names one; it becomes the variant.
    COMPOSITION = {"characteristic": None}
    COMPOSITION_VARIANT = "characteristic"

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the artwork anchor for a port.

        :attr:`_VARIANT_ANCHORS` is checked before
        :attr:`Unit.PORT_ANCHORS`.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str
            Anchor name in the symbol.
        """
        renamed = self._VARIANT_ANCHORS.get(self.variant, {})
        return renamed.get(port_name) or super()._symbol_anchor(port_name)

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return the ports a variant adds.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs, or none when the class declares :attr:`PORTS`.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._PHASES)

    def __init__(
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        characteristic: str | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        names = _feed_names(n_feeds, "Separator")
        if characteristic is not None:
            if variant != "default":
                raise ValueError(
                    f"{name}: characteristic={characteristic!r} and variant={variant!r} "
                    f"both choose the drawing, and they disagree. The characteristic is "
                    f"the mark inside the separating vessel, so it *is* the variant: "
                    f"drop one of the two"
                )
            if characteristic not in self._CHARACTERISTICS:
                raise ValueError(
                    f"{name}: {characteristic!r} is not an ISO 10628-2 group-29 "
                    f"characteristic pandid composes a separator from; it draws "
                    f"{', '.join(repr(c) for c in self._CHARACTERISTICS)}. A cyclone, a "
                    f"sifter, an impact separator, a permanent magnet and a scrubber "
                    f"are distinct registered symbols rather than a body plus a mark, "
                    f"so each is a variant= of its own"
                )
            variant = characteristic
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Check the variant the author typed: device classes such as
        # GravitySeparator alias their default to a deprecated spelling.
        if characteristic is None and variant in self._CHARACTERISTICS:
            _SEPARATOR_CHARACTERISTIC_VARIANTS[variant].warn(self, where=name)
        self.characteristic = self.variant if self.variant in self._CHARACTERISTICS else None
        # Use the resolved variant: a device class may reach "horizontal"
        # through VARIANT_ALIASES.
        instead = self._ONE_FEED_VARIANTS.get(self.variant)
        if instead is not None and n_feeds != 1:
            raise ValueError(
                f"{name}: Separator(variant={self.variant!r}) is drawn with one feed "
                f"nozzle and you asked for {n_feeds}. Its charge nozzle is drawn on "
                f"whichever of three heads the line comes from, and a family is spread "
                f"down one face, so the drawing can offer one or the other and this one "
                f"offers the choice of head. {instead}"
            )
        # Add feeds before the draws to keep the port order stable.
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        if n_feeds == 1:
            # An alias, not a second port, so the feed series has one member.
            self.feed = self.feeds[0]
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


if TYPE_CHECKING:
    # Typed views for the overloads above; never built at run time. The
    # base class declares the ``feed`` alias.

    class Separator1(Separator):
        """Separator declaring ``feed_1`` for type checkers."""

        feed_1: Port

    class Separator2(Separator):
        """Separator declaring ``feed_1`` to ``feed_2`` for type checkers."""

        feed_1: Port
        feed_2: Port

    class Separator3(Separator):
        """Separator declaring ``feed_1`` to ``feed_3`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Separator4(Separator):
        """Separator declaring ``feed_1`` to ``feed_4`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Separator5(Separator):
        """Separator declaring ``feed_1`` to ``feed_5`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Separator6(Separator):
        """Separator declaring ``feed_1`` to ``feed_6`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Separator7(Separator):
        """Separator declaring ``feed_1`` to ``feed_7`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Separator8(Separator):
        """Separator declaring ``feed_1`` to ``feed_8`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


#: Default drawn tray count: eight decks, as ISO 10628-2 item 2.6 X8011
#: draws. The drawn count need not match the real tray count.
DEFAULT_TRAYS = 8

# Deprecations of the distillation ports on Column, which now belong to
# DistillationColumn. Port positions are unchanged, so no note is given.
COLUMN_REFLUX_IN = Deprecation(
    what="Column(...).reflux_in", instead="DistillationColumn(...).reflux_in", removed_in="0.2.0"
)
COLUMN_BOILUP_IN = Deprecation(
    what="Column(...).boilup_in", instead="DistillationColumn(...).boilup_in", removed_in="0.2.0"
)
COLUMN_REBOILER_DUTY = Deprecation(
    what="Column(...).reboiler_duty",
    instead="DistillationColumn(...).reboiler_duty",
    removed_in="0.2.0",
)
COLUMN_CONDENSER_DUTY = Deprecation(
    what="Column(...).condenser_duty",
    instead="DistillationColumn(...).condenser_duty",
    removed_in="0.2.0",
)
#: Deprecation of ``distillate`` on every tower in favour of ``overhead``,
#: a position name like Separator's ``overflow``; an absorber's overhead
#: is not distillate.
COLUMN_DISTILLATE = Deprecation(
    what="Column(...).distillate", instead="Column(...).overhead", removed_in="0.2.0"
)


class Column(Unit):
    """General tower: a dished-end shell with feeds, overhead and bottoms.

    Every column has feeds, ``overhead`` off the top and ``bottoms`` off
    the bottom. :class:`DistillationColumn` adds the reflux and reboiler
    ports, :class:`Stripper` the reboiler only, and :class:`Absorber`
    nothing, so ``t: Column`` accepts all four. Use a plain ``Column`` for
    a scrubber, adsorber or molecular sieve. For one release,
    ``col.reflux_in``, ``.boilup_in``, ``.reboiler_duty`` and
    ``.condenser_duty`` still work on a plain Column with a warning to use
    DistillationColumn, and ``col.distillate`` warns towards ``overhead``.

    ``n_feeds`` adds ``feed_1`` to ``feed_n`` down the west side,
    ``feed_1`` highest, for a solvent or entrainer feed; with one, ``feed``
    is an alias for ``feed_1``. ``n_draws`` adds side draws on the east
    face: ``draw`` for one, ``draw_1`` to ``draw_n`` for more. A draw
    places a port only; give its phase through the stream. A pumparound is
    a draw and a feed connected separately.

    ``internals`` furnishes the bare shell with an ISO 10628-2 group-27
    internal, drawn ``trays`` times. A bare column is ISO item 2.1 X8100;
    the tray tower is item 2.2 X8101::

        Column("T-101")                                    # a bare shell
        Column("T-102", internals="tray")                  # a tray tower
        Column("T-103", internals="bubble_cap_tray", trays=12)
        Column("T-104", internals="valve_tray", trays=30)
        Column("T-105", internals="packing", trays=2)      # two beds

    The internals are ``"tray"`` (27.1), ``"baffle_tray"``,
    ``"bubble_cap_tray"``, ``"valve_tray"``, ``"sieve_tray"``,
    ``"filter_insert"``, ``"fluidised_bed"`` and ``"packing"``. Absorbers,
    strippers and adsorbers have no ISO symbols of their own; they are this
    shell with the internal they contain.

    ``feed_stages`` and ``draw_stages`` put each feed or draw on a stage,
    numbered 1 at the top to ``trays`` at the bottom, one entry per port in
    declaration order; ``None`` keeps that port on the even spread::

        Column("T-101", internals="valve_tray", trays=30,
               n_feeds=2, feed_stages=[12, 22])
        Column("T-301", internals="valve_tray", trays=30,
               n_draws=1, draw_stages=[15])

    Parameters
    ----------
    name : str
        Tag.
    n_feeds : int, default=1
        Number of feed ports.
    variant : str, default="default"
        Shell drawing.
    internals : str or None, optional
        Group-27 internal; none when omitted. Fixed at construction, as
        are ``trays``, ``feed_stages`` and ``draw_stages``.
    trays : int, default=DEFAULT_TRAYS
        Drawn count of decks or beds.
    feed_stages, draw_stages : list[int or None], optional
        Stage per feed or draw.
    n_draws : int, default=0
        Number of side draws.
    width, height, label_pos, description, reference
        As for :class:`Unit`.

    Raises
    ------
    ValueError
        If a count is out of range, a stage list has the wrong length, a
        stage is outside the column, or a stage is named with no internals.
    """

    overhead: Port
    bottoms: Port
    # feed_1 to feed_n, highest first.
    feeds: tuple[Port, ...]
    # Alias for feed_1 when there is one feed.
    feed: Port
    # Side draws, highest first. No bare ``draw`` annotation here, since
    # most columns have none; ColumnDraw1 declares it.
    draws: tuple[Port, ...]

    # Two typed overload families instead of all 64 combinations:
    #
    # - any literal n_feeds with n_draws=0 returns Column1 to Column8;
    # - n_feeds=1 with a literal n_draws returns ColumnDraw1 to ColumnDraw8.
    #
    # Both counts above one, or a computed count, return Column; use
    # ``col.feeds``, ``col.draws`` or ``col.port(...)``. Retired ports are
    # served by Unit.__getattr__, which type checkers do not see, so
    # ``col.reflux_in`` is still flagged on a plain Column.
    if TYPE_CHECKING:
        # Family A: any n_feeds, n_draws=0 (keyword-only, as at run time).
        @overload
        def __new__(
            cls,
            name: str,
            n_feeds: Literal[1] = 1,
            *args: Any,
            n_draws: Literal[0] = 0,
            **kwargs: Any,
        ) -> "Column1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, n_draws: Literal[0] = 0, **kwargs: Any
        ) -> "Column8": ...

        # Family B: n_feeds=1, n_draws required, so a bare Column("T-1")
        # still resolves to Column1.
        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[1], **kwargs: Any
        ) -> "ColumnDraw1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[2], **kwargs: Any
        ) -> "ColumnDraw2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[3], **kwargs: Any
        ) -> "ColumnDraw3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[4], **kwargs: Any
        ) -> "ColumnDraw4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[5], **kwargs: Any
        ) -> "ColumnDraw5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[6], **kwargs: Any
        ) -> "ColumnDraw6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[7], **kwargs: Any
        ) -> "ColumnDraw7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, n_draws: Literal[8], **kwargs: Any
        ) -> "ColumnDraw8": ...

        # Both counts above one, or computed counts.
        @overload
        def __new__(
            cls, name: str, n_feeds: int = 1, *args: Any, n_draws: int = 0, **kwargs: Any
        ) -> "Column": ...
        def __new__(
            cls, name: str, n_feeds: int = 1, *args: Any, n_draws: int = 0, **kwargs: Any
        ) -> "Column": ...

    kind = "column"
    # Highest rank: readers expect the tower arrangement below.
    LAYOUT_CONFIDENCE = 8
    # The artwork faces (overhead N, bottoms S, returns E) do not say where
    # the condenser or reboiler is drawn. NE and SE give the overhead
    # system and the reboiler loop a column each and keep the west side
    # for feeds. Returns match their draws, since each returns from the
    # same cluster. Return lines usually reach claims only as reversed
    # flow (pandid.layout.claims), so the return entries have little
    # effect. A side draw goes east at a lower weight.
    PLACES = {
        "feed": "W",
        "overhead": "NE",
        "reflux_in": "NE",
        "bottoms": "SE",
        "boilup_in": "SE",
        "draw": ("E", 4),
    }
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
    ]

    # The artwork still anchors overhead under its old name.
    PORT_ANCHORS = {"overhead": "distillate"}

    # Distillation ports served on a plain Column for one release, with a
    # warning, built as DistillationColumn builds them.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {
        "reflux_in": ("inlet", "liquid", COLUMN_REFLUX_IN),
        "boilup_in": ("inlet", "vapor", COLUMN_BOILUP_IN),
        "reboiler_duty": ("inlet", "energy", COLUMN_REBOILER_DUTY),
        "condenser_duty": ("outlet", "energy", COLUMN_CONDENSER_DUTY),
    }
    # Old port name -> current port, on every tower.
    _RETIRED_PORT_ALIASES: dict[str, tuple[str, Deprecation]] = {
        "distillate": ("overhead", COLUMN_DISTILLATE),
    }

    # A bare shell by default (ISO item 2.1 X8100); a default deck would
    # assert trays the author never gave.
    COMPOSITION = {"internals": None, "trays": DEFAULT_TRAYS}
    # Read once in __init__ by every column subclass.
    _FIXED_AT_CONSTRUCTION = frozenset(
        {"internals", "trays", "feed_stages", "draw_stages"}
    )

    def __init__(
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        internals: str | None = _UNSTATED,
        trays: int = DEFAULT_TRAYS,
        feed_stages: list[int | None] | None = None,
        n_draws: int = 0,
        draw_stages: list[int | None] | None = None,
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        names = _feed_names(n_feeds, "Column")
        draw_names = _draw_names(n_draws, "Column")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        if internals is _UNSTATED:
            internals = self.composition_defaults(self.variant)["internals"]
        self.internals = internals
        self.trays = trays
        from pandid.render.iso_parts import internals_overlays

        _compose_onto(self, () if internals is None else internals_overlays(internals, trays))
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        self.draws = tuple(self._add_port(draw, "outlet", "draw") for draw in draw_names)
        if n_feeds == 1:
            # An alias, not a second port, so the feed series has one member.
            self.feed = self.feeds[0]
        self.feed_stages = feed_stages
        self.draw_stages = draw_stages
        self._stage_fractions = {
            **_stage_fractions(name, internals, trays, feed_stages, names, "feed_stages", "feed"),
            **_stage_fractions(
                name, internals, trays, draw_stages, draw_names, "draw_stages", "draw"
            ),
        }

    def _series_pin(self, port_name: str) -> float | None:
        """Return the shell fraction a stage pins a port to.

        Parameters
        ----------
        port_name : str
            Feed or draw port name.

        Returns
        -------
        float or None
            Fraction of the shell, or ``None`` for the even spread.
        """
        return self._stage_fractions.get(port_name)


if TYPE_CHECKING:
    # Typed views for the overloads above; never built at run time. The
    # base class declares the ``feed`` alias.

    class Column1(Column):
        """Column declaring ``feed_1`` for type checkers."""

        feed_1: Port

    class Column2(Column):
        """Column declaring ``feed_1`` to ``feed_2`` for type checkers."""

        feed_1: Port
        feed_2: Port

    class Column3(Column):
        """Column declaring ``feed_1`` to ``feed_3`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Column4(Column):
        """Column declaring ``feed_1`` to ``feed_4`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Column5(Column):
        """Column declaring ``feed_1`` to ``feed_5`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Column6(Column):
        """Column declaring ``feed_1`` to ``feed_6`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Column7(Column):
        """Column declaring ``feed_1`` to ``feed_7`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Column8(Column):
        """Column declaring ``feed_1`` to ``feed_8`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port

    # Typed views for Family B. A single draw is named ``draw``, with no
    # ``draw_1``, so ColumnDraw1 declares it.

    class ColumnDraw1(Column):
        """Column declaring ``draw`` for type checkers."""

        draw: Port

    class ColumnDraw2(Column):
        """Column declaring ``draw_1`` to ``draw_2`` for type checkers."""

        draw_1: Port
        draw_2: Port

    class ColumnDraw3(Column):
        """Column declaring ``draw_1`` to ``draw_3`` for type checkers."""

        draw_1: Port
        draw_2: Port
        draw_3: Port

    class ColumnDraw4(Column):
        """Column declaring ``draw_1`` to ``draw_4`` for type checkers."""

        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port

    class ColumnDraw5(Column):
        """Column declaring ``draw_1`` to ``draw_5`` for type checkers."""

        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port

    class ColumnDraw6(Column):
        """Column declaring ``draw_1`` to ``draw_6`` for type checkers."""

        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port
        draw_6: Port

    class ColumnDraw7(Column):
        """Column declaring ``draw_1`` to ``draw_7`` for type checkers."""

        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port
        draw_6: Port
        draw_7: Port

    class ColumnDraw8(Column):
        """Column declaring ``draw_1`` to ``draw_8`` for type checkers."""

        draw_1: Port
        draw_2: Port
        draw_3: Port
        draw_4: Port
        draw_5: Port
        draw_6: Port
        draw_7: Port
        draw_8: Port


class DistillationColumn(Column):
    """Distillation column with reflux and reboiler ports.

    Adds to :class:`Column` the return ports ``reflux_in`` (liquid from
    the reflux drum) and ``boilup_in`` (vapour from the reboiler), and the
    ``reboiler_duty`` and ``condenser_duty`` energy streams. Every other
    argument is :class:`Column`'s::

        DistillationColumn("T-101", internals="valve_tray", trays=30)

    These ports are declared here, not on Column, so a type checker knows
    :class:`Absorber` and :class:`Stripper` lack them.
    """

    kind = "column"
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("reflux_in", "inlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
        ("condenser_duty", "outlet", "energy"),
    ]

    overhead: Port
    bottoms: Port
    reflux_in: Port
    boilup_in: Port
    reboiler_duty: Port
    condenser_duty: Port

    # Typed overloads for a literal n_feeds, as on Absorber.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "DistillationColumn1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "DistillationColumn2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "DistillationColumn3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "DistillationColumn4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "DistillationColumn5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "DistillationColumn6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "DistillationColumn7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "DistillationColumn8": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: int, *args: Any, **kwargs: Any
        ) -> "DistillationColumn": ...
        def __new__(
            cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any
        ) -> "DistillationColumn": ...


if TYPE_CHECKING:

    class DistillationColumn1(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` for type checkers."""

        feed_1: Port

    class DistillationColumn2(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_2`` for type checkers."""

        feed_1: Port
        feed_2: Port

    class DistillationColumn3(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_3`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port

    class DistillationColumn4(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_4`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class DistillationColumn5(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_5`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class DistillationColumn6(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_6`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class DistillationColumn7(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_7`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class DistillationColumn8(DistillationColumn):
        """DistillationColumn declaring ``feed_1`` to ``feed_8`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


class Absorber(Column):
    """Absorption or scrubbing tower: a solute moves from a gas into a liquid.

    A :class:`Column` with no distillation ports. Gas enters at the bottom
    and lean liquid at the top, as two feeds on the stages they enter;
    treated gas leaves by ``overhead`` and rich liquid by ``bottoms``::

        Absorber("V-501", internals="packing",
                 n_feeds=2, feed_stages=[1, 8])

    ``reflux_in``, ``boilup_in``, ``reboiler_duty`` and ``condenser_duty``
    raise, with no deprecation period, because nothing in an absorber
    boils. ``internals`` defaults to ``"packing"``; every other argument is
    :class:`Column`'s.
    """

    kind = "column"
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
    ]

    overhead: Port
    bottoms: Port

    # No distillation ports, even with a warning. ``distillate`` still
    # warns towards ``overhead``.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {}

    # Packed by default.
    COMPOSITION = {"internals": "packing", "trays": DEFAULT_TRAYS}

    # Own overloads, so a literal n_feeds returns Absorber2 rather than
    # Column2 and ``t: Absorber = Absorber("V-1")`` type-checks. n_draws
    # has no typed family here; use ``absorber.draws[i]`` or
    # ``absorber.port("draw_2")``.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Absorber1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Absorber2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Absorber3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Absorber4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Absorber5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Absorber6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Absorber7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Absorber8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Absorber": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Absorber": ...


if TYPE_CHECKING:

    class Absorber1(Absorber):
        """Absorber declaring ``feed_1`` for type checkers."""

        feed_1: Port

    class Absorber2(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_2`` for type checkers."""

        feed_1: Port
        feed_2: Port

    class Absorber3(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_3`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Absorber4(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_4`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Absorber5(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_5`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Absorber6(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_6`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Absorber7(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_7`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Absorber8(Absorber):
        """Absorber declaring ``feed_1`` to ``feed_8`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


class Stripper(Column):
    """Stripping column: a light component is driven out of a liquid by heat.

    A :class:`Column` with a reboiler but no condenser or reflux, since the
    overhead is the stripped product. It has ``overhead``, ``bottoms``,
    ``boilup_in`` and ``reboiler_duty``; ``reflux_in`` and
    ``condenser_duty`` raise with no deprecation period. Every argument is
    :class:`Column`'s, including its ``internals`` default.
    """

    kind = "column"
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
    ]

    overhead: Port
    bottoms: Port
    boilup_in: Port
    reboiler_duty: Port

    # No reflux or condenser ports, even with a warning.
    _RETIRED_PORTS: dict[str, tuple[str, str, Deprecation]] = {}

    # Typed overloads for a literal n_feeds, as on Absorber.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[1] = 1, *args: Any, **kwargs: Any
        ) -> "Stripper1": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[2], *args: Any, **kwargs: Any
        ) -> "Stripper2": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[3], *args: Any, **kwargs: Any
        ) -> "Stripper3": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[4], *args: Any, **kwargs: Any
        ) -> "Stripper4": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[5], *args: Any, **kwargs: Any
        ) -> "Stripper5": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[6], *args: Any, **kwargs: Any
        ) -> "Stripper6": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[7], *args: Any, **kwargs: Any
        ) -> "Stripper7": ...

        @overload
        def __new__(
            cls, name: str, n_feeds: Literal[8], *args: Any, **kwargs: Any
        ) -> "Stripper8": ...

        @overload
        def __new__(cls, name: str, n_feeds: int, *args: Any, **kwargs: Any) -> "Stripper": ...
        def __new__(cls, name: str, n_feeds: int = 1, *args: Any, **kwargs: Any) -> "Stripper": ...


if TYPE_CHECKING:

    class Stripper1(Stripper):
        """Stripper declaring ``feed_1`` for type checkers."""

        feed_1: Port

    class Stripper2(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_2`` for type checkers."""

        feed_1: Port
        feed_2: Port

    class Stripper3(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_3`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port

    class Stripper4(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_4`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port

    class Stripper5(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_5`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port

    class Stripper6(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_6`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port

    class Stripper7(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_7`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port

    class Stripper8(Stripper):
        """Stripper declaring ``feed_1`` to ``feed_8`` for type checkers."""

        feed_1: Port
        feed_2: Port
        feed_3: Port
        feed_4: Port
        feed_5: Port
        feed_6: Port
        feed_7: Port
        feed_8: Port


# ----------------------------------------------------------------
# Variable-port unit types
# ----------------------------------------------------------------


class Mixer(Unit):
    """Mixer: combines several inlet streams into one outlet.

    Equipment drawn as a triangle; where two lines simply meet, use a
    :class:`Tee`. The inlets are ``in_1`` to ``in_n`` and :attr:`inlets`,
    indexed from zero (``m.inlets[0]`` is ``in_1``).

    Parameters
    ----------
    name : str
        Tag.
    n_inlets : int, default=2
        Number of inlets.
    variant, width, height, label_pos, description, reference
        As for :class:`Unit`.

    Raises
    ------
    ValueError
        If ``n_inlets`` is less than 1.
    """

    # in_1 to in_n in order. The count is per instance, so no class
    # annotation can name each member; use ``m.inlets[i]``,
    # ``m.port("in_3")`` or ``enumerate(m.inlets, start=1)``.
    inlets: tuple[Port, ...]
    outlet: Port

    # A literal n_inlets returns a typed view declaring in_1 to in_n
    # (Mixer1 to Mixer8), so ``Mixer("M", n_inlets=3).in_3`` is a Port and
    # ``.in_4`` is an error. A computed count gets Mixer; use
    # ``m.inlets[i]``. The views exist only for type checkers, and
    # ``*args``/``**kwargs`` defer to the __init__ signature.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[1], *args: Any, **kwargs: Any
        ) -> "Mixer1": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[2] = 2, *args: Any, **kwargs: Any
        ) -> "Mixer2": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[3], *args: Any, **kwargs: Any
        ) -> "Mixer3": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[4], *args: Any, **kwargs: Any
        ) -> "Mixer4": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[5], *args: Any, **kwargs: Any
        ) -> "Mixer5": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[6], *args: Any, **kwargs: Any
        ) -> "Mixer6": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[7], *args: Any, **kwargs: Any
        ) -> "Mixer7": ...

        @overload
        def __new__(
            cls, name: str, n_inlets: Literal[8], *args: Any, **kwargs: Any
        ) -> "Mixer8": ...

        @overload
        def __new__(cls, name: str, n_inlets: int, *args: Any, **kwargs: Any) -> "Mixer": ...
        def __new__(cls, name: str, n_inlets: int = 2, *args: Any, **kwargs: Any) -> "Mixer": ...

    kind = "mixer"
    # Machine rank, so the units it collects from do not pull it off its
    # header line.
    LAYOUT_CONFIDENCE = 2
    # No PLACES: the artwork fixes inlets west and the outlet east, and a
    # stated face would ignore mirroring.

    def __init__(
        self,
        name: str,
        n_inlets: int = 2,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Keep the ports as created, rather than re-matching names.
        self.inlets = tuple(
            self._add_port(f"in_{i}", "inlet", "process") for i in range(1, n_inlets + 1)
        )
        self._add_port("outlet", "outlet", "process")


if TYPE_CHECKING:
    # Typed views for the overloads above, written out because type
    # checkers read source; never built at run time.

    class Mixer1(Mixer):
        """Mixer declaring ``in_1`` for type checkers."""

        in_1: Port

    class Mixer2(Mixer):
        """Mixer declaring ``in_1`` to ``in_2`` for type checkers."""

        in_1: Port
        in_2: Port

    class Mixer3(Mixer):
        """Mixer declaring ``in_1`` to ``in_3`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port

    class Mixer4(Mixer):
        """Mixer declaring ``in_1`` to ``in_4`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port

    class Mixer5(Mixer):
        """Mixer declaring ``in_1`` to ``in_5`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port

    class Mixer6(Mixer):
        """Mixer declaring ``in_1`` to ``in_6`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port

    class Mixer7(Mixer):
        """Mixer declaring ``in_1`` to ``in_7`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port

    class Mixer8(Mixer):
        """Mixer declaring ``in_1`` to ``in_8`` for type checkers."""

        in_1: Port
        in_2: Port
        in_3: Port
        in_4: Port
        in_5: Port
        in_6: Port
        in_7: Port
        in_8: Port


class Splitter(Unit):
    """Splitter: divides one inlet stream into several outlets.

    Equipment drawn as a triangle; for a bypass, drain, vent or sample
    branch, use a :class:`Tee`. The outlets are ``out_1`` to ``out_n`` and
    :attr:`outlets`.

    Parameters
    ----------
    name : str
        Tag.
    n_outlets : int, default=2
        Number of outlets.
    variant, width, height, label_pos, description, reference
        As for :class:`Unit`.

    Raises
    ------
    ValueError
        If ``n_outlets`` is less than 1.
    """

    inlet: Port
    # out_1 to out_n in order; see Mixer.
    outlets: tuple[Port, ...]

    # Typed overloads for a literal n_outlets, as on Mixer.
    if TYPE_CHECKING:

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[1], *args: Any, **kwargs: Any
        ) -> "Splitter1": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[2] = 2, *args: Any, **kwargs: Any
        ) -> "Splitter2": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[3], *args: Any, **kwargs: Any
        ) -> "Splitter3": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[4], *args: Any, **kwargs: Any
        ) -> "Splitter4": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[5], *args: Any, **kwargs: Any
        ) -> "Splitter5": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[6], *args: Any, **kwargs: Any
        ) -> "Splitter6": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[7], *args: Any, **kwargs: Any
        ) -> "Splitter7": ...

        @overload
        def __new__(
            cls, name: str, n_outlets: Literal[8], *args: Any, **kwargs: Any
        ) -> "Splitter8": ...

        @overload
        def __new__(cls, name: str, n_outlets: int, *args: Any, **kwargs: Any) -> "Splitter": ...
        def __new__(
            cls, name: str, n_outlets: int = 2, *args: Any, **kwargs: Any
        ) -> "Splitter": ...

    kind = "splitter"
    # As Mixer: machine rank and no PLACES.
    LAYOUT_CONFIDENCE = 2

    def __init__(
        self,
        name: str,
        n_outlets: int = 2,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        self._add_port("inlet", "inlet", "process")
        self.outlets = tuple(
            self._add_port(f"out_{i}", "outlet", "process") for i in range(1, n_outlets + 1)
        )


if TYPE_CHECKING:
    # Typed views for the overloads above; never built at run time.

    class Splitter1(Splitter):
        """Splitter declaring ``out_1`` for type checkers."""

        out_1: Port

    class Splitter2(Splitter):
        """Splitter declaring ``out_1`` to ``out_2`` for type checkers."""

        out_1: Port
        out_2: Port

    class Splitter3(Splitter):
        """Splitter declaring ``out_1`` to ``out_3`` for type checkers."""

        out_1: Port
        out_2: Port
        out_3: Port

    class Splitter4(Splitter):
        """Splitter declaring ``out_1`` to ``out_4`` for type checkers."""

        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port

    class Splitter5(Splitter):
        """Splitter declaring ``out_1`` to ``out_5`` for type checkers."""

        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port

    class Splitter6(Splitter):
        """Splitter declaring ``out_1`` to ``out_6`` for type checkers."""

        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port
        out_6: Port

    class Splitter7(Splitter):
        """Splitter declaring ``out_1`` to ``out_7`` for type checkers."""

        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port
        out_6: Port
        out_7: Port

    class Splitter8(Splitter):
        """Splitter declaring ``out_1`` to ``out_8`` for type checkers."""

        out_1: Port
        out_2: Port
        out_3: Port
        out_4: Port
        out_5: Port
        out_6: Port
        out_7: Port
        out_8: Port


def _block_faces(spec: "int | Sequence[str]", default: str, owner: str, argument: str) -> list[str]:
    """Return one face per connection from an ``inputs`` or ``outputs`` value.

    A count puts every connection on the default face; a sequence names
    each face in order.

    Parameters
    ----------
    spec : int or Sequence[str]
        Count, or one face per connection.
    default : str
        Face for a count.
    owner : str
        Unit name, for error messages.
    argument : str
        Argument name, for error messages.

    Returns
    -------
    list[str]
        Compass faces.

    Raises
    ------
    ValueError
        If ``spec`` is a string, bool, negative count or holds an invalid
        face.
    """
    if isinstance(spec, bool) or not isinstance(spec, (int, Sequence)) or isinstance(spec, str):
        # Refuse a bare string, which would read as one face per character.
        raise ValueError(
            f"{owner}: {argument}= is a count ({argument}=3) or one face per "
            f"connection ({argument}=['W', 'W', 'N']), got {spec!r}"
        )
    if isinstance(spec, int):
        if spec < 0:
            raise ValueError(f"{owner}: {argument}= cannot be negative, got {spec}")
        return [default] * spec
    return [_block_face(face, owner) for face in spec]


def _block_face(face: object, owner: str) -> str:
    """Return a compass face from a compass or side name.

    Parameters
    ----------
    face : object
        ``"N"``, ``"S"``, ``"E"``, ``"W"``, or ``"top"``, ``"bottom"``,
        ``"left"``, ``"right"``.
    owner : str
        Unit name, for error messages.

    Returns
    -------
    str
        Compass face.

    Raises
    ------
    ValueError
        If ``face`` is not a face name.
    """
    resolved = (
        _FACE_OF_SIDE.get(face.strip().lower(), face.strip().upper())
        if isinstance(face, str)
        else None
    )
    if resolved not in ("N", "S", "E", "W"):
        raise ValueError(
            f"{owner}: {face!r} is not a face; a connection is on the 'N', 'S', "
            f"'E' or 'W' of the box (or the 'top'/'bottom'/'left'/'right' spelling)"
        )
    return resolved


class Block(Unit):
    """Block flow diagram box: a plant section drawn as a labelled rectangle.

    A block has no equipment ports, only connections and the side each is
    on.

    .. code-block:: python

        rx = fs.add(units.Block("Reaction",
                                inputs=["W", "W", "N"],
                                outputs=["E", "S"]))
        fs.connect(feed.outlet, rx.in_1)      # west
        fs.connect(recycle.out_1, rx.in_3)    # north
        fs.connect(rx.out_2, drain.inlet)     # south

    ``inputs`` and ``outputs`` give one face per connection, or a count on
    the default face (inputs west, outputs east). Connections are
    ``in_1`` to ``in_n`` and ``out_1`` to ``out_m``, numbered across the
    family; :attr:`inlets` and :attr:`outlets` are the ports and
    :attr:`input_faces` and :attr:`output_faces` their faces.

    Layout reads each face as a placement claim (north puts the peer in the
    row above), so a BFD lays itself out (:mod:`pandid.layout.claims`). A
    face names the box's own side: a turned or mirrored :meth:`pin` moves
    every connection with the box. :func:`pandid.portgeom.port_faces`
    reports faces on the finished sheet.

    The box grows to space its connections at
    :data:`~pandid.render.symbols.BLOCK_PITCH` and to fit its name. An
    explicit ``width`` or ``height`` wins, but a box too small for its
    connections is refused by the constructor, an assignment,
    :meth:`nozzle` and :meth:`pin`. A name wider than an explicit width
    overhangs the box and, on its opaque halo, hides what is beside it.

    Parameters
    ----------
    name : str
        Section name, written inside the box.
    inputs, outputs : int or Sequence[str], default=1
        Count, or one face per connection.
    variant, width, height, label_pos, description, reference
        As for :class:`Unit`; there are no variants.

    Attributes
    ----------
    DEFAULT_INPUT_FACE, DEFAULT_OUTPUT_FACE : str
        Faces used for a count: ``"W"`` and ``"E"``.

    Raises
    ------
    ValueError
        If there are no connections, a face is invalid, or the box is too
        small for its connections.
    """

    # Only the families: their sizes are the caller's, so even ``in_1``
    # may not exist. tests/test_port_annotations.py lists the classes that
    # declare families.
    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]

    # Tell type checkers any other attribute is a Port, so ``b.in_3``
    # type-checks. Only Block pays the lost typo detection, since its
    # numbered connections outnumber its fixed ones; a typo still raises
    # at run time with the list of real ports.
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Port: ...

    kind = "block"

    DEFAULT_INPUT_FACE = "W"
    DEFAULT_OUTPUT_FACE = "E"

    # Class-level defaults, so Unit.__init__ can set width and height
    # before the connections exist.
    _width: float | None = None
    _height: float | None = None

    def __init__(
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        width: float | None = None,
        height: float | None = None,
        label_pos: str | None = None,
        description: str = "",
        reference: str = "",
    ):
        in_faces = _block_faces(inputs, self.DEFAULT_INPUT_FACE, name, "inputs")
        out_faces = _block_faces(outputs, self.DEFAULT_OUTPUT_FACE, name, "outputs")
        if not in_faces and not out_faces:
            raise ValueError(
                f"{name}: a block with no connections is a rectangle with a word "
                f"in it, which nothing can be routed to. Give it at least one "
                f"inputs= or outputs=."
            )
        super().__init__(
            name,
            variant=variant,
            width=width,
            height=height,
            label_pos=label_pos,
            description=description,
            reference=reference,
        )
        # Connection name -> face, in drawn order; the symbol is built from it.
        self._faces: dict[str, str] = {}
        self.inlets = tuple(
            self._add_connection(f"in_{i}", "inlet", face)
            for i, face in enumerate(in_faces, start=1)
        )
        self.outlets = tuple(
            self._add_connection(f"out_{i}", "outlet", face)
            for i, face in enumerate(out_faces, start=1)
        )
        # Check now, so the error points at the constructor, not a render.
        self._check_box()

    def _add_connection(self, name: str, direction: str, face: str) -> Port:
        """Create a connection and record its face.

        The port is added first, so a refused name records no face.

        Parameters
        ----------
        name : str
            Port name.
        direction : str
            ``"inlet"`` or ``"outlet"``.
        face : str
            Compass face.

        Returns
        -------
        Port
            The new port.
        """
        port = self._add_port(name, direction, "process")
        self._faces[name] = face
        return port

    @property
    def width(self) -> float | None:
        """Return the box width, or ``None`` to size it to the connections."""
        return self._width

    @width.setter
    def width(self, value: float | None) -> None:
        """Set the box width.

        Parameters
        ----------
        value : float or None
            Width in pixels, or ``None`` to size automatically.

        Raises
        ------
        ValueError
            If the width is too small for the connections; the old width
            is kept.
        """
        self._resize("_width", value)

    @property
    def height(self) -> float | None:
        """Return the box height, or ``None`` to size it to the connections."""
        return self._height

    @height.setter
    def height(self, value: float | None) -> None:
        """Set the box height.

        Parameters
        ----------
        value : float or None
            Height in pixels, or ``None`` to size automatically.

        Raises
        ------
        ValueError
            If the height is too small for the connections; the old height
            is kept.
        """
        self._resize("_height", value)

    def _resize(self, attr: str, value: float | None) -> None:
        """Set a box dimension, restoring the old value if it is refused.

        Parameters
        ----------
        attr : str
            ``"_width"`` or ``"_height"``.
        value : float or None
            New value.

        Raises
        ------
        ValueError
            If the box is too small for the connections.
        """
        was = getattr(self, attr)
        setattr(self, attr, value)
        # Unit.__init__ sets the size before connections exist; the
        # constructor checks at the end.
        if "_faces" not in self.__dict__:
            return
        try:
            self._check_box()
        except ValueError:
            setattr(self, attr, was)
            raise

    def pin(
        self,
        *,
        col: int | None = None,
        row: int | None = None,
        x: float | None = None,
        y: float | None = None,
        orientation: float = _UNCHANGED,
        mirrored: bool | str = _UNCHANGED,
        port: str | None = _UNSTATED,
    ) -> "Block":
        """Place the block, checking the placed box can draw it.

        A quarter turn changes which box axis each face runs along.

        Parameters
        ----------
        col, row, x, y, orientation, mirrored, port
            As for :meth:`Unit.pin`.

        Returns
        -------
        Block
            This block.

        Raises
        ------
        ValueError
            If the placement leaves too little room for a face's
            connections; the previous placement is kept.
        """
        # Restore the stated pin, not the resolved corner, so a refused
        # call keeps the anchor port the previous pin named.
        was, was_ports = self._pin, dict(self._pin_ports)
        super().pin(
            col=col, row=row, x=x, y=y, orientation=orientation, mirrored=mirrored, port=port
        )
        try:
            self._check_box()
        except ValueError:
            # The sheet stays marked stale; the extra layout run gives the
            # same frames.
            self._pin_ports = was_ports
            self._pin = was
            raise
        return self

    @property
    def input_faces(self) -> tuple[str, ...]:
        """Return each input's face, in port order, such as ``('W', 'W', 'N')``.

        Use :meth:`nozzle` to move a connection.
        """
        return tuple(self._faces[port.name] for port in self.inlets)

    @property
    def output_faces(self) -> tuple[str, ...]:
        """Return each output's face, in port order."""
        return tuple(self._faces[port.name] for port in self.outlets)

    def face(self, port_name: str) -> str:
        """Return the side of the box a connection is on.

        This is the declared side; a turned or mirrored block draws it
        elsewhere on the sheet (see :func:`pandid.portgeom.port_faces`).

        Parameters
        ----------
        port_name : str
            Connection name.

        Returns
        -------
        str
            Compass face of the box.

        Raises
        ------
        KeyError
            If there is no such connection.
        """
        try:
            return self._faces[port_name]
        except KeyError:
            raise KeyError(
                f"Block {self.name!r} has no connection named {port_name!r}; "
                f"available: {sorted(self.ports)}"
            ) from None

    def nozzle(self, port_name: str, face: str) -> "Block":
        """Move a connection to another side of the box.

        Unlike :meth:`Unit.nozzle`, ``face`` names the box's own side, so
        a later turn or mirror moves the connection with the box, and any
        side is allowed. The move updates the declaration that ``to_dict``
        writes back.

        Parameters
        ----------
        port_name : str
            Connection name.
        face : str
            Compass face or side name.

        Returns
        -------
        Block
            This block.

        Raises
        ------
        KeyError
            If there is no such connection.
        ValueError
            If ``face`` is invalid or the destination side has no room; the
            block is unchanged.
        """
        if port_name not in self.ports:
            raise KeyError(
                f"Block {self.name!r} has no port {port_name!r}; "
                f"available ports: {sorted(self.ports)}"
            )
        was = self._faces[port_name]
        self._faces[port_name] = _block_face(face, self.name)
        try:
            self._check_box()
        except ValueError:
            self._faces[port_name] = was
            raise
        # The artwork and ports moved, so the layout is stale.
        self._invalidate_layout()
        return self

    def ports_on(self, face: str) -> tuple[Port, ...]:
        """Return the connections on one side of the box, in drawn order.

        First is the west end of a north or south face and the north end of
        a west or east face. Without :meth:`order_on`, this is declaration
        order, inputs before outputs.

        Parameters
        ----------
        face : str
            Compass face or side name.

        Returns
        -------
        tuple[Port, ...]
            Ports on that face.
        """
        wanted = _block_face(face, self.name)
        return tuple(self.ports[name] for name, on in self._faces.items() if on == wanted)

    def order_on(self, face: str, ports: "Sequence[Port]") -> "Block":
        """Set the drawn order of the connections on one side of the box.

        Without this, a face draws its connections in declaration order,
        inputs before outputs. Pass every connection on the face, first to
        last, so the call is idempotent; ports rather than names, so a typo
        is caught. First is the west end of a north or south face and the
        north end of a west or east face, on the box's own axes.

        .. code-block:: python

            loop = fs.add(units.Block("Synthesis Loop",
                                      inputs=["W", "S"],
                                      outputs=["E", "S"]))
            # purge west, recycle east
            loop.order_on("S", [loop.out_2, loop.in_2])

        A connection moved onto the face later takes its declaration-order
        place, so order a face once it is complete.

        Parameters
        ----------
        face : str
            Compass face or side name.
        ports : Sequence[Port]
            Every connection on the face, first to last.

        Returns
        -------
        Block
            This block.

        Raises
        ------
        TypeError
            If an item is not a Port.
        ValueError
            If a port belongs to another unit or face, is repeated, or a
            connection on the face is missing; the block is unchanged.
        """
        wanted = _block_face(face, self.name)
        on_face = [name for name, on in self._faces.items() if on == wanted]
        named: list[str] = []
        for port in ports:
            if not isinstance(port, Port):
                raise TypeError(
                    f"{self.name}: order_on() takes the connections themselves and "
                    f"not their names, so a checker can see a typo -- "
                    f"order_on({wanted!r}, [b.out_2, b.in_2]), or b.outlets[1] / "
                    f"b.port('out_2') where the name is computed. "
                    f"Got {port!r}."
                )
            if self.ports.get(port.name) is not port:
                raise ValueError(
                    f"{self.name}: {port.name!r} is a connection of "
                    f"{port.owner.name!r}, not of this block, so it is not on any "
                    f"face of it. order_on() orders one block's own wall; "
                    f"the {wanted} face carries "
                    f"{', '.join(on_face) if on_face else 'nothing'}."
                )
            if self._faces[port.name] != wanted:
                raise ValueError(
                    f"{self.name}: {port.name!r} is on the "
                    f"{self._faces[port.name]} face, not the {wanted}. order_on() "
                    f"orders what is already on a side; move it first with "
                    f"nozzle({port.name!r}, {wanted!r})."
                )
            if port.name in named:
                raise ValueError(
                    f"{self.name}: order_on({wanted!r}, ...) names {port.name!r} "
                    f"twice, so it asks for one connection in two places. Name "
                    f"each of the {wanted} face's connections once: "
                    f"{', '.join(on_face)}."
                )
            named.append(port.name)
        missing = [name for name in on_face if name not in named]
        if missing:
            raise ValueError(
                f"{self.name}: order_on({wanted!r}, ...) names {len(named)} of the "
                f"{len(on_face)} connections on the {wanted} face and leaves "
                f"{', '.join(missing)} unplaced. Name every one, first to last "
                f"along the face; it currently carries {', '.join(on_face)}."
            )
        # The dict order is the drawn order. Replace only this face's
        # members, in place, so other faces keep their order. Counts are
        # unchanged, so the box needs no re-check.
        replacement = iter(named)
        self._faces = {
            (next(replacement) if on == wanted else name): on for name, on in self._faces.items()
        }
        # Ports on the face moved, so the layout is stale.
        self._invalidate_layout()
        return self

    def symbol(self) -> "Symbol":
        """Return this block's symbol, built to its connections.

        Called by :meth:`~pandid.render.symbols.SymbolRegistry.for_unit` on
        every port resolution. It does not check the box, since
        :meth:`_check_box` calls it.

        Returns
        -------
        Symbol
            Block artwork.
        """
        from pandid.render.symbols import block_symbol

        # Pass the name only when it sizes the box; otherwise every block
        # would need its own <defs> entry.
        return block_symbol(tuple(self._faces.items()), "" if self.width is not None else self.tag)

    def _check_box(self) -> None:
        """Raise unless the placed box spaces each face's connections at pitch.

        Measured on the box :func:`~pandid.portgeom.resolve_size` gives for
        the current :attr:`~Unit.pin_`, allowing for a quarter turn, which
        swaps the axis a face runs along. Callers commit a candidate
        placement first and roll it back on error.

        Raises
        ------
        ValueError
            If a face with two or more connections is drawn shorter than
            the symbol needs.
        """
        from pandid.portgeom import resolve_size
        from pandid.render.symbols import block_box_too_small

        sym = self.symbol()
        placed = self.pin_
        w, h = resolve_size(self, placed)
        turned = int(getattr(placed, "orientation", 0) or 0) in (90, 270)
        for face, count in Counter(self._faces.values()).items():
            # One connection on a face has no spacing to crush.
            if count < 2:
                continue
            upright = face in ("W", "E")
            along = sym.height if upright else sym.width
            # A quarter turn swaps which box axis a face runs along.
            drawn, axis = (w, "width") if upright == turned else (h, "height")
            if drawn < along - 1e-9:
                raise block_box_too_small(self.name, face, count, axis, drawn, along, turned=turned)
