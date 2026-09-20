"""SVG normalization shared by golden and gallery comparisons."""

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
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "<defs>")
        end = next(i for i, ln in enumerate(lines) if ln.strip() == "</defs>")
    except StopIteration:
        return "\n".join(lines)  # no defs to sort; the provenance edit still stands
    body = lines[start + 1 : end]
    markers = []
    j = 0
    while j < len(body) and body[j].strip().startswith("<marker "):
        markers.append(tuple(body[j : j + 3]))
        j += 3
    symbols = sorted(body[j:])
    markers.sort()
    new_body = [line for group in markers for line in group] + symbols
    return "\n".join(lines[: start + 1] + new_body + lines[end:])
