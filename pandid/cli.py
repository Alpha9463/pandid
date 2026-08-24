"""The ``pandid`` command line.

:mod:`pandid.spec` already reads an entire flowsheet from a YAML or JSON
file, so the only thing left between an equipment list and a drawing is
a Python prompt. This module removes it. It is a shell over the public
API and knows nothing about drawing: it reads the spec, calls the
methods a script would call, and turns whatever the engine raises into
one line on stderr and an exit code a shell can gate on.

    pandid draw plant.yaml -o plant.pdf --page-size A3 --border zone
    pandid validate plant.yaml
    pandid symbols --kind valve

The exit codes are the interface a script sees, so they distinguish the
three things that can go wrong rather than all reporting 1:

===== ============================================================
``0`` the command did what it was asked
``1`` the flowsheet was rejected: the spec could not be read, or
      validation found errors, or the engine refused the request
      (an unknown page size, a page too small for its furniture)
``2`` the command line was wrong: an unknown flag, a missing
      argument, an option value this module checks itself
``3`` an optional extra is not installed (PyYAML to read a YAML
      spec, the ``pdf`` extra to write a PDF or a PNG)
===== ============================================================
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from pandid import __version__, spec, units
from pandid.flowsheet import Flowsheet
from pandid.render.svg import TABLE_SHEET

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_MISSING_DEPENDENCY = 3


class _Failure(Exception):
    """Something wrong, and the code to report it under."""

    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.code = code


def _note(message: str) -> None:
    """Write to stderr, behind whatever is queued on stdout.

    The two streams are buffered differently once either is a pipe, so
    without the flush a note lands above the line it is about.
    """
    sys.stdout.flush()
    print(message, file=sys.stderr)


def _fail(message: str, code: int) -> int:
    _note(f"error: {message}")
    return code


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _fold(name: str) -> str:
    """``HeatExchanger``, ``heat_exchanger``, ``hex``: one way."""
    return name.lower().replace("_", "").replace("-", "")


def _suggest(value: str, candidates: Sequence[str]) -> str:
    close = difflib.get_close_matches(_fold(value), [_fold(c) for c in candidates], n=1, cutoff=0.6)
    if not close:
        return ""
    match = next(c for c in candidates if _fold(c) == close[0])
    return f" (did you mean {match!r}?)"


# --------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------


def _load(path: Path) -> Flowsheet:
    """Read a spec file, choosing the reader from its extension."""
    suffix = path.suffix.lower()
    if suffix not in (".yaml", ".yml", ".json"):
        named = repr(suffix) if suffix else "a file with no extension"
        raise _Failure(
            f"{path}: cannot read a spec from {named}; write it as .yaml, .yml or .json")
    # Open the file *before* the extension picks a reader.
    # ``spec.from_yaml`` imports PyYAML before it opens anything, so on a
    # machine without the optional extra a path that is simply not there
    # was reported as a dependency problem and exited 3 -- the code this
    # module's docstring reserves for an extra that is not installed --
    # while the same missing path spelled .json exited 1. The file is the
    # earlier question and is asked first; the extra is only a problem
    # once there is something to read with it.
    #
    # Nothing on the dev box or in CI sees this, because both have
    # PyYAML: ``tests/test_cli`` blocks the import to reach it.
    with path.open("rb"):
        pass
    if suffix == ".json":
        return spec.from_json(path)
    return spec.from_yaml(path)


def _draw(args: argparse.Namespace) -> int:
    fs = _load(args.spec)
    out = args.output if args.output is not None else args.spec.with_suffix(".svg")
    fs.render(
        out,
        page_size=args.page_size,
        border=args.border,
        diagram=args.diagram,
        connections=args.connections,
        show_stream_table=args.stream_table,
        jump_direction=args.jump_direction,
        debug=args.debug if args.debug is not None else False,
    )
    sheet = f"{args.page_size.upper()}, " if args.page_size else ""
    print(
        f"wrote {out}  ({sheet}{_plural(len(fs.units), 'unit')}, "
        f"{_plural(len(fs.streams), 'stream')})"
    )
    if fs.warnings:
        # The drawing is made either way; say where to read what was
        # flagged -- and name the drawing that was made, since one
        # finding depends on it and a bare `pandid validate` would answer
        # about a PFD.
        sheet = f" --diagram '{args.diagram}'" if args.diagram != "pfd" else ""
        _note(f"{_plural(len(fs.warnings), 'warning')}; "
              f"see: pandid validate{sheet} {args.spec}")
    return EXIT_OK


def _validate(args: argparse.Namespace) -> int:
    fs = _load(args.spec)
    # Lay the sheet out first: the geometric checks have nothing to
    # measure until every unit has a frame, so validating a freshly read
    # spec without this reports only what the reader itself caught.
    fs.route()
    issues = fs.validate(diagram=args.diagram)
    for issue in issues:
        print(f"{issue.severity}: {issue.code}: {issue.message}")
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = len(issues) - errors
    if not issues:
        print(
            f"{args.spec}: no problems found "
            f"({_plural(len(fs.units), 'unit')}, {_plural(len(fs.streams), 'stream')})"
        )
        return EXIT_OK
    tail = "" if errors else "; warnings do not stop the drawing"
    print(f"{args.spec}: {_plural(errors, 'error')}, {_plural(warnings, 'warning')}{tail}")
    return EXIT_FAILED if errors else EXIT_OK


def _catalogue() -> list[tuple[str, str, list[str]]]:
    """Every symbol as ``(class name, kind, variants)``, per kind.

    The kinds come from the unit classes rather than from the registry,
    so what is listed is what a flowsheet can actually put on a sheet: a
    ``kind`` a spec is free to name, with the variants the renderer has
    artwork for.

    One row per ``kind``, not one row per class that carries it. Every
    ``units`` class used to have a kind of its own, but ``Absorber`` and
    ``Stripper`` do not: both are ``"column"``, the same as ``Column``,
    because neither draws anything the registry does not already draw
    under it. Filtered through ``spec._ALIASES``, the table that already
    says which class a bare ``kind: column`` resolves to, so a class
    whose ports are a reduced subset of its kind's does not print the
    kind's whole variant list a second time under its own name.
    """
    from pandid.render.symbols import default_registry

    rows = []
    for name in units.__all__:
        kind = getattr(units, name).kind
        if spec._ALIASES.get(kind) != name:
            continue
        variants = default_registry.variants(kind)
        if variants:
            rows.append((name, kind, variants))
    return sorted(rows)


def _row(label: str, items: Sequence[str], pad: int, width: int) -> list[str]:
    """``label``, then its items, wrapped under a hanging indent."""
    lines = [label.ljust(pad)]
    for item in items:
        if len(lines[-1]) > pad and len(lines[-1]) + len(item) > width:
            lines.append(" " * pad)
        lines[-1] += item + "  "
    return [line.rstrip() for line in lines]


def _symbols(args: argparse.Namespace) -> int:
    catalogue = _catalogue()
    rows = catalogue
    if args.kind is not None:
        wanted = _fold(args.kind)
        rows = [row for row in catalogue if wanted in (_fold(row[0]), _fold(row[1]))]
        if not rows:
            names = [name for name, _, _ in catalogue]
            raise _Failure(
                f"no equipment kind called {args.kind!r}{_suggest(args.kind, names)}; "
                f"available kinds: {', '.join(names)}",
                EXIT_USAGE,
            )

    # A class name is what a spec writes; the kind is what the symbol is
    # filed under and what the engine names in its own messages. They
    # read the same for all but a couple, so the second is shown only
    # where it differs.
    labels = [name if _fold(name) == kind else f"{name} ({kind})" for name, kind, _ in rows]
    pad = max(len(label) for label in labels) + 2
    width = max(shutil.get_terminal_size(fallback=(100, 24)).columns - 1, pad + 24)
    for label, (_, _, variants) in zip(labels, rows):
        for line in _row(label, variants, pad, width):
            print(line)
    if args.kind is None:
        total = sum(len(variants) for _, _, variants in rows)
        _note(
            f"{_plural(total, 'symbol')} in {_plural(len(rows), 'kind')}; narrow this with "
            "--kind, e.g. pandid symbols --kind valve"
        )
    return EXIT_OK


# --------------------------------------------------------------
# The command line itself
# --------------------------------------------------------------


def _diagram_option(command: argparse.ArgumentParser, help: str) -> None:
    """``--diagram``, on both commands that answer about a sheet.

    ``draw`` makes the drawing and ``validate`` reports on it, so the two
    have to be told the same thing about which drawing it is. A P&ID
    draws its process lines without arrowheads, and ``nozzles-crowded``
    is a finding about the paper left between two arrowheads: on a sheet
    that draws none there are none to be crowded, so a ``validate`` that
    could not be told judged every spec as a PFD and reported a defect in
    ink the drawing does not contain.

    Declared once so the spelling and the default cannot drift apart.
    """
    command.add_argument("--diagram", choices=("pfd", "p&id"), default="pfd", help=help)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pandid",
        description="Draw a P&ID or process flow diagram from a flowsheet spec file.",
    )
    parser.add_argument("--version", action="version", version=f"pandid {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    draw = commands.add_parser("draw", help="render a spec file to a drawing")
    draw.add_argument("spec", type=Path, metavar="SPEC", help="the spec file (.yaml, .yml, .json)")
    draw.add_argument(
        "-o", "--output", type=Path, metavar="OUT",
        help="where to write it; the extension picks the format (.svg, .pdf/.png with the "
             "pdf extra, or .drawio for an editable draw.io model). Default: the spec's "
             "name with .svg",
    )
    draw.add_argument(
        "--page-size", metavar="SIZE",
        help="draw on a sheet of exactly this size (A4 to A0); omit to fit the sheet to the "
             "drawing",
    )
    draw.add_argument(
        "--border", choices=("none", "zone"),
        help="'zone' rules the zone-lettered drawing frame around the sheet",
    )
    _diagram_option(
        draw,
        "which drawing this is; a P&ID draws its process lines without "
        "arrowheads (default: pfd)",
    )
    draw.add_argument(
        "--connections", choices=("none", "flanged", "flanged-at-nozzles"),
        default="none",
        help="mark the sheet's joints; 'flanged' marks every equipment nozzle "
             "and both sides of every valve and in-line fitting, "
             "'flanged-at-nozzles' marks the nozzles only. A P&ID only "
             "(default: none)",
    )
    # ``nargs="?"`` for the reason ``--debug`` has it: the option grew a
    # value and the flag spelling still has to mean what it always
    # meant. ``--stream-table`` alone draws the table under the drawing;
    # ``--stream-table sheet`` writes the table's own sheet to OUT
    # instead, so a set with both is two runs with two outputs.
    draw.add_argument(
        "--stream-table", nargs="?", const=True, default=False,
        choices=(TABLE_SHEET,), metavar=TABLE_SHEET,
        help="draw the stream property table under the drawing, or pass "
             f"'{TABLE_SHEET}' to draw the table as a sheet of its own",
    )
    draw.add_argument(
        "--jump-direction", choices=("vertical", "horizontal"), default="vertical",
        help="which of two crossing lines gets the semicircle hop (default: vertical)",
    )
    # Every other render option is reachable from here, and a debugging
    # view is if anything more use from a shell than from a script: it
    # is the thing you switch on for one render, look at, and switch off
    # again. ``nargs="?"`` gives that the shortest spelling there is --
    # ``--debug`` alone for the default grid, ``--debug 100`` to change
    # it -- and the two land on the same bool-or-number the API takes.
    draw.add_argument(
        "--debug", nargs="?", type=float, const=True, default=None, metavar="SPACING",
        help="draw the coordinate overlay under the diagram: the grid, every pin() anchor "
             "and every port. Optionally takes the grid spacing in drawing units",
    )
    draw.set_defaults(run=_draw)

    validate = commands.add_parser(
        "validate", help="report what the engine thinks of a spec, without drawing it"
    )
    validate.add_argument(
        "spec", type=Path, metavar="SPEC", help="the spec file (.yaml, .yml, .json)"
    )
    _diagram_option(
        validate,
        "which drawing the findings are about; a P&ID draws no arrowheads, so "
        "nozzles pitched inside the heads they would carry on a PFD are not a "
        "defect on one (default: pfd)",
    )
    validate.set_defaults(run=_validate)

    symbols = commands.add_parser("symbols", help="list the equipment symbols that can be drawn")
    symbols.add_argument(
        "--kind", metavar="KIND",
        help="list one kind only, named as a spec would name it (Valve, HeatExchanger, hex)",
    )
    symbols.set_defaults(run=_symbols)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit code.

    Every failure a user can provoke is reported as one line on stderr.
    A traceback out of here is a bug in the engine, not a bad spec.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(None if argv is None else list(argv))
    except SystemExit as e:  # --help, --version, a bad line
        return e.code if isinstance(e.code, int) else EXIT_USAGE

    try:
        return int(args.run(args))
    except _Failure as e:
        return _fail(str(e), e.code)
    except ImportError as e:
        # PyYAML and the pdf extra are the two optional installs, and
        # both of these messages already name the package to install and
        # the extra.
        return _fail(str(e), EXIT_MISSING_DEPENDENCY)
    except ValueError as e:
        # SpecError is a ValueError, and so is every refusal from the
        # engine. Those messages are written to be read by whoever wrote
        # the file, so they are printed as they are rather than wrapped
        # in anything.
        return _fail(str(e), EXIT_FAILED)
    except OSError as e:
        # A file that is not there, or not readable, or a directory that
        # is not.
        detail = f"{e.filename}: {e.strerror}" if e.filename and e.strerror else str(e)
        return _fail(detail, EXIT_FAILED)
