"""Provide the ``pandid`` command line.

A thin shell over the public API: it reads a spec with :mod:`pandid.spec`,
calls the same methods a script would, and reports any failure as one
line on stderr with an exit code::

    pandid draw plant.yaml -o plant.pdf --page-size A3 --border zone
    pandid validate plant.yaml
    pandid symbols --kind valve

===== ============================================================
``0`` success
``1`` the flowsheet was rejected: the spec could not be read,
      validation found errors, or the engine refused the request
      (such as an unknown page size)
``2`` the command line was wrong: an unknown flag, a missing
      argument, or an option value checked here
``3`` an optional extra is missing (PyYAML for a YAML spec, the
      ``pdf`` extra for PDF or PNG output)
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
from pandid.render.svg import CROSSING_STYLE_DEFAULT, CROSSING_STYLES
from pandid.render.svg import TABLE_SHEET

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_MISSING_DEPENDENCY = 3


class _Failure(Exception):
    """A user-facing failure and the exit code to report it under.

    Parameters
    ----------
    message : str
        One-line explanation.
    code : int, default=EXIT_FAILED
        Exit code.
    """

    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.code = code


def _note(message: str) -> None:
    """Write a line to stderr after flushing stdout.

    Flushing keeps the note after the output it refers to when either
    stream is a pipe.

    Parameters
    ----------
    message : str
        Line to write.
    """
    sys.stdout.flush()
    print(message, file=sys.stderr)


def _fail(message: str, code: int) -> int:
    """Report an error on stderr and return its exit code.

    Parameters
    ----------
    message : str
        Error text.
    code : int
        Exit code.

    Returns
    -------
    int
        ``code``.
    """
    _note(f"error: {message}")
    return code


def _plural(count: int, noun: str) -> str:
    """Return a count with its noun, pluralised with ``s`` when not 1.

    Parameters
    ----------
    count : int
        Number of items.
    noun : str
        Singular noun.

    Returns
    -------
    str
        Such as ``"1 unit"`` or ``"3 units"``.
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _fold(name: str) -> str:
    """Fold a kind or class name for comparison.

    Parameters
    ----------
    name : str
        Name such as ``HeatExchanger`` or ``heat_exchanger``.

    Returns
    -------
    str
        Lower case without underscores or hyphens.
    """
    return name.lower().replace("_", "").replace("-", "")


def _suggest(value: str, candidates: Sequence[str]) -> str:
    """Return a "did you mean" hint for a misspelt name.

    Parameters
    ----------
    value : str
        Name the user typed.
    candidates : Sequence[str]
        Valid names.

    Returns
    -------
    str
        `` (did you mean 'X'?)``, or an empty string when nothing is close.
    """
    close = difflib.get_close_matches(_fold(value), [_fold(c) for c in candidates], n=1, cutoff=0.6)
    if not close:
        return ""
    match = next(c for c in candidates if _fold(c) == close[0])
    return f" (did you mean {match!r}?)"


# --------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------


def _load(path: Path) -> Flowsheet:
    """Read a spec file, choosing the reader from its extension.

    Parameters
    ----------
    path : Path
        ``.yaml``, ``.yml`` or ``.json`` file.

    Returns
    -------
    Flowsheet
        Flowsheet built from the spec.

    Raises
    ------
    _Failure
        If the extension is not supported.
    OSError
        If the file cannot be opened.
    ImportError
        If PyYAML is needed and not installed.
    SpecError
        If the spec is invalid.
    """
    suffix = path.suffix.lower()
    if suffix not in (".yaml", ".yml", ".json"):
        named = repr(suffix) if suffix else "a file with no extension"
        raise _Failure(
            f"{path}: cannot read a spec from {named}; write it as .yaml, .yml or .json")
    # Open the file first, so a missing file reports exit 1 rather than a
    # missing PyYAML (exit 3).
    with path.open("rb"):
        pass
    if suffix == ".json":
        return spec.from_json(path)
    return spec.from_yaml(path)


def _draw(args: argparse.Namespace) -> int:
    """Render a spec and report any warnings.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``draw`` arguments.

    Returns
    -------
    int
        :data:`EXIT_OK`; failures raise.
    """
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
        crossing_style=args.crossing_style,
        debug=args.debug if args.debug is not None else False,
    )
    sheet = f"{args.page_size.upper()}, " if args.page_size else ""
    print(
        f"wrote {out}  ({sheet}{_plural(len(fs.units), 'unit')}, "
        f"{_plural(len(fs.streams), 'stream')})"
    )
    if fs.warnings:
        # Point to the validate command for the same diagram type.
        sheet = f" --diagram '{args.diagram}'" if args.diagram != "pfd" else ""
        _note(f"{_plural(len(fs.warnings), 'warning')}; "
              f"see: pandid validate{sheet} {args.spec}")
    return EXIT_OK


def _validate(args: argparse.Namespace) -> int:
    """Lay out and route a spec, then print its validation findings.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``validate`` arguments.

    Returns
    -------
    int
        :data:`EXIT_FAILED` if any finding is an error, else
        :data:`EXIT_OK`.
    """
    fs = _load(args.spec)
    # Route first so the geometric checks have frames to measure.
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
    """List the drawable kinds and their variants.

    Kinds come from the unit classes, so only kinds a spec can name are
    listed. One row per kind: classes that share a kind (``Absorber`` and
    ``Stripper`` are ``"column"``) appear only under the class
    ``spec._ALIASES`` resolves the kind to.

    Returns
    -------
    list[tuple[str, str, list[str]]]
        ``(class name, kind, variants)``, sorted by class name.
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
    """Format a label and its items, wrapped under a hanging indent.

    Parameters
    ----------
    label : str
        Row label.
    items : Sequence[str]
        Items to list.
    pad : int
        Indent for the items.
    width : int
        Line width.

    Returns
    -------
    list[str]
        Output lines.
    """
    lines = [label.ljust(pad)]
    for item in items:
        if len(lines[-1]) > pad and len(lines[-1]) + len(item) > width:
            lines.append(" " * pad)
        lines[-1] += item + "  "
    return [line.rstrip() for line in lines]


def _symbols(args: argparse.Namespace) -> int:
    """Print the symbol catalogue, optionally for one kind.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed ``symbols`` arguments.

    Returns
    -------
    int
        :data:`EXIT_OK`.

    Raises
    ------
    _Failure
        If ``--kind`` names no kind (exit 2).
    """
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

    # Show the kind beside the class name only where the two differ.
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
    """Add the shared ``--diagram`` option to a command.

    ``draw`` and ``validate`` must agree on the diagram type: a P&ID draws
    no arrowheads, so ``nozzles-crowded`` does not apply, and a block flow
    diagram needs no stream table.

    Parameters
    ----------
    command : argparse.ArgumentParser
        Subcommand parser.
    help : str
        Help text for this command.
    """
    command.add_argument("--diagram", choices=("pfd", "p&id", "bfd"), default="pfd",
                         help=help)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every subcommand.

    Returns
    -------
    argparse.ArgumentParser
        Parser whose subcommands set ``run`` to their handler.
    """
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
        "arrowheads, and 'bfd' is a block flow diagram (default: pfd)",
    )
    draw.add_argument(
        "--connections", choices=("none", "flanged", "flanged-at-nozzles"),
        default="none",
        help="mark the sheet's joints; 'flanged' marks every equipment nozzle "
             "and both sides of every valve and in-line fitting, "
             "'flanged-at-nozzles' marks the nozzles only. A P&ID only "
             "(default: none)",
    )
    # ``--stream-table`` alone draws the table under the drawing;
    # ``--stream-table sheet`` writes the table as its own sheet instead.
    draw.add_argument(
        "--stream-table", nargs="?", const=True, default=False,
        choices=(TABLE_SHEET,), metavar=TABLE_SHEET,
        help="draw the stream property table under the drawing, or pass "
             f"'{TABLE_SHEET}' to draw the table as a sheet of its own",
    )
    draw.add_argument(
        "--jump-direction", choices=("vertical", "horizontal"), default="vertical",
        help="which of two crossing lines carries the crossing mark "
             "(default: vertical)",
    )
    # Use the renderer's own choices and default, so the CLI and API agree.
    draw.add_argument(
        "--crossing-style", choices=CROSSING_STYLES, default=CROSSING_STYLE_DEFAULT,
        help="what that mark is: 'arc' bridges the crossed line, 'gap' "
             "interrupts the marking one (ISO 10628-1 5.3.4) at the cost of "
             "eating the run either side of it, 'plain' draws both lines "
             "straight through (ISO 15519-1 12.5) (default: %(default)s)",
    )
    # ``--debug`` alone uses the default grid; ``--debug 100`` sets it.
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
        "defect on one, and a 'bfd' owes no stream table (default: pfd)",
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

    Every failure a user can cause is reported as one line on stderr; a
    traceback indicates a bug.

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        Arguments, or ``None`` for ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit code from the table in the module docstring.
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
        # A missing optional extra; the message names what to install.
        return _fail(str(e), EXIT_MISSING_DEPENDENCY)
    except ValueError as e:
        # SpecError and engine refusals; their messages are user-facing.
        return _fail(str(e), EXIT_FAILED)
    except OSError as e:
        # A missing or unreadable file or directory.
        detail = f"{e.filename}: {e.strerror}" if e.filename and e.strerror else str(e)
        return _fail(detail, EXIT_FAILED)
