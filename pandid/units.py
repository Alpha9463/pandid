"""Unit classes: equipment, flags, fittings and instruments.

Ports are ``(name, direction, role)`` tuples in ``PORTS`` or added in
``__init__``, reachable as ``unit.ports["name"]``, ``unit.port("name")``
or attributes. A port family is also a tuple, such as ``mixer.inlets``.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict, TypeVar, Unpack

from pandid._checks import check_real, check_whole, is_real, is_whole, suggest
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
    "FlotationCell",
    "Deaerator",
    "Silo",
    "MixerSettler",
    "Crystallizer",
    "Absorber",
    "ExtractionColumn",
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
    "Motor",
    "Instrument",
    "Block",
]

# Port roles. "signal" ports carry signal lines, "shaft" and "drive"
# the shaft from a driver to its machine, the rest carry fluid; "draw"
# is a column side draw.
_VALID_ROLES = {
    "shaft",
    "drive",
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

# Sentinel for a pin() argument left unchanged.
_UNCHANGED: Any = object()

#: Sentinel for "not given", distinct from ``None``.
_UNSTATED: Any = object()

# Lets chainable methods return the subclass they were called on.
_UnitT = TypeVar("_UnitT", bound="Unit")

# Attributes layout and routing read. Assigning one marks the sheet's
# cached geometry stale (see Unit.__setattr__).
_LAYOUT_INPUTS = frozenset(
    {
        "name",
        "variant",
        "label_pos",
        "_pin",
        "_pin_ports",
        "width",
        "height",
        "_length",
        "_diameter",
        "_large_end",
        "_normal_position",
        "reference",
    }
)


class _NoSuchAttribute(AttributeError):
    """Error for a missing attribute or port, worded only when shown.

    Parameters
    ----------
    cls_name : str
        Name of the unit's class.
    where : str
        Tag of the unit.
    name : str
        Attribute asked for.
    ports : Mapping[str, Port]
        The unit's ports, listed in the message.
    """

    def __init__(self, cls_name: str, where: str, name: str,  # numpydoc ignore=GL08
                 ports: "Mapping[str, Port]") -> None:
        super().__init__(name)
        self._parts = (cls_name, where, name, ports)

    def __str__(self) -> str:
        """Return the message, listing the unit's ports.

        Returns
        -------
        str
            Message naming the attribute and the available ports.
        """
        cls_name, where, name, ports = self._parts
        return (f"{cls_name} {where!r} has no attribute or port {name!r}; "
                f"available ports: {sorted(ports)}")


#: Deprecation of the PLACES and LAYOUT_CONFIDENCE hints.
_PLACEMENT_HINTS = Deprecation(
    what="PLACES or LAYOUT_CONFIDENCE on a Unit subclass",
    instead="unit.nozzle(port, face) or unit.pin(orientation=..., mirrored=...)",
    removed_in="0.3.0",
    note="layout now places a unit's peers by the faces its nozzles are drawn on",
)


#: Deprecation of reassigning a variant that builds the unit's ports.
_VARIANT_REASSIGNED = Deprecation(
    what="reassigning variant on a built unit",
    instead="a new unit built with variant=",
    removed_in="0.4.0",
    note="its ports and faces are built from the variant it was given",
)


#: Deprecation of a vessel's default_input_face() and default_output_face().
_DEFAULT_FACES = Deprecation(
    what="default_input_face() or default_output_face()",
    instead=("inputs= and outputs= to choose the faces, and input_faces and "
             "output_faces to read them"),
    removed_in="0.3.0",
)


class _UnitOptions(TypedDict, total=False):
    """Keyword options a unit class passes on to :class:`Unit`.

    Attributes
    ----------
    width, height, label_pos, description, reference
        As for :class:`Unit`.
    """

    width: float | None
    height: float | None
    label_pos: str | None
    description: str
    reference: str


class Unit:
    """A piece of equipment, flag, fitting or instrument on a flowsheet.

    Parameters
    ----------
    name : str
        Tag, unique on the sheet except for repeatable symbols.
    variant : str, default="default"
        Drawing variant, one of :attr:`VARIANTS` when that is set.
    width, height : float or None, optional
        Box size, positive and finite; ``None`` uses the symbol's.
    label_pos : str or None, optional
        ``"top"``, ``"bottom"``, ``"left"`` or ``"right"``.
    description : str, default=""
        Text for the equipment list.
    reference : str, default=""
        Off-page drawing reference; Feed and Product only.

    Attributes
    ----------
    kind : str
        Equipment type and symbol registry key.
    PORTS : list[tuple[str, str, str]]
        Declared ports as ``(name, direction, role)``.
    VARIANTS : tuple[str, ...]
        Variants this class draws; empty means any of :attr:`kind`.
    VARIANT_ALIASES : dict[str, str]
        Class-local variant name to registry name.
    PORT_ANCHORS : dict[str, str]
        Port name to the name the symbol anchors it under.
    LAYOUT_CONFIDENCE, PLACES
        Deprecated; a subclass that changes either is reported.
    ONE_NOZZLE_MANY_RUNS : bool
        Whether validation skips the check for ports drawn at one point.
    COMPOSITION : dict[str, Any]
        Composition keywords and their defaults.
    COMPOSITION_VARIANT : str
        Composition keyword this class folds into :attr:`variant`.
    name : str
        Tag.
    variant : str
        Registry variant name. Reassigning it is deprecated on a unit
        whose ports or faces are built from it.
    ports : dict[str, Port]
        Ports by name.
    flowsheet : Flowsheet or None
        Sheet the unit is on.
    frame : Frame or None
        Resolved geometry, set by layout.
    balloon : Instrument or None
        Balloon carrying this unit's tag.

    Raises
    ------
    TypeError
        If ``width`` or ``height`` is neither ``None`` nor a real
        number.
    ValueError
        If the name is empty, the variant is not drawn by this class, a
        size is not positive and finite, or ``reference`` is given on
        equipment.
    """

    kind: str = "unit"
    PORTS: list[tuple[str, str, str]] = []
    # Variant-dependent ports, added through _variant_ports.
    _DEFAULT_PORTS: list[tuple[str, str, str]] = []
    _VARIANT_PORTS: dict[str, list[tuple[str, str, str]]] = {}

    VARIANTS: tuple[str, ...] = ()
    VARIANT_ALIASES: dict[str, str] = {}

    PORT_ANCHORS: dict[str, str] = {}

    LAYOUT_CONFIDENCE: float = 1

    PLACES: dict[str, "str | tuple[str, float] | None"] = {}

    ONE_NOZZLE_MANY_RUNS = False

    # Attributes __setattr__ refuses to reassign after __init__.
    _FIXED_AT_CONSTRUCTION: frozenset[str] = frozenset()

    # Composition parts, redrawn when the variant is reassigned.
    _composition: "tuple[_Part, ...]" = ()

    # Whether __init__ builds ports or faces from the variant.
    _VARIANT_BUILDS = False

    COMPOSITION: dict[str, Any] = {}

    COMPOSITION_VARIANT: str = ""

    # Layout solver state, set by the first layout.
    _slot: _Slot | None

    # Backing store for pin_.
    _pin: "Pin | None" = None

    # What a unit with no composed parts, large end or normal position
    # reads as. Hidden from type checkers.
    if not TYPE_CHECKING:
        overlays = ()
        large_end = "inlet"
        normal_position = "open"

    @classmethod
    def _declared_ports(cls) -> list[tuple[str, str, str]]:
        """Return PORTS from the nearest class that declares it.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs as ``(name, direction, role)``.
        """
        return list(next(klass.__dict__["PORTS"] for klass in cls.__mro__
                         if "PORTS" in klass.__dict__))

    @classmethod
    def _variant_ports(cls, variant: str) -> list[tuple[str, str, str]]:
        """Return a variant's ports, none if this class sets PORTS.

        Parameters
        ----------
        variant : str
            Resolved variant.

        Returns
        -------
        list[tuple[str, str, str]]
            Port specs as ``(name, direction, role)``.
        """
        return [] if cls._declared_ports() else cls._VARIANT_PORTS.get(variant, cls._DEFAULT_PORTS)

    @classmethod
    def composition_defaults(
        cls, variant: str, stated: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return each composition keyword's default for a variant.

        Parameters
        ----------
        variant : str
            Body variant.
        stated : Mapping[str, Any] or None, optional
            Current value of every composition keyword.

        Returns
        -------
        dict[str, Any]
            Resolved default per keyword.
        """
        return dict(cls.COMPOSITION)

    @classmethod
    def _generic_class(cls) -> type["Unit"] | None:
        """Return the ancestor that draws every variant of this kind.

        Returns
        -------
        type[Unit] or None
            Nearest ancestor with no :attr:`VARIANTS` and the same kind.
        """
        for klass in cls.__mro__:
            if issubclass(klass, Unit) and not klass.VARIANTS and klass.kind == cls.kind:
                return klass
        return None

    @classmethod
    def _unknown_variant(cls, name: str, variant: str) -> ValueError:
        """Return the error for a variant this class does not draw.

        Parameters
        ----------
        name : str
            Unit tag, for the message.
        variant : str
            Requested variant.

        Returns
        -------
        ValueError
            The error to raise.
        """
        suggestion = suggest(variant, cls.VARIANTS)
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

    def __init__(  # numpydoc ignore=GL08
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
        self._new_line_number = False
        self._pin: Pin | None = None  # intent; set only via pin()
        # Whether pin() was given an orientation or a mirror.
        self._turn_stated = False
        self._mirror_stated = False
        # Axes pinned to a port rather than the corner: {"y": "inlet"}.
        self._pin_ports: dict[str, str] = {}
        self.frame: Frame | None = None  # resolved; set only by layout
        self._port_faces: dict[str, str] = {}  # port name -> face
        for spec in self._declared_ports():
            self._add_port(*spec)
        if type(self).PLACES is not Unit.PLACES or type(self).LAYOUT_CONFIDENCE != 1:
            _PLACEMENT_HINTS.warn(self, where=name)

    def _invalidate_layout(self) -> None:
        """Mark the sheet's cached geometry stale, if on a sheet."""
        fs = getattr(self, "flowsheet", None)
        if fs is not None:
            fs._invalidate_layout()

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute, marking layout stale for a layout input.

        Parameters
        ----------
        name : str
            Attribute name.
        value : Any
            New value.

        Raises
        ------
        TypeError
            If ``width`` or ``height`` is neither ``None`` nor a real
            number.
        ValueError
            If ``width`` or ``height`` is a number that is not positive
            and finite, or a reassigned ``variant`` cannot carry the
            unit's parts, manholes or sockets.
        AttributeError
            If an attribute fixed at construction is reassigned.

        Warns
        -----
        DeprecationWarning
            If ``variant`` is reassigned on a unit whose ports or faces
            are built from it.
        """
        if name in ("width", "height") and value is not None:
            where = self.__dict__.get("name", "?")
            check_real(value, f"{where}: {name}")
            if value <= 0:
                raise ValueError(
                    f"{where}: {name}={value!r} is not a usable size; a symbol is "
                    f"drawn into a box with a positive, finite {name}, or "
                    f"{name}=None to size itself"
                )
        if name in self._FIXED_AT_CONSTRUCTION and name in self.__dict__:
            raise AttributeError(
                f"{self.name}: {name} is read-only. It is read once, in "
                f"__init__, to build the nozzles and artwork that describe "
                f"what this {type(self).__name__} is; reassigning it would "
                f"leave the drawing disagreeing with the object. Build a new "
                f"{type(self).__name__} with {name}={value!r} instead."
            )
        old = self.__dict__.get(name)
        super().__setattr__(name, value)
        if name == "variant" and old is not None:
            _recompose(self, old)
        if name in _LAYOUT_INPUTS:
            self._invalidate_layout()

    @property
    def tag(self) -> str:
        """Return the drawn tag; empty once a balloon carries it.

        Returns
        -------
        str
            Tag, or ``""``.
        """
        return "" if self.balloon is not None else self.name

    def _check_parts(self) -> None:
        """Refuse parts this unit's rules forbid on its variant.

        A plain unit refuses none.
        """

    def repeats(self, other: "Unit") -> bool:
        """Return whether this unit is another drawing of ``other``.

        Parameters
        ----------
        other : Unit
            Unit with the same tag.

        Returns
        -------
        bool
            Whether the shared tag is allowed.
        """
        return False

    @property
    def new_line_number(self) -> bool:
        """Return whether the line number breaks at this inline unit.

        On a valve, reducer, fitting or tee, ``True`` starts a new stream
        or line number after the unit.

        Returns
        -------
        bool
            Whether the line number breaks here.
        """
        return self._new_line_number

    @new_line_number.setter
    def new_line_number(self, value: bool) -> None:
        """Set the line-number break and renumber the unit's sheet.

        Parameters
        ----------
        value : bool
            Whether a new line number starts after this unit.
        """
        self._new_line_number = value
        if self.flowsheet is not None:
            self.flowsheet._invalidate_layout()
            self.flowsheet.renumber_streams()

    @property
    def pin_(self) -> Pin | None:
        """Return the pin with ``x`` and ``y`` set to the corner.

        Returns
        -------
        Pin or None
            Placement intent, or ``None`` when unpinned.
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
        """Replace the placement and drop any port relation.

        Parameters
        ----------
        value : Pin or None
            New placement intent; ``None`` clears the placement.
        """
        self._pin_ports = {}
        self._pin = value
        self._turn_stated = value is not None and value.orientation != 0
        self._mirror_stated = value is not None and (value.mirrored or value.mirror_y)

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

        Omitted arguments keep their current value. With ``port``, ``x``
        and ``y`` place that port rather than the corner. On a Feed or
        Product they place the flag's port unless ``port=None``. On an
        attached Instrument, ``x`` and ``y`` are absolute on their axes,
        and a ``col`` or ``row`` pin is reported as ``pin-not-honored``.
        A pin the unit is already drawn at leaves the layout as it is, and
        route() takes it as no change to the sheet.

        Parameters
        ----------
        col, row : int or None, optional
            Flow column, west to east, and place down that column.
        x, y : float or None, optional
            Pixel coordinate of the corner, or of ``port``.
        orientation : float, optional
            Clockwise turn in degrees, a multiple of 90.
        mirrored : bool or str, optional
            ``True`` or ``"x"`` flips E and W, ``"y"`` N and S, ``"xy"``
            both.
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
            If ``x`` or ``y`` is not a real number, or ``col`` or
            ``row`` is not a whole number.
        ValueError
            If ``x`` or ``y`` is not finite, ``orientation`` or
            ``mirrored`` is invalid, ``port`` locates no coordinate,
            or a face set with :meth:`nozzle` becomes unreachable.
        """
        from dataclasses import replace

        for axis, value in (("x", x), ("y", y)):
            if value is not None:
                check_real(value, f"{self.name}: pin {axis}")
        for axis, value in (("col", col), ("row", row)):
            if value is not None:
                check_whole(value, f"{self.name}: pin {axis}")

        from pandid.geometry import normalize_mirror, normalize_orientation

        # Start from the stored intent, which keeps port relations.
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
        # The port the caller named, before the flag default applies.
        named_port: str | None = None if port is _UNSTATED else port
        if port is _UNSTATED:
            # A flag's coordinates place its only port by default.
            port = next(iter(self.ports)) if isinstance(self, _Boundary) else None
        # Check the port name first, even with no coordinate.
        nozzle: str | None = None
        if port is not None:
            nozzle = self._canonical_port_name(port)
            if nozzle not in self.ports:
                raise KeyError(
                    f"{type(self).__name__} {self.name!r} has no port {nozzle!r} to "
                    f"pin by; available ports: {sorted(self.ports)}"
                )
        # Record per axis which port the coordinate locates.
        for axis, value in (("x", x), ("y", y)):
            if value is None:
                continue
            if nozzle is None:
                ports.pop(axis, None)
            else:
                ports[axis] = nozzle
        if named_port is not None:
            # Check the resulting pin, not this call alone.
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
        fs = self.flowsheet
        # The drawing already honours the pin, so its layout stands, and
        # route() takes the sheet as unchanged if it was.
        drawn = self._drawn_as(candidate, ports, {k: fields[k] for k in fields if k not in ("x", "y")})
        unchanged = (drawn and fs is not None and fs._given_then is not None
                     and fs._given() == fs._given_then)
        if drawn:
            self.__dict__.update(_pin_ports=ports, _pin=candidate)
        else:
            self._pin_ports = ports
            self._pin = candidate
        self._turn_stated = self._turn_stated or orientation is not _UNCHANGED
        self._mirror_stated = self._mirror_stated or mirrored is not _UNCHANGED
        if fs is not None and unchanged:
            fs._given_then = fs._given()
        return self

    def _drawn_as(self, pin: Pin, ports: dict[str, str], stated: dict[str, Any]) -> bool:
        """Return whether the unit is drawn where a pin would put it.

        Parameters
        ----------
        pin : Pin
            Pin to test.
        ports : dict[str, str]
            Axis to the port its coordinate places.
        stated : dict[str, Any]
            Grid ranks, turn and mirror given with the pin.

        Returns
        -------
        bool
            True if the unit has a frame whose corner, or port, is at
            each pinned coordinate and which draws each stated rank, turn
            and mirror.
        """
        from pandid.portgeom import port_point

        frame = self.frame
        if frame is None:
            return False
        for k, axis in enumerate(("x", "y")):
            want = getattr(pin, axis)
            drawn = (port_point(self, frame, ports[axis])[k] if axis in ports
                     else getattr(frame, axis))
            if want is not None and abs(drawn - want) > 1e-9:
                return False
        if "orientation" in stated and frame.orientation % 360 != stated["orientation"] % 360:
            return False
        return all(getattr(frame, field) == value for field, value in stated.items()
                   if field != "orientation")

    def nozzle(self: _UnitT, port_name: str, face: str) -> _UnitT:
        """Fix the face a port is drawn on.

        The face is as drawn, so a mirrored unit takes the face the
        reader sees.

        Parameters
        ----------
        port_name : str
            Port name.
        face : str
            ``"N"``, ``"S"``, ``"E"``, ``"W"``, ``"top"``, ``"bottom"``,
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
            If the port cannot be drawn on ``face``.
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
        self._port_faces[port_name] = face
        self._invalidate_layout()
        return self

    def _check_face(self, port_name: str, face: str, options: list[str]) -> None:
        """Raise if ``face`` is not one of ``options``.

        Parameters
        ----------
        port_name : str
            Port name, for the message.
        face : str
            Requested face.
        options : list[str]
            Faces the port can take.

        Raises
        ------
        ValueError
            If ``face`` is not in ``options``.
        """
        if face not in options:
            from pandid.portgeom import unreachable_face

            raise unreachable_face(self, port_name, face, options)

    def _add_port(self, name: str, direction: str, role: str) -> Port:
        """Create a port and expose it as an attribute.

        Parameters
        ----------
        name : str
            Port name.
        direction : str
            ``"inlet"`` or ``"outlet"``.
        role : str
            Port role, one of :data:`_VALID_ROLES`.

        Returns
        -------
        Port
            The new port.

        Raises
        ------
        ValueError
            If the name is taken or the role is unknown.
        """
        if name in self.ports:
            raise ValueError(f"{type(self).__name__!r} already has a port named {name!r}")
        if role not in _VALID_ROLES:
            raise ValueError(
                f"Invalid role {role!r} for port {name!r}. Allowed roles are: {_VALID_ROLES}"
            )
        port = Port(name=name, owner=self, direction=direction, role=role)
        self.ports[name] = port
        setattr(self, name, port)
        self.__dict__.pop("_series_members_cache", None)
        return port

    def has_another_port(self, port: "Port") -> bool:
        """Return whether a connected port can take another stream.

        Parameters
        ----------
        port : Port
            Port on this unit.

        Returns
        -------
        bool
            Whether the port belongs to a pool.
        """
        return self._pool_of(port.name) is not None

    def another_port(self, port: "Port") -> "Port":
        """Return a free member of ``port``'s pool, or ``port``.

        Parameters
        ----------
        port : Port
            Port on this unit.

        Returns
        -------
        Port
            Free pool member, or ``port`` when it has no pool.
        """
        base = self._pool_of(port.name)
        if base is None:
            return port
        members = self._pool_members(base)
        for member in members:
            if member.stream is None:
                return member
        n = len(members) + 1
        while f"{base}_{n}" in self.ports:
            n += 1
        return self._add_port(f"{base}_{n}", members[0].direction, members[0].role)

    def _pool_of(self, port_name: str) -> str | None:
        """Return the pool a port belongs to, or ``None``.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str or None
            Pool name.
        """
        return None

    def _pool_members(self, base: str) -> list["Port"]:
        """Return the ports in a pool, in port order.

        Parameters
        ----------
        base : str
            Pool name.

        Returns
        -------
        list[Port]
            Pool members.
        """
        return [p for name, p in self.ports.items() if self._pool_of(name) == base]

    def _mint_port(self, name: str) -> "Port | None":
        """Create the named pool member, or return ``None``.

        Parameters
        ----------
        name : str
            Member name, such as ``"sig_in_3"``.

        Returns
        -------
        Port or None
            New member, or ``None`` if the name is in no pool.
        """
        base = self._pool_of(name)
        if base is None:
            return None
        first = self._pool_members(base)[0]
        return self._add_port(name, first.direction, first.role)

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the name the symbol anchors a port under.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str
            Pool name, :attr:`PORT_ANCHORS` entry or the port name.
        """
        return self._pool_of(port_name) or type(self).PORT_ANCHORS.get(port_name, port_name)

    def _series_pin(self, port_name: str) -> float | None:
        """Return a port's fraction along its series, or ``None``.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        float or None
            Fraction along the series, or ``None`` if unpinned.
        """
        return None

    def _series_members(self, series: "PortSeries") -> dict[str, int]:
        """Return the ports in a series and their order.

        Parameters
        ----------
        series : PortSeries
            Symbol port series.

        Returns
        -------
        dict[str, int]
            Port name to index within the series.
        """
        cache = self.__dict__.setdefault("_series_members_cache", {})
        members = cache.get(id(series))
        if members is None:
            members = {n: i for i, n in enumerate(n for n in self.ports if series.matches(n))}
            cache[id(series)] = members
        return members

    def _canonical_port_name(self, name: str) -> str:
        """Return the real port name for a name or alias.

        Parameters
        ----------
        name : str
            Port name or alias.

        Returns
        -------
        str
            Port name, or ``name`` when nothing matches.
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
            Port name or alias.

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
        """Return ``ClassName('tag')``.

        Returns
        -------
        str
            Representation.
        """
        return f"{type(self).__name__}({self.name!r})"

    # Hidden from type checkers.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            """Raise an AttributeError that lists the unit's ports.

            Parameters
            ----------
            name : str
                Attribute asked for.

            Raises
            ------
            AttributeError
                Always; it lists the ports for a public name.
            """
            ports = self.__dict__.get("ports")
            if ports is not None and not name.startswith("_"):
                where = self.__dict__.get("name", "?")
                raise _NoSuchAttribute(type(self).__name__, where, name, ports)
            raise AttributeError(name)


# Fixed-port unit types


class _Boundary(Unit):
    """Base for the off-page flags :class:`Feed` and :class:`Product`.

    The flag's port takes any number of streams, all drawn from its tip.
    ``pin(x=..., y=...)`` places the port unless ``port=None``. A
    ``height`` leaves room to letter the flag: 42 or more, or 48 or more
    with a ``reference``.

    Parameters
    ----------
    name, variant
        As for :class:`Unit`.
    header : bool, default=False
        Whether the flag is a utility header drawn at several taps.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.
    """

    ONE_NOZZLE_MANY_RUNS = True

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        *,
        header: bool = False,
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        self.header = bool(header)
        # Drawn label, kept when a repeated header is renamed.
        self._tag = name

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute, refusing a height too short to letter the flag.

        The pennant is inset from the top and bottom of the flag's
        height and holds a line of type for the tag, and another for a
        ``reference``.

        Parameters
        ----------
        name : str
            Attribute name.
        value : Any
            New value.

        Raises
        ------
        ValueError
            If ``height``, or ``reference`` with ``height`` set, leaves
            the pennant too short for its lettering; the flag is left
            unchanged.
        """
        # A height set in __init__ is checked when the reference is set.
        if name == "reference" or (name == "height" and "reference" in self.__dict__):
            from pandid.document import _drawn_text
            from pandid.portgeom import FLAG_INSET, FLAG_INSET_REF
            from pandid.render.symbols import _TAG_TYPE

            height = value if name == "height" else self.__dict__.get("height", 0)
            lettered = _drawn_text(value if name == "reference"
                                   else self.__dict__.get("reference"))
            least = (2 * (FLAG_INSET_REF if lettered else FLAG_INSET)
                     + (2 if lettered else 1) * _TAG_TYPE)
            if is_real(height) and 0 < height < least:
                raise ValueError(
                    f"{self.__dict__.get('name', '?')}: a height of {height:g} is too small "
                    f"to letter a {type(self).__name__} flag"
                    f"{' with a reference' if lettered else ''}; give height={least:g} or more"
                )
        super().__setattr__(name, value)

    @property
    def tag(self) -> str:
        """Return the label drawn on the flag.

        Returns
        -------
        str
            Label, such as ``"CWSH"``.
        """
        return self._tag

    @property
    def connection(self) -> Port:
        """Return the flag's port.

        Returns
        -------
        Port
            ``outlet`` on a Feed, ``inlet`` on a Product.
        """
        return next(iter(self.ports.values()))

    def _pool_of(self, port_name: str) -> str | None:
        """Return the pool a port name is in.

        Parameters
        ----------
        port_name : str
            Port name, such as ``outlet_2``.

        Returns
        -------
        str or None
            The flag's port name, or ``None`` outside its pool.
        """
        base = self.connection.name
        if port_name == base:
            return base
        head, _, tail = port_name.rpartition("_")
        return base if head == base and tail.isdigit() else None

    def repeats(self, other: "Unit") -> bool:
        """Return whether this flag is another tap of the same header.

        Both must be headers of the same class, label, variant and
        reference.

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

    Parameters are those of :class:`Unit`, plus ``header``; with
    ``header=True`` it is a utility supply header.
    """

    outlet: Port

    kind = "feed"
    PORTS = [("outlet", "outlet", "feed")]


class Product(_Boundary):
    """Off-page flag where material leaves the sheet.

    Parameters are those of :class:`Unit`, plus ``header``; with
    ``header=True`` it is a return or collection header.
    """

    inlet: Port

    kind = "product"
    PORTS = [("inlet", "inlet", "product")]


class _FluidMover(Unit):
    """Base class for pumps, compressors and blowers."""

    suction: Port
    discharge: Port
    drive: Port

    PORTS = [("suction", "inlet", "process"), ("discharge", "outlet", "process"),
             ("drive", "inlet", "drive")]


class Pump(_FluidMover):
    """Centrifugal or positive-displacement pump.

    ``drive`` takes the shaft of a driver, such as a :class:`Motor`.
    Parameters are those of :class:`Unit`.
    """

    kind = "pump"


class Compressor(_FluidMover):
    """Gas compressor.

    ``drive`` takes the shaft of a driver, such as a :class:`Motor`.
    Parameters are those of :class:`Unit`.
    """

    kind = "compressor"


class _NormallyPositioned(Unit):
    """Base class for units with a normal position: Valve and Fitting.

    Parameters
    ----------
    name, variant
        As for :class:`Unit`.
    normal_position : str, default="open"
        ``"open"`` or ``"closed"`` in normal operation.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.
    """

    #: Normal positions a device may declare.
    NORMAL_POSITIONS = ("open", "closed")

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        *,
        normal_position: str = "open",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        self._normal_position = "open"
        self.normal_position = normal_position

    @property
    def normal_position(self) -> str:
        """Return the normal position.

        Returns
        -------
        str
            ``"open"`` or ``"closed"``.
        """
        return self._normal_position

    @normal_position.setter
    def normal_position(self, value: str) -> None:
        """Set the normal position, checking it can be drawn.

        Parameters
        ----------
        value : str
            ``"open"`` or ``"closed"``.

        Raises
        ------
        ValueError
            If ``value`` is neither, or the variant cannot be closed.
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
        """Accept a closed position; a subclass may refuse it."""


class Valve(_NormallyPositioned):
    """Valve: a body, optionally stroked by an actuator.

    Only the pairings in :data:`pandid.render.symbols.ACTUATED` are
    drawn, and the resolved variant is stored. ``variant="three_way"``
    adds a ``branch`` outlet, reached with ``port("branch")``.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body or body-and-actuator variant, such as ``"globe"``.
    actuator : str, default=""
        ``"diaphragm"``, ``"motor"``, ``"solenoid"``, ``"hydraulic"``,
        ``"handwheel"`` or empty.
    normal_position : str, default="open"
        ``"open"`` or ``"closed"``.
    fail : str, default=""
        Position on loss of actuating energy; see :attr:`fail`.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Raises
    ------
    ValueError
        If the actuator is unknown or contradicts the variant, the
        pairing is not drawn, ``normal_position`` is invalid or
        ``"closed"`` on a control, regulator, relief or psv variant,
        or ``fail`` is invalid or set on a variant outside
        :data:`~pandid.render.symbols.FAIL_ACTUATED`.
    """

    inlet: Port
    outlet: Port
    actuator: Port

    kind = "valve"
    # __init__ adds the ports from _VARIANT_PORTS.
    PORTS: list[tuple[str, str, str]] = []
    #: Ports of every variant except ``three_way``.
    _DEFAULT_PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("actuator", "inlet", "signal"),
    ]
    #: Ports by variant, defaulting to :data:`_DEFAULT_PORTS`.
    _VARIANT_PORTS = {"three_way": [*_DEFAULT_PORTS, ("branch", "outlet", "process")]}
    _VARIANT_BUILDS = True

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        *,
        actuator: str = "",
        normal_position: str = "open",
        fail: str = "",
        **options: Unpack[_UnitOptions],
    ):
        variant = self._resolve(name, variant, actuator)
        super().__init__(name, variant=variant, normal_position=normal_position, **options)
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        self._fail = ""
        self.fail = fail

    def _resolve(self, name: str, variant: str, actuator: str) -> str:
        """Return the variant that draws a body with an actuator.

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
            If the actuator is unknown or contradicts the variant, or
            the pairing is not drawn.
        """
        from pandid.render.symbols import ACTUATORS, actuated_variant, variant_actuator

        if not actuator:
            return variant
        if actuator not in ACTUATORS:
            raise ValueError(
                f"{name}: actuator is one of "
                f"{', '.join(repr(a) for a in ACTUATORS)}, got {actuator!r}. It is "
                f"what strokes the valve; what the valve *is* -- the body -- is "
                f"variant."
            )
        # A variant with a built-in actuator accepts only that one.
        fitted = variant_actuator(variant)
        if fitted:
            if actuator == fitted:
                return variant
            raise ValueError(
                f"{name}: variant {variant!r} already draws a valve with a "
                f"{fitted!r} operator on it, so it "
                f"cannot also take actuator={actuator!r} -- one drawing, two "
                f"operators. Name the body and the actuator (variant='gate', "
                f"actuator={actuator!r}), or the pairing on its own "
                f"(variant={variant!r})."
            )
        return actuated_variant(variant, actuator)

    @property
    def fail(self) -> str:
        """Return where the valve goes on loss of actuating energy.

        The positions ``"open"``, ``"closed"``, ``"last"``,
        ``"drift_open"``, ``"drift_closed"`` and ``"indeterminate"`` are
        drawn as FO, FC, FL, FL/DO, FL/DC and FI.

        Returns
        -------
        str
            Fail position, or ``""`` when unset.
        """
        return self._fail

    @fail.setter
    def fail(self, value: str) -> None:
        """Set the fail position, or clear it with ``""``.

        Parameters
        ----------
        value : str
            Fail position, or ``""``.

        Raises
        ------
        ValueError
            If ``value`` is not a fail position, or the variant is
            not in :data:`pandid.render.symbols.FAIL_ACTUATED`.
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
            If the variant is in
            :data:`pandid.render.symbols.NC_FORBIDDEN`.
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


#: One composition part, ``(keyword, value, place)``; ``place(value,
#: variant)`` returns the overlays that draw it on that body.
_Part = tuple[str, "str | None", "Callable[[str, str], tuple]"]


def _placed(parts: "Sequence[tuple[str, str, Callable[[str, str], tuple]]]",
            variant: str) -> tuple:
    """Return the overlays that draw the stated parts on one body.

    Parameters
    ----------
    parts : Sequence[tuple[str, str, Callable[[str, str], tuple]]]
        Stated ``(keyword, value, place)`` parts.
    variant : str
        Body variant.

    Returns
    -------
    tuple
        Overlays in part order.
    """
    return tuple(overlay for _, value, place in parts for overlay in place(value, variant))


def _carries(kind: str, variant: str, overlays: tuple) -> bool:
    """Return whether a body can be drawn with these overlays.

    Parameters
    ----------
    kind : str
        Unit kind.
    variant : str
        Body variant.
    overlays : tuple
        Overlays to draw on the body.

    Returns
    -------
    bool
        Whether the registry composes them.
    """
    from pandid.render.symbols import default_registry

    try:
        default_registry.composed(kind, variant, overlays)
    except ValueError:
        return False
    return True


def _compose_onto(unit: "Unit", *parts: _Part) -> None:
    """Set a unit's overlays from its composition parts.

    Parameters
    ----------
    unit : Unit
        Unit to draw the parts on.
    *parts : _Part
        Parts in drawing order; a ``None`` value draws nothing.

    Raises
    ------
    ValueError
        If the variant is unregistered or cannot carry the parts.
    """
    from pandid.render.symbols import default_registry

    unit._composition = parts
    stated = [(keyword, value, place) for keyword, value, place in parts if value is not None]
    overlays = _placed(stated, unit.variant)
    if not overlays:
        return
    # Raise the registry's own error for an unregistered variant.
    default_registry.get(unit.kind, unit.variant)
    if not _carries(unit.kind, unit.variant, overlays):
        # Name the parts that fail alone, else all of them.
        culprits = [part for part in stated
                    if not _carries(unit.kind, unit.variant, _placed([part], unit.variant))]
        able = [variant for variant in default_registry.variants(unit.kind)
                if variant != unit.variant
                and _carries(unit.kind, variant, _placed(stated, variant))]
        named = " and ".join(f"{keyword}={value!r}" for keyword, value, _ in culprits or stated)
        raise ValueError(
            f"{unit.name}: {type(unit).__name__} variant {unit.variant!r} cannot carry "
            f"{named}; variants that can: {', '.join(able) or 'none'}"
        )
    unit.overlays = overlays


def _recompose(unit: "Unit", old: str) -> None:
    """Redraw a unit's parts on its new variant, or restore ``old``.

    Overlays added after the parts are kept, after the redrawn parts.
    On a unit whose ports or faces are built from its variant, the
    reassignment is reported as deprecated. Whatever raises, the unit
    keeps ``old`` and its overlays.

    Parameters
    ----------
    unit : Unit
        Unit whose variant was reassigned.
    old : str
        Variant it had.

    Raises
    ------
    ValueError
        If the overlays no longer begin with the parts the unit was
        built with, or the new variant cannot carry the parts, the
        added overlays, the manholes or the sockets.

    Warns
    -----
    DeprecationWarning
        If the unit's ports or faces are built from its variant.
    """
    from pandid.render.symbols import default_registry

    overlays = unit.__dict__.get("overlays")
    stated = [(keyword, value, place) for keyword, value, place in unit._composition
              if value is not None]
    built, current = _placed(stated, old), tuple(overlays or ())
    walls = getattr(unit, "manholes", ()), getattr(unit, "sockets", ())
    try:
        if unit._composition:
            if current[:len(built)] != built:
                raise ValueError(
                    f"{unit.name}: its overlays no longer begin with the parts it was "
                    f"built with, so a new variant cannot redraw them. Build "
                    f"{type(unit).__name__}({unit.name!r}, ..., variant={unit.variant!r}) "
                    f"instead"
                )
            _compose_onto(unit, *unit._composition)
            unit._check_parts()
            added = current[len(built):]
            if added:
                drawn = _placed(stated, unit.variant) + added
                unit.overlays = drawn
                default_registry.composed(unit.kind, unit.variant, drawn)
            for keyword, placed in zip(("manholes", "sockets"), walls):
                _on_walls(unit, keyword, placed)
            if any(walls):
                default_registry.for_unit(unit)
        if unit._VARIANT_BUILDS:
            _VARIANT_REASSIGNED.warn(unit, where=unit.name, stacklevel=4)
    except BaseException:
        unit.__dict__["variant"] = old
        if overlays is None:
            unit.__dict__.pop("overlays", None)
        else:
            unit.__dict__["overlays"] = overlays
        raise


#: Placements of a wall part, ``(face, fraction)`` each.
_Walls = tuple[tuple[str, float], ...]


def _on_walls(unit: "Unit", keyword: str, entries: "Sequence[tuple[str, float]]") -> _Walls:
    """Return checked ``(face, fraction)`` placements for ``keyword``.

    Parameters
    ----------
    unit : Unit
        Unit whose walls carry the parts.
    keyword : str
        ``"manholes"`` or ``"sockets"``.
    entries : Sequence[tuple[str, float]]
        Placements as given.

    Returns
    -------
    tuple[tuple[str, float], ...]
        Placements, each face as ``"N"``, ``"S"``, ``"E"`` or ``"W"``.

    Raises
    ------
    ValueError
        If an entry is not a pair, the face is not a face, the fraction
        is not a number from 0 to 1, or the place is off the walls.
    """
    from pandid._checks import is_real
    from pandid.render.iso_parts import wall_point

    part = keyword[:-1]
    malformed = (
        f"{unit.name}: {keyword}= takes a list of (face, fraction) pairs, such as "
        f"{keyword}=[('E', 0.3)]; got {entries!r}"
    )
    if isinstance(entries, str) or not isinstance(entries, Sequence):
        raise ValueError(malformed)
    checked = []
    for entry in entries:
        if isinstance(entry, str) or not isinstance(entry, Sequence) or len(entry) != 2:
            raise ValueError(malformed)
        face, fraction = _block_face(entry[0], unit.name), entry[1]
        if not (is_real(fraction) and 0 <= fraction <= 1):
            raise ValueError(
                f"{unit.name}: the {part} at {tuple(entry)!r} needs a fraction from 0 to "
                f"1 of the way along the {face} face, 0 at its top or left end; got "
                f"{fraction!r}"
            )
        wall_point(unit.kind, unit.variant, face, fraction,
                   f"{unit.name}: the {part} at {(face, fraction)!r}")
        checked.append((face, fraction))
    return tuple(checked)


def _hold_walls(unit: "Vessel | Evaporator") -> None:
    """Add a port per socket and refuse walls the drawing cannot hold.

    Parameters
    ----------
    unit : Vessel or Evaporator
        Unit with its manholes and sockets set.

    Raises
    ------
    ValueError
        If the drawing cannot hold the manholes and sockets.
    """
    for i in range(1, len(unit.sockets) + 1):
        unit._add_port(f"socket_{i}", "outlet", "process")
    if unit.manholes or unit.sockets:
        unit.symbol()


def _kept_on_walls(unit: "Unit", sym: "Symbol", scale: tuple[float, float]) -> "Symbol":
    """Return ``sym``, refusing a nozzle its placement moves onto a face.

    Parameters
    ----------
    unit : Unit
        Unit drawn.
    sym : Symbol
        Its drawing.
    scale : tuple[float, float]
        ``(x, y)`` scale the drawing is placed at.

    Returns
    -------
    Symbol
        ``sym``.

    Raises
    ------
    ValueError
        If a nozzle is nearer another edge of the placed box than of
        the drawing.
    """
    from pandid.portgeom import outward_dir

    sx, sy = scale
    w, h = sym.width * sx, sym.height * sy
    for name, (x, y) in sym.ports.items():
        home, drawn = outward_dir(x, y, sym.width, sym.height), outward_dir(x * sx, y * sy, w, h)
        if drawn != home:
            raise ValueError(
                f"{unit.name}: {name} is drawn on the {home} wall, which its manholes and "
                f"sockets leave nearer the {drawn} edge of its {w:g}x{h:g} box, so its line "
                f"would leave {drawn}. Give it a larger "
                f"{'height' if drawn in ('N', 'S') else 'width'}, or move the manholes and "
                f"sockets along the wall"
            )
    return sym


def _built_to_size(unit: "Unit") -> bool:
    """Return whether a unit's shell is built to the size it is drawn at.

    Parameters
    ----------
    unit : Unit
        Unit to check.

    Returns
    -------
    bool
        Whether it is a vessel drawn with its shipped shell.
    """
    from pandid.render.symbols import VESSEL_SIZES, default_registry, vessel_shell

    return (unit.kind == "vessel" and unit.variant in VESSEL_SIZES
            and default_registry.get(unit.kind, unit.variant) is vessel_shell(unit.variant))


def _drawn_parts(unit: "Unit", overlays: tuple, faces: "dict[str, str] | None" = None) -> tuple:
    """Return the body a unit is drawn on, with every part placed on it.

    A vessel's shell is built to the stated size, its parts kept at
    their own size; with no size stated, the shell grows until each
    nozzle family has room on its wall clear of the supports. Any other
    body is drawn at its own size and placed scaled, and the manholes
    and sockets are placed at their drawn size.

    Parameters
    ----------
    unit : Unit
        Tank, vessel or evaporator.
    overlays : tuple[Overlay, ...]
        The unit's parts, placed for its body at its natural size.
    faces : dict[str, str], optional
        A vessel's family port name to face; the declared faces when
        omitted.

    Returns
    -------
    tuple
        The body; every part on it, manholes and sockets last; each
        socket's port in body coordinates; and the ``(x, y)`` scale the
        drawing is placed at.

    Raises
    ------
    ValueError
        If a placement is off the body's walls, or the box leaves no
        room for the body.
    """
    from pandid.render.iso_parts import wall_overlays
    from pandid.render.symbols import default_registry

    manholes, sockets = getattr(unit, "manholes", ()), getattr(unit, "sockets", ())
    # A quarter turn swaps the stated sizes onto the drawing's axes.
    turn = getattr(unit, "_pin", None)
    quarter = int(getattr(turn, "orientation", 0) or 0) in (90, 270)
    size = (unit.height, unit.width) if quarter else (unit.width, unit.height)
    natural = default_registry.get(unit.kind, unit.variant)
    if not _built_to_size(unit):
        if not manholes and not sockets:
            return natural, overlays, (), (1.0, 1.0)
        walls, ports, scale = wall_overlays(unit.kind, unit.variant, overlays, manholes,
                                            sockets, size, unit.name)
        return natural, overlays + walls, ports, scale

    on = tuple((getattr(unit, "_faces", {}) if faces is None else faces).items())
    try:
        return (*_shell_parts(unit, overlays, on, size), (1.0, 1.0))
    except ValueError as exc:
        if size == (None, None):
            raise
        raise _too_small(unit, overlays, on, size) from exc


def _shell_parts(unit: "Unit", overlays: tuple, faces: "tuple[tuple[str, str], ...]",
                 size: "tuple[float | None, float | None]") -> tuple:
    """Return a vessel's shell built to a size, with its parts placed on it.

    Parameters
    ----------
    unit : Unit
        Vessel built to size.
    overlays : tuple[Overlay, ...]
        Its parts, placed for its shell at its natural size.
    faces : tuple[tuple[str, str], ...]
        Family port name and face, in drawn order.
    size : tuple[float or None, float or None]
        Stated width and height of the drawn box, on the drawing's axes;
        a shell grows along an axis left ``None`` until each family has
        room on its wall clear of the supports.

    Returns
    -------
    tuple
        The shell; every part on it, manholes and sockets last; and each
        socket's port in body coordinates.

    Raises
    ------
    ValueError
        If the stated size cannot hold the shell, its parts and its
        families.
    """
    from pandid.render.iso_parts import anchored, seated, wall_overlays
    from pandid.render.symbols import (default_registry, vessel_room, vessel_shell,
                                       vessel_shell_fits, vessel_symbol)

    manholes, sockets = getattr(unit, "manholes", ()), getattr(unit, "sockets", ())
    natural = default_registry.get(unit.kind, unit.variant)

    def placed(body):
        """Return the parts and the sockets' ports on one shell.

        Parameters
        ----------
        body : Symbol
            The shell.

        Returns
        -------
        tuple
            Parts, then the sockets' ports.
        """
        drawn = tuple(seated(anchored(o, natural, body), body, unit.variant)
                      for o in overlays)
        walls, ports, _ = wall_overlays(unit.kind, unit.variant, drawn, manholes, sockets,
                                        (None, None), unit.name, body)
        return drawn + walls, ports

    parts, ports = placed(natural)
    grown = default_registry.composed(unit.kind, unit.variant, parts, ports)
    reach = (grown.width - natural.width, grown.height - natural.height)
    w, h = (length if stated is None else stated - extra
            for length, stated, extra in zip((natural.width, natural.height), size, reach))
    if any(length < least for length, least in zip((w, h), vessel_shell_fits(unit.variant))):
        raise ValueError("the box leaves no room for the shell's heads")
    body = vessel_shell(unit.variant, w, h)
    parts, ports = placed(body)
    # Grow the shell along each axis no size is stated for, by what each
    # step showed the shortfall falls per unit of growth.
    short = vessel_room(unit.variant, faces, parts, ports, (w, h))
    rate = [1.0, 1.0]
    for _ in range(8):
        step = [0.0 if stated is not None else lack / r
                for stated, lack, r in zip(size, short, rate)]
        if max(step) <= 1e-9:
            break
        w, h = w + step[0], h + step[1]
        body = vessel_shell(unit.variant, w, h)
        parts, ports = placed(body)
        was, short = short, vessel_room(unit.variant, faces, parts, ports, (w, h))
        rate = [min(1.0, max(0.25, (a - b) / g)) if g > 0 else r
                for a, b, g, r in zip(was, short, step, rate)]
    room = vessel_room(unit.variant, faces, parts, ports, (w, h))
    if any(more > 1e-9 and stated is not None for more, stated in zip(room, size)):
        raise ValueError("the walls cannot hold each family apart, clear of the supports")
    vessel_symbol(unit.kind, unit.variant, faces, parts, ports, (w, h))
    return body, parts, ports


def _too_small(unit: "Unit", overlays: tuple, faces: "tuple[tuple[str, str], ...]",
               size: "tuple[float | None, float | None]") -> ValueError:
    """Return the refusal of a stated size, naming the least size that draws.

    Parameters
    ----------
    unit : Unit
        Vessel built to size.
    overlays : tuple[Overlay, ...]
        Its parts, placed for its shell at its natural size.
    faces : tuple[tuple[str, str], ...]
        Family port name and face, in drawn order.
    size : tuple[float or None, float or None]
        Stated width and height of the drawn box, on the drawing's axes.

    Returns
    -------
    ValueError
        The refusal.
    """
    from pandid.render.symbols import default_registry

    def fits(trial):
        """Return whether the vessel draws at a size.

        Parameters
        ----------
        trial : tuple[float or None, float or None]
            Width and height.

        Returns
        -------
        bool
            Whether it draws.
        """
        try:
            _shell_parts(unit, overlays, faces, trial)
        except ValueError:
            return False
        return True

    def scaled(factor, axes):
        """Return the stated size with some axes scaled.

        Parameters
        ----------
        factor : float
            Scale.
        axes : tuple[int, ...]
            Axes to scale.

        Returns
        -------
        tuple[float or None, float or None]
            Width and height.
        """
        return tuple(v * factor if i in axes and v is not None else v
                     for i, v in enumerate(size))

    given = {i: v for i, v in enumerate(size) if v is not None}
    stated = tuple(given)
    natural = default_registry.get(unit.kind, unit.variant)
    # Look as far as many times the natural size.
    limit = max([64.0, *(16 * (natural.width, natural.height)[i] / v
                         for i, v in given.items() if v)])
    # A quarter turn swaps the drawing's axes back onto the sheet's.
    turn = getattr(unit, "_pin", None)
    names = (("height", "width") if int(getattr(turn, "orientation", 0) or 0) in (90, 270)
             else ("width", "height"))
    for axes in [(i,) for i in stated] + ([stated] if len(stated) > 1 else []):
        lo, hi = 1.0, 1.25
        while hi < limit and not fits(scaled(hi, axes)):
            lo, hi = hi, hi * 1.25
        if hi >= limit:
            continue
        for _ in range(24):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if fits(scaled(mid, axes)) else (mid, hi)
        was = " and ".join(f"a {names[i]} of {given[i]:g}" for i in axes)
        fix = " and ".join(f"{names[i]}={math.ceil(given[i] * hi - 1e-9):g}" for i in axes)
        return ValueError(
            f"{unit.name}: {was} is too small to draw this {unit.variant!r} vessel with "
            f"its nozzles and parts; give {fix} or more"
        )
    return ValueError(
        f"{unit.name}: Vessel(variant={unit.variant!r}) cannot be drawn at the size "
        f"given; leave width and height unset to draw it at its own size"
    )


_FaceFamiliesT = TypeVar("_FaceFamiliesT", bound="_FaceFamilies")


class _Families(Unit):
    """Base class for units whose ports form families on faces."""

    # Family port name -> face, in drawn order.
    _faces: dict[str, str]
    # Family ports whose face a list named, and those whose face the
    # author named by a list or nozzle().
    _listed: frozenset[str]
    _stated: set[str]

    def _offered(self, port_name: str, added: bool = True) -> list[str]:
        """Return the faces a family port may take, its own face first.

        Parameters
        ----------
        port_name : str
            Family port name.
        added : bool, default=True
            Include the symbol's family faces.

        Returns
        -------
        list[str]
            Faces on the unit's own axes.
        """
        raise NotImplementedError

    def _fits(self, faces: dict[str, str], frame: Frame) -> bool:
        """Return whether a placed box can draw the families on faces.

        Parameters
        ----------
        faces : dict[str, str]
            Family port name to face, in drawn order.
        frame : Frame
            The unit's placed box.

        Returns
        -------
        bool
            True if every face has room for its ports.
        """
        raise NotImplementedError

    def symbol(self, faces: dict[str, str] | None = None) -> "Symbol":
        """Return the symbol with the families on the given faces.

        Parameters
        ----------
        faces : dict[str, str], optional
            Family port name to face, in drawn order; the declared
            faces when omitted.

        Returns
        -------
        Symbol
            Artwork with the families placed.
        """
        raise NotImplementedError


class _FaceFamilies(_Families):
    """Base class for units with inlet and outlet families on faces."""

    if TYPE_CHECKING:
        # Each subclass sets these.
        inlets: tuple[Port, ...]
        outlets: tuple[Port, ...]

    # Error wording: the unit noun, a variable name and a family port.
    _NOUN, _VAR, _MEMBER = "unit", "v", "inlet or outlet"

    def _record_lists(self, inputs: "int | Sequence[str]",
                      outputs: "int | Sequence[str]") -> None:
        """Record which families were declared by a list of faces.

        Parameters
        ----------
        inputs, outputs : int or Sequence[str]
            Count, or one face per port, as declared.
        """
        self._listed = frozenset(
            port.name
            for family, spec in ((self.inlets, inputs), (self.outlets, outputs))
            if not isinstance(spec, int)
            for port in family
        )
        self._stated = set(self._listed)

    @property
    def input_faces(self) -> tuple[str, ...]:
        """Return each inlet's face, in port order.

        Returns
        -------
        tuple[str, ...]
            Compass face per inlet.
        """
        return tuple(self._faces[port.name] for port in self.inlets)

    @property
    def output_faces(self) -> tuple[str, ...]:
        """Return each outlet's face, in port order.

        Returns
        -------
        tuple[str, ...]
            Compass face per outlet.
        """
        return tuple(self._faces[port.name] for port in self.outlets)

    def face(self, port_name: str) -> str:
        """Return the declared face of an inlet or outlet.

        Parameters
        ----------
        port_name : str
            Inlet or outlet name or alias.

        Returns
        -------
        str
            Compass face.

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
                f"{type(self).__name__} {self.name!r} has no {self._MEMBER} "
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
            Family ports on that face, ordered as in :meth:`order_on`.

        Raises
        ------
        ValueError
            If ``face`` is not a face.
        """
        wanted = _block_face(face, self.name)
        return tuple(self.ports[name] for name, on in self._faces.items() if on == wanted)

    def order_on(self: _FaceFamiliesT, face: str, ports: "Sequence[Port]") -> _FaceFamiliesT:
        """Set the drawn order of the inlets and outlets on one face.

        First is the west end of a north or south face and the north end
        of a west or east face, on the unit's own axes. An unordered
        face draws in declaration order, inputs before outputs.

        Parameters
        ----------
        face : str
            Compass face or side name.
        ports : Sequence[Port]
            Every connection on the face, first to last.

        Returns
        -------
        _FaceFamilies
            This unit.

        Raises
        ------
        TypeError
            If an item is not a Port.
        ValueError
            If ``face`` is not a face, a port is on another unit or face
            or is repeated, or a connection on the face is missing.
        """
        wanted = _block_face(face, self.name)
        on_face = [name for name, on in self._faces.items() if on == wanted]
        named: list[str] = []
        v, noun = self._VAR, self._NOUN
        for port in ports:
            if not isinstance(port, Port):
                raise TypeError(
                    f"{self.name}: order_on() takes the connections themselves and "
                    f"not their names, so a checker can see a typo -- "
                    f"order_on({wanted!r}, [{v}.out_2, {v}.in_2]), or {v}.outlets[1] / "
                    f"{v}.port('out_2') where the name is computed. "
                    f"Got {port!r}."
                )
            if self.ports.get(port.name) is not port:
                raise ValueError(
                    f"{self.name}: {port.name!r} is a connection of "
                    f"{port.owner.name!r}, not of this {noun}, so it is not on any "
                    f"face of it. order_on() orders one {noun}'s own wall; "
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
        # Reorder this face in place; dict order is the drawn order.
        replacement = iter(named)
        self._faces = {
            (next(replacement) if on == wanted else name): on for name, on in self._faces.items()
        }
        self._invalidate_layout()
        return self


_MultiPortVesselT = TypeVar("_MultiPortVesselT", bound="_MultiPortVessel")


class _MultiPortVessel(_FaceFamilies):
    """Base class for :class:`Tank` and :class:`Vessel`.

    Inlets and outlets are families on the faces the artwork anchors for
    each role. ``vent``, ``relief`` and ``drain`` are fixed ports.

    Attributes
    ----------
    inlets, outlets : tuple[Port, ...]
        Port families in declaration order.
    """

    _VARIANT_BUILDS = True

    def _symbol_anchor(self, port_name: str) -> str:
        """Return the symbol anchor, resolving ``inlet``/``outlet``.

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
        """Return the variant's registered symbol.

        Returns
        -------
        Symbol or None
            The symbol, or ``None`` for an unregistered variant.
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
            Compass face; ``"W"`` or ``"E"`` without a symbol.
        """
        sym = self._registry_symbol()
        if sym is None:
            return "W" if role == "inlet" else "E"
        from pandid.portgeom import outward_dir

        x, y = sym.ports[role]
        return outward_dir(x, y, sym.width, sym.height)

    def _validate_face(self, role: str, port_name: str, face: str, placed=None) -> None:
        """Check that a family port may be drawn on a face.

        Parameters
        ----------
        role : str
            ``"inlet"`` or ``"outlet"``.
        port_name : str
            Family port name.
        face : str
            Compass face on the unit's own axes.
        placed : Pin, Frame or None, optional
            Placement whose drawn faces a refusal names.

        Raises
        ------
        ValueError
            If the artwork offers no such face, or the face has no room.
        """
        from pandid.portgeom import own_faces, stated_faces, unreachable_face

        sym = self._registry_symbol()
        if sym is None:
            # Unknown variant: leave the error to render time.
            return
        drawn = {own: on for on, own in own_faces(placed).items()}
        options = {**sym.port_faces.get(role, {}), **sym.family_faces.get(role, {})}
        if face not in options:
            raise unreachable_face(self, port_name, drawn[face], [drawn[f] for f in options])
        # Refuse a second port on a zero-length face.
        band = sym.bands.get(face)
        if band is None or band[0] < band[1]:
            return
        others = [name for name, on in stated_faces(self, placed).items()
                  if on == face and name != port_name]
        if others:
            from pandid.render.symbols import bandless_face

            raise bandless_face(self.name, face, band[0], [*others, port_name], sym, drawn)

    def default_input_face(self) -> str:
        """Return the face an inlet uses when none is named.

        Returns
        -------
        str
            The artwork's inlet face.

        Warns
        -----
        DeprecationWarning
            Always.
        """
        _DEFAULT_FACES.warn(self, where=self.name)
        return self._home_face("inlet")

    def default_output_face(self) -> str:
        """Return the face an outlet uses when none is named.

        Returns
        -------
        str
            The artwork's outlet face.

        Warns
        -----
        DeprecationWarning
            Always.
        """
        _DEFAULT_FACES.warn(self, where=self.name)
        return self._home_face("outlet")

    def _init_connections(
        self, inputs: "int | Sequence[str]", outputs: "int | Sequence[str]"
    ) -> None:
        """Create the inlet and outlet families.

        Parameters
        ----------
        inputs, outputs : int or Sequence[str]
            Count, or one face per port.

        Raises
        ------
        ValueError
            If a count or face is invalid, or a face has no room.
        """
        cls = type(self)
        own_in = cls.default_input_face is not _MultiPortVessel.default_input_face
        own_out = cls.default_output_face is not _MultiPortVessel.default_output_face
        if own_in or own_out:
            # Honour an overriding subclass until the hooks are removed.
            _DEFAULT_FACES.warn(self, where=self.name, stacklevel=4)
        in_home = self.default_input_face() if own_in else self._home_face("inlet")
        out_home = self.default_output_face() if own_out else self._home_face("outlet")
        in_faces = _block_faces(inputs, in_home, self.name, "inputs")
        out_faces = _block_faces(outputs, out_home, self.name, "outputs")
        self._faces = {}
        self.inlets = tuple(
            self._connect(f"in_{i}", "inlet", face)
            for i, face in enumerate(in_faces, start=1)
        )
        self.outlets = tuple(
            self._connect(f"out_{i}", "outlet", face)
            for i, face in enumerate(out_faces, start=1)
        )
        if len(self.inlets) == 1:
            # A single inlet or outlet is also ``inlet`` or ``outlet``.
            self.inlet = self.inlets[0]
        if len(self.outlets) == 1:
            self.outlet = self.outlets[0]
        self._record_lists(inputs, outputs)

    def _offered(self, port_name: str, added: bool = True) -> list[str]:
        """Return the faces the artwork offers a family port's role.

        Parameters
        ----------
        port_name : str
            Family port name.
        added : bool, default=True
            Include :attr:`Symbol.family_faces`, after the role's menu.

        Returns
        -------
        list[str]
            Faces on the unit's own axes, the port's face first.
        """
        role = "inlet" if port_name.startswith("in_") else "outlet"
        sym = self._registry_symbol()
        menu = ({**sym.port_faces.get(role, {}),
                 **(sym.family_faces.get(role, {}) if added else {})}
                if sym is not None else {})
        home = self._faces[port_name]
        return [home, *(face for face in menu if face != home)]

    def _fits(self, faces: dict[str, str], frame: Frame) -> bool:
        """Return whether the artwork can draw the families on faces.

        Parameters
        ----------
        faces : dict[str, str]
            Family port name to face, in drawn order.
        frame : Frame
            The unit's placed box.

        Returns
        -------
        bool
            True if the symbol builds with the families on ``faces``.
        """
        try:
            self.symbol(faces)
        except ValueError:
            return False
        return True

    def _connect(self, name: str, direction: str, face: str) -> Port:
        """Check a family port's face, then create the port.

        Parameters
        ----------
        name : str
            Port name, such as ``in_1``.
        direction : str
            ``"inlet"`` or ``"outlet"``.
        face : str
            Compass face.

        Returns
        -------
        Port
            The new port.

        Raises
        ------
        ValueError
            If the artwork offers no such face, or the face has no room.
        """
        self._validate_face(direction, name, face)
        port = self._add_port(name, direction, "process")
        self._faces[name] = face
        return port

    def nozzle(self: _MultiPortVesselT, port_name: str, face: str) -> _MultiPortVesselT:
        """Move a port to a named face.

        The face is as drawn, so a turned or mirrored unit takes the
        face the reader sees. An inlet or outlet moves to any face the
        artwork offers for its role. ``vent``, ``relief`` and ``drain``
        use :meth:`Unit.nozzle`.

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
        KeyError
            If the port does not exist.
        ValueError
            If ``face`` is not a face, or the artwork offers no such
            face or no room on it for the port.
        """
        from pandid.portgeom import own_faces

        canonical = self._canonical_port_name(port_name)
        if canonical not in self._faces:
            return super().nozzle(port_name, face)
        role = "inlet" if canonical.startswith("in_") else "outlet"
        resolved = _block_face(face, self.name)
        placed = self.pin_ if self.pin_ is not None else self.frame
        own = own_faces(placed)[resolved]
        self._validate_face(role, canonical, own, placed)
        self._faces[canonical] = own
        self._port_faces[canonical] = resolved
        self._stated.add(canonical)
        self._invalidate_layout()
        return self

    def symbol(self, faces: dict[str, str] | None = None) -> "Symbol":
        """Return the symbol with the families on faces, and overlays.

        Parameters
        ----------
        faces : dict[str, str], optional
            Family port name to face, in drawn order; the declared
            faces when omitted.

        Returns
        -------
        Symbol
            Vendored artwork with the families placed.

        Raises
        ------
        ValueError
            If the parts, manholes or sockets leave a nozzle nearer
            another edge than its face, or the box no room for the body.
        """
        from pandid.render.symbols import vessel_symbol

        overlays = tuple(getattr(self, "overlays", ()) or ())
        on = self._faces if faces is None else faces
        body, parts, ports, scale = _drawn_parts(self, overlays, on)
        size = (body.width, body.height) if _built_to_size(self) else None
        return _kept_on_walls(self, vessel_symbol(
            self.kind, self.variant, tuple(on.items()), parts, ports, size), scale)


class Vessel(_MultiPortVessel):
    """Pressure vessel for holdup.

    ``"default"`` and ``"dished"`` stand upright; ``"horizontal"`` is a
    lying drum. Besides its inlets and outlets, a vessel has ``vent``
    (top head), ``relief`` (top) and ``drain`` (low point). A single
    inlet is also ``inlet`` and a single outlet ``outlet``; otherwise
    use ``in_1``, ``out_1``, ... or :attr:`inlets` and :attr:`outlets`.

    The shell is drawn to the size it is given: ``width`` and ``height``
    are the drawn box, supports and wall parts included, and the heads,
    the supports and the wall parts keep their own size while the
    straight shell takes the rest. With no size given, the shell is
    drawn long enough for each family of nozzles to sit on its wall
    clear of the supports.

    Parameters
    ----------
    name : str
        Tag.
    inputs, outputs : int or Sequence[str], default=1
        Number of inlets or outlets, or one face per port.
    variant : str, default="default"
        Shell drawing.
    supports : str, optional
        ISO 10628-2 group-26 support: ``"skirt"`` (26.3), or a pair of
        ``"leg"`` (26.1), ``"bracket"`` (26.2) or ``"ring"`` (26.4).
        Set at construction only; assigning it later raises
        ``AttributeError``.
    manholes : Sequence[tuple[str, float]], default=()
        ISO 10628-2 26.5 manholes, one ``(face, fraction)`` each: the
        wall, and how far along it from its top or left end, 0 to 1.
        A manhole has no port. Set at construction only.
    sockets : Sequence[tuple[str, float]], default=()
        ISO 10628-2 26.6 sockets, placed as ``manholes`` are. Each is
        an outlet port, ``socket_1``, ``socket_2``, ... in the order
        given. Set at construction only.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Raises
    ------
    ValueError
        If a count or face is invalid, a face is absent or full on the
        artwork, the support is unknown, the variant cannot carry it,
        or a manhole or socket is not a ``(face, fraction)`` pair on a
        straight wall of the variant.
    """

    # Numbered nozzles a count can build.
    in_1: Port
    in_2: Port
    in_3: Port
    in_4: Port
    in_5: Port
    in_6: Port
    in_7: Port
    in_8: Port

    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]
    # Aliases for in_1 and out_1 when there is one of each.
    inlet: Port
    outlet: Port
    vent: Port
    relief: Port
    drain: Port

    kind = "vessel"
    PORTS = [
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    COMPOSITION = {"supports": None}
    _FIXED_AT_CONSTRUCTION = frozenset({"supports", "manholes", "sockets"})

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        supports: str | None = None,
        manholes: "Sequence[tuple[str, float]]" = (),
        sockets: "Sequence[tuple[str, float]]" = (),
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        self.manholes = _on_walls(self, "manholes", manholes)
        self.sockets = _on_walls(self, "sockets", sockets)
        self._init_connections(inputs, outputs)
        self.supports = supports
        from pandid.render.iso_parts import support_overlays

        _compose_onto(self, ("supports", supports, lambda name, _body: support_overlays(name)))
        _hold_walls(self)


class Tank(_MultiPortVessel):
    """Storage tank.

    Variants are ``"default"`` (dished roof), ``"conical"``,
    ``"floating_roof"``, ``"sphere"``, ``"conical_bottom"``,
    ``"conical_ends"``, ``"dished_roof_conical_bottom"`` and
    ``"gas_holder"``. A tank has :class:`Vessel`'s ports and
    ``inputs``/``outputs`` families.

    Flat-floored variants fill low on the west shell and
    hopper-bottomed ones at the crown; :meth:`nozzle` moves an inlet to
    any other face the variant's artwork offers.

    Parameters
    ----------
    name : str
        Tag.
    inputs, outputs : int or Sequence[str], default=1
        Number of inlets or outlets, or one face per port.
    variant : str, default="default"
        Tank drawing.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Raises
    ------
    ValueError
        If a count or face is invalid, or a face is absent or full on
        the variant's artwork.
    """

    # Numbered nozzles a count can build.
    in_1: Port
    in_2: Port
    in_3: Port
    in_4: Port
    in_5: Port
    in_6: Port
    in_7: Port
    in_8: Port

    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]
    inlet: Port
    outlet: Port
    vent: Port
    relief: Port
    drain: Port

    kind = "tank"
    PORTS = [
        ("vent", "outlet", "vapor"),
        ("relief", "outlet", "process"),
        ("drain", "outlet", "liquid"),
    ]

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        self._init_connections(inputs, outputs)


class Blower(_FluidMover):
    """Fan or blower.

    ``"general"`` (the default) draws ISO 10628-2 item 17.1;
    ``"centrifugal"`` and ``"axial"`` draw those fans. ``drive`` takes
    the shaft of a driver, such as a :class:`Motor`. Parameters are
    those of :class:`Unit`.
    """

    kind = "blower"
    VARIANT_ALIASES = {"default": "general"}


class Reducer(Unit):
    """Reducer or expander: the fitting that changes a line's size.

    ``"concentric"`` (also ``"default"``) is symmetric about the run;
    ``"eccentric"`` is flat on top, and ``pin(mirrored="y")`` puts the
    flat side at the bottom. The run goes ``inlet`` to ``outlet``;
    ``large_end="inlet"`` draws a reduction and ``"outlet"`` an
    expansion.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body style.
    large_end : {"inlet", "outlet"}, default="inlet"
        Port on the wide face.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

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
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    LARGE_ENDS = ("inlet", "outlet")

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        *,
        large_end: str = "inlet",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        self._large_end = "inlet"
        self.large_end = large_end

    @property
    def large_end(self) -> str:
        """Return the port on the wide face.

        Returns
        -------
        str
            ``"inlet"`` for a reduction, ``"outlet"`` for an expansion.
        """
        return self._large_end

    @large_end.setter
    def large_end(self, value: str) -> None:
        """Set the port on the wide face.

        Parameters
        ----------
        value : str
            One of :attr:`LARGE_ENDS`.

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

    The run passes straight through ``inlet`` and ``outlet``; the branch
    leaves the south face at a right angle, or the north face where the
    unit it serves is drawn above the run.
    ``pin(mirrored=False)`` keeps the branch south,
    ``pin(mirrored="y")`` turns it north, ``orientation=90`` runs N to S
    with the branch W and ``orientation=270`` runs S to N with the branch
    E. A tee has no tag. Tees may share a name, and
    :meth:`~pandid.flowsheet.Flowsheet.add` renames them ``TEE (2)``,
    ``TEE (3)``. The run keeps its line number through the tee unless
    ``new_line_number`` is set; the branch starts its own.

    Parameters
    ----------
    name : str, default=""
        Flowsheet name; :data:`DEFAULT_NAME` when empty.
    branch : {"outlet", "inlet"}, default="outlet"
        ``"outlet"`` takes flow off the run; ``"inlet"`` returns it.
    variant : str, default="default"
        Drawing variant.
    **options
        ``width``, ``height``, ``description`` or ``reference``, as for
        :class:`Unit`.

    Attributes
    ----------
    DEFAULT_NAME : str
        Name used when none is given.
    BRANCH_DIRECTIONS : tuple[str, ...]
        Allowed ``branch`` values.

    Raises
    ------
    TypeError
        If ``label_pos`` is given.
    ValueError
        If ``branch`` is not in :attr:`BRANCH_DIRECTIONS`.
    """

    inlet: Port
    outlet: Port
    # Added in __init__, in the direction given by branch=.
    branch: Port

    kind = "tee"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    DEFAULT_NAME = "TEE"

    BRANCH_DIRECTIONS = ("outlet", "inlet")

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str = "",
        branch: str = "outlet",
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        if "label_pos" in options:
            raise TypeError(f"{name or self.DEFAULT_NAME}: a tee has no tag, so it takes no label_pos")
        if branch not in self.BRANCH_DIRECTIONS:
            raise ValueError(
                f"{name or self.DEFAULT_NAME}: branch= is "
                f"{' or '.join(repr(d) for d in self.BRANCH_DIRECTIONS)}, whether "
                f"the third connection takes flow off the run or returns it; got "
                f"{branch!r}"
            )
        super().__init__(name or self.DEFAULT_NAME, variant=variant, **options)
        self._add_port("branch", branch, "process")

    @property
    def branch_direction(self) -> str:
        """Return the branch port's direction.

        Returns
        -------
        str
            ``"outlet"`` (takeoff) or ``"inlet"`` (return).
        """
        return self.ports["branch"].direction

    @branch_direction.setter
    def branch_direction(self, value: str) -> None:
        """Refuse to change the branch direction.

        Parameters
        ----------
        value : str
            Requested direction.

        Raises
        ------
        AttributeError
            Always; the branch direction is read-only.
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
        """Return ``""``; a tee is never labelled.

        Returns
        -------
        str
            Empty string.
        """
        return ""

    def repeats(self, other: "Unit") -> bool:
        """Return whether ``other``, of the same name, is a tee.

        Parameters
        ----------
        other : Unit
            Unit with the same name.

        Returns
        -------
        bool
            Whether ``other`` is a :class:`Tee`.
        """
        return isinstance(other, Tee)


class Fitting(_NormallyPositioned):
    """In-line pipe device other than a valve.

    The variant picks the device: ``strainer``, ``strainer_cone``,
    ``strainer_y``, ``strainer_basket``, ``strainer_duplex``,
    ``orifice``, ``rotameter``, ``rupture_disc``, ``sight_glass``,
    ``sight_glass_lit``, ``silencer``, ``expansion_joint``,
    ``bellows``, ``blind``, ``damper``, ``spool``, ``static_mixer``
    (ISO 10628-2 item 12.2 X2673), ``rotary_mixer`` (item 12.1
    X2672), ``mixing_path`` (item 12.3 X8184), ``steam_trap`` (item
    24.15, 2181), ``hose``, ``coupling``, ``clamped_coupling``,
    ``flange`` (the default) and the flame arrestors
    (``flame_arrestor`` plus ``_explosion_proof``,
    ``_detonation_proof`` or ``_fire_resistant``).

    Primary flow elements are variants too: ``venturi``,
    ``flow_nozzle``, ``coriolis``, ``vortex``, ``ultrasonic``,
    ``turbine_meter``, ``positive_displacement``, ``v_cone``,
    ``wedge``, ``target``, ``pitot`` and ``averaging_pitot``.

    A stream keeps its line number through a fitting unless
    ``new_line_number`` is set. Only ``blind`` takes a
    ``normal_position``: ``"open"`` (default) draws the bored disc,
    ``"closed"`` the solid disc. Parameters are those of
    :class:`_NormallyPositioned`.

    Raises
    ------
    ValueError
        If ``normal_position`` is invalid, or ``"closed"`` on a variant
        other than ``blind``.
    """

    inlet: Port
    outlet: Port

    kind = "fitting"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]

    def _refuse_closed(self) -> None:
        """Refuse a closed position on a variant drawn one way only.

        Raises
        ------
        ValueError
            If the variant has no closed drawing.
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

    ``motive`` drives the nozzle, ``suction`` is the entrained stream
    and ``discharge`` leaves the diffuser. Parameters are those of
    :class:`Unit`.
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
    """Open end to atmosphere, such as a PSV tailpipe or tank breather.

    Variants: ``"default"`` (stack with a weather cap),
    ``"exhaust_head"`` (silencing hood) and ``"breather"`` (tank
    conservation vent). Each has one inlet, piped from below.
    Parameters are those of :class:`Unit`.
    """

    inlet: Port

    kind = "vent"
    PORTS = [("inlet", "inlet", "vapor")]


class Funnel(Unit):
    """Open charging funnel whose one port, ``outlet``, feeds a line.

    Parameters are those of :class:`Unit`.
    """

    outlet: Port

    kind = "funnel"
    PORTS = [("outlet", "outlet", "feed")]


class Furnace(Unit):
    """Fired heater or furnace: a stream heated by burning fuel.

    ``"default"`` draws a fired heater with its coil and stack,
    ``"general"`` the ISO 10628-2 furnace (item 4.3) and
    ``"combustion_chamber"`` a chamber making hot gas (item 4.5).
    Parameters are those of :class:`Unit`.
    """

    inlet: Port
    outlet: Port
    fuel: Port

    kind = "furnace"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("fuel", "inlet", "feed"),
    ]


class Boiler(Unit):
    """Steam boiler, ISO 10628-2 item 4.1, 2532.

    ``feedwater`` enters the west wall and ``steam`` leaves the dome's
    apex. Parameters are those of :class:`Unit`.
    """

    feedwater: Port
    steam: Port

    kind = "boiler"
    PORTS = [("feedwater", "inlet", "process"), ("steam", "outlet", "process")]


class Stack(Unit):
    """Exhaust stack or chimney, ISO 10628-2 item 4.7, 2041.

    Its one port is ``inlet``, low on the shaft. Parameters are those
    of :class:`Unit`.
    """

    inlet: Port

    kind = "stack"
    PORTS = [("inlet", "inlet", "vapor")]


class Flare(Unit):
    """Flare stack, ISO 10628-2 item 4.8, 2591.

    One inlet low on the shaft. Parameters are those of :class:`Unit`.
    """

    inlet: Port

    kind = "flare"
    PORTS = [("inlet", "inlet", "vapor")]


class Turbine(Unit):
    """Steam or gas turbine, or expander.

    Parameters are those of :class:`Unit`.
    """

    inlet: Port
    outlet: Port

    kind = "turbine"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class _VariantPorted(Unit):
    """Base class for units whose ports come from their variant.

    Parameters
    ----------
    name, variant
        As for :class:`Unit`.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.
    """

    _VARIANT_BUILDS = True

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        # Use the resolved variant, not the argument.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)


class Filter(_VariantPorted):
    """Liquid or gas filter, with one of three port sets.

    - Clarifying (``inlet``, ``outlet``): ``default``, ``fixed_bed``,
      ``gas``, ``gas_fixed_bed`` and ``gas_belt``.
    - Cake-forming (adds ``wash_in`` and ``cake``): ``press``,
      ``belt``, ``rotary`` and ``rotary_scraper``.
    - Regenerated (adds ``regenerant_in`` and ``spent_regenerant``):
      ``ion_exchange``.

    Parameters are those of :class:`Unit`.
    """

    # Only the ports every variant has; device classes declare the rest.
    inlet: Port
    outlet: Port

    kind = "filter"
    PORTS: list[tuple[str, str, str]] = []
    _DEFAULT_PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
    ]
    _CAKE_FORMING = [
        ("inlet", "inlet", "process"),
        ("wash_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("cake", "outlet", "process"),
    ]
    _REGENERATED = [
        ("inlet", "inlet", "process"),
        ("regenerant_in", "inlet", "utility"),
        ("outlet", "outlet", "process"),
        ("spent_regenerant", "outlet", "process"),
    ]
    _VARIANT_PORTS = {
        "press": _CAKE_FORMING,
        "belt": _CAKE_FORMING,
        "rotary": _CAKE_FORMING,
        "rotary_scraper": _CAKE_FORMING,
        "ion_exchange": _REGENERATED,
    }


class Centrifuge(Unit):
    """Centrifuge, ISO 10628-2 group 9.

    ``overflow`` is drawn high on the shell and ``underflow`` low.
    Variants, by ISO item: ``"default"`` and ``"decanter"`` (9.6),
    ``"disc"`` (9.4), ``"high_speed"`` (9.1), ``"perforated_shell"``
    (9.2), ``"solid_shell"`` (9.3), ``"screw_perforated"`` (9.5),
    ``"pusher"`` (9.7) and ``"skimmer"`` (9.8). Every variant may be
    turned or mirrored. Parameters are those of :class:`Unit`.
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

    ``feed`` and ``product`` carry the solid; ``heating_in`` and
    ``vent``, on the casing wall, carry the drying gas in and out.
    Parameters are those of :class:`Unit`.
    """

    feed: Port
    product: Port
    heating_in: Port
    vent: Port

    kind = "dryer"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("heating_in", "inlet", "utility"),
        ("vent", "outlet", "vapor"),
    ]


class Kiln(Unit):
    """Kiln or calciner, where solids are heated and reacted.

    Ports: ``feed`` (raw solids), ``product`` (calcined solids),
    ``offgas`` (spent combustion gas), ``fuel`` and ``air``. Variants:
    ``"default"`` (rotary kiln), ``"fluidized_bed"`` (calciner) and
    ``"shaft"`` (vertical shaft kiln). Drawn one way up; ``validate``
    reports a turned kiln as ``gravity-turned``. Parameters are those
    of :class:`Unit`.
    """

    feed: Port
    product: Port
    offgas: Port
    fuel: Port
    air: Port

    kind = "kiln"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("product", "outlet", "process"),
        ("offgas", "outlet", "vapor"),
        ("fuel", "inlet", "feed"),
        ("air", "inlet", "utility"),
    ]


class Feeder(Unit):
    """Proportional or metering feeder, ISO 10628-2 group 19.

    Solids enter at ``feed`` and leave metered at ``discharge``;
    ``drive`` takes the shaft of a driver, such as a :class:`Motor`.
    Variants, by ISO item: ``"general"`` (19.1, the default),
    ``"rotary_valve"`` (19.2), ``"rotary_table"`` (19.3) and
    ``"metering"`` (19.4). Drawn one way up; ``validate`` reports a
    turned feeder as ``gravity-turned``. Parameters are those of
    :class:`Unit`.
    """

    feed: Port
    discharge: Port
    drive: Port

    kind = "feeder"
    VARIANT_ALIASES = {"default": "general"}
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process"),
             ("drive", "inlet", "drive")]


class SprayNozzle(Unit):
    """Spray nozzle, ISO 10628-2 item 19.5 2037.

    Drawn as a fan opening downward, with one ``inlet`` offered on the
    west and east faces. Parameters are those of :class:`Unit`.
    """

    inlet: Port

    kind = "spray_nozzle"
    PORTS = [("inlet", "inlet", "process")]


class ScreeningDevice(Unit):
    """Screening device: sieve, strainer or rake, ISO 10628-2 group 7.

    ``feed`` enters from above (from the west on ``"basket_reel"``),
    ``oversize`` leaves a side wall and ``undersize`` the apex below.
    Variants, by ISO item: ``"general"`` (7.1, the default),
    ``"coarse_rake"`` (7.2), ``"fine_rake"`` (7.3),
    ``"coarse_and_fine"`` (7.4), ``"vibrating"`` (7.5),
    ``"rotating_drum"`` (7.6) and ``"basket_reel"`` (7.7). Drawn one
    way up; ``validate`` reports a turned device as
    ``gravity-turned``. Parameters are those of :class:`Unit`.
    """

    feed: Port
    oversize: Port
    undersize: Port

    # "screen" is the Screen device class's name in pandid.spec.
    kind = "screening_device"
    VARIANT_ALIASES = {"default": "general"}
    PORTS = [
        ("feed", "inlet", "feed"),
        ("oversize", "outlet", "process"),
        ("undersize", "outlet", "process"),
    ]


class Kneader(Unit):
    """Kneader for paste, dough or rubber, ISO 10628-2 item 12.4 X8134.

    Drawn one way up; ``validate`` reports a turned kneader as
    ``gravity-turned``. Parameters are those of :class:`Unit`.
    """

    inlet: Port
    outlet: Port

    kind = "kneader"
    PORTS = [("inlet", "inlet", "process"), ("outlet", "outlet", "process")]


class Motor(Unit):
    """Electric motor, ISO 10628-2 items 20.6 to 20.8.

    ``shaft`` turns the machine it is connected to,
    ``fs.connect(motor.shaft, pump.drive)``, and the sheet draws the
    motor beside that machine, on the side its ``drive`` faces, joined
    by a short straight shaft. Variants, by ISO item: ``"general"``
    (20.6, the default), ``"ac"`` (20.7) and ``"dc"`` (20.8).
    Parameters are those of :class:`Unit`.
    """

    shaft: Port

    kind = "motor"
    VARIANT_ALIASES = {"default": "general"}
    PORTS = [("shaft", "outlet", "shaft")]


class CrushingMachine(Unit):
    """General size-reduction machine, ISO 10628-2 item 11.1 X8084.

    ``feed`` enters the top, ``discharge`` leaves the bottom and
    ``drive`` takes the shaft of a driver, such as a :class:`Motor`, on
    the east side. Drawn one way up; ``validate`` reports a turned
    machine as ``gravity-turned``. Parameters are those of
    :class:`Unit`.
    """

    feed: Port
    discharge: Port
    drive: Port

    kind = "crushing_machine"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process"),
             ("drive", "inlet", "drive")]


class Crusher(CrushingMachine):
    """Crusher for coarse size reduction, ISO 10628-2 item 11.2 X8085.

    Variants, by ISO item: ``"default"`` (general, 11.2), ``"jaw"``
    (11.5), ``"cone"`` (11.7), ``"hammer"`` (11.3), ``"impact"`` (11.4)
    and ``"roller"`` (11.6). Drawn one way up; ``validate`` reports a
    turned crusher as ``gravity-turned``. Parameters are those of
    :class:`Unit`.
    """

    kind = "crusher"


class Mill(CrushingMachine):
    """Mill for fine grinding, ISO 10628-2 item 11.8 X8086.

    Variants, by ISO item: ``"default"`` (general, 11.8), ``"hammer"``
    (11.9), ``"impact"`` (11.10), ``"roller"`` (11.11) and
    ``"vibration"`` (11.12). Drawn one way up; ``validate`` reports a
    turned mill as ``gravity-turned``. Parameters are those of
    :class:`Unit`.
    """

    kind = "mill"


class Conveyor(Unit):
    """Conveyor carrying bulk solids from tail end to head end.

    ``"default"`` is the belt (ISO 10628-2 item 18.2, 3821) and
    ``"screw"`` the enclosed screw (item 18.5 X8063). The symbol is
    built to ``length`` and ``diameter``. A belt's ``feed`` is the tail
    roller and ``discharge`` the head; a screw is fed through a top
    spout near the tail and discharges through a bottom spout near the
    head. ``drive`` takes the shaft of a driver, such as a
    :class:`Motor`: on top of a belt's head roller, and on a screw's
    head end.

    Parameters
    ----------
    name : str
        Tag.
    length : float, optional
        Run from tail to head; the symbol default when omitted.
    diameter : float, optional
        Belt roller or screw bore; :meth:`default_diameter` if omitted.
    variant : str, default="default"
        ``"default"`` (belt) or ``"screw"``.
    **options
        ``label_pos``, ``description`` or ``reference``, as for
        :class:`Unit`. ``width`` and ``height`` are refused; use
        ``length`` and ``diameter``.

    Raises
    ------
    ValueError
        If ``width`` or ``height`` is given, ``diameter`` is not
        positive, or ``length`` is below the minimum.
    """

    feed: Port
    discharge: Port
    drive: Port

    kind = "conveyor"
    PORTS = [("feed", "inlet", "feed"), ("discharge", "outlet", "process"),
             ("drive", "inlet", "drive")]

    _length: float
    _diameter: float

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        length: float | None = None,
        diameter: float | None = None,
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        from pandid.render.symbols import CONVEYOR_LENGTH

        width, height = options.get("width"), options.get("height")
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
        super().__init__(name, variant=variant, **options)
        # The length check reads the diameter.
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
    def variant(self) -> str:
        """Return the variant drawn.

        Returns
        -------
        str
            ``"default"`` (belt) or ``"screw"``.
        """
        return self._variant

    @variant.setter
    def variant(self, value: str) -> None:
        """Set the variant, checking the length against its minimum.

        Parameters
        ----------
        value : str
            ``"default"`` (belt) or ``"screw"``.

        Raises
        ------
        ValueError
            If the current length is below the new variant's minimum.
        """
        old = getattr(self, "_variant", value)
        self._variant = value
        if hasattr(self, "_length"):
            try:
                self.length = self._length
            except ValueError:
                self._variant = old
                raise

    @property
    def length(self) -> float:
        """Return the run from tail to head.

        Returns
        -------
        float
            Length in drawn units.
        """
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
            If ``value`` is below the variant's minimum length; a belt's
            minimum depends on its diameter.
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
        """Return the belt roller or screw bore.

        Returns
        -------
        float
            Diameter in drawn units.
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
            If ``value`` is not positive, or, on a belt, the current
            length is below the minimum for the new diameter.
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
    """Bucket elevator, ISO 10628-2 item 18.7 X8065.

    ``"z_form"`` (item 18.8 X8066) adds a horizontal run at each end.
    ``feed`` is the boot (low) and ``discharge`` the head (high); the
    straight elevator also offers north and south chute faces. Drawn
    one way up; ``validate`` reports a turned elevator as
    ``gravity-turned``. Parameters are those of :class:`Unit`.
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
        If ``number`` is not ``None``, text or a whole number.
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
    i = next((i for i, char in enumerate(tag) if char.isdigit()), len(tag))
    return tag[:i], tag[i:]


# A numbered signal pool member, such as sig_out_2.
_POOL_MEMBER = re.compile(r"(sig_in|sig_out)_\d+")

#: Where a balloon's reading is available (ISO 15519-2 Table 1).
DISPLAYS = ("field", "central", "subsidiary")

#: How a balloon relates to its host; ``"near"`` draws no line.
RELATIONS = ("sensing", "acting_on", "near")

# (symbol type, display) -> registered variant. Unlisted pairs use the
# symbol type unchanged.
_BALLOON_SYMBOLS = {
    ("default", "field"): "default",
    ("default", "central"): "panel",
    ("default", "subsidiary"): "aux",
    ("shared", "central"): "shared",
}

# Registered variant -> symbol type.
_BALLOON_SHAPES = {drawn: shape for (shape, _display), drawn in _BALLOON_SYMBOLS.items()}

# Display implied by a symbol type.
_IMPLIED_DISPLAY = {"shared": "central"}

# Variant spellings refused by name, and the display each means.
_DISPLAY_VARIANTS = {"panel": "central", "aux": "subsidiary"}

#: Deprecation of a unit face given as ``at=``.
_AT_FACE = Deprecation(
    what="at='N' (a unit face)",
    instead="face='N', or face: N in a spec",
    removed_in="0.3.0",
    note="at= now means only a fraction along a line",
)


class Instrument(Unit):
    """ISA-5.1 instrument balloon: function letters over a loop number.

    ``Instrument("FT-101")``, ``Instrument("FT101")`` and
    ``Instrument("FT", 101)`` give the same tag. ``pv`` taps the
    process; ``sig_in`` and ``sig_out`` are signal pools, so connecting
    to a used member gets a new one.

    Parameters
    ----------
    type : str
        Function letters, or the whole tag when ``number`` is empty.
    number : str or int, default=""
        Loop number.
    variant : str, default="default"
        Symbol type: ``"default"``, ``"shared"``, ``"computer"``,
        ``"sis"``, ``"logic"`` or ``"interlock"``.
    display : str, optional
        One of :data:`DISPLAYS`; implied by ``variant`` when omitted.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    type, number : str
        Function letters and loop number.
    display : str
        Where the reading is available.
    symbol_type : str
        Symbol type as given, without the display.
    host : Stream, Unit or None
        What :meth:`attach` placed the balloon on.
    at : float or None
        Fraction along a stream host; ``None`` on a unit host.
    face : str or None
        Face of a unit host, ``"N"``, ``"S"``, ``"E"`` or ``"W"``;
        ``None`` on a stream host.
    offset, angle, relation
        Attachment set by :meth:`attach`.
    quadrants : dict[str, tuple[str, ...]]
        Letter codes outside the symbol, set by :meth:`annotate`.
    tap : tuple[float, float] or None
        Resolved tap point, set by layout.

    Raises
    ------
    TypeError
        If ``number`` is not ``None``, text or a whole number.
    ValueError
        If ``display`` is unknown, ``variant`` is a display spelling, or
        the pair has no drawing.
    """

    pv: Port
    sig_in: Port
    sig_out: Port

    kind = "instrument"
    PORTS = [
        ("pv", "inlet", "signal"),
        ("sig_in", "inlet", "signal"),
        ("sig_out", "outlet", "signal"),
    ]

    # Pool names, which are also each pool's first member.
    _SIGNAL_POOLS = ("sig_in", "sig_out")

    # Variants that may be drawn several times under one tag.
    _REPEATABLE_VARIANTS = frozenset({"sis", "logic", "interlock"})

    def __init__(  # numpydoc ignore=GL08
        self,
        type: str,
        number: str | int = "",
        variant: str = "default",
        *,
        display: str | None = None,
        **options: Unpack[_UnitOptions],
    ):
        letters, num = split_tag(type, number)
        name = f"{letters}-{num}" if letters and num else letters + num
        # _resolved_variant sets the final display.
        self.display = "field"
        variant = self._resolved_variant(name, variant, display)
        super().__init__(name, variant=variant, **options)
        self.type = letters
        self.number = num
        self.symbol_type = _BALLOON_SHAPES.get(variant, variant)
        # The drawn tag; a repeated square has a distinct name.
        self._tag = name
        # Attachment intent, set only by attach().
        self.host: "Stream | Unit | None" = None
        self.at: float | None = None
        self.face = None
        self.offset: float = 45.0
        self.angle: float = 90.0
        self.relation: str = "sensing"
        # Primary element whose tag this balloon shares (add_balloon).
        self._marks: "Unit | None" = None
        self.quadrants: dict[str, tuple[str, ...]] = {}
        # Resolved tap point, set only by layout.
        self.tap: tuple[float, float] | None = None

    @property
    def face(self) -> str | None:
        """Return the face of a unit host the balloon hangs from.

        Returns
        -------
        str or None
            ``"N"``, ``"S"``, ``"E"`` or ``"W"``; ``None`` on a stream
            host.
        """
        return self._face

    @face.setter
    def face(self, value: str | None) -> None:
        """Set the face of a unit host, stated unless it is None.

        Parameters
        ----------
        value : str or None
            ``"N"``, ``"S"``, ``"E"`` or ``"W"``, or None.
        """
        self._face = value
        self._face_stated = value is not None

    def _resolved_variant(self, name: str, variant: str, display: str | None) -> str:
        """Set :attr:`display` and return the registered variant.

        Parameters
        ----------
        name : str
            Tag, for messages.
        variant : str
            Symbol type.
        display : str or None
            Where the reading is available; ``None`` implies one.

        Returns
        -------
        str
            Registered variant.

        Raises
        ------
        ValueError
            If ``variant`` is a display spelling, ``display`` is
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
            return variant
        drawn = ", ".join(
            f"variant={v!r} display={d!r}" for (v, d) in _BALLOON_SYMBOLS if d != "field"
        )
        raise ValueError(
            f"{name}: no balloon is drawn for variant={variant!r} with "
            f"display={display!r}. A location bar is registered artwork rather than "
            f"a stripe laid over any outline, and the pairs drawn today are {drawn}. "
            f"Ask for display='field', or for one of those"
        )

    # Signal pools. sig_in and sig_out are the first members; others are
    # created on demand.

    def signal_port(self, name: str) -> Port:
        """Return a port by name, creating a missing pool member.

        Parameters
        ----------
        name : str
            Port name, such as ``"sig_out_2"``.

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

    def _pool_of(self, port_name: str) -> str | None:
        """Return the port's signal pool, or ``None`` outside the pools.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str or None
            ``"sig_in"``, ``"sig_out"`` or ``None``.
        """
        if port_name in self._SIGNAL_POOLS:
            return port_name
        member = _POOL_MEMBER.fullmatch(port_name)
        return member.group(1) if member else None

    @property
    def tag(self) -> str:
        """Return the ISA tag drawn in the symbol.

        Returns
        -------
        str
            Drawn tag.
        """
        return self._tag

    def repeats(self, other: "Unit") -> bool:
        """Return whether this balloon may share ``other``'s tag.

        True for the same logic symbol drawn again, or for the primary
        element this balloon marks.

        Parameters
        ----------
        other : Unit
            Unit with the same tag.

        Returns
        -------
        bool
            Whether the shared tag is allowed.
        """
        if other is self._marks:
            return True
        return (
            isinstance(other, Instrument)
            and other.tag == self.tag
            and self.variant in self._REPEATABLE_VARIANTS
            # A logic square draws the sis symbol.
            and ("sis" if self.variant == "logic" else self.variant)
            == ("sis" if other.variant == "logic" else other.variant)
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

        Codes in a quadrant are sorted A, S then Z outward (ISO 15519-2
        5.2.5). An omitted argument leaves its quadrant unchanged; an
        empty sequence clears it::

            lic304.annotate(high="LAH", low="LAL")

        Parameters
        ----------
        high : str or Sequence[str], optional
            Quadrant (c): high functions.
        low : str or Sequence[str], optional
            Quadrant (d): low functions.
        safety : str or Sequence[str], optional
            Quadrant (a): safety information, such as a SIL.
        variable : str or Sequence[str], optional
            Quadrant (b): the variable for letter code U, such as pH.

        Returns
        -------
        Instrument
            This balloon.

        Raises
        ------
        ValueError
            If a code is empty.
        """
        quadrants = dict(self.quadrants)
        for name, codes in (("a", safety), ("b", variable), ("c", high), ("d", low)):
            if codes is None:
                continue
            if isinstance(codes, str):
                codes = (codes,) if codes else ()
            written = [str(code).strip() for code in codes]
            if not all(written):
                raise ValueError(
                    f"{self.name}: quadrant {name!r} was given an empty letter code. A "
                    f"quadrant holds the codes written outside the symbol, e.g. "
                    f"high='LAH'; leave the argument out to write nothing there"
                )
            if written:
                quadrants[name] = tuple(sorted(written, key=lambda code: next(
                    (" ASZ".index(c) for c in code[1:] if c in "ASZ"), 4)))
            else:
                quadrants.pop(name, None)
        self.quadrants.clear()
        self.quadrants.update(quadrants)
        return self

    def attach(
        self,
        on: "Stream | Unit",
        *,
        at: float | str | None = None,
        face: str | None = None,
        offset: float = 45.0,
        angle: float = 90.0,
        relation: str = "sensing",
    ) -> "Instrument":
        """Anchor this balloon to a process line or to equipment.

        An absolute :meth:`~Unit.pin` overrides the standoff on the axis
        it names.

        Parameters
        ----------
        on : Stream or Unit
            Host line or equipment.
        at : float or str, optional
            Fraction from 0 to 1 inclusive along a stream; default 0.5.
            A unit face given here is deprecated; use ``face``.
        face : str, optional
            Face of a unit, ``"N"``, ``"S"``, ``"E"`` or ``"W"``, or
            ``"top"``, ``"bottom"``, ``"left"`` or ``"right"``; default
            ``"E"``. Where a line leaves a unit's ``"E"`` and the sheet
            draws a line along a unit or across an arrowhead,
            :meth:`~pandid.Flowsheet.route` tries the first of ``"N"``,
            ``"S"`` and ``"W"`` with no line and a process nozzle at its
            middle, kept if no finding grows.
        offset : float, default=45.0
            Requested tap-to-centre distance in pixels; 0 on a stream
            draws the balloon in the line.
        angle : float, default=90.0
            Requested degrees counter-clockwise from the flow on a
            stream, or from the face tangent on a unit.
        relation : str, default="sensing"
            One of :data:`RELATIONS`.

        Returns
        -------
        Instrument
            This balloon.

        Raises
        ------
        TypeError
            If ``on`` is not a Stream or Unit.
        ValueError
            If ``on`` is this balloon, ``at`` and ``face`` are both given
            or do not suit the host, ``offset`` is negative or
            ``relation`` is unknown.

        Warns
        -----
        DeprecationWarning
            If ``at`` names a face of a unit.
        """
        self._attach(on, at, face, offset, angle, relation, warn=True)
        return self

    def _deprecate_at(self, at: object, face: str | None, stacklevel: int = 4) -> None:
        """Warn that ``at`` named the unit face ``face``, if it did.

        Parameters
        ----------
        at : object
            The ``at`` this balloon is attached with.
        face : str or None
            The face that ``at`` resolved to.
        stacklevel : int, default=4
            Warning stack level; 4 names the caller of this method's caller.
        """
        from dataclasses import replace

        if isinstance(at, str):
            replace(_AT_FACE, what=f"at={at!r} (a unit face)",
                    instead=f"face={face!r}, or face: {face} in a spec",
                    ).warn(self, where=self.name, stacklevel=stacklevel)

    def _attach(self, on: "Stream | Unit", at: float | str | None, face: str | None,
                offset: float, angle: float, relation: str, warn: bool = False) -> None:
        """Anchor this balloon as :meth:`attach` does.

        Parameters
        ----------
        on, at, face, offset, angle, relation
            As for :meth:`attach`.
        warn : bool, default=False
            Warn the caller of :meth:`attach` for a face given as ``at``,
            after every check and before any field changes.

        Raises
        ------
        TypeError
            If ``on`` is not a Stream or Unit.
        ValueError
            If an argument is refused, as for :meth:`attach`.
        """
        from pandid.streams import Stream

        if not isinstance(on, (Stream, Unit)):
            raise TypeError(
                f"{self.name}: attach(on=...) takes a Stream or a Unit, got {type(on).__name__}"
            )
        if isinstance(on, Unit) and on is self:
            raise ValueError(f"{self.name} cannot be attached to itself")
        stream = isinstance(on, Stream)
        if at is not None and face is not None:
            raise ValueError(
                f"{self.name}: at= is a fraction along a line and face= a side of a "
                f"unit; {on.name} is a {'line' if stream else 'unit'}, so give "
                f"{'at' if stream else 'face'}= alone"
            )
        old = not stream and isinstance(at, str)
        fraction: float | None = None
        side: str | None = None
        if stream:
            if face is not None:
                raise ValueError(
                    f"{self.name}: face= is a side of a unit, and {on.name} is a line; "
                    f"give at=, a fraction 0..1 along it"
                )
            if isinstance(at, str):
                raise ValueError(
                    f"{self.name}: at= on a stream is a fraction 0..1 along its "
                    f"routed path, got {at!r}"
                )
            fraction = 0.5 if at is None else float(at)
            if not 0.0 <= fraction <= 1.0:
                raise ValueError(f"{self.name}: at= must be within 0..1, got {at!r}")
        else:
            if at is not None and not old:
                raise ValueError(
                    f"{self.name}: at= is a fraction along a line, and {on.name} is a "
                    f"unit; give face= 'N', 'S', 'E' or 'W'"
                )
            named = at if old else ("E" if face is None else face)
            side = (_FACE_OF_SIDE.get(named.strip().lower(), named.strip().upper())
                    if isinstance(named, str) else None)
            if side not in ("N", "S", "E", "W"):
                raise ValueError(
                    f"{self.name}: face= is a side of {on.name}: 'N', 'S', 'E' or 'W', "
                    f"or 'top', 'bottom', 'left' or 'right', got {named!r}"
                )
        offset, angle = float(offset), float(angle)
        if offset < 0:
            raise ValueError(f"{self.name}: offset= must not be negative, got {offset!r}")
        if relation not in RELATIONS:
            raise ValueError(
                f"{self.name}: relation= is what this balloon has to do with "
                f"{getattr(on, 'name', on)!r}, one of "
                f"{', '.join(repr(r) for r in RELATIONS)}, got {relation!r}"
            )
        if warn:
            self._deprecate_at(at, side, stacklevel=5)
        self.host = on
        self.at = fraction
        self.face = side
        self._face_stated = face is not None or old
        self.offset = offset
        self.angle = angle
        self.relation = relation
        self._invalidate_layout()


def _side_ports(*sides: str) -> list[tuple[str, str, str]]:
    """Return an inlet and an outlet port spec for each named side.

    Parameters
    ----------
    *sides : str
        Side names, such as ``"shell"``.

    Returns
    -------
    list[tuple[str, str, str]]
        ``("<side>_in", "inlet", "process")`` and the matching outlet.
    """
    return [
        (f"{side}_{end}", direction, "process")
        for side in sides
        for end, direction in (("in", "inlet"), ("out", "outlet"))
    ]


class HeatExchanger(_VariantPorted):
    """Heat exchanger with an inlet and an outlet on each of two sides.

    Most variants have ``shell`` and ``tube`` sides. ``air_cooled`` has
    ``tube`` and ``air``, ``plate`` and ``spiral`` have ``side_a`` and
    ``side_b``, and ``thin_film`` has ``jacket`` and ``product``.
    ``kettle`` adds ``bottoms``. Parameters are those of :class:`Unit`.
    """

    # Only the shell-and-tube ports are annotated; use
    # ``hx.port(name)`` for the others.
    shell_in: Port
    shell_out: Port
    tube_in: Port
    tube_out: Port

    kind = "hex"
    PORTS: list[tuple[str, str, str]] = []
    _DEFAULT_PORTS = _side_ports("shell", "tube")
    _VARIANT_PORTS = {
        "kettle": [*_DEFAULT_PORTS, ("bottoms", "outlet", "liquid")],
        "air_cooled": _side_ports("tube", "air"),
        "plate": _side_ports("side_a", "side_b"),
        "spiral": _side_ports("side_a", "side_b"),
        "thin_film": _side_ports("jacket", "product"),
    }


class Heater(Unit):
    """Single-stream heater; ``utility_in`` takes the heating medium."""

    inlet: Port
    outlet: Port
    utility_in: Port

    kind = "heater"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("utility_in", "inlet", "energy"),
    ]


class Cooler(Unit):
    """Single-stream cooler; ``utility_out`` carries the coolant."""

    inlet: Port
    outlet: Port
    utility_out: Port

    kind = "cooler"
    PORTS = [
        ("inlet", "inlet", "process"),
        ("outlet", "outlet", "process"),
        ("utility_out", "outlet", "energy"),
    ]


class CoolingTower(Unit):
    """Evaporative cooling tower.

    ``water`` and ``air`` ports are the two sides; ``makeup`` and
    ``blowdown`` are on the basin. ``"default"`` and ``"induced_draft"``
    draw a fan over the fill; ``"forced_draft"`` draws fans at the foot.
    """

    water_in: Port
    water_out: Port
    air_in: Port
    air_out: Port
    makeup: Port
    blowdown: Port

    kind = "cooling_tower"
    PORTS = [
        *_side_ports("water", "air"),
        ("makeup", "inlet", "utility"),
        ("blowdown", "outlet", "liquid"),
    ]


class Evaporator(Unit):
    """Evaporator: liquor concentrated by boiling off water.

    ``feed``, ``vapor`` and ``concentrate`` are the process;
    ``heating_in`` (west) and ``condensate`` (east) are the steam chest.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Heating element: ``"default"``, ``"calandria"``,
        ``"falling_film"``, ``"climbing_film"`` or ``"plate"``.
    supports : str, optional
        ``"leg"``, ``"bracket"``, ``"skirt"`` or ``"ring"``; fixed at
        construction.
    manholes, sockets : Sequence[tuple[str, float]], default=()
        As for :class:`Vessel`, on the W and E shell.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    supports : str or None
        Support drawn under the body.

    Raises
    ------
    ValueError
        If ``supports`` is unknown or the variant cannot carry it, or a
        manhole or socket is not a ``(face, fraction)`` pair on the
        shell.
    """

    feed: Port
    vapor: Port
    concentrate: Port
    heating_in: Port
    condensate: Port

    kind = "evaporator"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("concentrate", "outlet", "liquid"),
        ("heating_in", "inlet", "utility"),
        ("condensate", "outlet", "utility"),
    ]
    COMPOSITION = {"supports": None}
    _FIXED_AT_CONSTRUCTION = frozenset({"supports", "manholes", "sockets"})

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        supports: str | None = None,
        manholes: "Sequence[tuple[str, float]]" = (),
        sockets: "Sequence[tuple[str, float]]" = (),
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        from pandid.render.iso_parts import support_overlays

        self.manholes = _on_walls(self, "manholes", manholes)
        self.sockets = _on_walls(self, "sockets", sockets)
        self.supports = supports
        _compose_onto(self, ("supports", supports, lambda name, _body: support_overlays(name)))
        _hold_walls(self)

    def symbol(self) -> "Symbol":
        """Return the symbol with its parts, manholes and sockets.

        Returns
        -------
        Symbol
            Evaporator drawing.

        Raises
        ------
        ValueError
            If a manhole or socket is off the shell, or the box leaves
            no room for the body.
        """
        from pandid.render.symbols import default_registry

        overlays = tuple(getattr(self, "overlays", ()) or ())
        _, parts, ports, scale = _drawn_parts(self, overlays)
        return _kept_on_walls(
            self, default_registry.composed(self.kind, self.variant, parts, ports), scale)


#: Default thickener rake: the cross-beam stirrer (ISO 10628-2 28.4).
DEFAULT_RAKE = "cross_beam"


class Thickener(Unit):
    """Thickener or clarifier that settles solids out of a slurry.

    Ports are ``feed``, ``overflow`` and ``underflow``. ``validate``
    reports a turned thickener as ``gravity-turned``.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body drawing.
    rake : str or None, default=DEFAULT_RAKE
        Stirrer on the shaft, one of :class:`Reactor`'s ``agitator``
        names, or ``None``. Fixed at construction.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    rake : str or None
        Stirrer drawn on the shaft.

    Raises
    ------
    ValueError
        If ``rake`` is unknown or the variant cannot carry it.
    """

    feed: Port
    overflow: Port
    underflow: Port

    kind = "thickener"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    COMPOSITION = {"rake": DEFAULT_RAKE}
    _FIXED_AT_CONSTRUCTION = frozenset({"rake"})

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        rake: str | None = DEFAULT_RAKE,
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        from pandid.render.iso_parts import rake_overlays

        self.rake = rake
        _compose_onto(self, ("rake", rake, lambda name, _body: rake_overlays(name)))


class Crystallizer(Unit):
    """Draft-tube baffle crystallizer.

    ``feed`` enters the west wall, ``vapor`` leaves the head,
    ``overflow`` takes clear liquor from the settling zone behind the
    baffle and ``product`` draws the slurry from the leg. ``validate``
    reports a turned crystallizer as ``gravity-turned``.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body drawing.
    agitator : str or None, default="propeller"
        Agitator in the draft tube, one of :class:`Reactor`'s
        ``agitator`` names, or ``None``. Fixed at construction.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    agitator : str or None
        Agitator drawn in the draft tube.

    Raises
    ------
    ValueError
        If ``agitator`` is unknown or the variant cannot carry it.
    """

    feed: Port
    vapor: Port
    overflow: Port
    product: Port

    kind = "crystallizer"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("vapor", "outlet", "vapor"),
        ("overflow", "outlet", "liquid"),
        ("product", "outlet", "process"),
    ]
    COMPOSITION = {"agitator": "propeller"}
    _FIXED_AT_CONSTRUCTION = frozenset({"agitator"})

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        agitator: str | None = "propeller",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        from pandid.render.iso_parts import draft_tube_overlays

        self.agitator = agitator
        _compose_onto(self, ("agitator", agitator,
                             lambda name, _body: draft_tube_overlays(name)))


class FlotationCell(Unit):
    """Mechanical flotation cell.

    ``feed`` enters the west wall, ``concentrate`` leaves the froth
    launder on the east, ``tailings`` leaves the floor and ``air``
    enters the standpipe beside the shaft. ``validate`` reports a
    turned cell as ``gravity-turned``.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body drawing.
    agitator : str or None, default="turbine"
        Rotor on the shaft, one of :class:`Reactor`'s ``agitator``
        names, or ``None``. Fixed at construction.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    agitator : str or None
        Rotor drawn on the shaft.

    Raises
    ------
    ValueError
        If ``agitator`` is unknown or the variant cannot carry it.
    """

    feed: Port
    concentrate: Port
    tailings: Port
    air: Port

    kind = "flotation_cell"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("concentrate", "outlet", "process"),
        ("tailings", "outlet", "process"),
        ("air", "inlet", "utility"),
    ]
    COMPOSITION = {"agitator": "turbine"}
    _FIXED_AT_CONSTRUCTION = frozenset({"agitator"})

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        agitator: str | None = "turbine",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        from pandid.render.iso_parts import flotation_overlays

        self.agitator = agitator
        _compose_onto(self, ("agitator", agitator,
                             lambda name, _body: flotation_overlays(name)))


class Silo(_VariantPorted):
    """Silo or bunker for bulk solids, with a conical bottom.

    ``"default"`` draws the closed silo of ISO 10628-2 item 1.9, with a
    ``vent`` in its roof; ``"bunker"`` draws the open bunker of item
    1.8, with none. Solids enter the west wall at ``feed`` and leave the
    cone at ``discharge``. ``validate`` reports a turned silo as
    ``gravity-turned``. Parameters are those of :class:`Unit`.
    """

    feed: Port
    vent: Port
    discharge: Port

    kind = "silo"
    PORTS: list[tuple[str, str, str]] = []
    _DEFAULT_PORTS = [
        ("feed", "inlet", "feed"),
        ("vent", "outlet", "vapor"),
        ("discharge", "outlet", "process"),
    ]
    _VARIANT_PORTS = {
        "bunker": [("feed", "inlet", "feed"), ("discharge", "outlet", "process")],
    }


class MixerSettler(Unit):
    """Mixer-settler: one stage of solvent extraction.

    ``light_in`` and ``heavy_in`` enter the mixer on the west. The
    dispersion overflows into the settler; the light phase leaves over
    the weir at ``light_out`` and the heavy phase through the floor at
    ``heavy_out``. ``validate`` reports a turned mixer-settler as
    ``gravity-turned``.

    Parameters
    ----------
    name : str
        Tag.
    variant : str, default="default"
        Body drawing.
    agitator : str or None, default="turbine"
        Agitator in the mixer, one of :class:`Reactor`'s ``agitator``
        names, or ``None``. Fixed at construction.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    agitator : str or None
        Agitator drawn in the mixer.

    Raises
    ------
    ValueError
        If ``agitator`` is unknown or the variant cannot carry it.
    """

    light_in: Port
    heavy_in: Port
    light_out: Port
    heavy_out: Port

    kind = "mixer_settler"
    PORTS = [
        ("light_in", "inlet", "feed"),
        ("heavy_in", "inlet", "feed"),
        ("light_out", "outlet", "liquid"),
        ("heavy_out", "outlet", "liquid"),
    ]
    COMPOSITION = {"agitator": "turbine"}
    _FIXED_AT_CONSTRUCTION = frozenset({"agitator"})

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        variant: str = "default",
        agitator: str | None = "turbine",
        **options: Unpack[_UnitOptions],
    ):
        super().__init__(name, variant=variant, **options)
        from pandid.render.iso_parts import mixer_settler_overlays

        self.agitator = agitator
        _compose_onto(self, ("agitator", agitator,
                             lambda name, _body: mixer_settler_overlays(name)))


class Deaerator(Unit):
    """Deaerator: a storage drum with its deaerating column on top.

    ``feed`` and ``vent`` are on the column's crown, ``steam`` enters
    the drum's west end and ``outlet`` leaves its floor. ``validate``
    reports a turned deaerator as ``gravity-turned``. Parameters are
    those of :class:`Unit`.
    """

    feed: Port
    vent: Port
    steam: Port
    outlet: Port

    kind = "deaerator"
    PORTS = [
        ("feed", "inlet", "feed"),
        ("vent", "outlet", "vapor"),
        ("steam", "inlet", "utility"),
        ("outlet", "outlet", "liquid"),
    ]


def _feed_names(n_feeds: int, owner: str) -> list[str]:
    """Return the feed port names ``feed_1`` to ``feed_n``.

    Parameters
    ----------
    n_feeds : int
        Number of feeds.
    owner : str
        Class name, for messages.

    Returns
    -------
    list[str]
        Feed port names.

    Raises
    ------
    ValueError
        If ``n_feeds`` is less than 1.
    """
    if n_feeds < 1:
        raise ValueError(f"{owner} requires at least 1 feed, got {n_feeds}")
    return [f"feed_{i}" for i in range(1, n_feeds + 1)]


def _stage_fractions(
    name: str,
    internals: str | None,
    trays: int,
    stages: list[int | None] | None,
    names: list[str],
    keyword: str,
    noun: str,
) -> dict[str, float]:
    """Return the shell fraction of each port given a stage.

    Parameters
    ----------
    name : str
        Tag, for messages.
    internals : str or None
        Column internals.
    trays : int
        Drawn count of decks or beds.
    stages : list[int or None] or None
        One stage per port in ``names``; ``None`` keeps the even spread.
    names : list[str]
        Port names, in order.
    keyword : str
        Argument name, for messages.
    noun : str
        ``"feed"`` or ``"draw"``, for messages.

    Returns
    -------
    dict[str, float]
        Shell fraction per port with a stated stage.

    Raises
    ------
    ValueError
        If ``stages`` has the wrong length, names a stage when
        ``internals`` is ``None``, or names a stage outside the column.
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


#: Deprecation of ``duty`` on a jacketed reactor.
_JACKET_DUTY = Deprecation(
    what="duty on a jacketed Reactor",
    instead=("JacketedReactor, with jacket_in for the jacket's supply and "
             "jacket_out for its return"),
    removed_in="0.4.0",
    note="duty draws jacket_in, low on the jacket",
)


_SeriesFamiliesT = TypeVar("_SeriesFamiliesT", bound="_SeriesFamilies")


class _SeriesFamilies(_Families):
    """Base class for units whose feeds and draws are port series.

    Each member starts on its series' face and may move, by
    :meth:`nozzle` or layout, to a face the series also offers.
    """

    def _series_symbol(self):
        """Return the variant's registered symbol, or None.

        Returns
        -------
        Symbol or None
            The symbol, or ``None`` for an unregistered variant.
        """
        from pandid.render.symbols import default_registry

        try:
            return default_registry.get(self.kind, self.variant)
        except ValueError:
            return None

    def _init_families(self) -> None:
        """Put each series member on its series' face."""
        sym = self._series_symbol()
        series = sym.port_series if sym is not None else ()
        self._faces = {name: s.face for name in self.ports for s in series if s.matches(name)}
        self._listed, self._stated = frozenset(), set()

    def _offered(self, port_name: str, added: bool = True) -> list[str]:
        """Return the faces a member's series offers, its own face first.

        Parameters
        ----------
        port_name : str
            Series member.
        added : bool, default=True
            Include the faces the series also offers.

        Returns
        -------
        list[str]
            Faces on the unit's own axes.
        """
        sym = self._series_symbol()
        series = sym.series_for(port_name) if sym is not None else None
        faces = [] if series is None else [series.face, *(added and [s.face for s in series.also] or [])]
        home = self._faces[port_name]
        return [home, *(face for face in faces if face != home)]

    def _fits(self, faces: dict[str, str], frame: Frame | None) -> bool:
        """Return whether the members can be drawn on faces.

        A member a stage places on a further face must sit inside the
        stretch that face's placement spreads over.

        Parameters
        ----------
        faces : dict[str, str]
            Series member to face on the unit's own axes, in drawn
            order.
        frame : Frame or None
            The unit's placed box.

        Returns
        -------
        bool
            True if the symbol builds and every staged member on a
            further face is inside its stretch.
        """
        return self._misfit(faces, frame) is None

    def _misfit(self, faces: dict[str, str], placed=None) -> str | None:
        """Return why the members cannot be drawn on faces, or None.

        Parameters
        ----------
        faces : dict[str, str]
            Series member to face on the unit's own axes, in drawn
            order.
        placed : Pin, Frame or None, optional
            Placement whose drawn faces the reason names.

        Returns
        -------
        str or None
            Reason, or None if they can.
        """
        from pandid.portgeom import _xform, drawn_side

        try:
            self.symbol(faces)
        except ValueError as exc:
            return str(exc)
        sym = self._series_symbol()
        if sym is None:
            return None
        for name, face in faces.items():
            series = sym.series_for(name)
            pin = self._series_pin(name)
            if series is None or face == series.face or pin is None:
                continue
            on = series.on(face)
            assert on is not None
            _, lo, hi = on.reach(sym.width, sym.height)
            along = sym.height if face in ("W", "E") else sym.width
            if not lo - 1e-9 <= pin * along <= hi + 1e-9:
                return (f"{name}'s stage puts it outside the stretch of the "
                        f"{drawn_side(face, *_xform(placed))} wall clear of the other "
                        f"nozzles there")
        return None

    def symbol(self, faces: dict[str, str] | None = None) -> "Symbol":
        """Return the symbol with the series members on faces.

        Parameters
        ----------
        faces : dict[str, str], optional
            Series member to face, in drawn order; the declared faces
            when omitted.

        Returns
        -------
        Symbol
            The unit's drawing, one series per face where a member is
            off its series' face.
        """
        from pandid.render.symbols import default_registry, series_symbol

        on = self._faces if faces is None else faces
        overlays = tuple(getattr(self, "overlays", ()) or ())
        sym = self._series_symbol()
        if sym is None or all(
                (series := sym.series_for(name)) is not None and series.face == face
                for name, face in on.items()):
            return default_registry.for_unit(self)
        return series_symbol(self.kind, self.variant, tuple(on.items()), overlays)

    def nozzle(self: _SeriesFamiliesT, port_name: str, face: str) -> _SeriesFamiliesT:
        """Move a port to a named face.

        The face is as drawn, so a turned or mirrored unit takes the
        face the reader sees. A feed or draw moves to any face its
        series offers. Other ports use :meth:`Unit.nozzle`.

        Parameters
        ----------
        port_name : str
            Port name or alias.
        face : str
            Compass face or side name.

        Returns
        -------
        _SeriesFamilies
            This unit.

        Raises
        ------
        KeyError
            If the port does not exist.
        ValueError
            If ``face`` is not a face, or the series offers no such
            face or no room on it for the port.
        """
        from pandid.portgeom import own_faces, stated_faces, unreachable_face

        canonical = self._canonical_port_name(port_name)
        if canonical not in self._faces:
            return super().nozzle(port_name, face)
        resolved = _block_face(face, self.name)
        placed = self.pin_ if self.pin_ is not None else self.frame
        drawn = {own: on for on, own in own_faces(placed).items()}
        offered = [drawn[own] for own in self._offered(canonical)]
        if resolved not in offered:
            raise unreachable_face(self, canonical, resolved, offered)
        faces = stated_faces(self, placed)
        misfit = self._misfit({**faces, canonical: own_faces(placed)[resolved]}, placed)
        if misfit is not None:
            raise ValueError(
                f"{self.name}: {misfit}. Keep {canonical} on "
                f"{drawn[faces[canonical]]}, or move it with "
                f"nozzle({canonical!r}, ...) to another of {', '.join(offered)}")
        self._port_faces[canonical] = resolved
        self._stated.add(canonical)
        self._invalidate_layout()
        return self


class Reactor(_SeriesFamilies):
    """Reactor: a vessel body with an agitator and internals.

    ``Reactor("R-1")`` is a CSTR, ``variant="tubular"`` a PFR,
    ``internals="packing"`` a packed bed and
    ``internals="fluidised_bed"`` a fluidised bed. The agitator is
    drawn with its motor, which carries the ``drive`` port. ``vent``
    is the off-gas port, absent on ``"tubular"``; ``duty`` is the
    heating or cooling connection. ``"jacketed"`` has ``jacket_in``,
    low on the jacket, and ``jacket_out``, high on it, in place of
    ``duty``.

    Parameters
    ----------
    name : str
        Tag.
    n_feeds : int, default=1
        Number of feeds, ``feed_1`` to ``feed_n`` down the shell; with
        one, ``feed`` is an alias for ``feed_1``.
    variant : str, default="default"
        Body: ``"default"``, ``"jacketed"`` or ``"tubular"``.
    agitator : str or None, optional
        ``"agitator"``, ``"flat_blade"``, ``"gate_paddle"``,
        ``"cross_beam"``, ``"anchor"``, ``"helical"``, ``"impeller"``,
        ``"propeller"``, ``"disc"``, ``"turbine"`` or ``None``. Defaults
        to ``"agitator"`` on a stirred body without internals. Fixed at
        construction.
    internals : str or None, default=None
        ``"tray"``, ``"baffle_tray"``, ``"bubble_cap_tray"``,
        ``"valve_tray"``, ``"sieve_tray"``, ``"filter_insert"``,
        ``"fluidised_bed"``, ``"packing"`` or ``None``. Fixed at
        construction.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    agitator, internals : str or None
        Stirrer and internals drawn in the body.
    feeds : tuple[Port, ...]
        Feed ports, top to bottom.

    Raises
    ------
    ValueError
        If ``n_feeds`` is less than 1, a part is unknown, or the body
        cannot carry a part, such as ``agitator`` on ``"tubular"``.
    """

    # Numbered nozzles a count can build.
    feed_1: Port
    feed_2: Port
    feed_3: Port
    feed_4: Port
    feed_5: Port
    feed_6: Port
    feed_7: Port
    feed_8: Port

    # "jacketed" builds jacket_in and jacket_out in place of duty;
    # JacketedReactor declares them.
    outlet: Port
    vent: Port
    duty: Port
    # Present only with an agitator.
    drive: Port
    # feed_1 to feed_n, top to bottom.
    feeds: tuple[Port, ...]
    # Alias for feed_1 when there is one feed.
    feed: Port

    kind = "reactor"
    # __init__ adds the variant's ports.
    PORTS: list[tuple[str, str, str]] = []
    _DEFAULT_PORTS = [
        ("outlet", "outlet", "process"),
        ("vent", "outlet", "vapor"),
        ("duty", "inlet", "energy"),
    ]
    _VARIANT_PORTS: dict[str, list[tuple[str, str, str]]] = {
        "jacketed": [
            ("outlet", "outlet", "process"),
            ("vent", "outlet", "vapor"),
            ("jacket_in", "inlet", "utility"),
            ("jacket_out", "outlet", "utility"),
        ],
        "tubular": [
            ("outlet", "outlet", "process"),
            ("duty", "inlet", "energy"),
        ],
    }
    _VARIANT_BUILDS = True

    # Bodies that get an agitator by default.
    _STIRRED = ("default", "jacketed")

    # The agitator default depends on the body and internals.
    COMPOSITION = {"agitator": _UNSTATED, "internals": None}
    _FIXED_AT_CONSTRUCTION = frozenset({"agitator", "internals"})

    @classmethod
    def composition_defaults(
        cls, variant: str, stated: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return composition defaults for a body and stated parts.

        A stirred body gets the general agitator unless internals are
        stated; other bodies get none.

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

    def _check_parts(self) -> None:
        """Refuse an agitator on a body wider than it is tall.

        Raises
        ------
        ValueError
            If the reactor has an agitator and its body is not upright.
        """
        from pandid.render.symbols import default_registry

        if self.agitator is None:
            return
        # An agitator hangs from the head of an upright body.
        bodies = {v: default_registry.get(self.kind, v)
                  for v in default_registry.variants(self.kind)}
        upright = [v for v, body in bodies.items() if body.height >= body.width]
        if self.variant not in upright:
            raise ValueError(
                f"{self.name}: {type(self).__name__} variant {self.variant!r} cannot carry "
                f"agitator={self.agitator!r}; variants that can: {', '.join(upright)}"
            )

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        agitator: str | None = _UNSTATED,
        internals: str | None = None,
        **options: Unpack[_UnitOptions],
    ):
        names = _feed_names(n_feeds, type(self).__name__)
        super().__init__(name, variant=variant, **options)
        if agitator is _UNSTATED:
            agitator = self.composition_defaults(self.variant, {"internals": internals})["agitator"]
        self.agitator = agitator
        self.internals = internals
        # Port order: product, off-gas, duty, then feeds.
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        # Internals are drawn first, under the stirrer shaft.
        from pandid.render.iso_parts import agitator_overlays, internals_overlays

        _compose_onto(
            self,
            ("internals", internals, lambda name, _body: internals_overlays(name)),
            # Placed by the body's aspect.
            ("agitator", agitator, lambda name, body: agitator_overlays(name, self.kind, body)),
        )
        self._check_parts()
        if agitator is not None:
            self.drive = self._add_port("drive", "inlet", "energy")
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        if n_feeds == 1:
            self.feed = self.feeds[0]
        self._init_families()

    # Hidden from type checkers.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            """Return ``jacket_in`` for ``duty`` on a jacketed body.

            Only a body whose ports come from the variant table
            answers; a class with its own ``PORTS`` does not.

            Parameters
            ----------
            name : str
                Attribute asked for.

            Returns
            -------
            Any
                ``jacket_in``, after a deprecation warning.

            Raises
            ------
            AttributeError
                For any other missing attribute; it lists the ports.
            """
            jacket = self.__dict__.get("ports", {}).get("jacket_in")
            if name == "duty" and jacket is not None and not self._declared_ports():
                _JACKET_DUTY.warn(self, where=self.name)
                return jacket
            return super().__getattr__(name)


class Separator(_SeriesFamilies):
    """Flash drum or other separator.

    The phase separators (``"default"``, ``"horizontal"``,
    ``"knockout"``, ``"scrubber"``, ``"venturi_scrubber"``) have
    ``vapor`` and ``liquid`` draws. The mechanical separators and dust
    collectors have ``overflow`` (high) and ``underflow`` (apex).
    ``validate`` reports a turned separator as ``gravity-turned``.

    Parameters
    ----------
    name : str
        Tag.
    n_feeds : int, default=1
        Number of feeds, ``feed_1`` to ``feed_n`` down the wall; with
        one, ``feed`` is an alias for ``feed_1``. ``"horizontal"``
        takes one.
    variant : str, default="default"
        Body.
    characteristic : str, optional
        Group-29 mark: ``"gravity"``, ``"electrostatic"`` or
        ``"electromagnetic"``. Replaces ``variant``.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    characteristic : str or None
        Group-29 mark drawn, if any.
    feeds : tuple[Port, ...]
        Feed ports, top to bottom.

    Raises
    ------
    ValueError
        If ``characteristic`` is unknown or given with a non-default
        ``variant``, ``variant`` names a characteristic, ``n_feeds`` is
        less than 1, or the variant takes one feed only.
    """

    # Numbered nozzles a count can build.
    feed_1: Port
    feed_2: Port
    feed_3: Port
    feed_4: Port
    feed_5: Port
    feed_6: Port
    feed_7: Port
    feed_8: Port

    # Only the phase draws; other draws are ``sep.port("overflow")``.
    vapor: Port
    liquid: Port
    # feed_1 to feed_n, top to bottom.
    feeds: tuple[Port, ...]
    # Alias for feed_1 when there is one feed.
    feed: Port

    kind = "separator"
    # __init__ adds the feeds, then the variant's ports.
    PORTS: list[tuple[str, str, str]] = []
    _DEFAULT_PORTS = [
        ("vapor", "outlet", "vapor"),
        ("liquid", "outlet", "liquid"),
    ]
    # A high draw and a low draw, named by position.
    _OVER_AND_UNDER = [
        ("overflow", "outlet", "process"),
        ("underflow", "outlet", "process"),
    ]
    _VARIANT_PORTS = {
        "cyclone": _OVER_AND_UNDER,
        "gravity": _OVER_AND_UNDER,
        "electrostatic": _OVER_AND_UNDER,
        "sifter": _OVER_AND_UNDER,
        "impact": _OVER_AND_UNDER,
        "permanent_magnet": _OVER_AND_UNDER,
        "electromagnetic": _OVER_AND_UNDER,
    }
    _VARIANT_BUILDS = True
    # Variant -> {port: artwork anchor}, where the artwork renames one.
    _VARIANT_ANCHORS = {
        "cyclone": {"overflow": "vapor", "underflow": "liquid"},
        "gravity": {"overflow": "vapor", "underflow": "liquid"},
        "electrostatic": {"overflow": "vapor", "underflow": "liquid"},
        "electromagnetic": {"overflow": "vapor", "underflow": "liquid"},
        # The artwork names its single feed "feed".
        "horizontal": {"feed_1": "feed"},
    }

    _CHARACTERISTICS = ("gravity", "electrostatic", "electromagnetic")

    # Variant -> advice, for variants that take one feed.
    _ONE_FEED_VARIANTS = {
        "horizontal": "Separator(variant='default'), the upright drum, takes as many as "
                      "you like, and a Mixer ahead of the drum draws the junction where "
                      "two feeds really do combine before they enter",
    }

    COMPOSITION = {"characteristic": None}
    COMPOSITION_VARIANT = "characteristic"

    def _symbol_anchor(self, port_name: str) -> str:
        """Return a port's anchor, checking ``_VARIANT_ANCHORS`` first.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        str
            Anchor name in the artwork.
        """
        renamed = self._VARIANT_ANCHORS.get(self.variant, {})
        return renamed.get(port_name) or super()._symbol_anchor(port_name)

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        characteristic: str | None = None,
        **options: Unpack[_UnitOptions],
    ):
        names = _feed_names(n_feeds, type(self).__name__)
        if variant in self._CHARACTERISTICS:
            raise ValueError(
                f"{name}: {variant!r} is a characteristic, not a variant; "
                f"use Separator(characteristic={variant!r})"
            )
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
        super().__init__(name, variant=variant, **options)
        self.characteristic = self.variant if self.variant in self._CHARACTERISTICS else None
        # Check the variant after VARIANT_ALIASES.
        instead = self._ONE_FEED_VARIANTS.get(self.variant)
        if instead is not None and n_feeds != 1:
            raise ValueError(
                f"{name}: Separator(variant={self.variant!r}) is drawn with one feed "
                f"nozzle and you asked for {n_feeds}. Its charge nozzle is drawn on "
                f"whichever of three heads the line comes from, and a family is spread "
                f"down one face, so the drawing can offer one or the other and this one "
                f"offers the choice of head. {instead}"
            )
        # Feeds come before the draws.
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        if n_feeds == 1:
            self.feed = self.feeds[0]
        for spec in self._variant_ports(self.variant):
            self._add_port(*spec)
        self._init_families()


#: Default drawn tray count (ISO 10628-2 2.6).
DEFAULT_TRAYS = 8


class Column(_SeriesFamilies):
    """General tower: a shell with feeds, overhead and bottoms.

    :class:`DistillationColumn` adds the reflux and reboiler ports,
    :class:`Stripper` the reboiler only and :class:`Absorber` nothing.
    Stages are numbered 1 at the top to ``trays`` at the bottom::

        Column("T-101", internals="valve_tray", trays=30,
               n_feeds=2, feed_stages=[12, 22])

    Parameters
    ----------
    name : str
        Tag.
    n_feeds : int, default=1
        Number of feeds, ``feed_1`` to ``feed_n`` on the west side;
        with one, ``feed`` is an alias for ``feed_1``.
    variant : str, default="default"
        Shell drawing.
    internals : str or None, optional
        ``"tray"``, ``"baffle_tray"``, ``"bubble_cap_tray"``,
        ``"valve_tray"``, ``"sieve_tray"``, ``"filter_insert"``,
        ``"fluidised_bed"``, ``"packing"`` or ``None`` (the default).
        Fixed at construction.
    trays : int, default=DEFAULT_TRAYS
        Drawn count of decks or beds. Fixed at construction.
    feed_stages : list[int or None], optional
        Stage per feed; ``None`` keeps the even spread. Fixed at
        construction.
    n_draws : int, default=0
        Number of side draws on the east face: ``draw`` for one, else
        ``draw_1`` to ``draw_n``.
    draw_stages : list[int or None], optional
        Stage per draw; ``None`` keeps the even spread. Fixed at
        construction.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    internals : str or None
        Internals drawn in the shell.
    trays : int
        Drawn count of decks or beds.
    feeds, draws : tuple[Port, ...]
        Feed and side-draw ports, in declaration order.
    feed_stages, draw_stages : list[int or None] or None
        Stages as given.

    Raises
    ------
    ValueError
        If a count is out of range, an internal is unknown or the shell
        cannot carry it, a stage list has the wrong length, a stage is
        outside the column, or a stage is given with no internals.
    """

    # Numbered nozzles a count can build.
    feed_1: Port
    feed_2: Port
    feed_3: Port
    feed_4: Port
    feed_5: Port
    feed_6: Port
    feed_7: Port
    feed_8: Port
    draw_1: Port
    draw_2: Port
    draw_3: Port
    draw_4: Port
    draw_5: Port
    draw_6: Port
    draw_7: Port
    draw_8: Port

    overhead: Port
    bottoms: Port
    # feed_1 to feed_n, in declaration order.
    feeds: tuple[Port, ...]
    # Alias for feed_1 when there is one feed.
    feed: Port
    # Side draws in declaration order.
    draws: tuple[Port, ...]
    # The side draw when there is one.
    draw: Port

    kind = "column"
    PORTS = [
        ("overhead", "outlet", "vapor"),
        ("bottoms", "outlet", "liquid"),
    ]

    PORT_ANCHORS = {"overhead": "distillate"}

    COMPOSITION = {"internals": None, "trays": DEFAULT_TRAYS}
    _FIXED_AT_CONSTRUCTION = frozenset(
        {"internals", "trays", "feed_stages", "draw_stages"}
    )

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        n_feeds: int = 1,
        variant: str = "default",
        internals: str | None = _UNSTATED,
        trays: int = DEFAULT_TRAYS,
        feed_stages: list[int | None] | None = None,
        n_draws: int = 0,
        draw_stages: list[int | None] | None = None,
        **options: Unpack[_UnitOptions],
    ):
        names = _feed_names(n_feeds, type(self).__name__)
        if n_draws < 0:
            raise ValueError(
                f"{type(self).__name__} cannot take a negative number of draws, got {n_draws}"
            )
        draw_names = ["draw"] if n_draws == 1 else [f"draw_{i}" for i in range(1, n_draws + 1)]
        super().__init__(name, variant=variant, **options)
        if internals is _UNSTATED:
            internals = self.composition_defaults(self.variant)["internals"]
        self.internals = internals
        self.trays = trays
        from pandid.render.iso_parts import internals_overlays

        _compose_onto(
            self, ("internals", internals, lambda name, _body: internals_overlays(name, trays))
        )
        self.feeds = tuple(self._add_port(feed, "inlet", "feed") for feed in names)
        self.draws = tuple(self._add_port(draw, "outlet", "draw") for draw in draw_names)
        if n_feeds == 1:
            self.feed = self.feeds[0]
        self.feed_stages = feed_stages
        self.draw_stages = draw_stages
        self._stage_fractions = {
            **_stage_fractions(name, internals, trays, feed_stages, names, "feed_stages", "feed"),
            **_stage_fractions(
                name, internals, trays, draw_stages, draw_names, "draw_stages", "draw"
            ),
        }
        self._init_families()

    def _series_pin(self, port_name: str) -> float | None:
        """Return the shell fraction a stage pins a port to.

        Parameters
        ----------
        port_name : str
            Port name.

        Returns
        -------
        float or None
            Fraction down the shell, or ``None`` with no stated stage.
        """
        return self._stage_fractions.get(port_name)


class DistillationColumn(Column):
    """Distillation column with reflux and reboiler ports.

    Adds to :class:`Column` the inlets ``reflux_in`` (liquid) and
    ``boilup_in`` (vapour), and the energy ports ``reboiler_duty`` and
    ``condenser_duty``. Every argument is :class:`Column`'s.
    """

    PORTS = [
        *Column.PORTS,
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


class Absorber(Column):
    """Absorption or scrubbing tower with :class:`Column`'s ports.

    ``internals`` defaults to ``"packing"``; every other argument is
    :class:`Column`'s. Lean liquid and gas are two feeds::

        Absorber("V-501", n_feeds=2, feed_stages=[1, 8])
    """

    overhead: Port
    bottoms: Port

    COMPOSITION = {"internals": "packing", "trays": DEFAULT_TRAYS}


class ExtractionColumn(Column):
    """Liquid-liquid extraction column with :class:`Column`'s ports.

    ``internals`` defaults to ``"sieve_tray"`` and ``n_feeds`` to 2. The
    heavy phase enters ``feed_1`` on the top stage and the light phase
    ``feed_2`` on the bottom one; the light phase leaves at ``overhead``
    and the heavy at ``bottoms``. Every argument is :class:`Column`'s::

        ExtractionColumn("C-301", trays=12)
    """

    overhead: Port
    bottoms: Port

    COMPOSITION = {"internals": "sieve_tray", "trays": DEFAULT_TRAYS}

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        n_feeds: int = 2,
        variant: str = "default",
        internals: str | None = _UNSTATED,
        trays: int = DEFAULT_TRAYS,
        feed_stages: list[int | None] | None = None,
        n_draws: int = 0,
        draw_stages: list[int | None] | None = None,
        **options: Unpack[_UnitOptions],
    ):
        if feed_stages is None and n_feeds == 2 and internals is not None:
            feed_stages = [1, trays]
        super().__init__(name, n_feeds=n_feeds, variant=variant, internals=internals,
                         trays=trays, feed_stages=feed_stages, n_draws=n_draws,
                         draw_stages=draw_stages, **options)


class Stripper(Column):
    """Stripping column: a tower with boil-up and reboiler ports.

    Ports are ``overhead``, ``bottoms``, ``boilup_in`` and
    ``reboiler_duty``. Every argument is :class:`Column`'s.
    """

    PORTS = [
        *Column.PORTS,
        ("boilup_in", "inlet", "vapor"),
        ("reboiler_duty", "inlet", "energy"),
    ]

    overhead: Port
    bottoms: Port
    boilup_in: Port
    reboiler_duty: Port


# Variable-port unit types


class Mixer(Unit):
    """Mixer: combines several inlet streams into one outlet.

    Drawn as a triangle. From four inlets, the inlet face grows to keep
    them 20 apart where the sheet draws no worse for it. Where valves or
    fittings on its inlet lines are drawn over each other, it grows to
    space the inlets the widest of them across its line plus a gap, kept
    where the sheet draws no worse for it.

    Parameters
    ----------
    name : str
        Tag.
    n_inlets : int, default=2
        Number of inlets.
    variant
        As for :class:`Unit`.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    inlets : tuple[Port, ...]
        Inlets ``in_1`` to ``in_n``, in order.

    Raises
    ------
    ValueError
        If ``n_inlets`` is less than 1.
    """

    # Numbered nozzles a count can build.
    in_1: Port
    in_2: Port
    in_3: Port
    in_4: Port
    in_5: Port
    in_6: Port
    in_7: Port
    in_8: Port

    # in_1 to in_n in order.
    inlets: tuple[Port, ...]
    outlet: Port

    kind = "mixer"
    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        n_inlets: int = 2,
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        if n_inlets < 1:
            raise ValueError(f"Mixer requires at least 1 inlet, got {n_inlets}")
        super().__init__(name, variant=variant, **options)
        self.inlets = tuple(
            self._add_port(f"in_{i}", "inlet", "process") for i in range(1, n_inlets + 1)
        )
        self._add_port("outlet", "outlet", "process")
        # Whether the sheet draws the stock face for a face that would grow.
        self._stock_face = False
        # Pitch the sheet spaces the nozzles at to fit the furniture on their
        # lines, or 0.0.
        self._fit_pitch = 0.0


class Splitter(Unit):
    """Splitter: divides one inlet stream into several outlets.

    Drawn as a triangle. From four outlets, the outlet face grows to keep
    them 20 apart where the sheet draws no worse for it. Where valves or
    fittings on its outlet lines are drawn over each other, it grows to
    space the outlets the widest of them across its line plus a gap, kept
    where the sheet draws no worse for it.

    Parameters
    ----------
    name : str
        Tag.
    n_outlets : int, default=2
        Number of outlets.
    variant
        As for :class:`Unit`.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    outlets : tuple[Port, ...]
        Outlets ``out_1`` to ``out_n``, in order.

    Raises
    ------
    ValueError
        If ``n_outlets`` is less than 1.
    """

    # Numbered nozzles a count can build.
    out_1: Port
    out_2: Port
    out_3: Port
    out_4: Port
    out_5: Port
    out_6: Port
    out_7: Port
    out_8: Port

    inlet: Port
    # out_1 to out_n in order.
    outlets: tuple[Port, ...]

    kind = "splitter"

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        n_outlets: int = 2,
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        if n_outlets < 1:
            raise ValueError(f"Splitter requires at least 1 outlet, got {n_outlets}")
        super().__init__(name, variant=variant, **options)
        self._add_port("inlet", "inlet", "process")
        self.outlets = tuple(
            self._add_port(f"out_{i}", "outlet", "process") for i in range(1, n_outlets + 1)
        )
        # Whether the sheet draws the stock face for a face that would grow.
        self._stock_face = False
        # Pitch the sheet spaces the nozzles at to fit the furniture on their
        # lines, or 0.0.
        self._fit_pitch = 0.0


def _block_faces(spec: "int | Sequence[str]", default: str, owner: str, argument: str) -> list[str]:
    """Return one face per connection from a count or a face list.

    Parameters
    ----------
    spec : int or Sequence[str]
        Count on the default face, or one face per connection.
    default : str
        Face used for a count.
    owner : str
        Block name, for messages.
    argument : str
        ``"inputs"`` or ``"outputs"``, for messages.

    Returns
    -------
    list[str]
        Compass face per connection.

    Raises
    ------
    ValueError
        If ``spec`` is neither a count nor a face list, is negative, or
        names an invalid face.
    """
    if isinstance(spec, bool) or not isinstance(spec, (int, Sequence)) or isinstance(spec, str):
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
    """Return the compass face for a compass or side name.

    Parameters
    ----------
    face : object
        ``"N"``, ``"S"``, ``"E"``, ``"W"``, or ``"top"``, ``"bottom"``,
        ``"left"``, ``"right"``.
    owner : str
        Block name, for messages.

    Returns
    -------
    str
        ``"N"``, ``"S"``, ``"E"`` or ``"W"``.

    Raises
    ------
    ValueError
        If ``face`` is not a face.
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


class Block(_FaceFamilies):
    """Block flow diagram box: a plant section drawn as a rectangle.

    Connections are ``in_1`` to ``in_n`` and ``out_1`` to ``out_m``;
    :attr:`input_faces` and :attr:`output_faces` are their faces. A
    face names the box's own side, and layout draws each peer on that
    side. The box grows to fit its connections and name::

        rx = fs.add(units.Block("Reaction",
                                inputs=["W", "W", "N"],
                                outputs=["E", "S"]))
        fs.connect(recycle.out_1, rx.in_3)    # north

    Parameters
    ----------
    name : str
        Section name, written inside the box.
    inputs, outputs : int or Sequence[str], default=1
        Count on the default face, or one face per connection.
    variant
        As for :class:`Unit`; there are no variants.
    **options
        ``width``, ``height``, ``label_pos``, ``description`` or
        ``reference``, as for :class:`Unit`.

    Attributes
    ----------
    inlets, outlets : tuple[Port, ...]
        Connections in order.
    DEFAULT_INPUT_FACE, DEFAULT_OUTPUT_FACE : str
        Faces used for a count: ``"W"`` and ``"E"``.

    Raises
    ------
    ValueError
        If there are no connections, ``inputs`` or ``outputs`` is not a
        count or a face list, a count is negative, a face is invalid,
        or the box is too small for its connections.
    """

    # Only the families; their sizes are the caller's.
    inlets: tuple[Port, ...]
    outlets: tuple[Port, ...]

    # Type checkers read any other attribute as a Port.
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Port: ...

    kind = "block"
    _NOUN, _VAR, _MEMBER = "block", "b", "connection"

    DEFAULT_INPUT_FACE = "W"
    DEFAULT_OUTPUT_FACE = "E"

    def __init__(  # numpydoc ignore=GL08
        self,
        name: str,
        inputs: "int | Sequence[str]" = 1,
        outputs: "int | Sequence[str]" = 1,
        variant: str = "default",
        **options: Unpack[_UnitOptions],
    ):
        in_faces = _block_faces(inputs, self.DEFAULT_INPUT_FACE, name, "inputs")
        out_faces = _block_faces(outputs, self.DEFAULT_OUTPUT_FACE, name, "outputs")
        if not in_faces and not out_faces:
            raise ValueError(
                f"{name}: a block with no connections is a rectangle with a word "
                f"in it, which nothing can be routed to. Give it at least one "
                f"inputs= or outputs=."
            )
        super().__init__(name, variant=variant, **options)
        self._faces = {}
        self.inlets = tuple(
            self._add_connection(f"in_{i}", "inlet", face)
            for i, face in enumerate(in_faces, start=1)
        )
        self.outlets = tuple(
            self._add_connection(f"out_{i}", "outlet", face)
            for i, face in enumerate(out_faces, start=1)
        )
        self._record_lists(inputs, outputs)
        self._check_box()

    def _add_connection(self, name: str, direction: str, face: str) -> Port:
        """Create a connection and record its face.

        Parameters
        ----------
        name : str
            Connection name.
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

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute, keeping the old size if the box is too small.

        Parameters
        ----------
        name : str
            Attribute name.
        value : Any
            New value.

        Raises
        ------
        TypeError
            If ``width`` or ``height`` is neither ``None`` nor a real
            number.
        ValueError
            If ``width`` or ``height`` is not positive and finite, or the
            box is too small for its connections.
        """
        was = self.__dict__.get(name)
        super().__setattr__(name, value)
        # Unit.__init__ sets the size before the connections exist.
        if name in ("width", "height") and "_faces" in self.__dict__:
            try:
                self._check_box()
            except ValueError:
                super().__setattr__(name, was)
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
        KeyError
            As for :meth:`Unit.pin`.
        TypeError
            As for :meth:`Unit.pin`.
        ValueError
            As for :meth:`Unit.pin`, or if the placement leaves too
            little room for a face's connections; the previous
            placement is kept.
        """
        # Keep the stated pin to restore on refusal.
        was, was_ports = self._pin, dict(self._pin_ports)
        was_stated = self._turn_stated, self._mirror_stated
        super().pin(
            col=col, row=row, x=x, y=y, orientation=orientation, mirrored=mirrored, port=port
        )
        try:
            self._check_box()
        except ValueError:
            self._pin_ports = was_ports
            self._pin = was
            self._turn_stated, self._mirror_stated = was_stated
            raise
        return self

    def nozzle(self, port_name: str, face: str) -> "Block":
        """Move a connection to another side of the box.

        ``face`` names the box's own side, so a later turn or mirror
        moves the connection with the box.

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
            If ``face`` is invalid or the side has no room; the block is
            unchanged.
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
        self._stated.add(port_name)
        self._invalidate_layout()
        return self

    def symbol(self, faces: dict[str, str] | None = None) -> "Symbol":
        """Return this block's symbol, built to its connections.

        Parameters
        ----------
        faces : dict[str, str], optional
            Connection name to face, in drawn order; the declared faces
            when omitted.

        Returns
        -------
        Symbol
            Block artwork.
        """
        from pandid.render.symbols import block_symbol

        on = self._faces if faces is None else faces
        # Pass the name only when it sizes the box.
        return block_symbol(tuple(on.items()), "" if self.width is not None else self.tag)

    def _offered(self, port_name: str, added: bool = True) -> list[str]:
        """Return every face of the box, the connection's own first.

        Parameters
        ----------
        port_name : str
            Connection name.
        added : bool, default=True
            Unused; a block's faces are all its own.

        Returns
        -------
        list[str]
            Faces on the box's own axes.
        """
        home = self._faces[port_name]
        return [home, *(face for face in ("W", "E", "N", "S") if face != home)]

    def _fits(self, faces: dict[str, str], frame: Frame) -> bool:
        """Return whether the placed box holds each face's connections.

        Parameters
        ----------
        faces : dict[str, str]
            Connection name to face, in drawn order.
        frame : Frame
            The block's placed box.

        Returns
        -------
        bool
            True if no face is shorter than its connections need.
        """
        turned = int(frame.orientation) % 360 in (90, 270)
        return self._crowded(faces, frame.w, frame.h, turned) is None

    def _crowded(self, faces: dict[str, str], w: float, h: float,
                 turned: bool) -> tuple[str, int, str, float, float] | None:
        """Return the first face too short for its connections, or None.

        Parameters
        ----------
        faces : dict[str, str]
            Connection name to face, in drawn order.
        w, h : float
            Placed box size.
        turned : bool
            Whether the block is turned a quarter.

        Returns
        -------
        tuple[str, int, str, float, float] or None
            Face, connection count, box axis, its drawn length and the
            length needed.
        """
        sym = self.symbol(faces)
        for face, count in Counter(faces.values()).items():
            # A single connection needs no spacing.
            if count < 2:
                continue
            upright = face in ("W", "E")
            along = sym.height if upright else sym.width
            # A quarter turn swaps which box axis a face runs along.
            drawn, axis = (w, "width") if upright == turned else (h, "height")
            if drawn < along - 1e-9:
                return face, count, axis, drawn, along
        return None

    def _check_box(self) -> None:
        """Raise if the placed box crowds a face's connections.

        Raises
        ------
        ValueError
            If a face with two or more connections is shorter than
            they need.
        """
        from pandid.portgeom import resolve_size
        from pandid.render.symbols import block_box_too_small

        placed = self.pin_
        w, h = resolve_size(self, placed)
        turned = int(getattr(placed, "orientation", 0) or 0) in (90, 270)
        crowded = self._crowded(self._faces, w, h, turned)
        if crowded is not None:
            raise block_box_too_small(self.name, *crowded, turned=turned)


# Defined at run time only; type checkers still report a missing name.
if not TYPE_CHECKING:
    def __getattr__(name: str) -> NoReturn:
        """Refuse a missing name, saying where its class lives.

        Parameters
        ----------
        name : str
            Attribute asked for.

        Raises
        ------
        AttributeError
            Always; names ``pandid.devices`` for a device class and the
            instrument calls for a transmitter, controller or indicator.
        """
        said = f"module 'pandid.units' has no attribute {name!r}"
        if name.startswith("_"):
            raise AttributeError(said)
        from pandid import devices

        if name in getattr(devices, "__all__", ()):
            raise AttributeError(f"{said}: {name} is in pandid.devices. Import it as "
                                 f"from pandid import {name}")
        if name.endswith(("Transmitter", "Controller", "Indicator")):
            raise AttributeError(
                f"{said}: a transmitter, controller or indicator is an Instrument "
                f"tagged by its letters, with no class of its own. Add one with "
                f"fs.add_instrument(\"LT\", 101, sensing=...), or a transmitter, a "
                f"controller and their signal lines with "
                f"fs.add_control_loop(\"L\", 101, measuring=..., acting_on=...)")
        raise AttributeError(said)
