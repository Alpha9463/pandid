"""Test that text widths come from the face's own advances, per script."""

import importlib.util
import unicodedata

import pytest

from pandid import Flowsheet, units as U

#: Whether ReportLab, whose Helvetica the export backend sets ``sans-serif`` in, is installed.
_HAS_REPORTLAB = importlib.util.find_spec("reportlab") is not None
_FACE = {False: "Helvetica", True: "Helvetica-Bold"}

#: Seven CJK ideographs, each East Asian Width class W.
CJK = "蒸馏塔分离单元"

#: "Café" spelled with a combining acute accent (NFD).
CAFE_COMBINING = unicodedata.normalize("NFD", "Café")

#: A tag mixing Latin letters, one CJK ideograph and digits.
MIXED = "T-塔100"


def _flat_rate(s, size, bold=False) -> float:
    """Return the width one rate per character gives, as before the face's advances."""
    return len(str(s)) * size * (0.62 if bold else 0.56)


def _old_label_span(text: str) -> float:
    """Return the label span the formula before script awareness gives."""
    return 8.0 * len(text) + 30.0


# --- pandid.render.furniture.text_width ----------------------------------


def test_an_ambiguous_width_character_is_treated_as_narrow():
    """Check that an ambiguous width character is treated as narrow."""
    from pandid.render.furniture import text_width

    assert text_width("αβγ", 12) < 3 * 12  # Greek alpha, beta, gamma
    assert text_width("Дет", 12) < 3 * 12  # Cyrillic "Дет"


#: Lettering the flat rate got wrong: (text, bold, per cent the flat rate exceeded the face).
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
    ("MMMMMMMM", False, -33),
    ("Mass Flow (kg/h)", False, +18),
    ("0.0441 kg/kg total", False, +28),
    ("Ethanol Purification A300", False, +25),
    ("Fermentation and Beer Stripping Section", False, +21),
]


@pytest.mark.skipif(not _HAS_REPORTLAB, reason="the pdf extra is not installed")
@pytest.mark.parametrize("code", list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)))
@pytest.mark.parametrize("bold", [False, True])
def test_every_advance_in_the_table_is_the_faces_own(code, bold):
    """Check that every advance in the table is the face's own."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from pandid.render.furniture import text_width

    ch = chr(code)
    assert text_width(ch, 1000, bold) == pytest.approx(stringWidth(ch, _FACE[bold], 1000), abs=1e-3)


@pytest.mark.skipif(not _HAS_REPORTLAB, reason="the pdf extra is not installed")
@pytest.mark.parametrize("s, bold, _pct", FLAT_RATE_ERROR)
def test_a_string_measures_what_the_backend_will_set_it_at(s, bold, _pct):
    """Check that a string measures what the backend will set it at."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from pandid.render.furniture import text_width

    assert text_width(s, 10.5, bold) == pytest.approx(stringWidth(s, _FACE[bold], 10.5))


@pytest.mark.parametrize("s, bold, pct", FLAT_RATE_ERROR)
def test_the_flat_rate_it_replaced_missed_by_up_to_a_third_either_way(s, bold, pct):
    """Check that a flat rate misses this lettering by up to a third either way."""
    from pandid.render.furniture import text_width

    drawn = text_width(s, 10.5, bold)
    assert round(100 * (_flat_rate(s, 10.5, bold) - drawn) / drawn) == pct


def test_a_cjk_string_is_no_longer_priced_like_the_same_count_of_latin_letters():
    """Check that a CJK string is not priced like the same count of Latin letters."""
    from pandid.render.furniture import text_width

    four_cjk = CJK[:4]
    assert len(four_cjk) == len("Pump") == 4
    flat_pump, flat_cjk = _flat_rate("Pump", 12), _flat_rate(four_cjk, 12)
    assert flat_pump == flat_cjk

    new_pump, new_cjk = text_width("Pump", 12), text_width(four_cjk, 12)
    assert new_cjk > new_pump
    assert new_cjk == pytest.approx(4 * 12)  # a full em per ideograph


def test_a_combining_mark_advances_nothing():
    """Check that a combining mark advances nothing."""
    from pandid.render.furniture import text_width

    assert text_width(CAFE_COMBINING, 12) == text_width("Cafe", 12)
    assert text_width(CAFE_COMBINING, 12) < _flat_rate(CAFE_COMBINING, 12)


def test_a_mixed_latin_and_cjk_tag_charges_each_script_its_own_rate():
    """Check that a mixed Latin and CJK tag charges each script its own rate."""
    from pandid.render.furniture import text_width

    latin = text_width("T-100", 12)
    assert text_width(MIXED, 12) == pytest.approx(latin + 1 * 12)


# --- pandid.render.svg._unit_label_box (the erasing halo) ---------------


@pytest.mark.parametrize("tag", ["Pump", "MW-101", "WWW"])
def test_the_halo_covers_the_tag_as_the_face_sets_it(tag):
    """Check that the halo covers the tag as the face sets it."""
    from pandid.render.furniture import text_width
    from pandid.render.svg import _TAG_TYPE, _unit_label_box

    box = _unit_label_box((100.0, 200.0, "middle", "middle", "top", tag))
    assert box is not None
    assert box[2] - box[0] >= text_width(tag, _TAG_TYPE)


def test_a_debug_label_box_covers_the_label_as_the_face_sets_it():
    """Check that a debug label box covers the label as the face sets it."""
    from pandid.render.debug import _box
    from pandid.render.furniture import text_width

    x0, _y0, x1, _y1 = _box(0.0, 0.0, "MMMM", 9.0, 1.0)
    assert x1 - x0 >= text_width("MMMM", 9.0)


def test_the_halo_undercounted_a_cjk_tag_by_over_a_third_and_now_does_not():
    """Check that a CJK tag's halo is over a third wider than the flat rate made it."""
    from pandid.render.svg import _unit_label_box

    item = (100.0, 200.0, "middle", "middle", "top", CJK)
    old_hw = len(CJK) * 6.6 + 8
    box = _unit_label_box(item)
    assert box is not None
    new_hw = box[2] - box[0]
    assert new_hw > old_hw
    assert (new_hw - old_hw) / new_hw > 1 / 3


def test_the_halo_still_covers_only_what_a_combining_mark_actually_draws():
    from pandid.render.svg import _unit_label_box

    plain = _unit_label_box((100.0, 200.0, "middle", "middle", "top", "Cafe"))
    accented = _unit_label_box((100.0, 200.0, "middle", "middle", "top", CAFE_COMBINING))
    assert plain is not None and accented is not None
    assert (accented[2] - accented[0]) == (plain[2] - plain[0])


# --- pandid.render.symbols.label_span (a block's own box) ---------------


def test_a_block_sized_to_its_name_holds_the_name_as_the_face_sets_it():
    """Check that a block sized to its name holds the name as the face sets it."""
    from pandid.portgeom import unit_box
    from pandid.render.furniture import text_width
    from pandid.render.svg import _TAG_TYPE

    name = "W" * 15
    fs = Flowsheet("wide block")
    a = fs.add(U.Block(name))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.layout()
    assert a.frame is not None
    x0, _y0, x1, _y1 = unit_box(a, a.frame)
    assert x1 - x0 >= text_width(name, _TAG_TYPE)


def test_label_span_charges_a_cjk_tag_a_full_em_not_the_latin_rate():
    from pandid.render.symbols import label_span

    assert label_span(CJK) > _old_label_span(CJK)
    assert label_span(CJK) == pytest.approx(12.0 * len(CJK) + 30.0)


# --- end to end: validate() no longer agrees with the defect ------------


def test_a_cjk_block_the_old_formula_missed_is_now_caught():
    """Check that a CJK block sized by the flat formula is reported as too narrow."""
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
    """Check that a CJK block that sizes itself fits its own name."""
    fs = Flowsheet("cjk-block-auto")
    a = fs.add(U.Block(CJK))
    b = fs.add(U.Block("Recovery"))
    fs.connect(a.out_1, b.in_1)
    fs.to_svg()
    assert "label-overruns-symbol" not in [w.code for w in fs.warnings]


def test_a_boundary_flags_cjk_tag_is_not_undersized_either():
    """Check that a boundary flag is sized for its CJK tag."""
    from pandid.portgeom import resolve_size

    fs = Flowsheet("cjk-flag")
    f = fs.add(U.Feed(CJK))
    p = fs.add(U.Product("P"))
    fs.connect(f.outlet, p.inlet)
    w, _ = resolve_size(f)
    assert w > max(80.0, _old_label_span(CJK))
