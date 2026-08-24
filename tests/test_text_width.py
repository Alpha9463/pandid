"""What the renderer thinks a string draws at.

Two rules, and both used to be one flat rate per character.

:func:`pandid.render.furniture.text_width` -- which sizes every box,
column and cell of sheet furniture in both backends -- now charges each
character **the advance the face actually sets it at**, from a table of
Helvetica's own numbers. That face is not a guess: pandid writes
``font-family="sans-serif"`` on every string, svglib registers the
generic family onto ReportLab's Helvetica, and
:mod:`pandid.render.export` already writes that down and draws its
baselines from it. So wherever the ``pdf`` extra is installed these
tests measure pandid's ruler against the backend that will do the
drawing, character by character, rather than against a second copy of
pandid's own arithmetic.

The equipment-tag halo (``_unit_label_box`` in :mod:`pandid.render.svg`),
a labelled block's own box (``label_span`` in
:mod:`pandid.render.symbols`, shared by ``block_symbol`` and a boundary
flag's ``resolve_size``) and the ``label-overruns-symbol`` check
(:mod:`pandid.validate`) still read a string off
:func:`pandid.render.furniture.script_counts` at per-character rates of
their own, so a CJK tag is neither undersized on the sheet nor waved
through by the check meant to catch it.

Every case here is real text -- a real CJK string, a real combining
mark reached by NFD-normalising a real accented word, a real mixed-script
tag -- never a mocked width function: the bugs these cover are about what
an actual glyph draws, and a mock would only ever measure its own
assumption back.
"""

import importlib.util
import unicodedata

import pytest

from pandid import Flowsheet, units as U

#: Helvetica is what the export backend resolves pandid's ``sans-serif``
#: to (:mod:`pandid.render.export`), so ReportLab is the one ruler in
#: reach that is not pandid's own. Skipped, not faked, where it is
#: absent: a table of numbers checked against a copy of itself is not
#: checked. Follows ``tests/test_export.py``'s reading of the extra.
_HAS_REPORTLAB = importlib.util.find_spec("reportlab") is not None
_FACE = {False: "Helvetica", True: "Helvetica-Bold"}

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


def _flat_rate(s, size, bold=False) -> float:
    """The formula ``text_width`` used before it had the face's own
    advances: one rate for every character, whatever character it was.
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


#: Drawing text the flat rate got wrong, with how wrong it was: the
#: string, whether it is set bold, and the per cent the flat rate came
#: to over what the face draws. Negative is the dangerous direction --
#: a cell ruled to hold a string it measured short of, which is what
#: made a section heading run through and past its own rules. All of it
#: is ordinary lettering off these sheets, none of it contrived.
FLAT_RATE_ERROR = [
    ("STREAM NUMBER", True, -9),
    ("PROCESS FLOW DIAGRAM", True, -6),
    ("Pump", True, -11),
    ("MMMMMMMM", True, -26),
    ("Mass Flow (kg/h)", True, +23),
    ("0.0441 kg/kg total", True, +34),
    ("Ethanol Purification A300", True, +28),
    ("STREAM NUMBER", False, -17),
    ("PROCESS FLOW DIAGRAM", False, -14),
    ("Pump", False, -14),
    ("Fermentation and Beer Stripping Section", False, +21),
]


@pytest.mark.skipif(not _HAS_REPORTLAB, reason="the pdf extra is not installed")
@pytest.mark.parametrize("code", list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)))
@pytest.mark.parametrize("bold", [False, True])
def test_every_advance_in_the_table_is_the_faces_own(code, bold):
    """The table is data, and data nothing checks is data that drifts.
    Every character of both bands, against the backend that will draw
    it -- not a spot check and not a tolerance: pandid holds Helvetica's
    numbers so it can answer on a machine with no Helvetica to ask, and
    the only thing that makes those the numbers is this.

    Compared at a thousandth of a unit rather than bit for bit: both
    sides hold the same integer advance and reach a width by a division
    and a multiplication in a different order, so ``W`` comes out
    944,0000000000001 on one side and 944,0 on the other. That is the
    float arithmetic disagreeing, not the metric.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from pandid.render.furniture import text_width

    ch = chr(code)
    assert text_width(ch, 1000, bold) == pytest.approx(stringWidth(ch, _FACE[bold], 1000), abs=1e-3)


@pytest.mark.skipif(not _HAS_REPORTLAB, reason="the pdf extra is not installed")
@pytest.mark.parametrize("s, bold, _pct", FLAT_RATE_ERROR)
def test_a_string_measures_what_the_backend_will_set_it_at(s, bold, _pct):
    """Whole strings, not only characters: the sum is exact too, so a
    box ruled to ``text_width`` is a box the lettering fits."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from pandid.render.furniture import text_width

    assert text_width(s, 10.5, bold) == pytest.approx(stringWidth(s, _FACE[bold], 10.5))


@pytest.mark.parametrize("s, bold, pct", FLAT_RATE_ERROR)
def test_the_flat_rate_it_replaced_missed_by_up_to_a_third_either_way(s, bold, pct):
    """What was actually wrong, kept where it can be read. One rate for
    every character reads as calibrated -- 0,56 em is within a few
    thousandths of the mean of Helvetica's ASCII -- and a mean is not a
    ruler: no real string is the mean, and drawing text is capitals and
    digits and narrow letters in whatever proportion the author wrote.
    """
    from pandid.render.furniture import text_width

    drawn = text_width(s, 10.5, bold)
    assert round(100 * (_flat_rate(s, 10.5, bold) - drawn) / drawn) == pct


def test_a_cjk_string_is_no_longer_priced_like_the_same_count_of_latin_letters():
    """The bug this closes: ``text_width("Pump") == text_width(4 CJK)``."""
    from pandid.render.furniture import text_width

    four_cjk = CJK[:4]
    assert len(four_cjk) == len("Pump") == 4
    flat_pump, flat_cjk = _flat_rate("Pump", 12), _flat_rate(four_cjk, 12)
    assert flat_pump == flat_cjk  # the bug, restated: codepoint-blind

    new_pump, new_cjk = text_width("Pump", 12), text_width(four_cjk, 12)
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
    assert text_width(CAFE_COMBINING, 12) < _flat_rate(CAFE_COMBINING, 12)


def test_a_mixed_latin_and_cjk_tag_charges_each_script_its_own_rate():
    """ "T-100" off the face's own advances, "塔" a full em: the two rules
    meet inside one string and neither is applied to the other's
    characters."""
    from pandid.render.furniture import text_width

    latin = text_width("T-100", 12)
    assert text_width(MIXED, 12) == pytest.approx(latin + 1 * 12)


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
