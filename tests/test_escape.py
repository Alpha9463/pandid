"""Test escaping, identifier generation, and paint validation."""

import re
import xml.etree.ElementTree as ET

import pytest

from pandid import Flowsheet, units as U
from pandid.document import (
    Annotation,
    Revision,
    TableBox,
    TitleBlock,
    equipment_list,
    legend,
    notes,
)
from pandid.render.escape import _NAME_CHARS, _UNSAFE_RUN, escaped, ident, writable
from pandid.render.svg import arrow_marker_id
from pandid.streams import check_color, check_dasharray

# Attribute name used by injection probes.
INJECTED = "pandidinjected"

#: Distinct hostile payload classes accepted by the escaping primitive.
PAYLOADS = {
    "double quote": f'x" {INJECTED}="1',
    "single quote": f"x' {INJECTED}='1",
    "element": "<script>alert(1)</script>",
    "ampersand": "steam & water",
    "entity": "&lt; &amp; &#0;",
    "cdata close": "]]>",
    "comment": "<!-- x --> --",
    "control characters": "a\x00b\x01c\x1fd",
    "newlines": "one\ntwo\r\nthree",
    "non-ascii": "Cl₂ 中文 \U0001f525",
    "url reference": "url(#no-such-id)",
    "very long": "A" * 120,
}

#: Representative fields for each renderer path that escapes user text.
ESCAPE_CONTEXTS = {
    "document title": "flowsheet name",
    "unit tag": "unit name",
    "equipment description": "unit description",
    "off-page flag": "off-page reference",
    "instrument letters": "instrument letters",
    "instrument loop number": "loop number",
    "stream label": "stream name",
    "line number": "line-number size",
    "stream-table heading": "stream property name",
    "stream-table value": "stream property value",
    "title fallback": "title",
    "title-block cell": "project",
    "revision-history cell": "revision",
    "note": "note text",
    "legend": "legend entry",
    "annotation title": "annotation title",
    "table title": "table title",
    "table header": "table header",
    "table cell": "table cell",
}

#: One payload exercising markup, quote, ampersand, and control-character escaping.
RENDER_PROBE = f'<script {INJECTED}="1">&\x00</script>'

#: Render options exposing every selected document context.
RENDERED = dict(
    border="zone", diagram="p&id", connections="flanged", show_stream_table=True, check=False
)

_URL = re.compile(r"url\(#([^)]*)\)")
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _plant(payload: str, field: str) -> Flowsheet:
    """Create a sheet with a payload in one rendered context.

    Parameters
    ----------
    payload : str
        User-controlled value to render.
    field : str
        Name of the rendered context containing the value.

    Returns
    -------
    Flowsheet
        Pinned flowsheet with document furniture and annotations.
    """

    def at(name: str, ordinary: str) -> str:
        """Select the hostile payload for its named context.

        Parameters
        ----------
        name : str
            Context represented by the current value.
        ordinary : str
            Safe value used outside the selected context.

        Returns
        -------
        str
            Payload for the selected context or the ordinary value.
        """
        return payload if field == name else ordinary

    # The custom scheme renders all line-number components.
    fs = Flowsheet(
        at("flowsheet name", "PLANT"),
        line_numbering_scheme="{size}-{schedule}-{service}-{sequence}-{spec}-{insulation}",
    )
    feed = fs.add(
        U.Feed(
            at("unit name", "F-1"),
            reference=at("off-page reference", "PFD-1"),
        )
    )
    pump = fs.add(U.Pump("P-101", description=at("unit description", "Feed pump")))
    product = fs.add(U.Product("Q-1"))
    fs.connect(feed.outlet, pump.suction, name=at("stream name", "S-1"))
    # An auto-named stream renders its line number.
    line = fs.connect(
        pump.discharge,
        product.inlet,
        size=at("line-number size", '6"'),
        schedule=at("line-number schedule", "40"),
        service=at("line-number service", "P"),
        sequence=at("line-number sequence", "1001"),
        spec=at("line-number spec", "A1A"),
        insulation=at("line-number insulation", "H"),
    )
    line.properties[at("stream property name", "Duty")] = at("stream property value", "12 kW")
    loop = fs.add_loop("F", at("loop number", "301"))
    fs.add_instrument("FT", loop, near=pump, at="N", offset=40)
    # A direct instrument accepts the selected tag.
    fs.add_instrument(at("instrument letters", "PI"), 205, near=product, at="N", offset=40)

    fs.title_block = TitleBlock(
        # A blank title renders the flowsheet-name fallback.
        title=at("title", ""),
        subtitle=at("subtitle", "Process Flow Diagram"),
        drawing_number=at("drawing number", "PFD-0001"),
        project=at("project", "A300"),
        client=at("client", "Acme"),
        company=at("company", "Contractor"),
        status=at("status", "ISSUED FOR REVIEW"),
        sheet=at("sheet", "1"),
        of_sheets=at("of sheets", "1"),
        scale=at("scale", "NTS"),
        drawn_by=at("drawn by", "AA"),
        checked_by=at("checked by", "BB"),
        approved_by=at("approved by", "CC"),
        date=at("date", "2026-01-01"),
        revisions=[Revision(rev=at("revision", "A"), date="2026-01-01", description="Issued")],
    )
    fs.annotations.append(equipment_list(fs, align="top-left"))
    fs.annotations.append(notes([at("note text", "Vent to flare.")]))
    fs.annotations.append(legend([("SS", at("legend entry", "316L"))]))
    fs.annotations.append(Annotation(title=at("annotation title", "REMARKS"), rows=["none"]))
    fs.annotations.append(
        TableBox(
            title=at("table title", "STREAMS"),
            headers=[at("table header", "Tag")],
            rows=[[at("table cell", "S-1")]],
            align="bottom-left",
        )
    )
    return fs


def _svg_document(payload: str, field: str) -> str:
    """Render a value through the SVG backend.

    Parameters
    ----------
    payload : str
        User-controlled value to render.
    field : str
        Name of the model field containing the value.

    Returns
    -------
    str
        Rendered SVG document.
    """
    return _plant(payload, field).to_svg(**RENDERED)


def _drawio_document(payload: str, field: str) -> str:
    """Render a value through the Draw.io backend.

    Parameters
    ----------
    payload : str
        User-controlled value to render.
    field : str
        Name of the model field containing the value.

    Returns
    -------
    str
        Rendered Draw.io XML document.
    """
    return _plant(payload, field).to_drawio(
        border="zone",
        diagram="p&id",
        connections="flanged",
        show_stream_table=True,
        check=False,
    )


def _parsed(document: str) -> ET.Element:
    """Parse XML or fail the current test.

    Parameters
    ----------
    document : str
        XML document to parse.

    Returns
    -------
    xml.etree.ElementTree.Element
        Parsed XML root element.
    """
    try:
        return ET.fromstring(document)
    except ET.ParseError as exc:
        pytest.fail(f"not well-formed XML: {exc}", pytrace=False)


def _carries_no_injected_markup(root: ET.Element) -> None:
    """Assert that XML contains no injected elements or attributes.

    Parameters
    ----------
    root : xml.etree.ElementTree.Element
        Parsed XML root element.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    for element in root.iter():
        for name in element.attrib:
            assert INJECTED not in name, f"{element.tag} carries an injected {name!r}"
        assert not element.tag.endswith("script"), "a payload became a <script> element"


def _every_reference_resolves(root: ET.Element) -> None:
    """Assert that SVG references name defined identifiers.

    Parameters
    ----------
    root : xml.etree.ElementTree.Element
        Parsed SVG root element.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    ids = {element.get("id") for element in root.iter() if element.get("id") is not None}
    for element in root.iter():
        for value in element.attrib.values():
            for ref in _URL.findall(value):
                assert ref in ids, f"url(#{ref}) names no id in the document"
        href = element.get("href") or element.get(_XLINK_HREF) or ""
        if href.startswith("#"):
            assert href[1:] in ids, f"href={href!r} names no id in the document"


@pytest.mark.parametrize("field", ESCAPE_CONTEXTS.values(), ids=tuple(ESCAPE_CONTEXTS))
def test_a_hostile_value_cannot_break_the_svg_document(field: str) -> None:
    """Verify SVG escaping in every rendered context.

    Parameters
    ----------
    field : str
        SVG renderer context containing the injection probe.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    svg = _svg_document(RENDER_PROBE, field)
    root = _parsed(svg)
    _carries_no_injected_markup(root)
    _every_reference_resolves(root)


@pytest.mark.parametrize("field", ESCAPE_CONTEXTS.values(), ids=tuple(ESCAPE_CONTEXTS))
def test_a_hostile_value_cannot_break_the_drawio_document(field: str) -> None:
    """Verify Draw.io escaping in every rendered context.

    Parameters
    ----------
    field : str
        Draw.io renderer context containing the injection probe.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    root = _parsed(_drawio_document(RENDER_PROBE, field))
    _carries_no_injected_markup(root)
    _carries_no_html_beyond_br(root)


def _carries_no_html_beyond_br(root: ET.Element) -> None:
    """Assert that Draw.io cell values contain no HTML markup.

    Parameters
    ----------
    root : xml.etree.ElementTree.Element
        Parsed Draw.io XML root element.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    for element in root.iter():
        value = element.get("value")
        if not value:
            continue
        bare = value.replace("<br>", "")
        assert "<" not in bare and ">" not in bare, (
            f"{element.tag} value={value!r} decodes to HTML markup draw.io "
            f"reads as a tag, not as the text it was given"
        )


@pytest.mark.parametrize("payload", PAYLOADS.values(), ids=list(PAYLOADS))
def test_escaped_hostile_content_is_safe_in_text_and_attributes(payload: str) -> None:
    """Verify hostile payloads are safe in XML text and attributes.

    Parameters
    ----------
    payload : str
        Hostile string accepted by the escaping primitive.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    content = escaped(payload)
    text = _parsed(f"<value>{content}</value>")
    attribute = _parsed(f'<value payload="{content}"/>')
    assert not list(text), payload
    assert text.text == writable(payload).replace("\r\n", "\n").replace("\r", "\n")
    assert list(attribute.attrib) == ["payload"]


def test_no_file_path_reaches_the_sheet(tmp_path):
    """Verify rendered output omits its output path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary output directory supplied by pytest.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    out = tmp_path / f"{INJECTED}.svg"
    _plant("ordinary", "flowsheet name").render(str(out))
    assert INJECTED not in out.read_text(encoding="utf-8")


# --- colour and dash: refused, not escaped ----------------------------


#: Invalid paint values representing markup, control-byte, and URL input.
HOSTILE_PAINTS = (
    PAYLOADS["element"],
    PAYLOADS["control characters"],
    PAYLOADS["url reference"],
)


@pytest.mark.parametrize("payload", HOSTILE_PAINTS)
@pytest.mark.parametrize("field", ["color", "dasharray"])
def test_a_paint_that_is_not_a_paint_is_refused(field, payload):
    """Verify invalid colour and dash values are rejected.

    Parameters
    ----------
    field : str
        Paint attribute under validation.
    payload : str
        Invalid paint value.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _plant("ordinary", "flowsheet name")
    with pytest.raises(ValueError) as raised:
        setattr(fs.streams[0], field, payload)
    assert field in str(raised.value)
    assert repr(payload) in str(raised.value)


@pytest.mark.parametrize(
    "color",
    [
        "#00aa77",
        "rgb(0, 170, 119)",
        "rebeccapurple",
    ],
)
def test_a_colour_that_is_a_colour_is_accepted(color):
    """Verify representative CSS colours are accepted.

    Parameters
    ----------
    color : str
        Valid CSS colour.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    check_color(color)


@pytest.mark.parametrize("dash", ["7,4", "9 3 2 3", "none"])
def test_a_dash_that_is_a_dash_is_accepted(dash):
    """Verify representative dash patterns are accepted.

    Parameters
    ----------
    dash : str
        Valid dash-array value.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    check_dasharray(dash)


def test_a_stream_keeps_the_paint_it_was_given():
    """Verify valid paint values are retained in SVG output.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _plant("ordinary", "flowsheet name")
    fs.streams[0].color = "#0a7"
    fs.streams[0].dasharray = "6,3"
    assert (fs.streams[0].color, fs.streams[0].dasharray) == ("#0a7", "6,3")
    svg = fs.to_svg(**RENDERED)
    assert 'stroke="#0a7"' in svg
    assert 'stroke-dasharray="6,3"' in svg


# --- ids ---------------------------------------------------------------


def test_a_marker_id_is_a_name_however_the_colour_is_spelled():
    """Verify colour-derived marker identifiers are valid XML names.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _plant("ordinary", "flowsheet name")
    fs.streams[0].color = "rgb(0, 170, 119)"
    root = _parsed(fs.to_svg(check=False))
    _every_reference_resolves(root)
    marker = arrow_marker_id("rgb(0, 170, 119)")
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", marker), marker
    assert f'id="{marker}"' in fs.to_svg(check=False)


def test_two_colours_never_share_one_marker():
    """Verify distinct colours use distinct marker identifiers.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert arrow_marker_id("rgb(1,2,3)") != arrow_marker_id("rgb(1, 2, 3)")


def test_an_ordinary_colour_keeps_the_id_it_always_had():
    """Verify ordinary colour identifiers remain stable.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert arrow_marker_id("black") == "arrow_black"
    assert arrow_marker_id("#0a7") == "arrow_0a7"


def test_ident_leaves_a_name_alone():
    """Verify identifier generation preserves valid names.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert ident("sym", "valve_control_s62.5x40") == "sym_valve_control_s62.5x40"


def test_ident_is_a_function_of_its_input_alone():
    """Verify identifier generation is deterministic.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert ident("arrow", "rgb(1, 2, 3)") == ident("arrow", "rgb(1, 2, 3)")


def test_the_two_spellings_of_a_name_character_agree():
    """Verify identifier character definitions agree.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    for code in range(0x80):
        char = chr(code)
        assert (char in _NAME_CHARS) is not bool(_UNSAFE_RUN.fullmatch(char)), repr(char)


# --- the escaper itself -------------------------------------------------


@pytest.mark.parametrize("value", ["P-101", "FT-301", "6 in", "Cl2", "中文"])
def test_escaping_ordinary_content_changes_nothing(value):
    """Verify ordinary text remains unchanged.

    Parameters
    ----------
    value : str
        Safe text value.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert escaped(value) == value


def test_escaping_writes_the_five_and_drops_the_unwritable():
    """Verify XML characters are escaped and control bytes are removed.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert escaped('A&B<C>"D"') == "A&amp;B&lt;C&gt;&quot;D&quot;"
    assert escaped("a\x00b\x08c") == "abc"
    assert writable("a\tb\nc\rd") == "a\tb\nc\rd"


def test_an_inch_mark_is_escaped_and_stays_escaped():
    """Verify inch marks remain escaped in line numbers.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    assert escaped('6"-P-1001-A1A') == "6&quot;-P-1001-A1A"
