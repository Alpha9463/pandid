"""Getting a user's string into a drawing without it becoming markup.

Both backends build their document by concatenating strings, so every
value that comes from a spec file or an API call reaches the file as
text the parser will read back. Two things have to be true of it, and
they are different things:

* **it has to survive the five metacharacters.** ``&``, ``<``, ``>``,
  ``"`` and ``'`` all mean something to an XML parser, so a tag written
  ``A&B`` closes the document early and a description written
  ``" onload="alert(1)`` closes the *attribute* and opens a second one.
  An SVG is opened in a browser, so that second one is script, out of a
  file somebody was handed. :func:`escaped` is the answer, and it is the
  same answer for an attribute value as for a text node: XML gives ``"``
  and ``'`` no meaning between tags, but escaping them there costs
  nothing and means no call site has to know which of the two it is
  writing.

* **it has to survive characters XML cannot spell at all.** XML 1.0
  §2.2 admits tab, newline and carriage return and then nothing below
  ``U+0020``, so a ``NUL`` or a ``BEL`` in a tag has no representation,
  not even as ``&#1;``, and makes the file unparseable however carefully
  the five were escaped. :func:`escaped` drops them. Dropping rather
  than refusing, because a control character has no glyph: there is
  nothing a drawing could have shown, so nothing is lost by leaving it
  out. A value that is *wrong* rather than unwritable -- a colour that
  is not a colour -- is refused instead, at the point it is set; see
  :func:`pandid.streams.check_color`.

The third hazard is an **id**. A ``<marker>`` id built by pasting a
colour into a string gives ``arrow_rgb(1,2,3)``, which is not an XML
name: a browser drops the definition and the arrowheads silently vanish,
while a PDF export, which resolves the reference itself, keeps them.
:func:`ident` mints one that is always a name, and the reference is
written from the same call, so the definition and the ``url(#...)``
pointing at it cannot disagree.
"""

from __future__ import annotations

import hashlib
import html
import re
import string

#: Everything XML 1.0 §2.2 has no spelling for: the C0 controls but tab,
#: newline and carriage return, the surrogate block (which a Python
#: ``str`` can carry unpaired), and the two permanent non-characters at
#: the end of the BMP. A numeric reference does not rescue these -- the
#: production is over *characters*, so ``&#1;`` is as illegal as the
#: byte itself -- which is why they are removed rather than escaped.
_UNWRITABLE = re.compile(
    "[^"
    "\t\n\r"
    " -퟿"
    "-�"
    "\U00010000-\U0010ffff"
    "]"
)

#: The characters an XML ``NCName`` may carry *after* its first. The
#: real production (XML Namespaces §3, over ``NameChar``) admits most of
#: Unicode; this is the ASCII part of it, which is all an id derived
#: from a colour or a symbol key ever needs and which no reader can
#: mis-handle.
_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_.-")

#: The same set negated, in runs: what :func:`ident` collapses. Spelled
#: out rather than built from the set above so the class reads as a
#: class; ``tests/test_escape.py`` holds the two together.
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9_.-]+")

#: How many hex figures of the digest tell apart two values that
#: sanitise to the same text. Thirty-two bits, against a handful of
#: colours on one sheet: collision-proof in practice and still short
#: enough to read in a diff.
_DIGEST = 8


def writable(value) -> str:
    """*value* with every character XML cannot carry taken out.

    Half of :func:`escaped`, on its own for the one caller that has to
    do the other half differently: the draw.io export escapes the five
    itself, because draw.io reads a cell's ``value`` as HTML and one
    substitution too many turns a ``<br>`` into the word "br". The
    removal is not a matter of taste in the same way, so it is shared.
    """
    return _UNWRITABLE.sub("", str(value))


def escaped(value) -> str:
    """*value* as XML: the five escaped, the unwritable dropped.

    Fit for a text node and for an attribute value alike. Stringifies
    first, so a number or a ``None`` reaching a cell is written the way
    Python writes it rather than raising here.
    """
    return html.escape(writable(value))


def ident(prefix: str, value) -> str:
    """A valid XML name for the thing *value* names, under *prefix*.

    ``prefix`` is a fixed word saying what kind of id this is
    (``"arrow"``, ``"sym"``). It leads, so the result opens with a letter
    whatever *value* is -- an XML name may not start with a digit, and
    half the colours anyone writes are hex.

    A *value* already made of name characters is used as it stands, so
    the ids on an ordinary sheet stay the readable ones they have always
    been: ``black`` gives ``arrow_black``. Anything else has its runs of
    unusable characters collapsed to one underscore **and a digest of
    the original appended**, because the collapse is lossy and two
    colours must never land on one definition: ``rgb(1, 2, 3)`` and
    ``rgb(1,2,3)`` sanitise alike, and the digest is what tells them
    apart.

    Call this for the reference as well as for the definition. That is
    the point of it being a function: a marker id and the ``url(#...)``
    naming it are then one string by construction, rather than two call
    sites that agree until one of them is edited.
    """
    text = str(value)
    if text and all(c in _NAME_CHARS for c in text):
        return f"{prefix}_{text}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST]
    return f"{prefix}_{_UNSAFE_RUN.sub('_', text).strip('_')}_{digest}"
