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
    """Return ``str(value)`` with XML-unwritable characters removed."""
    return _UNWRITABLE.sub("", str(value))


def escaped(value) -> str:
    """Return ``str(value)`` escaped for an XML text node or attribute.

    Escape the five XML metacharacters and remove unwritable characters.
    """
    return html.escape(writable(value))


def fmt(value: float, places: int) -> str:
    """Return ``value`` in fixed point to at most ``places`` decimals.

    Drop trailing zeros and write ``-0`` as ``0``.
    """
    s = f"{value:.{places}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def ident(prefix: str, value) -> str:
    """Return a valid XML name for ``value``, prefixed with ``prefix``.

    A value made only of name characters is kept as is
    (``ident("arrow", "black")`` is ``arrow_black``). Otherwise each run
    of other characters becomes one underscore and a digest of the
    value is appended.

    Parameters
    ----------
    prefix : str
        Word naming the id's kind, such as ``"arrow"``. It must start
        with a letter.
    value : object
        Value the id is derived from.
    """
    text = str(value)
    if text and all(c in _NAME_CHARS for c in text):
        return f"{prefix}_{text}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST]
    return f"{prefix}_{_UNSAFE_RUN.sub('_', text).strip('_')}_{digest}"
