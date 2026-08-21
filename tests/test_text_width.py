"""Script-aware text width.

``text_width`` (:mod:`pandid.render.furniture`), the equipment-tag halo
(``_unit_label_box`` in :mod:`pandid.render.svg`), a labelled block's own
box (``label_span`` in :mod:`pandid.render.symbols`, shared by
``block_symbol`` and a boundary flag's ``resolve_size``) and the
``label-overruns-symbol`` check (:mod:`pandid.validate`) all read a
string's drawn width off :func:`pandid.render.furniture.script_counts`,
so a CJK tag is neither undersized on the sheet nor waved through by the
check meant to catch it.

Every case here is real text -- a real CJK string, a real combining
mark reached by NFD-normalising a real accented word, a real mixed-script
tag -- never a mocked width function: the bug this fixes is about what an
actual glyph draws, and a mock would only ever measure its own
assumption back.
"""

import unicodedata

import pytest

from pandid import Flowsheet, units as U

#: Seven CJK ideographs, "蒸馏塔分离单元" -- "distillation tower
#: separation unit". A real, if arbitrarily chosen, non-Latin tag: every
#: one of the seven is East Asian Width class W (wide), so it is charged
#: close to a full em rather than the Latin rate.
CJK = "蒸馏塔分离单元"

#: "Café", spelled with a *combining* acute accent (NFD) rather than the
#: precomposed é: the base letters plus a codepoint (category Mn) that
#: draws on top of the "e" instead of beside it.
CAFE_COMBINING = unicodedata.normalize("NFD", "Café")

#: A tag mixing a Latin prefix, one CJK ideograph ("塔", tower) and a
#: Latin/digit suffix -- the case a single-script table would get wrong
#: in one direction or the other.
MIXED = "T-塔100"


def _old_text_width(s, size, bold=False) -> float:
    """The formula ``text_width`` used before it read scripts: what
    every Latin, digit or punctuation string must still measure as.
    """
    return len(str(s)) * size * (0.62 if bold else 0.56)


def _old_label_span(text: str) -> float:
    """The formula ``block_symbol``/``label-overruns-symbol``/
    ``resolve_size`` shared before script awareness.
    """
    return 8.0 * len(text) + 30.0


# --- pandid.render.furniture.script_counts / text_width -----------------


def test_script_counts_sorts_a_cjk_string_wide_a_combining_mark_zero():
    from pandid.render.furniture import script_counts

    assert script_counts(CJK) == (0, 7, 0)
    assert script_counts(CAFE_COMBINING) == (4, 0, 1)  # C, a, f, e narrow; the accent zero
    assert script_counts(MIXED) == (5, 1, 0)  # "T-100" narrow, "塔" wide


def test_an_ambiguous_width_character_is_treated_as_narrow():
    """Greek and Cyrillic letters are East Asian Width class A
    (Ambiguous): narrow set among Latin text, wide set among CJK. This
    renderer never knows which kind of line it is drawing, so it takes
    Unicode's own stated default for that case (UAX #11): narrow. That
    is also the reading that leaves a Latin-tagged sheet exactly where
    it was.
    """
    from pandid.render.furniture import script_counts

    assert script_counts("αβγ") == (3, 0, 0)  # Greek alpha, beta, gamma
    assert script_counts("Дет") == (3, 0, 0)  # Cyrillic "Дет"


@pytest.mark.parametrize(
    "s",
    [
        "Pump",
        "T-100",
        "P-101A",
        "S1",
        "",
        "Fermentation and Beer Stripping Section",
    ],
)
@pytest.mark.parametrize("bold", [False, True])
def test_text_width_is_bit_identical_to_the_old_formula_for_latin_text(s, bold):
    """The constraint the fix is built around: ``_ADV``/``_ADV_BOLD``
    were measured against a real PDF rendering and are accurate to
    within a few percent, so a Latin, digit or punctuation string must
    keep computing through the exact expression it always has -- not
    just the same value, the same float.
    """
    from pandid.render.furniture import text_width

    assert text_width(s, 12, bold) == _old_text_width(s, 12, bold)


def test_a_cjk_string_is_no_longer_priced_like_the_same_count_of_latin_letters():
    """The bug this closes: ``text_width("Pump") == text_width(4 CJK)``."""
    from pandid.render.furniture import text_width

    four_cjk = CJK[:4]
    assert len(four_cjk) == len("Pump") == 4
    old_pump, old_cjk = _old_text_width("Pump", 12), _old_text_width(four_cjk, 12)
    assert old_pump == old_cjk  # the bug, restated: codepoint-blind

    new_pump, new_cjk = text_width("Pump", 12), text_width(four_cjk, 12)
    assert new_pump == old_pump  # Latin: unmoved
    assert new_cjk > new_pump  # CJK: no longer priced as if it were Latin
    assert new_cjk == pytest.approx(4 * 12)  # a full em per ideograph


def test_a_combining_mark_advances_nothing():
    """ "Café" spelled with a combining accent draws the same width as
    without it: the accent stacks on the "e" rather than sitting beside
    it. Charged a full letter, it is the same bug pointed at an accent
    instead of an ideograph.
    """
    from pandid.render.furniture import text_width

    assert text_width(CAFE_COMBINING, 12) == text_width("Cafe", 12)
    assert text_width(CAFE_COMBINING, 12) < _old_text_width(CAFE_COMBINING, 12)


def test_a_mixed_latin_and_cjk_tag_charges_each_script_its_own_rate():
    from pandid.render.furniture import text_width

    assert text_width(MIXED, 12) == pytest.approx(5 * 12 * 0.56 + 1 * 12)


# --- pandid.render.svg._unit_label_box (the erasing halo) ---------------


def test_the_halo_is_unmoved_for_a_latin_tag():
    from pandid.render.svg import _unit_label_box

    item = (100.0, 200.0, "middle", "middle", "top", "Pump")
    box = _unit_label_box(item)
    assert box is not None
    assert box[2] - box[0] == pytest.approx(len("Pump") * 6.6 + 8)


def test_the_halo_undercounted_a_cjk_tag_by_over_a_third_and_now_does_not():
    """The issue's own numbers: an erasing halo undersized by more than
    a third leaves ink the tag was meant to blank still showing through
    it. Checked as a ratio -- the old formula's halo against the fixed
    one's -- rather than against a hand-measured pixel count, since
    those came from a real installed CJK font this environment cannot
    reproduce.
    """
    from pandid.render.svg import _unit_label_box

    item = (100.0, 200.0, "middle", "middle", "top", CJK)
    old_hw = len(CJK) * 6.6 + 8
    box = _unit_label_box(item)
    assert box is not None
    new_hw = box[2] - box[0]
    assert new_hw > old_hw
    assert (new_hw - old_hw) / new_hw > 1 / 3  # the halo used to fall this far short


def test_the_halo_still_covers_only_what_a_combining_mark_actually_draws():
    from pandid.render.svg import _unit_label_box

    plain = _unit_label_box((100.0, 200.0, "middle", "middle", "top", "Cafe"))
    accented = _unit_label_box((100.0, 200.0, "middle", "middle", "top", CAFE_COMBINING))
    assert plain is not None and accented is not None
    assert (accented[2] - accented[0]) == (plain[2] - plain[0])


# --- pandid.render.symbols.label_span (a block's own box) ---------------


def test_label_span_is_unmoved_for_latin_text():
    from pandid.render.symbols import label_span

    for s in ("Pump", "Fermentation and Beer Stripping Section", ""):
        assert label_span(s) == _old_label_span(s)


def test_label_span_charges_a_cjk_tag_a_full_em_not_the_latin_rate():
    from pandid.render.symbols import label_span

    assert label_span(CJK) > _old_label_span(CJK)
    assert label_span(CJK) == pytest.approx(12.0 * len(CJK) + 30.0)


# --- end to end: validate() no longer agrees with the defect ------------


def test_a_cjk_block_the_old_formula_missed_is_now_caught():
    """A width chosen to just satisfy the *pre-fix* formula for a CJK
    name (8 px/character, no script awareness) -- which the fixed,
    script-aware check correctly reports as still too narrow, since a
    CJK character draws close to a full em rather than the Latin rate.

    Before the fix this rendered with no warning at all: the box, the
    check and the bug all shared the same blind formula, so a genuinely
    overrunning CJK tag measured itself as fine.
    """
    old_formula_width = _old_label_span(CJK)
    fs = Flowsheet("cjk-block-too-narrow")
    a = fs.add(U.Block(CJK, width=old_formula_width))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.to_svg()
    found = [w for w in fs.warnings if w.code == "label-overruns-symbol"]
    assert len(found) == 1
    assert CJK in found[0].message


def test_a_cjk_block_that_sizes_itself_still_fits_its_own_name():
    """``block_symbol`` and the check now share :func:`label_span`, so a
    block left to size itself to a CJK name is never accused of
    overrunning it -- the same promise the check's own message makes
    for a Latin one (``test_a_block_that_sizes_itself_always_fits_its_name``).
    Fixing the check without fixing ``block_symbol`` would have made
    this fail instead: a false ``label-overruns-symbol`` on every
    auto-sized CJK block, for doing exactly what the message tells it to.
    """
    fs = Flowsheet("cjk-block-auto")
    a = fs.add(U.Block(CJK))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.to_svg()
    assert "label-overruns-symbol" not in [w.code for w in fs.warnings]


def test_a_boundary_flags_cjk_tag_is_not_undersized_either():
    """``resolve_size`` shares :func:`~pandid.render.symbols.label_span`
    with ``block_symbol``, so a Feed/Product flag lettered in CJK sizes
    itself the same script-aware way a block does, rather than the
    Latin-rate formula it used to share with the pre-fix ``block_symbol``.
    """
    from pandid.portgeom import resolve_size

    fs = Flowsheet("cjk-flag")
    f = fs.add(U.Feed(CJK))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, p.inlet)
    w, _ = resolve_size(f)
    assert w > max(80.0, _old_label_span(CJK))
