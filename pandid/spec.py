"""Read and write flowsheets as declarative data.

A spec is a plain mapping describing the same flowsheet the topology API
(``fs.add`` / ``fs.connect``) builds, and :func:`to_dict` writes one back,
so a diagram round-trips through data.

    fs = Flowsheet.from_dict(spec)   # plain dict, no dependencies
    fs = Flowsheet.from_json(path)   # stdlib only
    fs = Flowsheet.from_yaml(path)   # needs the PyYAML extra
    spec = fs.to_dict()              # feeds back into from_dict()

The spec is validated: an unknown key is an error, so a typo cannot drop
a nozzle silently. Every message names its entry (``units[3] 'P-101'``)
and lists the accepted values, as :meth:`pandid.units.Unit.port` does.

The format::

    name: Feed Metering Skid      # required; the rest is optional
    stream_naming_scheme: "S{n}"
    stream_number_start: 1        # the S1 a flag draws
    line_numbering_scheme: "{size}-{service}-{sequence}-{spec}"
    line_number_start: 1001       # the 1001 in 6"-P-1001-A1A
    loop_number_start: 101        # where an unnumbered loop starts
    auto_faces: true              # engine picks each movable face
    components: [{name: Water, formula: H2O}]

    units:
      - {kind: Feed, name: Raw Feed, reference: PFD-100,
         pin: {x: 60, y: 275}}
      - {kind: Feed, name: CWSH, header: true}    # tap it as often
      - {kind: Fitting, name: ST-101, variant: strainer,
         description: Strainer}
      - {kind: Valve, name: HV-101, variant: gate,
         normal_position: closed}
      - {kind: Mixer, name: M-100, n_inlets: 2}
      - {kind: Vessel, name: V-101, variant: horizontal,
         width: 130, height: 42, port_faces: {inlet: N},
         pin: {x: 680, y: 210, mirrored: y}}
      - {kind: Vessel, name: D-301, supports: skirt}   # what it stands on
      - {kind: Reactor, name: R-201, internals: packing, agitator: null}
      - {kind: Column, name: T-101, internals: valve_tray, trays: 30}

    loops:
      - {variable: L, number: 101}   # a loop draws nothing itself
      - {variable: F}                # no number: takes the next one

    instruments:
      - {type: LIC, number: 101, display: central,
         near: LT-101, at: S, offset: 115, port_faces: {sig_out: W}}
      - {balloon_of: FE-101, at: N, offset: 38}   # the element's own tag

    streams:
      - {from: [Raw Feed, outlet], to: [ST-101, inlet],
         size: '6"', service: P, spec: A1A}
      - {from: [LIC-101, sig_out], to: [FV-101, actuator],
         kind: electric}
      - {from: [FV-200, outlet], to: [M-100, in_2],
         draw_as_recycle: true, tabulate: true,
         properties: {"Temperature (C)": 25 C}}

    stream_table_sections: [[Benzene, Mass Fraction]]
    stream_table: {font_size: 8}
    stream_labels: {enclosure: diamond}
    title_block: {title: ..., revisions: [{rev: A, date: ..., by: AA}]}
    annotations: [{type: equipment_list, align: top-right}]

Units are addressed by name. A symbol drawn more than once, such as an
interlock square or a utility header flag, is addressed by the name the
flowsheet gives each drawing, in list order: ``I-1``, then ``I-1 (2)``.
Each entry carries the tag, so a header tapped twice is two ``CWSH``
entries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Literal, cast
from math import isfinite

from pandid import devices as device_types
from pandid._checks import is_real as _is_real, is_whole as _is_integral
from pandid import units as unit_types
from pandid.components import Component
from pandid.document import (
    Annotation,
    Revision,
    StreamLabelOptions,
    StreamTableOptions,
    TableBox,
    TitleBlock,
    equipment_list,
    legend,
    notes,
    _drawn_text,
    _drawn_text_fields,
    _resolve_enclosure,
)
from pandid.flowsheet import (
    DEFAULT_LINE_NUMBER_START,
    DEFAULT_LINE_NUMBERING_SCHEME,
    DEFAULT_LOOP_NUMBER_START,
    DEFAULT_STREAM_NUMBER_START,
    Flowsheet,
    _inferred_kind,
)
from pandid.loops import Loop
from pandid.portgeom import pin_intent, port_refusal
from pandid.ports import Port
from pandid.streams import LINE_NUMBER_FIELDS, Stream
from pandid.units import Instrument, Unit, _Boundary


class SpecError(ValueError):
    """Raised when a flowsheet spec cannot be understood.

    A subclass of :class:`ValueError`, so ``except ValueError`` still
    catches it, while a tool loading user files can tell a bad spec apart
    from an engine error.
    """


# ----------------------------------------------------------------
# Primitive validation. Each helper takes the path of the value it
# checks, so the message points at the entry to fix.
# ----------------------------------------------------------------


def _suggest(value: Any, candidates) -> str:
    """Return a ``" (did you mean 'variant'?)"`` hint for a near-miss.

    Parameters
    ----------
    value : Any
        Value given.
    candidates : Iterable
        Accepted values.

    Returns
    -------
    str
        Hint, or ``""`` when nothing is close.
    """
    close = get_close_matches(str(value), [str(c) for c in candidates], n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    """Check that a value is a mapping with text keys.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Mapping[str, Any]
        The value.

    Raises
    ------
    SpecError
        If it is not a mapping or a key is not text.
    """
    if not isinstance(value, Mapping):
        raise SpecError(
            f"{where} must be a mapping of field -> value, "
            f"got {type(value).__name__}: {value!r}"
        )
    for key in value:
        if not isinstance(key, str):
            raise SpecError(f"{where}: field names must be text, got {key!r}")
    return value


def _sequence(value: Any, where: str) -> list:
    """Check that a value is a list, not text.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    list
        The items.

    Raises
    ------
    SpecError
        If it is not a non-text sequence.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SpecError(f"{where} must be a list, got {type(value).__name__}: {value!r}")
    return list(value)


def _check_keys(data: Mapping[str, Any], allowed, where: str) -> None:
    """Refuse keys outside an allowed set.

    Parameters
    ----------
    data : Mapping[str, Any]
        Entry to check.
    allowed : Collection[str]
        Accepted keys.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        On the first unknown key, with a suggestion.
    """
    for key in data:
        if key not in allowed:
            raise SpecError(
                f"{where}: unknown key {key!r}{_suggest(key, allowed)}; "
                f"allowed keys: {sorted(allowed)}"
            )


def _text(value: Any, where: str) -> str:
    """Check that a value is text.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    str
        The value.

    Raises
    ------
    SpecError
        If it is not a string.
    """
    if not isinstance(value, str):
        raise SpecError(f"{where} must be text, got {value!r} (quote it if it is a number)")
    return value


def _shown(value: Any) -> bool:
    """Return whether a value is text or a number that is only displayed.

    Line-number components and stream properties are drawn, not computed
    with, so ``Decimal`` is accepted there as well as any real number
    (:func:`pandid._checks.is_real`).

    Parameters
    ----------
    value : Any
        Value to check.

    Returns
    -------
    bool
        Whether it is text, a non-bool real number or a ``Decimal``.
    """
    return isinstance(value, (str, Decimal)) or _is_real(value)


def _drawn(value: Any, where: str) -> str:
    """Read a drawn-text field as the text it draws.

    A number such as ``1200`` in a data box is what an engineer writes, and
    YAML reads it as an ``int``; the sheet draws ``str()`` of it, so the
    reader does too, through :func:`~pandid.document._drawn_text` as the
    title block does. ``None`` (an empty YAML value) is blank. Identifiers
    and settings stay strict and use :func:`_text`.

    Parameters
    ----------
    value : Any
        Value to read.
    where : str
        Spec path, for error messages.

    Returns
    -------
    str
        The text drawn.

    Raises
    ------
    SpecError
        If it is a list or mapping rather than a single value.
    """
    if isinstance(value, (Mapping, list, tuple, set)):
        raise SpecError(f"{where} must be text, got {value!r}")
    return _drawn_text(value)


def _number(value: Any, where: str) -> float:
    """Check that a value is a real number, returned unchanged.

    It is not coerced to float, because ``120`` and ``120.0`` are written
    differently in the SVG. See :func:`pandid._checks.is_real` for what
    counts.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    float
        The value, of the type given.

    Raises
    ------
    SpecError
        If it is not a real number, or is a bool or ``Decimal``.
    """
    if not _is_real(value):
        raise SpecError(f"{where} must be a number, got {value!r}")
    return value


def _column_width(value: Any, where: str) -> float | Literal["auto"]:
    """Check a stream-table column-width floor: a number or ``"auto"``.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    float or {"auto"}
        The value.

    Raises
    ------
    SpecError
        If it is neither.
    """
    if value == "auto":
        return "auto"
    if not _is_real(value):
        raise SpecError(f'{where} must be a number or "auto", got {value!r}')
    return value


def _integer(value: Any, where: str) -> int:
    """Check that a value is a whole number.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    int
        The value, of the integer type given.

    Raises
    ------
    SpecError
        If it is not a ``numbers.Integral`` or is a bool.
    """
    if not _is_integral(value):
        raise SpecError(f"{where} must be a whole number, got {value!r}")
    return value


def _flag(value: Any, where: str) -> bool:
    """Check that a value is true or false.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    bool
        The value.

    Raises
    ------
    SpecError
        If it is not a bool.
    """
    if not isinstance(value, bool):
        raise SpecError(f"{where} must be true or false, got {value!r}")
    return value


def _faces(value: Any, where: str) -> int | list[str]:
    """Check a connection count, or a list of one face per connection.

    The unit class validates the face names. A bare string is refused,
    since it would read as one face per character.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Spec path, for error messages.

    Returns
    -------
    int or list[str]
        Count or faces.

    Raises
    ------
    SpecError
        If it is neither a whole number nor a list of text.
    """
    if isinstance(value, bool) or _is_integral(value):
        return _integer(value, where)
    return [_text(face, f"{where}[{i}]") for i, face in enumerate(_sequence(value, where))]


def _composed(value: Any, default: Any, where: str) -> Any:
    """Check a composition keyword's value: a part name or a count.

    The class default decides which: an int default means a count (such
    as ``trays``), anything else a part name (such as ``agitator``),
    which the class validates. ``null`` means "none" and differs from an
    omitted key, which takes the class default.

    Parameters
    ----------
    value : Any
        Value to check.
    default : Any
        Class default for the keyword.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Any
        Count, part name or ``None``.

    Raises
    ------
    SpecError
        If the value has the wrong type.
    """
    if isinstance(default, int) and not isinstance(default, bool):
        return _integer(value, where)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SpecError(
            f"{where} must be the name of a part, or null for none at all, got {value!r}"
        )
    return value


def _stages(value: Any, where: str) -> list[int | None]:
    """Check a ``feed_stages`` or ``draw_stages`` list.

    Parameters
    ----------
    value : Any
        One stage number per feed or draw, or ``null`` for one that keeps
        the even spread.
    where : str
        Spec path, for error messages.

    Returns
    -------
    list[int or None]
        Stages.

    Raises
    ------
    SpecError
        If it is not a list of whole numbers and nulls.
    """
    return [None if item is None else _integer(item, f"{where}[{i}]")
            for i, item in enumerate(_sequence(value, where))]


def _component(value: Any, where: str) -> str | float:
    """Check a line-number component.

    Parameters
    ----------
    value : Any
        Text such as ``6"``, or a number for an unquoted metric size
        (``size: 150``).
    where : str
        Spec path, for error messages.

    Returns
    -------
    str or float
        The value, unchanged; any number type accepted by :func:`_shown`.

    Raises
    ------
    SpecError
        If it is neither text nor a number.
    """
    if not _shown(value):
        raise SpecError(
            f"{where} must be text or a number (an imperial size carries its own "
            f"inch mark, e.g. '6\"'), got {value!r}"
        )
    return value


def _fail_from(error: Exception, where: str) -> SpecError:
    """Return a library error as a SpecError naming the spec entry.

    Parameters
    ----------
    error : Exception
        Error raised by the library.
    where : str
        Spec path.

    Returns
    -------
    SpecError
        Error to raise.
    """
    message = error.args[0] if error.args else str(error)
    return SpecError(f"{where}: {message}")


# --------------------------------------------------------------
# The equipment registry
# --------------------------------------------------------------


def _snake(name: str) -> str:
    """Return a class name in snake_case (``HeatExchanger`` to ``heat_exchanger``).

    Parameters
    ----------
    name : str
        CamelCase name.

    Returns
    -------
    str
        snake_case name.
    """
    out = [name[0].lower()]
    for char in name[1:]:
        out.append(f"_{char.lower()}" if char.isupper() else char)
    return "".join(out)


# Every class a spec may name, from units and devices: _resolve_kind reads
# device classes such as Cyclone, and _write_unit writes the class name.
_CLASSES: dict[str, type[Unit]] = {
    name: getattr(unit_types, name) for name in unit_types.__all__ if name != "Unit"
}
_CLASSES.update({name: getattr(device_types, name) for name in device_types.__all__})

# Accept the class name (HeatExchanger) and its snake_case spelling.
_ALIASES: dict[str, str] = {}
for _name, _cls in _CLASSES.items():
    for _alias in (_name, _snake(_name)):
        _ALIASES[_alias.lower()] = _name
# Also accept Unit.kind (hex), resolved to the base class in units only:
# many device classes share a kind, so including them would make the
# answer depend on iteration order.
for _name in unit_types.__all__:
    if _name != "Unit":
        _ALIASES[_CLASSES[_name].kind.lower()] = _name


def _resolve_kind(value: Any, where: str) -> type[Unit]:
    """Return the unit class a ``kind`` value names.

    Parameters
    ----------
    value : Any
        Class name, snake_case name or ``Unit.kind``.
    where : str
        Spec path, for error messages.

    Returns
    -------
    type[Unit]
        Unit class.

    Raises
    ------
    SpecError
        If the kind is unknown or is Instrument, which has its own section.
    """
    name = _ALIASES.get(_text(value, f"{where}.kind").strip().lower())
    if name is None:
        raise SpecError(
            f"{where}: unknown equipment kind {value!r}{_suggest(value, _CLASSES)}; "
            f"available kinds: {sorted(_CLASSES)}"
        )
    if name == "Instrument":
        raise SpecError(
            f"{where}: instruments go in the top-level 'instruments:' section, not in "
            "'units:'; that is where their tag (type/number) and attachment "
            "(on/at/offset/angle) live"
        )
    return _CLASSES[name]


# --------------------------------------------------------------
# Reading: spec -> Flowsheet
# --------------------------------------------------------------

_TOP_KEYS = {
    "name", "stream_naming_scheme", "stream_number_start",
    "line_numbering_scheme", "line_number_start", "loop_number_start",
    "auto_faces", "components", "units", "loops",
    "instruments", "streams", "stations", "stream_table_sections", "stream_table",
    "stream_labels", "title_block", "annotations",
}
# Removed top-level keys and why, reported by name rather than as unknown.
_RETIRED_KEYS = {
    "direction": "the layout engine only draws left to right, so it never did anything",
}
_PIN_KEYS = {"x", "y", "col", "row", "orientation", "mirrored", "port"}
_UNIT_KEYS = {
    "kind", "name", "variant", "description", "reference", "width", "height",
    "label_pos", "new_line_number", "pin", "port_faces",
}
_INSTRUMENT_KEYS = {
    "type", "number", "variant", "display", "description", "reference", "width",
    "height", "label_pos", "new_line_number", "sensing", "acting_on", "near",
    "at", "offset", "angle", "pin", "port_faces", "quadrants",
}
# The three ways an instrument entry names its anchor.
_ANCHOR_KEYS = ("sensing", "acting_on", "near")
# Keys of a primary element's balloon entry: an instrument entry's, less
# the tag and anchor, which balloon_of supplies. Derived, so the writer
# and reader cannot drift apart.
_BALLOON_KEYS = ({"balloon_of"} | _INSTRUMENT_KEYS) - {"type", "number", *_ANCHOR_KEYS}
# quadrants: key -> ISO quadrant letter; keys match Instrument.annotate.
_QUADRANT_KEYS = {"safety": "a", "variable": "b", "high": "c", "low": "d"}
_LOOP_KEYS = {"variable", "number"}
_STREAM_KEYS = {
    "from", "to", "kind", "name", "draw_as_recycle", "properties", "tabulate", "via",
    "color", "dasharray", "ends", "inline_at", "logical_to",
    *LINE_NUMBER_FIELDS,
}
_COMPONENT_KEYS = {"name", "formula"}
# Keys only some classes take, mapped to those classes; any other class
# refuses the key. Port counts:
_VARIABLE_PORTS = {
    "n_inlets": ("Mixer",),
    "n_outlets": ("Splitter",),
    "n_feeds": ("Column", "Reactor"),
    "n_draws": ("Column",),
}
# Conveyor dimensions, used instead of width and height.
_KIND_SIZES = {
    "length": ("Conveyor",),
    "diameter": ("Conveyor",),
}
# Class-specific text fields.
_KIND_TEXT = {
    "normal_position": ("Valve", "Fitting"),
    # Position on loss of motive power; a blind has no actuator.
    "fail": ("Valve",),
    # Direction of a tee's branch.
    "branch": ("Tee",),
    # Port on a reducer's wide face.
    "large_end": ("Reducer",),
}
# Connection families: a count, or one face per connection.
_KIND_FACES = {
    "inputs": ("Block", "Tank", "Vessel"),
    "outputs": ("Block", "Tank", "Vessel"),
}
# Order along a face, applied with order_on after construction. Written
# only where it differs from declaration order.
_KIND_ORDER = {
    "port_order": ("Block", "Tank", "Vessel"),
}
# A header flag is a utility service that may be tapped repeatedly.
_KIND_FLAGS = {
    "header": ("Feed", "Product"),
}
# Stage per feed or draw; placement, not a composition part.
_KIND_STAGES = {
    "feed_stages": ("Column",),
    "draw_stages": ("Column",),
}
# Composition keywords, derived from each declaring class's
# Unit.COMPOSITION so the spec format gains new keywords automatically.
# Only the declaring class is listed; _takes matches subclasses.
_KIND_COMPOSITION: dict[str, tuple[str, ...]] = {}
for _name, _cls in _CLASSES.items():
    for _key in _cls.__dict__.get("COMPOSITION", {}):
        _KIND_COMPOSITION[_key] = tuple(sorted((*_KIND_COMPOSITION.get(_key, ()), _name)))
# Every class-specific key a unit entry may carry beyond _UNIT_KEYS.
_KIND_KEYS = {**_VARIABLE_PORTS, **_KIND_SIZES, **_KIND_TEXT, **_KIND_FLAGS,
              **_KIND_FACES, **_KIND_ORDER, **_KIND_COMPOSITION, **_KIND_STAGES}


def from_dict(spec: Mapping[str, Any]) -> Flowsheet:
    """Build a :class:`~pandid.flowsheet.Flowsheet` from a mapping.

    Parameters
    ----------
    spec : Mapping[str, Any]
        Declarative flowsheet data.

    Returns
    -------
    Flowsheet
        Connected sheet reconstructed from the data.

    Raises
    ------
    SpecError
        If an entry cannot be honored. The error names its location.
    """
    where = "the flowsheet spec"
    data = _mapping(spec, where)
    for key, why in _RETIRED_KEYS.items():
        if key in data:
            raise SpecError(f"{where}: {key!r} is no longer part of the spec: {why}; remove it")
    _check_keys(data, _TOP_KEYS, where)
    if "name" not in data:
        raise SpecError(f"{where} needs a 'name' (the flowsheet's title)")

    scheme = data.get("stream_naming_scheme", "S{n}")
    stream_start = data.get("stream_number_start", DEFAULT_STREAM_NUMBER_START)
    line_scheme = data.get("line_numbering_scheme", DEFAULT_LINE_NUMBERING_SCHEME)
    start = data.get("line_number_start", DEFAULT_LINE_NUMBER_START)
    loop_start = data.get("loop_number_start", DEFAULT_LOOP_NUMBER_START)
    fs = Flowsheet(
        _drawn(data["name"], f"{where}: 'name'"),
        stream_naming_scheme=_text(scheme, f"{where}: 'stream_naming_scheme'"),
        stream_number_start=_integer(stream_start, f"{where}: 'stream_number_start'"),
        line_numbering_scheme=_text(line_scheme, f"{where}: 'line_numbering_scheme'"),
        line_number_start=_integer(start, f"{where}: 'line_number_start'"),
        loop_number_start=_integer(loop_start, f"{where}: 'loop_number_start'"),
        auto_faces=_flag(data.get("auto_faces", True), f"{where}: 'auto_faces'"),
    )

    for i, entry in enumerate(_sequence(data.get("components", []), "components")):
        fs.add_component(_read_component(entry, f"components[{i}]"))

    for i, entry in enumerate(_sequence(data.get("units", []), "units")):
        _read_unit(fs, entry, f"units[{i}]")

    for i, entry in enumerate(_sequence(data.get("loops", []), "loops")):
        _read_loop(fs, entry, f"loops[{i}]")
    # Continue loop numbering after the numbers the file used, as the
    # equivalent add_loop() calls would.
    fs._resume_loop_numbering()

    # Instruments are created before the streams so a controller output
    # can be connected, but attached afterwards because a balloon may
    # hang off a line that does not exist yet.
    pending = []
    for i, entry in enumerate(_sequence(data.get("instruments", []), "instruments")):
        where_i = f"instruments[{i}]"
        mapping = _mapping(entry, where_i)
        # A balloon's element already exists, so attach it now.
        if "balloon_of" in mapping:
            _read_balloon(fs, mapping, where_i)
            continue
        pending.append((_read_instrument(fs, entry, where_i), mapping, where_i))

    pending_inline = []
    pending_logical = []
    for i, entry in enumerate(_sequence(data.get("streams", []), "streams")):
        stream = _read_stream(fs, entry, f"streams[{i}]")
        if "inline_at" in entry:
            pending_inline.append((stream, entry["inline_at"], f"streams[{i}].inline_at"))
        if "logical_to" in entry:
            pending_logical.append((stream, entry["logical_to"], f"streams[{i}].logical_to"))

    for i, entry in enumerate(_sequence(data.get("stations", []), "stations")):
        _read_station_assembly(fs, entry, f"stations[{i}]")

    for stream, value, where_i in pending_inline:
        try:
            fs._set_inline_at(stream, _number(value, where_i))
        except ValueError as e:
            raise _fail_from(e, where_i) from None

    from pandid.inline import restore_logical_run
    for stream, value, where_i in pending_logical:
        endpoint = _read_endpoint(fs, value, where_i)
        try:
            restore_logical_run(fs, stream, endpoint)
        except ValueError as e:
            raise _fail_from(e, where_i) from None

    for i, assembly in enumerate(fs._station_assemblies):
        root = assembly.run
        if root is None:
            continue
        segments = root._logical_segments
        incoming = assembly.station.inlet.stream
        outgoing = assembly.station.outlet.stream
        position = next((index for index, segment in enumerate(segments)
                         if segment is incoming), None)
        if (root._logical_to is None or incoming is None or position is None
                or position + 1 >= len(segments)
                or segments[position + 1] is not outgoing
                or incoming._inline_at != assembly.at):
            raise SpecError(f"stations[{i}]: run does not contain this station attachment")

    for inst, entry, where_i in pending:
        _attach_instrument(fs, inst, entry, where_i)

    fs.stream_table_sections = [
        _read_section(entry, f"stream_table_sections[{i}]")
        for i, entry in enumerate(_sequence(data.get("stream_table_sections", []),
                                            "stream_table_sections"))
    ]
    if "stream_table" in data:
        fs.stream_table = _read_stream_table(data["stream_table"], "stream_table")
    if "stream_labels" in data:
        fs.stream_labels = _read_stream_labels(data["stream_labels"], "stream_labels")
    if "title_block" in data:
        fs.title_block = _read_title_block(data["title_block"], "title_block")
    for i, entry in enumerate(_sequence(data.get("annotations", []), "annotations")):
        fs.add_annotation(_read_annotation(fs, entry, f"annotations[{i}]"))
    return fs


def _read_component(entry: Any, where: str) -> Component:
    """Read one ``components:`` entry.

    Parameters
    ----------
    entry : Any
        A name, or a mapping with ``name`` and optional ``formula``.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Component
        The component.

    Raises
    ------
    SpecError
        If the entry is malformed.
    """
    if isinstance(entry, str):
        return Component(entry)
    data = _mapping(entry, where)
    _check_keys(data, _COMPONENT_KEYS, where)
    if "name" not in data:
        raise SpecError(f"{where} needs a 'name'")
    formula = data.get("formula")
    return Component(
        _text(data["name"], f"{where}.name"),
        None if formula is None else _drawn(formula, f"{where}.formula"),
    )


def _takes(cls: type[Unit], owners: tuple[str, ...]) -> bool:
    """Return whether ``cls`` is or inherits from one of the owner classes.

    Parameters
    ----------
    cls : type[Unit]
        Unit class.
    owners : tuple[str, ...]
        Names of the classes that declare a keyword.

    Returns
    -------
    bool
        Whether ``cls`` takes the keyword.
    """
    return any(issubclass(cls, _CLASSES[owner]) for owner in owners)


def _read_unit(fs: Flowsheet, entry: Any, where: str) -> Unit:
    """Read one ``units:`` entry and add the unit to the sheet.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Any
        Unit mapping.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Unit
        The added unit.

    Raises
    ------
    SpecError
        If the entry is malformed, names a key its class does not take,
        or the class rejects a value.
    """
    data = _mapping(entry, where)
    if "kind" not in data:
        raise SpecError(
            f"{where} needs a 'kind' (the equipment type, e.g. 'Pump'); got {dict(data)!r}"
        )
    cls = _resolve_kind(data["kind"], where)
    if "name" not in data:
        raise SpecError(f"{where}: a {cls.__name__} needs a 'name' (its tag, e.g. 'P-101')")
    name = _text(data["name"], f"{where}.name")
    where = f"{where} {name!r}"

    allowed = set(_UNIT_KEYS)
    for key, owners in _KIND_KEYS.items():
        # Match by inheritance, so device classes take their base's keys.
        if _takes(cls, owners):
            allowed.add(key)
        elif key in data:
            takers = " or ".join(f"a {owner}" for owner in owners)
            raise SpecError(f"{where}: only {takers} takes {key!r}, not a {cls.__name__}")
    _check_keys(data, allowed, where)

    kwargs: dict[str, Any] = {}
    if "variant" in data:
        kwargs["variant"] = _text(data["variant"], f"{where}.variant")
    for key in ("description", "reference"):
        if key in data:
            kwargs[key] = _drawn(data[key], f"{where}.{key}")
    for key in ("width", "height"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    for key in _VARIABLE_PORTS:
        if key in data:
            kwargs[key] = _integer(data[key], f"{where}.{key}")
    for key in _KIND_SIZES:
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    for key in _KIND_TEXT:
        if key in data:
            kwargs[key] = _text(data[key], f"{where}.{key}")
    for key in _KIND_FLAGS:
        if key in data:
            kwargs[key] = _flag(data[key], f"{where}.{key}")
    for key in _KIND_FACES:
        if key in data:
            kwargs[key] = _faces(data[key], f"{where}.{key}")
    for key in _KIND_STAGES:
        if key in data:
            kwargs[key] = _stages(data[key], f"{where}.{key}")
    # Composition parts; the class default decides each value's type.
    for key, default in cls.COMPOSITION.items():
        if key in data:
            kwargs[key] = _composed(data[key], default, f"{where}.{key}")
    try:
        unit = cls(name, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None

    _read_common(fs, unit, data, where)
    # Order faces after _read_common has moved ports onto them. The key
    # was already refused on other classes; isinstance is for the checker.
    if "port_order" in data and isinstance(unit, (unit_types.Block, unit_types.Tank,
                                                   unit_types.Vessel)):
        _read_port_order(unit, data["port_order"], f"{where}.port_order")
    return unit


_STATION_ROLES = (
    "control", "upstream_isolation", "downstream_isolation", "reduction", "expansion",
    "bypass", "upstream_drain", "downstream_drain",
)
_STATION_KEYS = {
    "members", "tees", "inlet", "outlet", "mirrored", "gap", "bypass_rise",
    "drain_drop", "bypass_over", "run", "at", *_STATION_ROLES,
}


def _read_station_assembly(fs: Flowsheet, entry: Any, where: str) -> None:
    """Restore the identity and local geometry of a wired station.

    Parameters
    ----------
    fs : Flowsheet
        Sheet containing the station's units and streams.
    entry : Any
        Station record from a declarative spec.
    where : str
        Location used in validation errors.

    Raises
    ------
    SpecError
        If a member, port, or placement option is invalid.
    """
    from pandid.stations import (
        BYPASS_ANCHORS, DEFAULT_BYPASS_RISE, DEFAULT_DRAIN_DROP, DEFAULT_GAP,
        StationAssembly, ValveStation,
    )
    from pandid.units import Reducer, Tee, Valve

    data = _mapping(entry, where)
    _check_keys(data, _STATION_KEYS, where)
    required = {"members", "tees", "inlet", "outlet", "control"}
    if missing := required - data.keys():
        raise SpecError(f"{where}: missing {sorted(missing)}")
    members = tuple(_find_unit(fs, _text(name, f"{where}.members"), where)
                    for name in _sequence(data["members"], f"{where}.members"))
    tees = tuple(_find_unit(fs, _text(name, f"{where}.tees"), where)
                 for name in _sequence(data["tees"], f"{where}.tees"))
    roles = {role: (_find_unit(fs, _text(data[role], f"{where}.{role}"), where)
                    if role in data else None) for role in _STATION_ROLES}
    if (not members or len(set(members)) != len(members)
            or any(unit not in members for unit in tees)
            or any(unit not in members for unit in roles.values() if unit is not None)
            or any(not isinstance(unit, Tee) for unit in tees)
            or not isinstance(roles["control"], Valve)
            or any(not isinstance(roles[key], Valve) for key in (
                "upstream_isolation", "downstream_isolation", "bypass",
                "upstream_drain", "downstream_drain") if roles[key] is not None)
            or any(not isinstance(roles[key], Reducer) for key in (
                "reduction", "expansion") if roles[key] is not None)):
        raise SpecError(f"{where}: members and roles must identify one station")
    inlet = _read_endpoint(fs, data["inlet"], f"{where}.inlet")
    outlet = _read_endpoint(fs, data["outlet"], f"{where}.outlet")
    if inlet.owner not in members or outlet.owner not in members:
        raise SpecError(f"{where}: station endpoints must belong to its members")
    station = ValveStation(
        control=cast(Valve, roles["control"]),
        upstream_isolation=cast("Valve | None", roles["upstream_isolation"]),
        downstream_isolation=cast("Valve | None", roles["downstream_isolation"]),
        reduction=cast("Reducer | None", roles["reduction"]),
        expansion=cast("Reducer | None", roles["expansion"]),
        bypass=cast("Valve | None", roles["bypass"]),
        upstream_drain=cast("Valve | None", roles["upstream_drain"]),
        downstream_drain=cast("Valve | None", roles["downstream_drain"]),
        tees=tuple(cast(Tee, tee) for tee in tees), members=members,
        inlet=inlet, outlet=outlet,
    )
    branch_members = {station.bypass, station.upstream_drain, station.downstream_drain}
    main = [unit for unit in members if unit not in branch_members]
    if (not main or inlet is not main[0].ports.get("inlet")
            or outlet is not main[-1].ports.get("outlet")
            or tees != tuple(unit for unit in main if isinstance(unit, Tee))):
        raise SpecError(f"{where}: station members and tees must follow the wired main run")
    for before, after in zip(main, main[1:]):
        connection = before.ports["outlet"].stream
        if (connection is None or connection.kind != "material"
                or connection.dest is not after.ports.get("inlet")):
            raise SpecError(f"{where}: station main members are not wired in order")
    if station.bypass is not None:
        bypass_in = station.bypass.inlet.stream
        bypass_out = station.bypass.outlet.stream
        if (len(tees) < 2 or bypass_in is None or bypass_out is None
                or bypass_in.source is not tees[0].ports.get("branch")
                or bypass_out.dest is not tees[-1].ports.get("branch")):
            raise SpecError(f"{where}: bypass must connect the station's outer tees")
    for drain in (station.upstream_drain, station.downstream_drain):
        if drain is None:
            continue
        connection = drain.inlet.stream
        if (connection is None or connection.source.owner not in tees
                or connection.source.name != "branch"):
            raise SpecError(f"{where}: drain must connect to a station tee")
    run = None
    if "run" in data:
        index = _integer(data["run"], f"{where}.run")
        if index < 0 or index >= len(fs.streams):
            raise SpecError(f"{where}.run: stream index is out of range")
        run = fs.streams[index]
    at = _number(data["at"], f"{where}.at") if "at" in data else None
    if (run is None) != (at is None) or (at is not None and not 0 < at < 1):
        raise SpecError(f"{where}: run and an interior at fraction must occur together")
    options = {key: _number(data[key], f"{where}.{key}") if key in data else default
               for key, default in (("gap", DEFAULT_GAP),
                                    ("bypass_rise", DEFAULT_BYPASS_RISE),
                                    ("drain_drop", DEFAULT_DRAIN_DROP))}
    if any(not isfinite(value) or value <= 0 for value in options.values()):
        raise SpecError(f"{where}: station spacing must be positive")
    bypass_over = (_text(data["bypass_over"], f"{where}.bypass_over")
                   if "bypass_over" in data else None)
    if bypass_over is not None and (
        bypass_over not in BYPASS_ANCHORS or roles[bypass_over] is None
    ):
        raise SpecError(f"{where}.bypass_over: named station member is unavailable")
    assembly = StationAssembly(
        station=station, mirrored=_flag(data.get("mirrored", False), f"{where}.mirrored"),
        gap=options["gap"], bypass_rise=options["bypass_rise"],
        drain_drop=options["drain_drop"],
        bypass_over=bypass_over,
        run=run, at=at,
    )
    fs._station_assemblies.append(assembly)


def _read_loop(fs: Flowsheet, entry: Any, where: str) -> Loop:
    """Read one ``loops:`` entry and declare the loop.

    Members are not listed; each instrument carries its whole tag. An
    omitted ``number`` takes the sheet's next one, as
    :meth:`~pandid.flowsheet.Flowsheet.add_loop` does; :func:`to_dict`
    always writes the number.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Any
        Mapping with ``variable`` and optional ``number``.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Loop
        The declared loop.

    Raises
    ------
    SpecError
        If ``variable`` is missing, ``number`` has the wrong type, or the
        sheet refuses the loop.
    """
    data = _mapping(entry, where)
    _check_keys(data, _LOOP_KEYS, where)
    if "variable" not in data:
        raise SpecError(
            f"{where} needs a 'variable': a loop is identified by what it measures "
            "and its number together, e.g. {variable: F, number: 303} for loop F-303. "
            "The number may be left out to take the sheet's next one; the variable "
            "may not, because nothing else on the sheet knows what this loop measures"
        )
    number = data.get("number")
    if number is not None and not (isinstance(number, str) or _is_integral(number)):
        raise SpecError(f"{where}.number must be a loop number or text, got {number!r}")
    try:
        return fs.add_loop(_text(data["variable"], f"{where}.variable"), number)
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_instrument(fs: Flowsheet, entry: Any, where: str) -> Instrument:
    """Read one ``instruments:`` entry and add the balloon, unattached.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Any
        Instrument mapping.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Instrument
        The added balloon; :func:`_attach_instrument` attaches it later.

    Raises
    ------
    SpecError
        If the entry is malformed or the instrument rejects a value.
    """
    data = _mapping(entry, where)
    _check_keys(data, _INSTRUMENT_KEYS, where)
    if "type" not in data:
        raise SpecError(
            f"{where} needs a 'type': the ISA functional letters, e.g. "
            "{type: FT, number: 101} for FT-101"
        )
    type_ = _text(data["type"], f"{where}.type")
    number = data.get("number", "")
    if not (isinstance(number, str) or _is_integral(number)):
        raise SpecError(f"{where}.number must be a loop number or text, got {number!r}")

    kwargs: dict[str, Any] = {}
    for key in ("variant", "display"):
        if key in data:
            kwargs[key] = _text(data[key], f"{where}.{key}")
    for key in ("description", "reference"):
        if key in data:
            kwargs[key] = _drawn(data[key], f"{where}.{key}")
    for key in ("width", "height"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    try:
        inst = Instrument(type_, number, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None
    if "quadrants" in data:
        _annotate_instrument(inst, data["quadrants"], f"{where}.quadrants")
    _read_common(fs, inst, data, f"{where} {inst.name!r}")
    return inst


def _annotate_instrument(inst: Instrument, entry: Any, where: str) -> None:
    """Apply an instrument entry's ``quadrants:`` mapping.

    Parameters
    ----------
    inst : Instrument
        Balloon to annotate.
    entry : Any
        Mapping of ``safety``, ``variable``, ``high`` and ``low`` to a code
        or list of codes.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If the mapping is malformed or a code is refused.
    """
    data = _mapping(entry, where)
    _check_keys(data, set(_QUADRANT_KEYS), where)
    codes: dict[str, Any] = {}
    for key, value in data.items():
        codes[key] = ([_text(v, f"{where}.{key}[{i}]") for i, v in enumerate(value)]
                      if isinstance(value, (list, tuple))
                      else _text(value, f"{where}.{key}"))
    try:
        inst.annotate(**codes)
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_common(fs: Flowsheet, unit: Unit, data: Mapping[str, Any], where: str) -> None:
    """Apply the shared unit fields and add the unit to the sheet.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    unit : Unit
        Unit or instrument just constructed.
    data : Mapping[str, Any]
        Its entry.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If a field is malformed or the sheet refuses the unit.
    """
    if "label_pos" in data:
        unit.label_pos = _text(data["label_pos"], f"{where}.label_pos")
    if "new_line_number" in data:
        unit.new_line_number = _flag(data["new_line_number"], f"{where}.new_line_number")
    try:
        fs.add(unit)
    except ValueError as e:
        raise _fail_from(e, where) from None
    if "pin" in data:
        _read_pin(unit, data["pin"], f"{where}.pin")
    if "port_faces" in data:
        _read_port_faces(unit, data["port_faces"], f"{where}.port_faces")


def _read_balloon(fs: Flowsheet, entry: Mapping[str, Any], where: str) -> Instrument:
    """Read a ``balloon_of`` entry and add the primary element's balloon.

    See :meth:`~pandid.flowsheet.Flowsheet.add_balloon`. It is an
    instrument entry, not a key on the element, so balloons are rebuilt
    in the order they were made.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Mapping[str, Any]
        Balloon mapping.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Instrument
        The added balloon.

    Raises
    ------
    SpecError
        If the element is not on the sheet or a value is refused.
    """
    _check_keys(entry, _BALLOON_KEYS, where)
    name = _text(entry["balloon_of"], f"{where}.balloon_of")
    element = next((u for u in fs.units if u.name == name), None)
    if element is None:
        raise SpecError(
            f"{where}.balloon_of names {name!r}, which is not a unit on this sheet. "
            f"A balloon carries the tag of the element it is drawn for, so that "
            f"element has to be in the 'units:' section"
        )
    kwargs: dict[str, Any] = {}
    if "at" in entry:
        at = entry["at"]
        kwargs["at"] = at if isinstance(at, str) else _number(at, f"{where}.at")
    for key in ("offset", "angle", "width", "height"):
        if key in entry:
            kwargs[key] = _number(entry[key], f"{where}.{key}")
    for key in ("variant", "display", "label_pos"):
        if key in entry:
            kwargs[key] = _text(entry[key], f"{where}.{key}")
    for key in ("description", "reference"):
        if key in entry:
            kwargs[key] = _drawn(entry[key], f"{where}.{key}")
    try:
        inst = fs.add_balloon(element, **kwargs)
    except (TypeError, ValueError) as e:
        raise _fail_from(e, where) from None
    # add_balloon already added the balloon, so set the remaining fields
    # here instead of through _read_common.
    if "new_line_number" in entry:
        inst.new_line_number = _flag(entry["new_line_number"], f"{where}.new_line_number")
    if "quadrants" in entry:
        _annotate_instrument(inst, entry["quadrants"], f"{where}.quadrants")
    if "pin" in entry:
        _read_pin(inst, entry["pin"], f"{where}.pin")
    if "port_faces" in entry:
        _read_port_faces(inst, entry["port_faces"], f"{where}.port_faces")
    return inst


def _read_pin(unit: Unit, entry: Any, where: str) -> None:
    """Apply a ``pin:`` mapping to a unit.

    Parameters
    ----------
    unit : Unit
        Unit to pin.
    entry : Any
        Mapping of ``x``, ``y``, ``col``, ``row``, ``orientation``,
        ``mirrored`` and ``port``.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If the mapping is malformed or the unit refuses the pin.
    """
    data = _mapping(entry, where)
    _check_keys(data, _PIN_KEYS, where)
    kwargs: dict[str, Any] = {}
    for key in ("x", "y"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    for key in ("col", "row"):
        if key in data:
            kwargs[key] = _integer(data[key], f"{where}.{key}")
    if "orientation" in data:
        kwargs["orientation"] = data["orientation"]
    if "mirrored" in data:
        kwargs["mirrored"] = data["mirrored"]
    ports = _read_pin_ports(unit, data.get("port"),
                            {a for a in ("x", "y") if a in kwargs},
                            {r for r in ("col", "row") if r in kwargs},
                            f"{where}.port")
    try:
        # One pin() call for the corner axes and one per named port.
        # port=None is explicit so an unported coordinate stays a corner,
        # even on a flag whose default anchor is its port. Orientation,
        # mirroring and grid cells go with the corner call.
        unit.pin(port=None,
                 **{axis: value for axis, value in kwargs.items() if axis not in ports})
        for nozzle in dict.fromkeys(ports.values()):
            unit.pin(port=nozzle,
                     **{axis: kwargs[axis] for axis, p in ports.items() if p == nozzle})
    except ValueError as e:
        raise _fail_from(e, where) from None


def _read_pin_ports(unit: Unit, entry: Any, stated: set[str], ranks: set[str],
                    where: str) -> dict[str, str]:
    """Read a pin's ``port:`` key as ``{axis: port}``.

    ``port: inlet`` measures every stated coordinate to that port, as
    :meth:`~pandid.units.Unit.pin` does; ``port: {y: inlet}`` names a port
    per axis, so x can be a corner while y is a port. Only the shape is
    checked here; :func:`~pandid.portgeom.port_refusal` judges the whole
    pin, as :meth:`~pandid.units.Unit.pin` does.

    Parameters
    ----------
    unit : Unit
        Unit being pinned.
    entry : Any
        ``None``, a port name, or a mapping of axis to port name.
    stated : set[str]
        Pixel axes the pin states.
    ranks : set[str]
        Grid keys (``col``, ``row``) the pin states.
    where : str
        Spec path, for error messages.

    Returns
    -------
    dict[str, str]
        Port per measured axis.

    Raises
    ------
    SpecError
        If the key is malformed, names an unknown port, or the pin would
        be refused.
    """
    key = where.rsplit(".", 1)[-1]
    if entry is None:
        return {}
    if not isinstance(entry, (str, Mapping)):
        raise SpecError(
            f"{where} names the nozzle a coordinate was measured to: either one "
            f"name for every coordinate this pin states (port: inlet) or one per "
            f"axis (port: {{y: inlet}}), got {type(entry).__name__}: {entry!r}"
        )
    # Look ports up with _find_port, so pooled ports are created and a typo
    # is reported against this key rather than as a KeyError from pin().
    if isinstance(entry, str):
        _find_port(unit, entry, where)
        _refuse_port(port_refusal(entry, ("x", "y"), stated, ranks, key), where)
        return dict.fromkeys(sorted(stated), entry)
    axes = _mapping(entry, where)
    _check_keys(axes, {"x", "y"}, where)
    if not axes:
        raise SpecError(f"{where} names no axis; give port: {{x: ...}} or drop port")
    named = {axis: _text(name, f"{where}.{axis}") for axis, name in sorted(axes.items())}
    for axis, name in named.items():
        _find_port(unit, name, f"{where}.{axis}")
    for axis, name in named.items():
        _refuse_port(port_refusal(name, (axis,), stated, ranks, f"{key}.{axis}"),
                     f"{where}.{axis}")
    return named


def _refuse_port(complaint: str | None, where: str) -> None:
    """Raise a :func:`~pandid.portgeom.port_refusal` complaint, if any.

    Parameters
    ----------
    complaint : str or None
        Refusal message, or ``None``.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If ``complaint`` is not ``None``.
    """
    if complaint is not None:
        raise SpecError(f"{where}: {complaint}")


def _read_port_faces(unit: Unit, entry: Any, where: str) -> None:
    """Apply a ``port_faces:`` mapping with :meth:`~pandid.units.Unit.nozzle`.

    Parameters
    ----------
    unit : Unit
        Unit whose ports move.
    entry : Any
        Mapping of port name to face.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If a port is unknown or a face is refused.
    """
    for port_name, face in _mapping(entry, where).items():
        _find_port(unit, port_name, where)
        try:
            unit.nozzle(port_name, _text(face, f"{where}.{port_name}"))
        except ValueError as e:
            raise _fail_from(e, f"{where}.{port_name}") from None


def _read_port_order(
    unit: "unit_types.Block | unit_types.Tank | unit_types.Vessel", entry: Any, where: str
) -> None:
    """Apply ``port_order: {S: [out_2, in_2]}``, one ``order_on`` per face.

    Parameters
    ----------
    unit : Block, Tank or Vessel
        Unit whose faces are ordered.
    entry : Any
        Mapping of face to port names, first to last.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If a port is unknown or an order is refused.
    """
    for face, names in _mapping(entry, where).items():
        at = f"{where}.{face}"
        ports = [_find_port(unit, name, at)
                 for name in _sequence(names, at)]
        try:
            unit.order_on(_text(face, at), ports)
        except ValueError as e:
            raise _fail_from(e, at) from None


def _find_port(unit: Unit, name: Any, where: str) -> Port:
    """Return a unit's port by name, creating pooled or retired ports.

    Pooled ports (``sig_out_2``, ``outlet_2``) are created on request, an
    alias (``feed``) resolves to its port, and a retired port is created
    through ``getattr`` with its deprecation warning, so
    ``from_dict(to_dict(fs))`` rebuilds every port the sheet used.

    Parameters
    ----------
    unit : Unit
        Unit to search.
    name : Any
        Port name.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Port
        The port.

    Raises
    ------
    SpecError
        If the unit has no such port.
    """
    if isinstance(name, str) and name not in unit.ports:
        minted = unit._mint_port(name)
        if minted is not None:
            return minted
    # Resolve aliases first; they are attributes, not entries in ports.
    if isinstance(name, str):
        name = unit._canonical_port_name(name)
    # Create a retired port by reading it, as the author's script did;
    # to_dict writes streams on it under that name.
    if isinstance(name, str) and name not in unit.ports:
        try:
            retired = getattr(unit, name)
        except AttributeError:
            retired = None
        if isinstance(retired, Port):
            return retired
    if not isinstance(name, str) or name not in unit.ports:
        raise SpecError(
            f"{where}: {type(unit).__name__} {unit.name!r} has no port {name!r}"
            f"{_suggest(name, unit.ports)}; available ports: {sorted(unit.ports)}"
        )
    return unit.ports[name]


def _find_unit(fs: Flowsheet, name: str, where: str) -> Unit:
    """Return the unit with a given name.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to search.
    name : str
        Unit name.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Unit
        The unit.

    Raises
    ------
    SpecError
        If no unit has that name.
    """
    for unit in fs.units:
        if unit.name == name:
            return unit
    names = [u.name for u in fs.units]
    raise SpecError(
        f"{where}: no unit named {name!r} on this flowsheet{_suggest(name, names)}; "
        f"declared units: {sorted(names)}"
    )


def _read_endpoint(fs: Flowsheet, entry: Any, where: str) -> Port:
    """Read a stream endpoint, ``[unit, port]`` or ``{unit, port}``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Any
        Endpoint.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Port
        The named port.

    Raises
    ------
    SpecError
        If the endpoint is malformed or names an unknown unit or port.
    """
    if isinstance(entry, Mapping):
        _check_keys(entry, {"unit", "port"}, where)
        missing = [key for key in ("unit", "port") if key not in entry]
        if missing:
            raise SpecError(f"{where}: an endpoint mapping needs {missing}; got {dict(entry)!r}")
        unit_name, port_name = entry["unit"], entry["port"]
    elif isinstance(entry, Sequence) and not isinstance(entry, (str, bytes)):
        if len(entry) != 2:
            raise SpecError(
                f"{where}: an endpoint is [unit, port] (exactly two items), got {list(entry)!r}"
            )
        unit_name, port_name = entry
    else:
        raise SpecError(
            f"{where}: an endpoint is [unit, port] (a two-item list) or "
            f"{{unit: ..., port: ...}}, got {entry!r}"
        )
    unit = _find_unit(fs, _text(unit_name, f"{where}: the unit name"), where)
    return _find_port(unit, port_name, where)


def _read_stream(fs: Flowsheet, entry: Any, where: str) -> Stream:
    """Read one ``streams:`` entry and connect it.

    ``inline_at`` and ``logical_to`` are applied later by
    :func:`from_dict`.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Any
        Stream mapping.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Stream
        The new stream.

    Raises
    ------
    SpecError
        If the entry is malformed or the connection is refused.
    """
    data = _mapping(entry, where)
    _check_keys(data, _STREAM_KEYS, where)
    for key in ("from", "to"):
        if key not in data:
            raise SpecError(
                f"{where}: a connection needs both 'from' and 'to'; {key!r} is missing "
                f"from {dict(data)!r}"
            )
    src = _read_endpoint(fs, data["from"], f"{where}.from")
    dst = _read_endpoint(fs, data["to"], f"{where}.to")
    kwargs: dict[str, Any] = {}
    if "kind" in data:
        kwargs["kind"] = _text(data["kind"], f"{where}.kind")
    if "name" in data:
        kwargs["name"] = _text(data["name"], f"{where}.name")
    if "draw_as_recycle" in data:
        kwargs["draw_as_recycle"] = _flag(data["draw_as_recycle"], f"{where}.draw_as_recycle")
    if "ends" in data:
        kwargs["ends"] = _read_ends(data["ends"], f"{where}.ends")
    for key in LINE_NUMBER_FIELDS:
        if key in data:
            kwargs[key] = _component(data[key], f"{where}.{key}")
    try:
        stream = fs.connect(src, dst, **kwargs)
    except ValueError as e:
        raise _fail_from(e, where) from None

    for key in ("color", "dasharray"):
        if key in data:
            setattr(stream, key, _text(data[key], f"{where}.{key}"))
    if "properties" in data:
        stream.properties = _read_properties(data["properties"], f"{where}.properties")
    if "tabulate" in data:
        stream.tabulate = _flag(data["tabulate"], f"{where}.tabulate")
    if "via" in data:
        stream.via(_read_waypoints(data["via"], f"{where}.via"))
    return stream


def _read_ends(entry: Any, where: str) -> "str | tuple[str, str]":
    """Read a stream's ``ends``: one connection name, or ``[source, dest]``.

    ``connect()`` validates the names against
    :data:`~pandid.render.svg.CONNECTIONS`.

    Parameters
    ----------
    entry : Any
        Name or two-item list.
    where : str
        Spec path, for error messages.

    Returns
    -------
    str or tuple[str, str]
        Connection name or pair.

    Raises
    ------
    SpecError
        If the value has the wrong shape.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return (_text(entry[0], f"{where}[0]"), _text(entry[1], f"{where}[1]"))
    raise SpecError(
        f"{where} must be a connection name for both ends or a two-item "
        f"[source, dest] list, got {entry!r}"
    )


def _read_properties(entry: Any, where: str) -> dict[str, str | float]:
    """Read a stream's ``properties`` mapping.

    Parameters
    ----------
    entry : Any
        Mapping of property name to text (with units) or number, including
        ``Decimal`` (:func:`_shown`).
    where : str
        Spec path, for error messages.

    Returns
    -------
    dict[str, str or float]
        Properties.

    Raises
    ------
    SpecError
        If a value is neither text nor a number.
    """
    out: dict[str, str | float] = {}
    for key, value in _mapping(entry, where).items():
        if not _shown(value):
            raise SpecError(
                f"{where}[{key!r}] must be text or a number (values carry their own "
                f"units, e.g. '25 C'), got {value!r}"
            )
        out[key] = value
    return out


def _read_waypoints(entry: Any, where: str) -> list[tuple[float, float]]:
    """Read a stream's ``via`` list of ``[x, y]`` waypoints.

    Parameters
    ----------
    entry : Any
        List of two-number lists.
    where : str
        Spec path, for error messages.

    Returns
    -------
    list[tuple[float, float]]
        Waypoints in pixels.

    Raises
    ------
    SpecError
        If an item is not a pair of numbers.
    """
    points = []
    for i, item in enumerate(_sequence(entry, where)):
        pair = _sequence(item, f"{where}[{i}]")
        if len(pair) != 2:
            raise SpecError(f"{where}[{i}]: a waypoint is [x, y], got {pair!r}")
        points.append((_number(pair[0], f"{where}[{i}].x"), _number(pair[1], f"{where}[{i}].y")))
    return points


def _read_host(fs: Flowsheet, entry: Any, where: str) -> Stream | Unit:
    """Return an instrument's host: a unit or stream name, or a port's stream.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built.
    entry : Any
        Unit or stream name, or an endpoint whose stream is the host.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Stream or Unit
        Host.

    Raises
    ------
    SpecError
        If the name is ambiguous or unknown, or the port has no stream.
    """
    if isinstance(entry, str):
        unit = next((u for u in fs.units if u.name == entry), None)
        stream = next((s for s in fs.streams if s.name == entry), None)
        if unit is not None and stream is not None:
            raise SpecError(
                f"{where}: {entry!r} names both a unit and a stream; identify the stream "
                "as [unit, port] (the port it leaves from) instead"
            )
        if unit is not None:
            return unit
        if stream is not None:
            return stream
        names = [u.name for u in fs.units] + [s.name for s in fs.streams if not s.auto_named]
        raise SpecError(
            f"{where}: nothing named {entry!r} to attach to{_suggest(entry, names)}; "
            f"hosts available: {sorted(names)}"
        )
    port = _read_endpoint(fs, entry, where)
    if port.stream is None:
        raise SpecError(
            f"{where}: {port.owner.name}.{port.name} carries no stream, so there is no "
            "line to tap; attach to a connected port or name the unit itself"
        )
    return port.stream


def _attach_instrument(fs: Flowsheet, inst: Instrument, data: Mapping[str, Any],
                       where: str) -> None:
    """Attach a balloon to the host named by its entry, if any.

    Parameters
    ----------
    fs : Flowsheet
        Built sheet, streams included.
    inst : Instrument
        Balloon to attach.
    data : Mapping[str, Any]
        Its entry: at most one of ``sensing``, ``acting_on`` and ``near``,
        with ``at``, ``offset`` and ``angle``.
    where : str
        Spec path, for error messages.

    Raises
    ------
    SpecError
        If several anchors are named, placement keys have no anchor, or
        the attachment is refused.
    """
    where = f"{where} {inst.name!r}"
    named = [key for key in _ANCHOR_KEYS if key in data]
    if len(named) > 1:
        raise SpecError(
            f"{where}: a balloon is anchored to one thing, and this entry named "
            f"{len(named)} ({', '.join(repr(k) for k in named)}). Which one decides "
            f"what is drawn between them: 'sensing' and 'acting_on' draw a "
            f"connection, 'near' draws nothing"
        )
    if not named:
        stray = [key for key in ("at", "offset", "angle") if key in data]
        if stray:
            raise SpecError(
                f"{where}: {stray} only mean something with one of "
                f"{', '.join(repr(k) for k in _ANCHOR_KEYS)}: the stream or unit the "
                f"balloon is placed against"
            )
        return
    relation = named[0]
    host = _read_host(fs, data[relation], f"{where}.{relation}")
    kwargs: dict[str, Any] = {"relation": relation}
    if "at" in data:
        at = data["at"]
        kwargs["at"] = at if isinstance(at, str) else _number(at, f"{where}.at")
    for key in ("offset", "angle"):
        if key in data:
            kwargs[key] = _number(data[key], f"{where}.{key}")
    try:
        inst.attach(host, **kwargs)
    except (TypeError, ValueError) as e:
        raise _fail_from(e, where) from None


def _read_section(entry: Any, where: str) -> tuple[str, str]:
    """Read a stream-table section, ``[before_key, heading]``.

    Parameters
    ----------
    entry : Any
        Property row the heading goes above, and the heading.
    where : str
        Spec path, for error messages.

    Returns
    -------
    tuple[str, str]
        The pair.

    Raises
    ------
    SpecError
        If it is not two text items.
    """
    pair = _sequence(entry, where)
    if len(pair) != 2:
        raise SpecError(
            f"{where}: a section is [before_key, heading] (the property row the heading "
            f"is injected above), got {pair!r}"
        )
    # The key is matched against property names; the heading is drawn.
    return _text(pair[0], f"{where}[0]"), _drawn(pair[1], f"{where}[1]")


def _read_stream_table(entry: Any, where: str) -> StreamTableOptions:
    """Read ``stream_table:``, the table's drawing options.

    ``font_size: null`` is accepted as the default (automatic). The
    widths take a number or ``"auto"`` but not null. The layout judges
    whether values are usable.

    Parameters
    ----------
    entry : Any
        Mapping of :class:`~pandid.document.StreamTableOptions` fields.
    where : str
        Spec path, for error messages.

    Returns
    -------
    StreamTableOptions
        Options.

    Raises
    ------
    SpecError
        If a key is unknown or a value has the wrong type.
    """
    data = _mapping(entry, where)
    _check_keys(data, {f.name for f in dataclass_fields(StreamTableOptions)}, where)
    options = StreamTableOptions()
    if data.get("font_size") is not None:
        options.font_size = _number(data["font_size"], f"{where}.font_size")
    if "label_width" in data:
        options.label_width = _column_width(data["label_width"], f"{where}.label_width")
    if "column_width" in data:
        options.column_width = _column_width(data["column_width"], f"{where}.column_width")
    for key in ("sheet_subtitle", "sheet_drawing_number"):
        if key in data:
            setattr(options, key, _drawn(data[key], f"{where}.{key}"))
    return options


def _read_stream_labels(entry: Any, where: str) -> StreamLabelOptions:
    """Read ``stream_labels:``, how stream numbers are drawn.

    The options class validates ``enclosure``, so the spec and the API
    give the same error.

    Parameters
    ----------
    entry : Any
        Mapping with optional ``enclosure``.
    where : str
        Spec path, for error messages.

    Returns
    -------
    StreamLabelOptions
        Options.

    Raises
    ------
    SpecError
        If a key is unknown or the enclosure is refused.
    """
    data = _mapping(entry, where)
    _check_keys(data, {f.name for f in dataclass_fields(StreamLabelOptions)}, where)
    if "enclosure" not in data:
        return StreamLabelOptions()
    shape = _text(data["enclosure"], f"{where}.enclosure")
    try:
        return StreamLabelOptions(enclosure=_resolve_enclosure(shape))
    except ValueError as exc:
        raise SpecError(f"{where}.enclosure: {exc}") from exc


def _read_title_block(entry: Any, where: str) -> TitleBlock:
    """Read ``title_block:``.

    Fields are converted with :func:`~pandid.document._drawn_text`, as the
    title strip and :func:`_write_title_block` do, so ``sheet: 1`` is
    accepted and every written block reads back. The allowed keys are the
    text fields from :func:`~pandid.document._drawn_text_fields` plus
    ``revisions``.

    Parameters
    ----------
    entry : Any
        Title block mapping.
    where : str
        Spec path, for error messages.

    Returns
    -------
    TitleBlock
        Title block.

    Raises
    ------
    SpecError
        If a key is unknown or the revisions are malformed.
    """
    data = _mapping(entry, where)
    text_fields = _drawn_text_fields(TitleBlock)
    _check_keys(data, text_fields | {"revisions"}, where)
    kwargs: dict[str, Any] = {
        key: _drawn_text(value) for key, value in data.items() if key in text_fields
    }
    revisions = []
    for i, item in enumerate(_sequence(data.get("revisions", []), f"{where}.revisions")):
        rev_where = f"{where}.revisions[{i}]"
        rev = _mapping(item, rev_where)
        _check_keys(rev, _drawn_text_fields(Revision), rev_where)
        revisions.append(Revision(**{key: _drawn_text(value) for key, value in rev.items()}))
    return TitleBlock(revisions=revisions, **kwargs)


_ANNOTATION_KEYS = {
    "annotation": {"type", "title", "rows", "align", "position", "margin", "width", "font_size"},
    "table": {"type", "title", "headers", "rows", "align", "position", "margin", "font_size",
              "col_align"},
    "equipment_list": {"type", "title", "align", "position", "margin", "width", "include"},
    "notes": {"type", "title", "items", "align", "position", "margin", "width", "numbered"},
    "legend": {"type", "title", "entries", "align", "position", "margin", "width"},
}


def _read_placement(data: Mapping[str, Any], where: str) -> dict[str, Any]:
    """Read the placement and size keys shared by every box.

    Parameters
    ----------
    data : Mapping[str, Any]
        Box entry.
    where : str
        Spec path, for error messages.

    Returns
    -------
    dict[str, Any]
        Keyword arguments: ``align``, ``position``, ``margin``, ``width``
        and ``font_size`` where given.

    Raises
    ------
    SpecError
        If a value has the wrong type.
    """
    out: dict[str, Any] = {}
    if "align" in data:
        out["align"] = _text(data["align"], f"{where}.align")
    if "position" in data:
        pair = _sequence(data["position"], f"{where}.position")
        if len(pair) != 2:
            raise SpecError(
                f"{where}.position: an absolute placement is [x, y] (the box's top-left "
                f"corner), got {pair!r}"
            )
        out["position"] = (_number(pair[0], f"{where}.position[0]"),
                           _number(pair[1], f"{where}.position[1]"))
    for key in ("margin", "width", "font_size"):
        if key in data:
            out[key] = _number(data[key], f"{where}.{key}")
    return out


def _read_rows(entry: Any, where: str) -> list:
    """Read annotation rows: text lines, or lists of cells.

    Lines and cells are drawn text (:func:`_drawn`), so a number reads as
    the string the sheet draws.

    Parameters
    ----------
    entry : Any
        Rows.
    where : str
        Spec path, for error messages.

    Returns
    -------
    list
        Strings and tuples of cell strings.

    Raises
    ------
    SpecError
        If a row is malformed.
    """
    rows: list = []
    for i, row in enumerate(_sequence(entry, where)):
        if isinstance(row, (list, tuple)):
            cells = _sequence(row, f"{where}[{i}]")
            rows.append(tuple(_drawn(c, f"{where}[{i}][{j}]") for j, c in enumerate(cells)))
        else:
            rows.append(_drawn(row, f"{where}[{i}]"))
    return rows


def _read_annotation(fs: Flowsheet, entry: Any, where: str) -> Annotation | TableBox:
    """Read one ``annotations:`` entry.

    Parameters
    ----------
    fs : Flowsheet
        Sheet being built, for an equipment list.
    entry : Any
        Box mapping; ``type`` defaults to ``"annotation"``.
    where : str
        Spec path, for error messages.

    Returns
    -------
    Annotation or TableBox
        The box.

    Raises
    ------
    SpecError
        If the type or a key is unknown or a value is refused.
    """
    data = _mapping(entry, where)
    kind = data.get("type", "annotation")
    if kind not in _ANNOTATION_KEYS:
        raise SpecError(
            f"{where}: unknown box type {kind!r}{_suggest(kind, _ANNOTATION_KEYS)}; "
            f"available types: {sorted(_ANNOTATION_KEYS)}"
        )
    _check_keys(data, _ANNOTATION_KEYS[kind], where)
    kwargs = _read_placement(data, where)
    if "title" in data:
        kwargs["title"] = _text(data["title"], f"{where}.title")

    try:
        if kind == "equipment_list":
            include = data.get("include")
            if include is not None:
                include = [_text(t, f"{where}.include") for t in _sequence(include,
                                                                          f"{where}.include")]
            return equipment_list(fs, include=include, **kwargs)
        if kind == "notes":
            if "items" not in data:
                raise SpecError(f"{where}: a notes box needs 'items' (the list of note texts)")
            items = [_drawn(t, f"{where}.items")
                     for t in _sequence(data["items"], f"{where}.items")]
            if "numbered" in data:
                kwargs["numbered"] = _flag(data["numbered"], f"{where}.numbered")
            return notes(items, **kwargs)
        if kind == "legend":
            if "entries" not in data:
                raise SpecError(f"{where}: a legend box needs 'entries' (abbreviation -> meaning)")
            entries = data["entries"]
            pairs = (list(entries.items()) if isinstance(entries, Mapping)
                     else [tuple(_sequence(e, f"{where}.entries")) for e in
                           _sequence(entries, f"{where}.entries")])
            return legend(pairs, **kwargs)
        if kind == "table":
            if "headers" in data:
                kwargs["headers"] = [_drawn(h, f"{where}.headers")
                                     for h in _sequence(data["headers"], f"{where}.headers")]
            if "col_align" in data:
                kwargs["col_align"] = [_text(a, f"{where}.col_align")
                                       for a in _sequence(data["col_align"], f"{where}.col_align")]
            kwargs["rows"] = [_sequence(row, f"{where}.rows[{i}]")
                              for i, row in enumerate(_sequence(data.get("rows", []),
                                                                f"{where}.rows"))]
            return TableBox(**kwargs)
        kwargs["rows"] = _read_rows(data.get("rows", []), f"{where}.rows")
        return Annotation(**kwargs)
    except SpecError:
        raise  # already carries its own path
    except ValueError as e:
        raise _fail_from(e, where) from None  # e.g. a bad align=


# --------------------------------------------------------------
# Writing: Flowsheet -> spec
# --------------------------------------------------------------

_MIRROR_NAMES = {(True, False): "x", (False, True): "y", (True, True): "xy"}


def to_dict(fs: Flowsheet) -> dict:
    """Serialize a flowsheet to a spec that :func:`from_dict` reads back.

    Only values that differ from a default are written, so the output
    stays readable. Layout results (frames, routed paths, computed stream
    numbers) are omitted, since the engine derives them again.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to serialize.

    Returns
    -------
    dict
        Declarative representation of the sheet.

    Raises
    ------
    SpecError
        If a naming scheme is a callable or a unit's class is not built in.
    ValueError
        If the stream-label enclosure is not a known shape.
    """
    if not isinstance(fs.stream_naming_scheme, str):
        raise SpecError(
            "a callable stream_naming_scheme cannot be written to a spec; use a format "
            "string such as 'S{n}'"
        )
    if not isinstance(fs.line_numbering_scheme, str):
        raise SpecError(
            "a callable line_numbering_scheme cannot be written to a spec; use a format "
            f"string such as {DEFAULT_LINE_NUMBERING_SCHEME!r}"
        )
    spec: dict[str, Any] = {"name": fs.name}
    if fs.stream_naming_scheme != "S{n}":
        spec["stream_naming_scheme"] = fs.stream_naming_scheme
    if fs.stream_number_start != DEFAULT_STREAM_NUMBER_START:
        spec["stream_number_start"] = fs.stream_number_start
    if fs.line_numbering_scheme != DEFAULT_LINE_NUMBERING_SCHEME:
        spec["line_numbering_scheme"] = fs.line_numbering_scheme
    if fs.line_number_start != DEFAULT_LINE_NUMBER_START:
        spec["line_number_start"] = fs.line_number_start
    # Loops below carry literal numbers; this keeps a loop added by hand
    # later in the sheet's series.
    if fs.loop_number_start != DEFAULT_LOOP_NUMBER_START:
        spec["loop_number_start"] = fs.loop_number_start
    if not fs.auto_faces:
        spec["auto_faces"] = False
    if fs.components:
        spec["components"] = [
            c.name if c.formula is None else {"name": c.name, "formula": c.formula}
            for c in fs.components
        ]

    equipment = [u for u in fs.units if not isinstance(u, Instrument)]
    instruments = [u for u in fs.units if isinstance(u, Instrument)]
    if equipment:
        spec["units"] = [_write_unit(u) for u in equipment]
    # No section when no loop is declared.
    if fs.loops:
        spec["loops"] = [{"variable": loop.variable, "number": loop.number}
                         for loop in fs.loops]
    if instruments:
        spec["instruments"] = [_write_instrument(u) for u in instruments]
    if fs.streams:
        spec["streams"] = [_write_stream(s) for s in fs.streams]
    if fs._station_assemblies:
        spec["stations"] = [_write_station_assembly(fs, assembly)
                            for assembly in fs._station_assemblies]
    if fs.stream_table_sections:
        spec["stream_table_sections"] = [list(sec) for sec in fs.stream_table_sections]
    # Only fields changed from their defaults.
    table = {f.name: getattr(fs.stream_table, f.name)
             for f in dataclass_fields(StreamTableOptions)
             if getattr(fs.stream_table, f.name) != f.default}
    if table:
        spec["stream_table"] = table
    labels = {f.name: getattr(fs.stream_labels, f.name)
              for f in dataclass_fields(StreamLabelOptions)
              if getattr(fs.stream_labels, f.name) != f.default}
    if labels:
        # Check the enclosure on output too, since it can be assigned past
        # validation; a ValueError, as the sheet rather than a spec is wrong.
        _resolve_enclosure(fs.stream_labels.enclosure)
        spec["stream_labels"] = labels
    if fs.title_block is not None:
        spec["title_block"] = _write_title_block(fs.title_block)
    if fs.annotations:
        spec["annotations"] = [_write_annotation(a) for a in fs.annotations]
    return spec


def _write_common(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    """Write the fields every unit shares, where they differ from defaults.

    Parameters
    ----------
    unit : Unit
        Unit or instrument.
    entry : dict[str, Any]
        Entry being built; updated in place.

    Returns
    -------
    dict[str, Any]
        ``entry``.
    """
    if unit.variant != "default":
        entry["variant"] = unit.variant
    if unit.description:
        entry["description"] = unit.description
    if unit.reference:
        entry["reference"] = unit.reference
    for key in ("width", "height", "label_pos"):
        if getattr(unit, key) is not None:
            entry[key] = getattr(unit, key)
    if unit.new_line_number:
        entry["new_line_number"] = True
    return entry


def _write_composition(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    """Write composition parts that differ from the class defaults.

    Defaults come from :meth:`~pandid.units.Unit.composition_defaults`,
    given the unit's own parts, since one part can change another's
    default (internals suppress a reactor's agitator). ``None`` is written
    as ``null`` when it differs from the default, because a stated empty
    differs from an omitted key.

    Parameters
    ----------
    unit : Unit
        Unit to write.
    entry : dict[str, Any]
        Entry being built; updated in place.

    Returns
    -------
    dict[str, Any]
        ``entry``.
    """
    cls = type(unit)
    stated = {key: getattr(unit, key) for key in cls.COMPOSITION}
    for key, default in cls.composition_defaults(unit.variant, stated).items():
        value = getattr(unit, key)
        if value != default:
            entry[key] = value
    # Where a keyword is folded into the variant, write only the keyword;
    # the variant spelling is deprecated.
    folded = cls.COMPOSITION_VARIANT
    if folded and entry.get(folded) is not None:
        entry.pop("variant", None)
    return entry


def _write_placement(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    """Write a unit's pin and port faces.

    Parameters
    ----------
    unit : Unit
        Unit to write.
    entry : dict[str, Any]
        Entry being built; updated in place.

    Returns
    -------
    dict[str, Any]
        ``entry``.
    """
    if unit.pin_ is not None:
        pin: dict[str, Any] = {}
        # Write the stated coordinates and the port each was measured to,
        # not the resolved corner, so the pin survives a later turn.
        intent = pin_intent(unit)
        for key in ("x", "y"):
            if key in intent:
                pin[key] = intent[key][1]
        for key in ("col", "row"):
            value = getattr(unit.pin_, key)
            if value is not None:
                pin[key] = value
        named = {axis: port for axis, (port, _) in intent.items() if port is not None}
        if named:
            # One port for every axis is written as ``port: inlet``;
            # otherwise as an axis mapping.
            ports = set(named.values())
            pin["port"] = (ports.pop() if len(ports) == 1 and len(named) == len(intent)
                           else dict(sorted(named.items())))
        if unit.pin_.orientation:
            pin["orientation"] = int(unit.pin_.orientation)
        mirror = _MIRROR_NAMES.get((unit.pin_.mirrored, unit.pin_.mirror_y))
        if mirror:
            pin["mirrored"] = mirror
        entry["pin"] = pin
    if unit._port_faces:
        entry["port_faces"] = dict(unit._port_faces)
    return entry


def _write_connection_faces(unit, entry: dict[str, Any],
                            default_input: str, default_output: str,
                            omit_bare_single: bool = False) -> None:
    """Write ``inputs``, ``outputs`` and ``port_order`` for a family unit.

    Used for :class:`~pandid.units.Block`, :class:`~pandid.units.Tank` and
    :class:`~pandid.units.Vessel`. A family all on its default face is
    written as a count, otherwise as a list of faces. ``port_order`` is
    written only for faces whose order differs from declaration order.

    Parameters
    ----------
    unit : Block, Tank or Vessel
        Unit to write.
    entry : dict[str, Any]
        Entry being built; updated in place.
    default_input, default_output : str
        Default faces.
    omit_bare_single : bool, default=False
        Omit a key for a single connection on the default face. Set for
        Tank and Vessel; a Block always writes both.
    """
    for key, faces, default in (
        ("inputs", unit.input_faces, default_input),
        ("outputs", unit.output_faces, default_output),
    ):
        if omit_bare_single and len(faces) == 1 and faces[0] == default:
            continue
        entry[key] = len(faces) if all(f == default for f in faces) else list(faces)
    declared = [port.name for port in (*unit.inlets, *unit.outlets)]
    port_order = {
        face: [port.name for port in unit.ports_on(face)]
        for face in ("N", "S", "E", "W")
    }
    port_order = {
        face: order for face, order in port_order.items()
        if order != [name for name in declared if name in order]
    }
    if port_order:
        entry["port_order"] = port_order


def _write_unit(unit: Unit) -> dict[str, Any]:
    """Write one ``units:`` entry.

    Parameters
    ----------
    unit : Unit
        Equipment unit.

    Returns
    -------
    dict[str, Any]
        Unit entry, with class-specific keys only where they differ from
        defaults.

    Raises
    ------
    SpecError
        If the unit's class is not one :func:`from_dict` can build.
    """
    kind = type(unit).__name__
    if kind not in _CLASSES:
        # Refuse now rather than write a spec that cannot be read.
        raise SpecError(
            f"{unit.name!r} is a {kind}, which is not one of the built-in equipment "
            f"classes, so it cannot be written to a spec; available kinds: {sorted(_CLASSES)}"
        )
    # Write the tag, not the name, so repeated taps get their names back
    # on reading. A tee has no tag, so its name is written.
    entry: dict[str, Any] = {"kind": kind, "name": unit.tag or unit.name}
    _write_common(unit, entry)
    _write_composition(unit, entry)
    if isinstance(unit, unit_types.Block):
        _write_connection_faces(unit, entry, unit.DEFAULT_INPUT_FACE, unit.DEFAULT_OUTPUT_FACE)
    elif isinstance(unit, (unit_types.Tank, unit_types.Vessel)):
        # The default face depends on the artwork, and a single default
        # connection is omitted.
        _write_connection_faces(unit, entry, unit.default_input_face(),
                                unit.default_output_face(), omit_bare_single=True)
    elif isinstance(unit, unit_types.Mixer):
        entry["n_inlets"] = len(unit.inlets)
    elif isinstance(unit, unit_types.Splitter):
        entry["n_outlets"] = len(unit.outlets)
    elif isinstance(unit, (unit_types.Column, unit_types.Reactor)):
        # One feed is the default.
        if len(unit.feeds) > 1:
            entry["n_feeds"] = len(unit.feeds)
        # Stages only where given; omitted means the even spread.
        if isinstance(unit, unit_types.Column) and unit.feed_stages is not None:
            entry["feed_stages"] = list(unit.feed_stages)
        if isinstance(unit, unit_types.Column):
            # Zero draws is the default.
            if len(unit.draws) > 0:
                entry["n_draws"] = len(unit.draws)
            if unit.draw_stages is not None:
                entry["draw_stages"] = list(unit.draw_stages)
    elif isinstance(unit, unit_types.Tee):
        # Only a returning tee; a takeoff is the default.
        if unit.branch_direction != "outlet":
            entry["branch"] = unit.branch_direction
    elif isinstance(unit, unit_types.Reducer):
        # Only an expansion; a reduction is the default.
        if unit.large_end != "inlet":
            entry["large_end"] = unit.large_end
    elif isinstance(unit, unit_types.Conveyor):
        # Always written, since nothing else records the run.
        entry["length"] = unit.length
        # Only when it differs from the variant's default.
        if unit.diameter != unit.default_diameter():
            entry["diameter"] = unit.diameter
    elif isinstance(unit, unit_types._NormallyPositioned):
        # Only when closed; open is the default.
        if unit.normal_position != "open":
            entry["normal_position"] = unit.normal_position
        # Only a declared fail position.
        fail = getattr(unit, "fail", "")
        if fail:
            entry["fail"] = fail
    elif isinstance(unit, _Boundary):
        # Only a header flag.
        if unit.header:
            entry["header"] = True
    return _write_placement(unit, entry)


def _write_instrument(inst: Instrument) -> dict[str, Any]:
    """Write one ``instruments:`` entry.

    A primary element's balloon is written as ``balloon_of`` its element.

    Parameters
    ----------
    inst : Instrument
        Balloon.

    Returns
    -------
    dict[str, Any]
        Instrument entry.
    """
    entry: dict[str, Any] = (
        {"balloon_of": inst._marks.name} if inst._marks is not None
        else {"type": inst.type, "number": inst.number}
    )
    _write_common(inst, entry)
    # Write symbol type and display separately; the registry variant
    # written by _write_common may be one the constructor refuses.
    entry.pop("variant", None)
    if inst.symbol_type != "default":
        entry["variant"] = inst.symbol_type
    if inst.display != "field":
        entry["display"] = inst.display
    if inst.quadrants:
        by_name = {name: list(codes) for name, letter in _QUADRANT_KEYS.items()
                   for codes in [inst.quadrants.get(letter, ())] if codes}
        if by_name:
            entry["quadrants"] = by_name
    if inst._marks is not None:
        entry["at"] = inst.at
        if inst.offset != 46.0:
            entry["offset"] = inst.offset
        if inst.angle != 90.0:
            entry["angle"] = inst.angle
        # Write its pin and port faces as for any unit.
        return _write_placement(inst, entry)
    if inst.host is not None:
        # Name a stream by its source port; auto-numbered names change.
        entry[inst.relation] = (
            [inst.host.source.owner.name, inst.host.source.name]
            if isinstance(inst.host, Stream) else inst.host.name
        )
        entry["at"] = inst.at
        if inst.offset != 45.0:
            entry["offset"] = inst.offset
        if inst.angle != 90.0:
            entry["angle"] = inst.angle
    return _write_placement(inst, entry)


def _write_station_assembly(fs: Flowsheet, assembly) -> dict[str, Any]:
    """Write one station's members and relative placement intent.

    Parameters
    ----------
    fs : Flowsheet
        Sheet containing the station's original run, if any.
    assembly : StationAssembly
        Registered station assembly.

    Returns
    -------
    dict[str, Any]
        Declarative membership and local spacing.
    """
    from pandid.stations import DEFAULT_BYPASS_RISE, DEFAULT_DRAIN_DROP, DEFAULT_GAP

    station = assembly.station
    entry: dict[str, Any] = {
        "members": [unit.name for unit in station.members],
        "tees": [unit.name for unit in station.tees],
        "inlet": [station.inlet.owner.name, station.inlet.name],
        "outlet": [station.outlet.owner.name, station.outlet.name],
    }
    for role in _STATION_ROLES:
        unit = getattr(station, role)
        if unit is not None:
            entry[role] = unit.name
    if assembly.mirrored:
        entry["mirrored"] = True
    for key, default in (("gap", DEFAULT_GAP),
                         ("bypass_rise", DEFAULT_BYPASS_RISE),
                         ("drain_drop", DEFAULT_DRAIN_DROP)):
        value = getattr(assembly, key)
        if value != default:
            entry[key] = value
    if assembly.bypass_over is not None:
        entry["bypass_over"] = assembly.bypass_over
    if assembly.run is not None:
        entry["run"] = next(i for i, stream in enumerate(fs.streams)
                            if stream is assembly.run)
        entry["at"] = assembly.at
    return entry


def _write_stream(stream: Stream) -> dict[str, Any]:
    """Write one ``streams:`` entry.

    Parameters
    ----------
    stream : Stream
        Connection to write.

    Returns
    -------
    dict[str, Any]
        Declarative stream entry.
    """
    entry: dict[str, Any] = {
        "from": [stream.source.owner.name, stream.source.name],
        "to": [stream.dest.owner.name, stream.dest.name],
    }
    # Write kind when it differs from what connect() would infer from the
    # ports, so a material line between utility ports survives.
    if stream.kind != _inferred_kind(stream.source, stream.dest):
        entry["kind"] = stream.kind
    if not stream.auto_named:
        entry["name"] = stream.name
    if stream.draw_as_recycle:
        entry["draw_as_recycle"] = True
    for key in LINE_NUMBER_FIELDS:
        value = getattr(stream, key)
        # Skip an auto-assigned sequence; it is derived from topology.
        if value is not None and not (key == "sequence" and value == stream._auto_sequence):
            entry[key] = value
    for key in ("color", "dasharray"):
        if getattr(stream, key) is not None:
            entry[key] = getattr(stream, key)
    if stream.ends is not None:
        # A pair is written as a list.
        entry["ends"] = (stream.ends if isinstance(stream.ends, str)
                         else list(stream.ends))
    if stream.route is not None and stream.route.manual:
        entry["via"] = [list(point) for point in stream.route.waypoints]
    if stream.properties:
        entry["properties"] = dict(stream.properties)
    if stream.tabulate:
        entry["tabulate"] = True
    if stream._inline_at is not None:
        entry["inline_at"] = stream._inline_at
    if stream._logical_to is not None:
        entry["logical_to"] = [stream._logical_to.owner.name, stream._logical_to.name]
    return entry


def _stated_text(obj: TitleBlock | Revision) -> dict[str, Any]:
    """Return the drawn-text fields of a block or revision that differ from defaults.

    Compared with the default rather than tested for truth, so a stated
    revision ``0`` is written.

    Parameters
    ----------
    obj : TitleBlock or Revision
        Object to write.

    Returns
    -------
    dict[str, Any]
        Changed fields.
    """
    text = _drawn_text_fields(type(obj))
    return {f.name: getattr(obj, f.name) for f in dataclass_fields(type(obj))
            if f.name in text and getattr(obj, f.name) != f.default}


def _write_title_block(block: TitleBlock) -> dict[str, Any]:
    """Write ``title_block:``.

    Parameters
    ----------
    block : TitleBlock
        Title block.

    Returns
    -------
    dict[str, Any]
        Changed fields and revisions.
    """
    entry: dict[str, Any] = _stated_text(block)
    if block.revisions:
        entry["revisions"] = [_stated_text(rev) for rev in block.revisions]
    return entry


def _write_annotation(box: Annotation | TableBox) -> dict[str, Any]:
    """Write one ``annotations:`` entry.

    Equipment lists, notes and legends are written as plain annotations
    with the same rows, so they draw the same. A title other than the
    default ``""`` is written as stated, even when falsy.

    Parameters
    ----------
    box : Annotation or TableBox
        Box to write.

    Returns
    -------
    dict[str, Any]
        Annotation entry.
    """
    entry: dict[str, Any] = {"type": "table" if isinstance(box, TableBox) else "annotation"}
    # Compare with the default rather than test for truth: a stated 0 or
    # None is written, so the reader refuses it instead of dropping it.
    if box.title != "":
        entry["title"] = box.title
    if isinstance(box, TableBox):
        if box.headers:
            entry["headers"] = list(box.headers)
        entry["rows"] = [list(row) for row in box.rows]
        if box.col_align:
            entry["col_align"] = list(box.col_align)
    else:
        entry["rows"] = [row if isinstance(row, str) else list(row) for row in box.rows]
    entry["align"] = box.align
    if box.position is not None:
        entry["position"] = list(box.position)
    if box.margin:
        entry["margin"] = box.margin
    width = getattr(box, "width", None)  # only Annotation sizes up
    if width is not None:
        entry["width"] = width
    if box.font_size != 11.0:
        entry["font_size"] = box.font_size
    return entry


# --------------------------------------------------------------
# File loaders
# --------------------------------------------------------------


def from_json(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a JSON spec file, using the standard library.

    Parameters
    ----------
    path : str or Path
        JSON file.

    Returns
    -------
    Flowsheet
        Flowsheet read from the file.

    Raises
    ------
    SpecError
        If the file is not valid JSON or the spec is invalid.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: not valid JSON, {e.msg} at line {e.lineno}, column {e.colno}")
    return from_dict(data)


_YAML_LOADER: Any = None


def _core_schema_loader(yaml_module) -> Any:
    """Return a safe PyYAML loader using YAML 1.2 core-schema booleans.

    PyYAML follows YAML 1.1, which reads ``N``, ``on``, ``yes`` and the
    like as booleans and unquoted dates as dates, turning ``at: N`` into
    ``False``. This loader treats only ``true`` and ``false`` as booleans
    and leaves dates as text. It is built once and cached.

    Parameters
    ----------
    yaml_module : module
        The imported ``yaml`` package.

    Returns
    -------
    type
        Loader class.
    """
    global _YAML_LOADER
    if _YAML_LOADER is None:
        dropped = {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}

        class Loader(yaml_module.SafeLoader):
            """Safe loader without YAML 1.1 booleans and timestamps."""

        Loader.yaml_implicit_resolvers = {
            char: [(tag, pattern) for tag, pattern in resolvers if tag not in dropped]
            for char, resolvers in yaml_module.SafeLoader.yaml_implicit_resolvers.items()
        }
        Loader.add_implicit_resolver(
            "tag:yaml.org,2002:bool",
            re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
            list("tTfF"),
        )
        _YAML_LOADER = Loader
    return _YAML_LOADER


def from_yaml(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a YAML spec file.

    Needs the optional PyYAML dependency (``pip install 'pandid[yaml]'``).

    Parameters
    ----------
    path : str or Path
        YAML file.

    Returns
    -------
    Flowsheet
        Flowsheet read from the file.

    Raises
    ------
    ImportError
        If PyYAML is not installed.
    SpecError
        If the file is not valid YAML, is empty, or the spec is invalid.
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "Reading a flowsheet from YAML needs PyYAML, which is not installed. "
            "Install it with:  pip install 'pandid[yaml]'  (or: pip install PyYAML). "
            "Flowsheet.from_dict() and Flowsheet.from_json() need no extra packages."
        ) from e
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.load(text, Loader=_core_schema_loader(yaml))
    except yaml.YAMLError as e:
        raise SpecError(f"{path}: not valid YAML, {e}") from None
    if data is None:
        raise SpecError(f"{path} is empty; a spec needs at least a 'name'")
    return from_dict(data)
