"""Read and write flowsheets as declarative data.

A spec is a plain mapping that :func:`from_dict` reads and
:func:`to_dict` writes. A bad entry raises :class:`SpecError` naming
it, or another error :func:`from_dict` lists.

The format::

    name: Feed Metering Skid      # required
    stream_naming_scheme: "S{n}"
    stream_number_start: 1
    line_numbering_scheme: "{size}-{service}-{sequence}-{spec}"
    line_number_start: 1001
    loop_number_start: 101
    valve_station_tag_scheme: "{letters}-{number}{suffix}"
    auto_faces: true
    components: [{name: Water, formula: H2O}]

    units:
      - {kind: Feed, name: Raw Feed, reference: PFD-100,
         pin: {x: 60, y: 275}}
      - {kind: Feed, name: CWSH, header: true}
      - {kind: Fitting, name: ST-101, variant: strainer,
         description: Strainer}
      - {kind: Valve, name: HV-101, variant: gate,
         normal_position: closed}
      - {kind: Mixer, name: M-100, n_inlets: 2}
      - {kind: Vessel, name: V-101, variant: horizontal,
         width: 130, height: 42, port_faces: {inlet: N},
         pin: {x: 680, y: 210, mirrored: y}}
      - {kind: Vessel, name: D-301, supports: skirt,
         manholes: [[E, 0.3]], sockets: [[W, 0.6]]}
      - {kind: Reactor, name: R-201, internals: packing, agitator: null}
      - {kind: Column, name: T-101, internals: valve_tray, trays: 30}

    loops:
      - {variable: L, number: 101}
      - {variable: F}                # takes the next number

    packages:
      - {name: PK-301, units: [P-301A, P-301B, F-301],
         description: Dosing Package, reference: VENDOR DWG 4711}

    instruments:
      - {type: LIC, number: 101, display: central,
         near: LT-101, face: S, offset: 115, port_faces: {sig_out: W}}
      - {balloon_of: FE-101, face: N, offset: 38}

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
    annotations: [{type: equipment_table, align: top-right}]

Units are addressed by name. Each drawing of a repeated symbol is an
entry with the tag, addressed in list order as ``I-1``, ``I-1 (2)``.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast
from math import isfinite

from pandid import devices as device_types
from pandid._checks import is_real as _is_real, is_whole as _is_integral, suggest
from pandid import units as unit_types
from pandid.components import Component
from pandid.deprecation import Deprecation
from pandid.document import (
    Annotation,
    Revision,
    StreamLabelOptions,
    StreamTableOptions,
    TableBox,
    TitleBlock,
    equipment_table,
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
from pandid.stations import (
    DEFAULT_BYPASS_RISE, DEFAULT_DRAIN_DROP, DEFAULT_GAP, DEFAULT_VALVE_STATION_TAG_SCHEME,
)
from pandid.streams import LINE_NUMBER_FIELDS, Stream
from pandid.units import Instrument, Unit, _Boundary


class SpecError(ValueError):
    """Error for a flowsheet spec that cannot be read or written."""


# Primitive validation


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    """Check that a value is a mapping with text keys.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

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
    """Return a non-text sequence as a list.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    list
        The items.

    Raises
    ------
    SpecError
        If it is text or not a sequence.
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
        Keys the entry may carry.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        On the first unknown key.
    """
    for key in data:
        if key not in allowed:
            raise SpecError(
                f"{where}: unknown key {key!r}{suggest(str(key), allowed)}; "
                f"allowed keys: {sorted(allowed)}"
            )


def _text(value: Any, where: str) -> str:
    """Check that a value is text.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

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
    """Return whether a value is text or a number.

    Parameters
    ----------
    value : Any
        Value to test.

    Returns
    -------
    bool
        True for text, a Decimal or a number ``is_real`` accepts.
    """
    return isinstance(value, (str, Decimal)) or _is_real(value)


def _drawn(value: Any, where: str) -> str:
    """Return a scalar field as the text it draws.

    Parameters
    ----------
    value : Any
        Field value.
    where : str
        Entry path for error messages.

    Returns
    -------
    str
        The text; ``None`` is blank.

    Raises
    ------
    SpecError
        If it is a list, tuple, set or mapping.
    """
    if isinstance(value, (Mapping, list, tuple, set)):
        raise SpecError(f"{where} must be text, got {value!r}")
    return _drawn_text(value)


def _number(value: Any, where: str) -> float:
    """Check that a value is a finite number ``is_real`` accepts.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    float
        The value, as given.

    Raises
    ------
    SpecError
        If ``is_real`` refuses it or it is not finite.
    """
    if not _is_real(value):
        raise SpecError(f"{where} must be a number, got {value!r}")
    if not isfinite(value):
        raise SpecError(f"{where} must be a finite number, got {value!r}")
    return value


def _column_width(value: Any, where: str) -> float | Literal["auto"]:
    """Check a stream-table column width: a number or ``"auto"``.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    float or {"auto"}
        The value.

    Raises
    ------
    SpecError
        If it is not ``"auto"`` and ``_number`` refuses it.
    """
    if value == "auto":
        return "auto"
    if not _is_real(value):
        raise SpecError(f'{where} must be a number or "auto", got {value!r}')
    return _number(value, where)


def _integer(value: Any, where: str) -> int:
    """Check that a value is a whole number.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    int
        The value.

    Raises
    ------
    SpecError
        If it is not a whole number, or is a bool.
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
        Entry path for error messages.

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
    """Check a connection count, or a list of one face each.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    int or list[str]
        The count, or the faces.

    Raises
    ------
    SpecError
        If it is a bool, or neither a whole number nor a sequence of
        text.
    """
    if isinstance(value, bool) or _is_integral(value):
        return _integer(value, where)
    return [_text(face, f"{where}[{i}]") for i, face in enumerate(_sequence(value, where))]


def _walls(value: Any, where: str) -> list[tuple[Any, ...]]:
    """Check a ``manholes`` or ``sockets`` list of placements.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    list[tuple]
        One ``(face, fraction)`` per item, for the class to check.

    Raises
    ------
    SpecError
        If it is not a list of lists.
    """
    return [tuple(_sequence(item, f"{where}[{i}]"))
            for i, item in enumerate(_sequence(value, where))]


def _composed(value: Any, default: Any, where: str) -> Any:
    """Check a composition value: a count, a part name or ``None``.

    Parameters
    ----------
    value : Any
        Value to check.
    default : Any
        Class default; an int means the value is a count.
    where : str
        Entry path for error messages.

    Returns
    -------
    int, str or None
        The value.

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
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    list[int or None]
        One stage per item; ``None`` where none is given.

    Raises
    ------
    SpecError
        If it is not a list of whole numbers and nulls.
    """
    return [None if item is None else _integer(item, f"{where}[{i}]")
            for i, item in enumerate(_sequence(value, where))]


def _component(value: Any, where: str) -> str | float:
    """Check a line-number component: text or a number.

    Parameters
    ----------
    value : Any
        Value to check.
    where : str
        Entry path for error messages.

    Returns
    -------
    str or float
        The value.

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
    """Return a library error as a SpecError naming ``where``.

    Parameters
    ----------
    error : Exception
        Library error.
    where : str
        Entry path for error messages.

    Returns
    -------
    SpecError
        Error with the message after ``where``.
    """
    message = error.args[0] if error.args else str(error)
    return SpecError(f"{where}: {message}")


@contextmanager
def _blame(where: str, errors: tuple[type[Exception], ...] = (ValueError,)) -> Iterator[None]:
    """Re-raise library errors in the block as SpecErrors.

    Parameters
    ----------
    where : str
        Entry path for error messages.
    errors : tuple[type[Exception], ...], default=(ValueError,)
        Exception types to convert.

    Yields
    ------
    None
        Control to the block.

    Raises
    ------
    SpecError
        If the block raises one of ``errors``.
    """
    try:
        yield
    except errors as e:
        raise _fail_from(e, where) from None


def _read_fields(data: Mapping[str, Any], where: str,
                 readers: Sequence[tuple[Iterable[str], Callable[[Any, str], Any]]]
                 ) -> dict[str, Any]:
    """Read each listed key ``data`` has with its reader, in order.

    Parameters
    ----------
    data : Mapping[str, Any]
        Entry to read.
    where : str
        Entry path for error messages.
    readers : Sequence[tuple[Iterable[str], Callable]]
        Pairs of keys and the reader for them.

    Returns
    -------
    dict[str, Any]
        Read value per listed key present.

    Raises
    ------
    SpecError
        If a reader refuses a value.
    """
    return {key: read(data[key], f"{where}.{key}")
            for keys, read in readers for key in keys if key in data}


# The equipment registry


# Every class a spec may name, from units and devices.
_CLASSES: dict[str, type[Unit]] = {
    name: getattr(unit_types, name) for name in unit_types.__all__ if name != "Unit"
}
_CLASSES.update({name: getattr(device_types, name) for name in device_types.__all__})

# Accept the class name (HeatExchanger) and its snake_case spelling.
_ALIASES: dict[str, str] = {}
for _name, _cls in _CLASSES.items():
    for _alias in (_name, re.sub(r"(?<=.)([A-Z])", r"_\1", _name)):
        _ALIASES[_alias.lower()] = _name
# Also accept Unit.kind (hex), resolved to its base class in units.
for _name in unit_types.__all__:
    if _name != "Unit":
        _ALIASES[_CLASSES[_name].kind.lower()] = _name


def _resolve_kind(value: Any, where: str) -> type[Unit]:
    """Return the unit class a ``kind`` value names.

    Parameters
    ----------
    value : Any
        The entry's ``kind``.
    where : str
        Entry path for error messages.

    Returns
    -------
    type[Unit]
        The named class.

    Raises
    ------
    SpecError
        If the kind is not text, is unknown, or is Instrument.
    """
    name = _ALIASES.get(_text(value, f"{where}.kind").strip().lower())
    if name is None:
        raise SpecError(
            f"{where}: unknown equipment kind {value!r}{suggest(str(value), _CLASSES)}; "
            f"available kinds: {sorted(_CLASSES)}"
        )
    if name == "Instrument":
        raise SpecError(
            f"{where}: instruments go in the top-level 'instruments:' section, not in "
            "'units:'; that is where their tag (type/number) and attachment "
            "(on/at/offset/angle) live"
        )
    return _CLASSES[name]


# Reading: spec -> Flowsheet

_TOP_KEYS = {
    "name", "stream_naming_scheme", "stream_number_start",
    "line_numbering_scheme", "line_number_start", "loop_number_start",
    "valve_station_tag_scheme", "auto_faces", "components", "units", "loops",
    "instruments", "streams", "stations", "packages", "stream_table_sections",
    "stream_table", "stream_labels", "title_block", "annotations",
}
# Sheet settings: Flowsheet keyword and spec key, default, reader.
_SHEET_SETTINGS: tuple[tuple[str, Any, Callable[[Any, str], Any]], ...] = (
    ("stream_naming_scheme", "S{n}", _text),
    ("stream_number_start", DEFAULT_STREAM_NUMBER_START, _integer),
    ("line_numbering_scheme", DEFAULT_LINE_NUMBERING_SCHEME, _text),
    ("line_number_start", DEFAULT_LINE_NUMBER_START, _integer),
    ("loop_number_start", DEFAULT_LOOP_NUMBER_START, _integer),
    ("valve_station_tag_scheme", DEFAULT_VALVE_STATION_TAG_SCHEME, _text),
)
# Top-level keys refused with their own reason.
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
    "at", "face", "offset", "angle", "pin", "port_faces", "quadrants",
}
# The three ways an instrument entry names its anchor.
_ANCHOR_KEYS = ("sensing", "acting_on", "near")
# Keys of a balloon entry: an instrument entry's, less the tag and
# anchor, plus balloon_of.
_BALLOON_KEYS = ({"balloon_of"} | _INSTRUMENT_KEYS) - {"type", "number", *_ANCHOR_KEYS}
# quadrants: key -> ISO quadrant letter; keys match Instrument.annotate.
_QUADRANT_KEYS = {"safety": "a", "variable": "b", "high": "c", "low": "d"}
_LOOP_KEYS = {"variable", "number"}
_PACKAGE_KEYS = {"name", "units", "description", "reference"}
_STREAM_KEYS = {
    "from", "to", "kind", "name", "draw_as_recycle", "properties", "tabulate", "via",
    "color", "dasharray", "ends", "inline_at", "logical_to",
    *LINE_NUMBER_FIELDS,
}
_COMPONENT_KEYS = {"name", "formula"}
# Constructor keywords only some classes take, and their readers.
_KIND_READERS: dict[str, Callable[[Any, str], Any]] = {
    "n_inlets": _integer, "n_outlets": _integer, "n_feeds": _integer, "n_draws": _integer,
    "length": _number, "diameter": _number,
    "normal_position": _text, "fail": _text, "branch": _text, "large_end": _text,
    "header": _flag, "inputs": _faces, "outputs": _faces,
    "feed_stages": _stages, "draw_stages": _stages,
    "manholes": _walls, "sockets": _walls,
}
# Each class's constructor keywords.
_TAKES = {cls: inspect.signature(cls).parameters.keys() for cls in _CLASSES.values()}
# Each keyword's owners: the classes that take it where no base class does.
_KIND_OWNERS = {
    key: tuple(sorted(
        name for name, cls in _CLASSES.items()
        if key in _TAKES[cls]
        and not any(key in _TAKES.get(base, ()) for base in cls.__mro__[1:])
    ))
    for key in _KIND_READERS
}
# Order along a face, applied with order_on after construction.
_KIND_ORDER = {
    "port_order": ("Block", "Tank", "Vessel"),
}
# Composition keywords from each declaring class's Unit.COMPOSITION.
_KIND_COMPOSITION: dict[str, tuple[str, ...]] = {}
for _name, _cls in _CLASSES.items():
    for _key in _cls.__dict__.get("COMPOSITION", {}):
        _KIND_COMPOSITION[_key] = tuple(sorted((*_KIND_COMPOSITION.get(_key, ()), _name)))
# Every class-specific key a unit entry may carry beyond _UNIT_KEYS.
_KIND_KEYS = {**_KIND_OWNERS, **_KIND_ORDER, **_KIND_COMPOSITION}


def from_dict(spec: Mapping[str, Any]) -> Flowsheet:
    """Build a :class:`~pandid.flowsheet.Flowsheet` from a spec.

    Parameters
    ----------
    spec : Mapping[str, Any]
        Declarative flowsheet data.

    Returns
    -------
    Flowsheet
        The connected sheet.

    Raises
    ------
    SpecError
        If an entry is invalid; the message names it.
    TypeError
        If an annotation ``type`` is unhashable.
    ValueError
        If ``stream_naming_scheme`` cannot format a stream number.
    """
    where = "the flowsheet spec"
    data = _mapping(spec, where)
    for key, why in _RETIRED_KEYS.items():
        if key in data:
            raise SpecError(f"{where}: {key!r} is no longer part of the spec: {why}; remove it")
    _check_keys(data, _TOP_KEYS, where)
    if "name" not in data:
        raise SpecError(f"{where} needs a 'name' (the flowsheet's title)")

    fs = Flowsheet(
        _drawn(data["name"], f"{where}: 'name'"),
        **{key: read(data.get(key, default), f"{where}: {key!r}")
           for key, default, read in _SHEET_SETTINGS},
        auto_faces=_flag(data.get("auto_faces", True), f"{where}: 'auto_faces'"),
    )

    for i, entry in enumerate(_sequence(data.get("components", []), "components")):
        fs.add_component(_read_component(entry, f"components[{i}]"))

    for i, entry in enumerate(_sequence(data.get("units", []), "units")):
        _read_unit(fs, entry, f"units[{i}]")

    for i, entry in enumerate(_sequence(data.get("loops", []), "loops")):
        _read_loop(fs, entry, f"loops[{i}]")
    # Continue loop numbering after the numbers the file used.
    fs._resume_loop_numbering()

    # Create instruments before the streams; attach them after.
    pending = []
    for i, entry in enumerate(_sequence(data.get("instruments", []), "instruments")):
        where_i = f"instruments[{i}]"
        mapping = _mapping(entry, where_i)
        # Attach a balloon to its element at once.
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
        with _blame(where_i):
            fs._set_inline_at(stream, _number(value, where_i))

    from pandid.inline import restore_logical_run
    for stream, value, where_i in pending_logical:
        endpoint = _read_endpoint(fs, value, where_i)
        with _blame(where_i):
            restore_logical_run(fs, stream, endpoint)

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

    for i, entry in enumerate(_sequence(data.get("packages", []), "packages")):
        _read_package(fs, entry, f"packages[{i}]")

    sections = []
    for i, entry in enumerate(_sequence(data.get("stream_table_sections", []),
                                        "stream_table_sections")):
        where_i = f"stream_table_sections[{i}]"
        pair = _sequence(entry, where_i)
        if len(pair) != 2:
            raise SpecError(
                f"{where_i}: a section is [before_key, heading] (the property row the heading "
                f"is injected above), got {pair!r}"
            )
        # The key is matched against property names; the heading is drawn.
        sections.append((_text(pair[0], f"{where_i}[0]"), _drawn(pair[1], f"{where_i}[1]")))
    fs.stream_table_sections = sections
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
    """Read one ``components:`` entry: a name or a mapping.

    Parameters
    ----------
    entry : Any
        Name, or mapping with ``name`` and optional ``formula``.
    where : str
        Entry path for error messages.

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


def _read_unit(fs: Flowsheet, entry: Any, where: str) -> Unit:
    """Read one ``units:`` entry and add the unit to the sheet.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Any
        The ``units:`` entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    Unit
        The added unit.

    Raises
    ------
    SpecError
        If the entry is malformed or the class refuses a value.
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
        # Match by inheritance: a device class takes its base's keys.
        if any(issubclass(cls, _CLASSES[owner]) for owner in owners):
            allowed.add(key)
        elif key in data:
            named = [f"{'an' if kind[0] in 'AEIOU' else 'a'} {kind}"
                     for kind in (*owners, cls.__name__)]
            raise SpecError(
                f"{where}: only {' or '.join(named[:-1])} takes {key!r}, not {named[-1]}"
            )
    _check_keys(data, allowed, where)

    kwargs = _read_fields(data, where, (
        (("variant",), _text),
        (("description", "reference"), _drawn),
        (("width", "height"), _number),
        *(((key,), read) for key, read in _KIND_READERS.items()),
    ))
    # Composition parts; the class default decides each value's type.
    for key, default in cls.COMPOSITION.items():
        if key in data:
            kwargs[key] = _composed(data[key], default, f"{where}.{key}")
    # A block's box is checked against its faces, so size it after
    # nozzle() has moved them.
    size = ({axis: kwargs.pop(axis) for axis in ("width", "height") if axis in kwargs}
            if issubclass(cls, unit_types.Block) else {})
    with _blame(where):
        unit = cls(name, **kwargs)
    if size:
        if "port_faces" in data:
            _read_port_faces(unit, data["port_faces"], f"{where}.port_faces")
        for axis, value in size.items():
            with _blame(f"{where}.{axis}"):
                setattr(unit, axis, value)

    _read_common(fs, unit, data, where)
    # Order faces after _read_common has moved ports onto them.
    if "port_order" in data and isinstance(unit, (unit_types.Block, unit_types.Tank,
                                                   unit_types.Vessel)):
        for face, names in _mapping(data["port_order"], f"{where}.port_order").items():
            at = f"{where}.port_order.{face}"
            ports = [_find_port(unit, name, at) for name in _sequence(names, at)]
            with _blame(at):
                unit.order_on(_text(face, at), ports)
    return unit


# Station spacing keys and their defaults.
_STATION_SPACING = (
    ("gap", DEFAULT_GAP), ("bypass_rise", DEFAULT_BYPASS_RISE), ("drain_drop", DEFAULT_DRAIN_DROP),
)
_STATION_ROLES = (
    "control", "upstream_isolation", "downstream_isolation", "reduction", "expansion",
    "bypass", "upstream_drain", "downstream_drain",
)
_STATION_KEYS = {
    "members", "tees", "inlet", "outlet", "mirrored", "gap", "bypass_rise",
    "drain_drop", "bypass_over", "run", "at", *_STATION_ROLES,
}


def _read_station_assembly(fs: Flowsheet, entry: Any, where: str) -> None:
    """Read one ``stations:`` entry and register the station.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Any
        The ``stations:`` entry.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        If a key, member, wiring or placement option is invalid.
    """
    from pandid.stations import BYPASS_ANCHORS, StationAssembly, ValveStation
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
    station = ValveStation(**cast("dict[str, Any]", roles),
                           tees=tuple(cast(Tee, tee) for tee in tees), members=members,
                           inlet=inlet, outlet=outlet)
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
    if at is not None and (run is None or not 0 < at < 1):
        raise SpecError(f"{where}: an at fraction needs a run and lies strictly between 0 and 1")
    options = {key: _number(data[key], f"{where}.{key}") if key in data else default
               for key, default in _STATION_SPACING}
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

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Any
        The ``loops:`` entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    Loop
        The declared loop.

    Raises
    ------
    SpecError
        If ``variable`` is missing, a field is invalid, or the loop
        is refused.
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
    with _blame(where):
        return fs.add_loop(_text(data["variable"], f"{where}.variable"), number)


def _read_package(fs: Flowsheet, entry: Any, where: str) -> None:
    """Read one ``packages:`` entry and add the package.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Any
        The ``packages:`` entry.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        If ``name`` or ``units`` is missing, a field is invalid, or the
        package is refused.
    """
    data = _mapping(entry, where)
    _check_keys(data, _PACKAGE_KEYS, where)
    for key in ("name", "units"):
        if key not in data:
            raise SpecError(f"{where} needs {key!r}: a package is its tag and the units "
                            f"inside its frame, e.g. {{name: PK-301, units: [P-301A, F-301]}}")
    names = _sequence(data["units"], f"{where}.units")
    units = [_find_unit(fs, _text(n, f"{where}.units[{k}]"), f"{where}.units[{k}]")
             for k, n in enumerate(names)]
    with _blame(where):
        fs.package(_text(data["name"], f"{where}.name"), units,
                   description=_drawn(data.get("description"), f"{where}.description"),
                   reference=_drawn(data.get("reference"), f"{where}.reference"))


def _read_instrument(fs: Flowsheet, entry: Any, where: str) -> Instrument:
    """Read one ``instruments:`` entry and add it, unattached.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Any
        The ``instruments:`` entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    Instrument
        The added instrument.

    Raises
    ------
    SpecError
        If the entry is malformed or a value is refused.
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

    kwargs = _read_fields(data, where, ((("variant", "display"), _text),
                                        (("description", "reference"), _drawn),
                                        (("width", "height"), _number)))
    with _blame(where):
        inst = Instrument(type_, number, **kwargs)
    if "quadrants" in data:
        _annotate_instrument(inst, data["quadrants"], f"{where}.quadrants")
    _read_common(fs, inst, data, f"{where} {inst.name!r}")
    return inst


def _annotate_instrument(inst: Instrument, entry: Any, where: str) -> None:
    """Apply an instrument entry's ``quadrants:`` mapping.

    Parameters
    ----------
    inst : Instrument
        Instrument to annotate.
    entry : Any
        The ``quadrants:`` mapping.
    where : str
        Entry path for error messages.

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
    with _blame(where):
        inst.annotate(**codes)


def _read_common(fs: Flowsheet, unit: Unit, data: Mapping[str, Any], where: str) -> None:
    """Apply the shared unit fields and add the unit to the sheet.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    unit : Unit
        Unit to set up and add.
    data : Mapping[str, Any]
        The unit's entry.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        If a field is malformed or the unit is refused.
    """
    if "label_pos" in data:
        unit.label_pos = _text(data["label_pos"], f"{where}.label_pos")
    if "new_line_number" in data:
        unit.new_line_number = _flag(data["new_line_number"], f"{where}.new_line_number")
    with _blame(where):
        fs.add(unit)
    if "pin" in data:
        _read_pin(unit, data["pin"], f"{where}.pin")
    if "port_faces" in data:
        _read_port_faces(unit, data["port_faces"], f"{where}.port_faces")


def _read_balloon(fs: Flowsheet, entry: Mapping[str, Any], where: str) -> Instrument:
    """Read a ``balloon_of`` entry and add the element's balloon.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Mapping[str, Any]
        The ``balloon_of`` entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    Instrument
        The added balloon.

    Raises
    ------
    SpecError
        If a key or value is refused, or the element is not on sheet.
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
    kwargs.update(_read_fields(entry, where, ((("offset", "angle", "width", "height"), _number),
                                              (("face", "variant", "display", "label_pos"),
                                               _text),
                                              (("description", "reference"), _drawn))))
    # A text at: is a face, warned of once the entry is read.
    old = kwargs.pop("at") if isinstance(kwargs.get("at"), str) and "face" not in kwargs else None
    if old is not None:
        kwargs["face"] = old
    with _blame(where, (TypeError, ValueError)):
        inst = fs.add_balloon(element, **kwargs)
    # add_balloon added the balloon; set the remaining fields here.
    if "new_line_number" in entry:
        inst.new_line_number = _flag(entry["new_line_number"], f"{where}.new_line_number")
    if "quadrants" in entry:
        _annotate_instrument(inst, entry["quadrants"], f"{where}.quadrants")
    if "pin" in entry:
        _read_pin(inst, entry["pin"], f"{where}.pin")
    if "port_faces" in entry:
        _read_port_faces(inst, entry["port_faces"], f"{where}.port_faces")
    inst._deprecate_at(old, inst.face)
    return inst


def _read_pin(unit: Unit, entry: Any, where: str) -> None:
    """Apply a ``pin:`` mapping to a unit.

    Parameters
    ----------
    unit : Unit
        Unit to pin.
    entry : Any
        The ``pin:`` mapping.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        If the mapping is malformed or the pin is refused.
    """
    data = _mapping(entry, where)
    _check_keys(data, _PIN_KEYS, where)
    kwargs = _read_fields(data, where, ((("x", "y"), _number), (("col", "row"), _integer)))
    if "orientation" in data:
        kwargs["orientation"] = data["orientation"]
    if "mirrored" in data:
        kwargs["mirrored"] = data["mirrored"]
    ports = _read_pin_ports(unit, data.get("port"),
                            {a for a in ("x", "y") if a in kwargs},
                            {r for r in ("col", "row") if r in kwargs},
                            f"{where}.port")
    with _blame(where):
        # One pin() call for the corner axes, orientation, mirroring
        # and grid cells, then one per named port. port=None keeps an
        # unported coordinate a corner.
        unit.pin(port=None,
                 **{axis: value for axis, value in kwargs.items() if axis not in ports})
        for nozzle in dict.fromkeys(ports.values()):
            unit.pin(port=nozzle,
                     **{axis: kwargs[axis] for axis, p in ports.items() if p == nozzle})


def _read_pin_ports(unit: Unit, entry: Any, stated: set[str], ranks: set[str],
                    where: str) -> dict[str, str]:
    """Read a pin's ``port:`` key as ``{axis: port}``.

    Parameters
    ----------
    unit : Unit
        Unit that owns the ports.
    entry : Any
        ``None``, one port for every stated axis, or a mapping.
    stated : set[str]
        Pixel axes the pin states.
    ranks : set[str]
        Grid keys (``col``, ``row``) the pin states.
    where : str
        Entry path for error messages.

    Returns
    -------
    dict[str, str]
        Port name per pixel axis.

    Raises
    ------
    SpecError
        If the key is malformed, names an unknown port, or is refused.
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
    # _find_port creates pooled ports and names this key in an error.
    if isinstance(entry, str):
        _find_port(unit, entry, where)
        if (complaint := port_refusal(entry, ("x", "y"), stated, ranks, key)) is not None:
            raise SpecError(f"{where}: {complaint}")
        return dict.fromkeys(sorted(stated), entry)
    axes = _mapping(entry, where)
    _check_keys(axes, {"x", "y"}, where)
    if not axes:
        raise SpecError(f"{where} names no axis; give port: {{x: ...}} or drop port")
    named = {axis: _text(name, f"{where}.{axis}") for axis, name in sorted(axes.items())}
    for axis, name in named.items():
        _find_port(unit, name, f"{where}.{axis}")
    for axis, name in named.items():
        if (complaint := port_refusal(name, (axis,), stated, ranks, f"{key}.{axis}")) is not None:
            raise SpecError(f"{where}.{axis}: {complaint}")
    return named


def _read_port_faces(unit: Unit, entry: Any, where: str) -> None:
    """Apply a ``port_faces:`` mapping of port name to face.

    Parameters
    ----------
    unit : Unit
        Unit whose ports move.
    entry : Any
        The ``port_faces:`` mapping.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        If it is not a mapping, a port is unknown or a face is refused.
    """
    for port_name, face in _mapping(entry, where).items():
        _find_port(unit, port_name, where)
        with _blame(f"{where}.{port_name}"):
            unit.nozzle(port_name, _text(face, f"{where}.{port_name}"))


def _find_port(unit: Unit, name: Any, where: str) -> Port:
    """Return a unit's port by name or alias, creating pooled ports.

    Parameters
    ----------
    unit : Unit
        Unit to search.
    name : Any
        Port name or alias.
    where : str
        Entry path for error messages.

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
    if isinstance(name, str):
        name = unit._canonical_port_name(name)
    if not isinstance(name, str) or name not in unit.ports:
        raise SpecError(
            f"{where}: {type(unit).__name__} {unit.name!r} has no port {name!r}"
            f"{suggest(str(name), unit.ports)}; available ports: {sorted(unit.ports)}"
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
        Entry path for error messages.

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
        f"{where}: no unit named {name!r} on this flowsheet{suggest(str(name), names)}; "
        f"declared units: {sorted(names)}"
    )


def _read_endpoint(fs: Flowsheet, entry: Any, where: str) -> Port:
    """Read a stream endpoint, ``[unit, port]`` or ``{unit, port}``.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to search.
    entry : Any
        The endpoint.
    where : str
        Entry path for error messages.

    Returns
    -------
    Port
        The named port.

    Raises
    ------
    SpecError
        If it is malformed or names an unknown unit or port.
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

    Parameters
    ----------
    fs : Flowsheet
        Sheet to read into.
    entry : Any
        The ``streams:`` entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    Stream
        The connected stream.

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
    kwargs = _read_fields(data, where, ((("kind", "name"), _text),
                                        (("draw_as_recycle",), _flag)))
    if "ends" in data:
        ends = data["ends"]
        if isinstance(ends, (list, tuple)) and len(ends) == 2:
            ends = (_text(ends[0], f"{where}.ends[0]"), _text(ends[1], f"{where}.ends[1]"))
        elif not isinstance(ends, str):
            raise SpecError(
                f"{where}.ends must be a connection name for both ends or a two-item "
                f"[source, dest] list, got {ends!r}"
            )
        kwargs["ends"] = ends
    kwargs.update(_read_fields(data, where, ((LINE_NUMBER_FIELDS, _component),)))
    with _blame(where):
        stream = fs.connect(src, dst, **kwargs)

    for key in ("color", "dasharray"):
        if key in data:
            setattr(stream, key, _text(data[key], f"{where}.{key}"))
    if "properties" in data:
        properties = _mapping(data["properties"], f"{where}.properties")
        for key, value in properties.items():
            if not _shown(value):
                raise SpecError(
                    f"{where}.properties[{key!r}] must be text or a number (values carry "
                    f"their own units, e.g. '25 C'), got {value!r}"
                )
        stream.properties = dict(properties)
    if "tabulate" in data:
        stream.tabulate = _flag(data["tabulate"], f"{where}.tabulate")
    if "via" in data:
        points = []
        for i, item in enumerate(_sequence(data["via"], f"{where}.via")):
            at = f"{where}.via[{i}]"
            pair = _sequence(item, at)
            if len(pair) != 2:
                raise SpecError(f"{at}: a waypoint is [x, y], got {pair!r}")
            points.append((_number(pair[0], f"{at}.x"), _number(pair[1], f"{at}.y")))
        stream.via(points)
    return stream


def _read_host(fs: Flowsheet, entry: Any, where: str) -> Stream | Unit:
    """Return the unit or stream an instrument entry names.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to search.
    entry : Any
        Unit or stream name, or a ``[unit, port]`` endpoint.
    where : str
        Entry path for error messages.

    Returns
    -------
    Stream or Unit
        The host.

    Raises
    ------
    SpecError
        If it names nothing, a unit and a stream, or an unwired port.
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
            f"{where}: nothing named {entry!r} to attach to{suggest(str(entry), names)}; "
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
    """Attach an instrument to the host its entry names, if any.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to search.
    inst : Instrument
        Instrument to attach.
    data : Mapping[str, Any]
        The instrument's entry.
    where : str
        Entry path for error messages.

    Raises
    ------
    SpecError
        If the anchor keys or host are invalid, or attaching fails.
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
        stray = [key for key in ("at", "face", "offset", "angle") if key in data]
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
    kwargs.update(_read_fields(data, where, ((("offset", "angle"), _number),
                                             (("face",), _text))))
    with _blame(where, (TypeError, ValueError)):
        inst.attach(host, **kwargs)


def _read_stream_table(entry: Any, where: str) -> StreamTableOptions:
    """Read ``stream_table:``, the table's drawing options.

    Parameters
    ----------
    entry : Any
        The ``stream_table:`` mapping.
    where : str
        Entry path for error messages.

    Returns
    -------
    StreamTableOptions
        The options.

    Raises
    ------
    SpecError
        If it is not a mapping, a key is unknown, or a value has the
        wrong type or is not finite.
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

    Parameters
    ----------
    entry : Any
        The ``stream_labels:`` mapping.
    where : str
        Entry path for error messages.

    Returns
    -------
    StreamLabelOptions
        The options.

    Raises
    ------
    SpecError
        If it is not a mapping, has an unknown key or a bad enclosure.
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

    Parameters
    ----------
    entry : Any
        The ``title_block:`` mapping.
    where : str
        Entry path for error messages.

    Returns
    -------
    TitleBlock
        The title block.

    Raises
    ------
    SpecError
        If it is not a mapping, a key is unknown or a revision is bad.
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


#: Deprecation of the equipment table's old box type.
_EQUIPMENT_LIST_TYPE = Deprecation(
    what="type: equipment_list",
    instead="type: equipment_table",
    removed_in="0.4.0",
)

_ANNOTATION_KEYS = {
    "annotation": {"type", "title", "rows", "align", "position", "margin", "width", "font_size"},
    "table": {"type", "title", "headers", "rows", "align", "position", "margin", "font_size",
              "col_align"},
    "equipment_table": {"type", "title", "align", "position", "margin", "width", "include"},
    "equipment_list": {"type", "title", "align", "position", "margin", "width", "include"},
    "notes": {"type", "title", "items", "align", "position", "margin", "width", "numbered"},
    "legend": {"type", "title", "entries", "align", "position", "margin", "width"},
}


def _read_placement(data: Mapping[str, Any], where: str) -> dict[str, Any]:
    """Read the placement and size keys shared by every box.

    Parameters
    ----------
    data : Mapping[str, Any]
        The box's entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    dict[str, Any]
        Box keyword arguments for the keys present.

    Raises
    ------
    SpecError
        If a value has the wrong type or is not finite, or
        ``position`` is not a pair.
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
    out.update(_read_fields(data, where, ((("margin", "width", "font_size"), _number),)))
    return out


def _read_annotation(fs: Flowsheet, entry: Any, where: str) -> Annotation | TableBox:
    """Read one ``annotations:`` entry.

    Parameters
    ----------
    fs : Flowsheet
        Sheet an equipment table reads.
    entry : Any
        The ``annotations:`` entry.
    where : str
        Entry path for error messages.

    Returns
    -------
    Annotation or TableBox
        The box.

    Raises
    ------
    SpecError
        If the type or a key is unknown, or a value is refused.
    TypeError
        If an annotation ``type`` is unhashable.
    """
    data = _mapping(entry, where)
    kind = data.get("type", "annotation")
    if kind not in _ANNOTATION_KEYS:
        raise SpecError(
            f"{where}: unknown box type {kind!r}{suggest(str(kind), _ANNOTATION_KEYS)}; "
            f"available types: {sorted(_ANNOTATION_KEYS)}"
        )
    _check_keys(data, _ANNOTATION_KEYS[kind], where)
    kwargs = _read_placement(data, where)
    if "title" in data:
        kwargs["title"] = _text(data["title"], f"{where}.title")

    try:
        if kind in ("equipment_table", "equipment_list"):
            include = data.get("include")
            if include is not None:
                include = [_text(t, f"{where}.include") for t in _sequence(include,
                                                                          f"{where}.include")]
            box = equipment_table(fs, include=include, **kwargs)
            if kind == "equipment_list":
                _EQUIPMENT_LIST_TYPE.warn(fs, where=where)
            return box
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
                     else [tuple(_sequence(e, f"{where}.entries[{i}]"))
                           for i, e in enumerate(_sequence(entries, f"{where}.entries"))])
            for i, pair in enumerate(pairs):
                if len(pair) != 2:
                    raise SpecError(
                        f"{where}.entries[{i}] must have two items, an abbreviation "
                        f"and its meaning, got {list(pair)!r}"
                    )
            # Entries are drawn text.
            return legend([(_drawn(abbreviation, f"{where}.entries[{i}][0]"),
                            _drawn(meaning, f"{where}.entries[{i}][1]"))
                           for i, (abbreviation, meaning) in enumerate(pairs)], **kwargs)
        if kind == "table":
            if "headers" in data:
                kwargs["headers"] = [_drawn(h, f"{where}.headers")
                                     for h in _sequence(data["headers"], f"{where}.headers")]
            if "col_align" in data:
                kwargs["col_align"] = [_text(a, f"{where}.col_align")
                                       for a in _sequence(data["col_align"], f"{where}.col_align")]
            kwargs["rows"] = [[_drawn(cell, f"{where}.rows[{i}][{j}]")
                               for j, cell in enumerate(_sequence(row, f"{where}.rows[{i}]"))]
                              for i, row in enumerate(_sequence(data.get("rows", []),
                                                                f"{where}.rows"))]
            return TableBox(**kwargs)
        rows: list = []
        for i, row in enumerate(_sequence(data.get("rows", []), f"{where}.rows")):
            if isinstance(row, (list, tuple)):
                cells = _sequence(row, f"{where}.rows[{i}]")
                rows.append(tuple(_drawn(c, f"{where}.rows[{i}][{j}]")
                                  for j, c in enumerate(cells)))
            else:
                rows.append(_drawn(row, f"{where}.rows[{i}]"))
        kwargs["rows"] = rows
        return Annotation(**kwargs)
    except SpecError:
        raise  # already carries its own path
    except ValueError as e:
        raise _fail_from(e, where) from None  # e.g. a bad align=


# Writing: Flowsheet -> spec

_MIRROR_NAMES = {(True, False): "x", (False, True): "y", (True, True): "xy"}


def to_dict(fs: Flowsheet) -> dict:
    """Write a flowsheet as a spec that :func:`from_dict` reads back.

    It writes author intent only, and leaves out most default values.

    Parameters
    ----------
    fs : Flowsheet
        Sheet to write.

    Returns
    -------
    dict
        The spec.

    Raises
    ------
    SpecError
        If a naming scheme is callable or a unit class is not built in.
    ValueError
        If the stream-label enclosure is unknown.
    """
    spec: dict[str, Any] = {"name": fs.name}
    for key, default, read in _SHEET_SETTINGS:
        value = getattr(fs, key)
        # The schemes are the text settings; only a format string is written.
        if read is _text and not isinstance(value, str):
            raise SpecError(f"a callable {key} cannot be written to a spec; use a format "
                            f"string such as {default!r}")
        if value != default:
            spec[key] = value
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
    if fs.packages:
        spec["packages"] = [{"name": p.name, "units": [u.name for u in p.units],
                             **{key: getattr(p, key) for key in ("description", "reference")
                                if getattr(p, key)}}
                            for p in fs.packages]
    if fs.stream_table_sections:
        spec["stream_table_sections"] = [list(sec) for sec in fs.stream_table_sections]
    table = {f.name: getattr(fs.stream_table, f.name)
             for f in dataclass_fields(StreamTableOptions)
             if getattr(fs.stream_table, f.name) != f.default}
    if table:
        spec["stream_table"] = table
    labels = {f.name: getattr(fs.stream_labels, f.name)
              for f in dataclass_fields(StreamLabelOptions)
              if getattr(fs.stream_labels, f.name) != f.default}
    if labels:
        _resolve_enclosure(fs.stream_labels.enclosure)
        spec["stream_labels"] = labels
    if fs.title_block is not None:
        block = spec["title_block"] = _stated_text(fs.title_block)
        if fs.title_block.revisions:
            block["revisions"] = [_stated_text(rev) for rev in fs.title_block.revisions]
    if fs.annotations:
        spec["annotations"] = [_write_annotation(a) for a in fs.annotations]
    return spec


def _write_common(unit: Unit, entry: dict[str, Any]) -> dict[str, Any]:
    """Write the shared unit fields that differ from their defaults.

    Parameters
    ----------
    unit : Unit
        Unit to write.
    entry : dict[str, Any]
        Entry to add the fields to.

    Returns
    -------
    dict[str, Any]
        The same entry.
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
    """Write composition parts that differ from their defaults.

    Parameters
    ----------
    unit : Unit
        Unit to write.
    entry : dict[str, Any]
        Entry to add the parts to.

    Returns
    -------
    dict[str, Any]
        The same entry.
    """
    cls = type(unit)
    stated = {key: getattr(unit, key) for key in cls.COMPOSITION}
    for key, default in cls.composition_defaults(unit.variant, stated).items():
        value = getattr(unit, key)
        if value != default:
            entry[key] = value
    # Drop the variant when the keyword folded into it is written.
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
        Entry to add the pin and faces to.

    Returns
    -------
    dict[str, Any]
        The same entry.
    """
    if unit.pin_ is not None:
        pin: dict[str, Any] = {}
        # Write each stated coordinate and the port it was measured to.
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
        if unit._turn_stated or unit.pin_.orientation:
            pin["orientation"] = int(unit.pin_.orientation)
        mirror = _MIRROR_NAMES.get((unit.pin_.mirrored, unit.pin_.mirror_y))
        if mirror or unit._mirror_stated:
            pin["mirrored"] = mirror or False
        entry["pin"] = pin
    if unit._port_faces:
        entry["port_faces"] = {**entry.get("port_faces", {}), **unit._port_faces}
    return entry


def _write_connection_faces(unit, entry: dict[str, Any],
                            omit_bare_single: bool = False) -> None:
    """Write a Block, Tank or Vessel's faces and ``port_order``.

    A family declared by a list is written as its faces, and one
    declared by a count as the count, with each face ``nozzle()`` moved
    under ``port_faces``.

    Parameters
    ----------
    unit : Block, Tank or Vessel
        Unit to write.
    entry : dict[str, Any]
        Entry to add the keys to.
    omit_bare_single : bool, default=False
        Omit a key for a single counted connection.
    """
    for key, family in (("inputs", unit.inlets), ("outputs", unit.outlets)):
        if any(port.name in unit._listed for port in family):
            entry[key] = [unit._faces[port.name] for port in family]
        elif not (omit_bare_single and len(family) == 1):
            entry[key] = len(family)
    moved = {name: face for name, face in unit._faces.items()
             if name in unit._stated and name not in unit._listed}
    if moved:
        entry["port_faces"] = {**entry.get("port_faces", {}), **moved}
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
        Unit to write.

    Returns
    -------
    dict[str, Any]
        The entry.

    Raises
    ------
    SpecError
        If the unit's class is not built in.
    """
    kind = type(unit).__name__
    if kind not in _CLASSES:
        raise SpecError(
            f"{unit.name!r} is a {kind}, which is not one of the built-in equipment "
            f"classes, so it cannot be written to a spec; available kinds: {sorted(_CLASSES)}"
        )
    # Write the tag; a tee has none, so write its name.
    entry: dict[str, Any] = {"kind": kind, "name": unit.tag or unit.name}
    _write_common(unit, entry)
    _write_composition(unit, entry)
    if isinstance(unit, (unit_types.Vessel, unit_types.Evaporator)):
        for key, places in (("manholes", unit.manholes), ("sockets", unit.sockets)):
            if places:
                entry[key] = [list(place) for place in places]
    # One feed is the default.
    if (any(issubclass(type(unit), _CLASSES[owner]) for owner in _KIND_OWNERS["n_feeds"])
            and len(getattr(unit, "feeds")) > 1):
        entry["n_feeds"] = len(getattr(unit, "feeds"))
    if isinstance(unit, unit_types.Block):
        _write_connection_faces(unit, entry)
    elif isinstance(unit, (unit_types.Tank, unit_types.Vessel)):
        _write_connection_faces(unit, entry, omit_bare_single=True)
    elif isinstance(unit, unit_types.Mixer):
        entry["n_inlets"] = len(unit.inlets)
    elif isinstance(unit, unit_types.Splitter):
        entry["n_outlets"] = len(unit.outlets)
    elif isinstance(unit, unit_types.Column):
        if unit.feed_stages is not None:
            entry["feed_stages"] = list(unit.feed_stages)
        if len(unit.draws) > 0:
            entry["n_draws"] = len(unit.draws)
        if unit.draw_stages is not None:
            entry["draw_stages"] = list(unit.draw_stages)
    elif isinstance(unit, unit_types.Tee):
        # A takeoff is the default.
        if unit.branch_direction != "outlet":
            entry["branch"] = unit.branch_direction
    elif isinstance(unit, unit_types.Reducer):
        # A reduction is the default.
        if unit.large_end != "inlet":
            entry["large_end"] = unit.large_end
    elif isinstance(unit, unit_types.Conveyor):
        entry["length"] = unit.length
        if unit.diameter != unit.default_diameter():
            entry["diameter"] = unit.diameter
    elif isinstance(unit, unit_types._NormallyPositioned):
        if unit.normal_position != "open":
            entry["normal_position"] = unit.normal_position
        fail = getattr(unit, "fail", "")
        if fail:
            entry["fail"] = fail
    elif isinstance(unit, _Boundary):
        if unit.header:
            entry["header"] = True
    return _write_placement(unit, entry)


def _write_instrument(inst: Instrument) -> dict[str, Any]:
    """Write one ``instruments:`` entry.

    Parameters
    ----------
    inst : Instrument
        Instrument or balloon to write.

    Returns
    -------
    dict[str, Any]
        The entry.
    """
    entry: dict[str, Any] = (
        {"balloon_of": inst._marks.name} if inst._marks is not None
        else {"type": inst.type, "number": inst.number}
    )
    _write_common(inst, entry)
    # Replace the registry variant with the symbol type.
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
        if inst._face_stated:
            entry["face"] = inst.face
        if inst.offset != 46.0:
            entry["offset"] = inst.offset
        if inst.angle != 90.0:
            entry["angle"] = inst.angle
        return _write_placement(inst, entry)
    if inst.host is not None:
        # Name a stream by its source port.
        entry[inst.relation] = (
            [inst.host.source.owner.name, inst.host.source.name]
            if isinstance(inst.host, Stream) else inst.host.name
        )
        if isinstance(inst.host, Stream):
            entry["at"] = inst.at
        elif inst._face_stated:
            entry["face"] = inst.face
        if inst.offset != 45.0:
            entry["offset"] = inst.offset
        if inst.angle != 90.0:
            entry["angle"] = inst.angle
    return _write_placement(inst, entry)


def _write_station_assembly(fs: Flowsheet, assembly) -> dict[str, Any]:
    """Write one ``stations:`` entry.

    Parameters
    ----------
    fs : Flowsheet
        Sheet whose streams index the run.
    assembly : StationAssembly
        Station to write.

    Returns
    -------
    dict[str, Any]
        The entry.
    """
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
    for key, default in _STATION_SPACING:
        value = getattr(assembly, key)
        if value != default:
            entry[key] = value
    if assembly.bypass_over is not None:
        entry["bypass_over"] = assembly.bypass_over
    if assembly.run is not None:
        entry["run"] = next(i for i, stream in enumerate(fs.streams)
                            if stream is assembly.run)
        if assembly.at is not None:
            entry["at"] = assembly.at
    return entry


def _write_stream(stream: Stream) -> dict[str, Any]:
    """Write one ``streams:`` entry.

    Parameters
    ----------
    stream : Stream
        Stream to write.

    Returns
    -------
    dict[str, Any]
        The entry.
    """
    entry: dict[str, Any] = {
        "from": [stream.source.owner.name, stream.source.name],
        "to": [stream.dest.owner.name, stream.dest.name],
    }
    # Write kind when it differs from the one connect() infers.
    if stream.kind != _inferred_kind(stream.source, stream.dest):
        entry["kind"] = stream.kind
    if not stream.auto_named:
        entry["name"] = stream.name
    if stream.draw_as_recycle:
        entry["draw_as_recycle"] = True
    for key in LINE_NUMBER_FIELDS:
        value = getattr(stream, key)
        if value is not None and not (key == "sequence" and value == stream._auto_sequence):
            entry[key] = value
    for key in ("color", "dasharray"):
        if getattr(stream, key) is not None:
            entry[key] = getattr(stream, key)
    if stream.ends is not None:
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
    """Return the drawn-text fields that differ from their defaults.

    Parameters
    ----------
    obj : TitleBlock or Revision
        Object to read.

    Returns
    -------
    dict[str, Any]
        Value per changed field.
    """
    text = _drawn_text_fields(type(obj))
    return {f.name: getattr(obj, f.name) for f in dataclass_fields(type(obj))
            if f.name in text and getattr(obj, f.name) != f.default}


def _write_annotation(box: Annotation | TableBox) -> dict[str, Any]:
    """Write one ``annotations:`` entry, as a table or annotation.

    Parameters
    ----------
    box : Annotation or TableBox
        Box to write.

    Returns
    -------
    dict[str, Any]
        The entry.
    """
    entry: dict[str, Any] = {"type": "table" if isinstance(box, TableBox) else "annotation"}
    # Write any title but the default, falsy ones included.
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
    width = getattr(box, "width", None)  # only Annotation has a width
    if width is not None:
        entry["width"] = width
    if box.font_size != 11.0:
        entry["font_size"] = box.font_size
    return entry


# File loaders


def from_json(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a JSON spec file.

    Parameters
    ----------
    path : str or Path
        JSON file.

    Returns
    -------
    Flowsheet
        The sheet.

    Raises
    ------
    OSError
        If the file cannot be read.
    SpecError
        If the file is not valid JSON or the spec is invalid.
    TypeError
        If an annotation ``type`` is unhashable.
    ValueError
        If the file is not UTF-8 or ``stream_naming_scheme`` is invalid.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text, object_pairs_hook=_unique_keys)
    except json.JSONDecodeError as e:
        raise SpecError(f"{path}: not valid JSON, {e.msg} at line {e.lineno}, column {e.colno}")
    except SpecError as e:
        raise SpecError(f"{path}: {e}") from None
    return from_dict(data)


def _written_twice(key: Any, line: int | None = None) -> SpecError:
    """Return the error for a key written twice in one mapping.

    Parameters
    ----------
    key : Any
        Repeated key.
    line : int or None, optional
        Line of the repeat.

    Returns
    -------
    SpecError
        The error naming the key.
    """
    at = "" if line is None else f" (line {line})"
    return SpecError(
        f"{key!r} is written twice in one mapping{at}; only one value can be "
        f"kept, so delete the other"
    )


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object from its pairs, refusing a repeated key.

    Parameters
    ----------
    pairs : list[tuple[str, Any]]
        Key-value pairs of one object.

    Returns
    -------
    dict[str, Any]
        The object.

    Raises
    ------
    SpecError
        If a key appears twice.
    """
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise _written_twice(key)
        data[key] = value
    return data


@cache
def _core_schema_loader() -> Any:
    """Return the cached safe YAML loader for spec files.

    Untagged booleans are ``true`` or ``false`` in lower, title or
    upper case, untagged integers are decimal with no leading zero,
    and floats follow the YAML 1.2 core schema; ``0101`` and
    ``0x1F`` stay text.

    Returns
    -------
    type
        The ``SafeLoader`` subclass.
    """
    import yaml

    dropped = {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp",
               "tag:yaml.org,2002:int", "tag:yaml.org,2002:float"}

    class Loader(yaml.SafeLoader):
        """Safe loader with YAML 1.2 booleans and numbers."""

        def flatten_mapping(self, node):
            """Refuse a repeated key but ``<<``, then merge.

            Parameters
            ----------
            node : yaml.MappingNode
                Mapping node to check.

            Raises
            ------
            SpecError
                If a key other than ``<<`` is written twice.
            """
            checked = self.__dict__.setdefault("_checked", set())
            # Check each node once, before merging rewrites it.
            if node not in checked:
                checked.add(node)
                seen = set()
                for key_node, _value in node.value:
                    if key_node.tag == "tag:yaml.org,2002:merge":
                        continue
                    key = self.construct_object(key_node)
                    try:
                        repeated = key in seen
                    except TypeError:
                        # Leave an unhashable key to the base class.
                        continue
                    if repeated:
                        raise _written_twice(key, key_node.start_mark.line + 1)
                    seen.add(key)
            super().flatten_mapping(node)

    Loader.yaml_implicit_resolvers = {
        char: [(tag, pattern) for tag, pattern in resolvers if tag not in dropped]
        for char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    Loader.add_implicit_resolver(
        "tag:yaml.org,2002:bool",
        re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
        list("tTfF"),
    )
    # Decimal integers only.
    Loader.add_implicit_resolver(
        "tag:yaml.org,2002:int",
        re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$"),
        list("-+0123456789"),
    )
    # YAML 1.2 core-schema floats, less bare digit strings: ``0101``
    # stays text; ``1e3`` and ``.5`` are floats.
    Loader.add_implicit_resolver(
        "tag:yaml.org,2002:float",
        re.compile(r"^(?:(?![-+]?[0-9]+$)[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)"
                   r"(?:[eE][-+]?[0-9]+)?"
                   r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"),
        list("-+0123456789."),
    )
    return Loader


def from_yaml(path: str | Path) -> Flowsheet:
    """Build a flowsheet from a YAML spec file.

    Parameters
    ----------
    path : str or Path
        YAML file.

    Returns
    -------
    Flowsheet
        The sheet.

    Raises
    ------
    ImportError
        If PyYAML is not installed.
    OSError
        If the file cannot be read.
    SpecError
        If the file is not valid YAML, is empty, or the spec is invalid.
    TypeError
        If an annotation ``type`` is unhashable.
    ValueError
        If the file is not UTF-8 or ``stream_naming_scheme`` is invalid.
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
        data = yaml.load(text, Loader=_core_schema_loader())
    except yaml.YAMLError as e:
        raise SpecError(f"{path}: not valid YAML, {e}") from None
    except SpecError as e:
        raise SpecError(f"{path}: {e}") from None
    if data is None:
        raise SpecError(f"{path} is empty; a spec needs at least a 'name'")
    return from_dict(data)
