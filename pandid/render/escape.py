"""Escape user strings, ids and numbers for SVG and draw.io XML."""

from __future__ import annotations

import hashlib
import html
import re
import string

# Characters XML 1.0 cannot represent: C0 controls other than tab,
# newline and carriage return, surrogates, and U+FFFE/U+FFFF.
_UNWRITABLE = re.compile(
    "[^"
    "\t\n\r"
    " -퟿"
    "-�"
    "\U00010000-\U0010ffff"
    "]"
)

# ASCII characters allowed in an XML name after the first.
_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_.-")

# Runs of characters outside _NAME_CHARS.
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9_.-]+")

# Hex digits of the digest appended by ident.
_DIGEST = 8


def writable(value) -> str:
    """Return ``str(value)`` with XML-unwritable characters removed.

    Parameters
    ----------
    value : object
        Value to write.

    Returns
    -------
    str
        Text without unwritable characters.
    """
    return _UNWRITABLE.sub("", str(value))


def escaped(value) -> str:
    """Return ``str(value)`` escaped for an XML text node or attribute.

    Parameters
    ----------
    value : object
        Value to write.

    Returns
    -------
    str
        Text with the five XML metacharacters escaped.
    """
    return html.escape(writable(value))


def fmt(value: float, places: int) -> str:
    """Return ``value`` in fixed point to at most ``places`` decimals.

    Parameters
    ----------
    value : float
        Number to write.
    places : int
        Maximum decimal places; trailing zeros are dropped.

    Returns
    -------
    str
        Number text, with ``-0`` written as ``0``.

    Raises
    ------
    ValueError
        If ``places`` is negative.
    """
    s = f"{value:.{places}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def ident(prefix: str, value) -> str:
    """Return a valid XML name for ``value``, prefixed with ``prefix``.

    Parameters
    ----------
    prefix : str
        Word naming the id's kind; it must start with a letter.
    value : object
        Value the id is derived from.

    Returns
    -------
    str
        ``prefix_value``, or a cleaned name with a digest appended.
    """
    text = str(value)
    if text and all(c in _NAME_CHARS for c in text):
        return f"{prefix}_{text}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST]
    return f"{prefix}_{_UNSAFE_RUN.sub('_', text).strip('_')}_{digest}"
