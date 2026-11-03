"""Render backends for laid-out flowsheets: SVG and draw.io."""

# Project URL written into every rendered file.
HOMEPAGE = "https://github.com/Alpha9463/pandid"


def generator() -> str:
    """Return the generator name ``"pandid <version>"``."""
    from pandid import __version__
    return f"pandid {__version__}"

