#!/usr/bin/env python3
"""Generate the SVG gallery from example flowsheets.

Run ``python scripts/gallery.py`` after an example or renderer change, then
review the generated assets. A version-only package update needs no redraw.
"""

import contextlib
import importlib.util
import io
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from pandid import Flowsheet  # noqa: E402

EXAMPLES = ROOT / "examples"
GALLERY = ROOT / "docs" / "gallery"


def _pandid_is_this_checkout() -> None:
    """Confirm that gallery rendering imports this checkout's package.

    Returns
    -------
    None
        The imported package belongs to this repository.

    Raises
    ------
    SystemExit
        If a previously imported package does not belong to this repository.
    """
    import pandid

    where = pathlib.Path(pandid.__file__).resolve()
    if not where.is_relative_to(ROOT):
        raise SystemExit(
            f"refusing to generate the gallery: pandid was imported from\n"
            f"    {where}\n"
            f"which is not this checkout at\n    {ROOT}\n"
            f"The drawings would be the installed release's, not this tree's."
        )


def captures() -> "dict[str, tuple[Flowsheet, dict]]":
    """Run every example once and capture its sheets in filename order.

    Returns
    -------
    dict[str, tuple[pandid.Flowsheet, dict]]
        Each sheet's flowsheet and SVG render options, keyed by sheet name.

    Raises
    ------
    SystemExit
        If an example cannot be imported or draws no sheet.
    """
    out = {}
    for stem in sorted(p.stem for p in EXAMPLES.glob("[0-9]*.py")):
        out |= _sheets(stem)
    return out


def sheets() -> list[str]:
    """Return gallery sheet names in filename order.

    Returns
    -------
    list[str]
        Sheet names used for gallery asset names.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return list(captures())


def _sheets(stem: str) -> "dict[str, tuple[Flowsheet, dict]]":
    """Run one example and capture its sheets with their title blocks dated.

    A one-sheet example's sheet is named by its stem, and sheet *n* of a
    longer example by ``{stem}_{n}``.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    dict[str, tuple[pandid.Flowsheet, dict]]
        Each sheet's flowsheet and SVG render options, keyed by sheet name.

    Raises
    ------
    SystemExit
        If the example cannot be imported or draws no sheet.
    """
    caught = _capture(stem)
    if not caught:
        raise SystemExit(f"examples/{stem}.py drew no sheet.")
    for fs, _kwargs in caught:
        _stamp(fs)
    names = [stem] if len(caught) == 1 else [f"{stem}_{n}" for n in range(1, len(caught) + 1)]
    return dict(zip(names, caught))


def _stamp(fs: Flowsheet) -> None:
    """Populate a blank title-block date from the latest revision.

    Parameters
    ----------
    fs : pandid.Flowsheet
        Flowsheet whose title block may need a stable date.

    Returns
    -------
    None
        The title block is updated in place when a revision date is available.
    """
    tb = getattr(fs, "title_block", None)
    if tb is not None and not tb.date and tb.revisions:
        tb.date = tb.revisions[-1].date


def _capture(stem: str) -> "list[tuple[Flowsheet, dict]]":
    """Run one example and capture every SVG render it requests.

    Parameters
    ----------
    stem : str
        Example filename stem.

    Returns
    -------
    list[tuple[pandid.Flowsheet, dict]]
        Each captured flowsheet and the options supplied to its render call.

    Raises
    ------
    SystemExit
        If the example cannot be imported.
    """
    caught: list[tuple[Flowsheet, dict]] = []
    original = Flowsheet.render

    def capture(self, path, **kwargs):
        """Capture one SVG render request without writing its output.

        Parameters
        ----------
        self : pandid.Flowsheet
            Flowsheet passed to :meth:`pandid.Flowsheet.render`.
        path : str or pathlib.Path
            Requested output path.
        **kwargs : object
            Render options passed by the example.

        Returns
        -------
        None
            The SVG render request is appended to the local capture list.
        """
        if pathlib.Path(path).suffix.lower() != ".drawio":
            caught.append((self, kwargs))

    sys.path.insert(0, str(EXAMPLES))  # the examples' own _bootstrap
    Flowsheet.render = capture  # type: ignore[method-assign]
    try:
        spec = importlib.util.spec_from_file_location(f"_gallery_{stem}", EXAMPLES / f"{stem}.py")
        if spec is None or spec.loader is None:
            raise SystemExit(f"could not import examples/{stem}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not caught and hasattr(module, "main"):
            module.main()
    finally:
        Flowsheet.render = original  # type: ignore[method-assign]
        sys.path.remove(str(EXAMPLES))
    return caught


def flowsheet(name: str) -> "tuple[Flowsheet, dict]":
    """Capture one gallery sheet and its SVG render options.

    Parameters
    ----------
    name : str
        Sheet name from :func:`sheets`.

    Returns
    -------
    tuple[pandid.Flowsheet, dict]
        Captured flowsheet and the options supplied to its SVG render call.

    Raises
    ------
    SystemExit
        If the example draws no sheet, or no sheet of that name.
    """
    stem = name if (EXAMPLES / f"{name}.py").exists() else name.rpartition("_")[0]
    caught = _sheets(stem)
    if name not in caught:
        raise SystemExit(f"examples/{stem}.py has no sheet {name!r}; its sheets are {', '.join(caught)}.")
    return caught[name]


def normalize(svg: str) -> str:
    """Canonicalize unordered SVG definitions for reproducible assets.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    str
        SVG document with sorted marker and definition entries.
    """
    lines = svg.split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "<defs>")
        end = next(i for i, ln in enumerate(lines) if ln.strip() == "</defs>")
    except StopIteration:
        return svg
    body = lines[start + 1 : end]
    markers = []
    j = 0
    while j < len(body) and body[j].strip().startswith("<marker "):
        markers.append(tuple(body[j : j + 3]))
        j += 3
    markers.sort()
    new_body = [line for group in markers for line in group] + sorted(body[j:])
    return "\n".join(lines[: start + 1] + new_body + lines[end:])


def main() -> None:
    """Write every gallery sheet as an SVG.

    Returns
    -------
    None
        Sheets are written to :data:`GALLERY`.
    """
    _pandid_is_this_checkout()
    GALLERY.mkdir(parents=True, exist_ok=True)
    for stem, (fs, kwargs) in captures().items():
        svg = normalize(fs.to_svg(**kwargs))
        (GALLERY / f"{stem}.svg").write_text(svg, encoding="utf-8")
        print(f"wrote {stem}.svg")


if __name__ == "__main__":
    main()
