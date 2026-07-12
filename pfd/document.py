"""Drawing documentation — the P&ID title block and revision history.

Attach a :class:`TitleBlock` to a flowsheet (``fs.title_block = TitleBlock(...)``)
and render with ``styling="pid"`` to draw a standard engineering title block
(drawing number, sheet, scale, drawn/checked/approved) plus a revision-history
table — the metadata ISO 10628 / typical P&ID sheets require.
"""

from dataclasses import dataclass, field


@dataclass
class Revision:
    """One row of the revision history."""
    rev: str = ""
    date: str = ""
    description: str = ""
    by: str = ""


@dataclass
class TitleBlock:
    """Title-block metadata for a drawing sheet."""
    title: str = ""
    drawing_number: str = ""
    project: str = ""
    client: str = ""
    sheet: str = "1"
    of_sheets: str = "1"
    scale: str = "NTS"
    drawn_by: str = ""
    checked_by: str = ""
    approved_by: str = ""
    date: str = ""
    revisions: list[Revision] = field(default_factory=list)
