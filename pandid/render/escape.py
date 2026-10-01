"""Write user strings into SVG and draw.io XML without creating markup.

Both backends build documents by concatenation, so user values must:

* escape ``&``, ``<``, ``>``, ``"`` and ``'``, or a value can end the
  document or an attribute and inject script into an SVG opened in a
  browser. :func:`escaped` escapes all five in text and attributes alike;
* drop characters XML 1.0 2.2 cannot represent (controls other than tab,
  newline and carriage return), which even numeric references cannot
  spell. They have no glyph, so nothing visible is lost. Wrong values,
  such as a bad colour, are refused where set
  (:func:`pandid.streams.check_color`).

Ids are the third case: a ``<marker>`` id pasted from a colour, such as
``arrow_rgb(1,2,3)``, is not an XML name, and a browser silently drops the
arrowheads. :func:`ident` always returns a valid name; use it for both the
definition and the ``url(#...)`` reference.
"""

from __future__ import annotations

import hashlib
import html
import re
import string

# Characters XML 1.0 2.2 cannot represent, even as references: C0 controls
# except tab, newline and carriage return, surrogates, and U+FFFE/U+FFFF.
_UNWRITABLE = re.compile(
    "[^"
    "\t\n\r"
    " -퟿"
    "-�"
    "\U00010000-\U0010ffff"
    "]"
)

# ASCII subset of the NCName characters allowed after the first (XML
# Namespaces 3), enough for ids from colours and symbol keys.
_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_.-")

# Runs outside _NAME_CHARS, which ident collapses; tests/test_escape.py
# keeps the two in step.
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9_.-]+")

# Hex digits of digest that separate values sanitising alike (32 bits).
_DIGEST = 8


def writable(value) -> str:
    """Return ``value`` as text with XML-unwritable characters removed.

    Used alone by the draw.io export, which escapes HTML cell values
    itself so that ``<br>`` survives.

    Parameters
    ----------
    value : object
        Value to write.

    Returns
    -------
    str
        ``str(value)`` without unwritable characters.
    """
    return _UNWRITABLE.sub("", str(value))


def escaped(value) -> str:
    """Return ``value`` escaped for an XML text node or attribute.

    Parameters
    ----------
    value : object
        Value to write; converted with ``str``.

    Returns
    -------
    str
        Text with the five metacharacters escaped and unwritable
        characters removed.
    """
    return html.escape(writable(value))


def ident(prefix: str, value) -> str:
    """Return a valid XML name for ``value``, prefixed with ``prefix``.

    A value made only of name characters is kept readable
    (``ident("arrow", "black")`` is ``arrow_black``). Otherwise runs of
    other characters become one underscore and a digest of the original
    is appended, so ``rgb(1, 2, 3)`` and ``rgb(1,2,3)`` stay distinct. Use
    it for both the definition and the reference.

    Parameters
    ----------
    prefix : str
        Leading word naming the id's kind, such as ``"arrow"``; it makes
        the name start with a letter.
    value : object
        Value the id is derived from.

    Returns
    -------
    str
        XML name.
    """
    text = str(value)
    if text and all(c in _NAME_CHARS for c in text):
        return f"{prefix}_{text}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST]
    return f"{prefix}_{_UNSAFE_RUN.sub('_', text).strip('_')}_{digest}"
