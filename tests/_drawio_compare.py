"""Normalize Draw.io provenance for exact artifact comparisons."""

from __future__ import annotations

import re

_AGENT = re.compile(r'(?P<prefix><mxfile\b[^>]*\bagent=)"[^"]*"')
_NORMALIZED_AGENT = '"pandid <version>"'


def normalize(document: str) -> str:
    """Replace a Draw.io document's generator version with a stable value.

    Parameters
    ----------
    document : str
        Draw.io XML document whose root ``mxfile`` element has an ``agent``
        attribute.

    Returns
    -------
    str
        The original document with only its root generator value replaced.

    Raises
    ------
    ValueError
        If the document does not contain exactly one root ``mxfile/@agent``
        attribute.
    """
    normalized, count = _AGENT.subn(rf"\g<prefix>{_NORMALIZED_AGENT}", document, count=1)
    if count != 1:
        raise ValueError("Draw.io document must contain one mxfile agent attribute")
    return normalized
