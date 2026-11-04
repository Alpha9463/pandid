"""SVG normalization shared by golden and gallery comparisons."""

from _render_cases import gallery
from pandid.render.svg import PROVENANCE_CLOSE, PROVENANCE_OPEN


def normalize(svg: str) -> str:
    """Sort SVG definitions and remove fenced renderer provenance."""
    lines = svg.split("\n")
    open_i = next((i for i, ln in enumerate(lines) if ln.strip() == PROVENANCE_OPEN.strip()), None)
    close_i = next(
        (i for i, ln in enumerate(lines) if ln.strip() == PROVENANCE_CLOSE.strip()), None
    )
    if open_i is not None and close_i is not None and close_i > open_i:
        del lines[open_i + 1 : close_i]
    return gallery.normalize("\n".join(lines))
