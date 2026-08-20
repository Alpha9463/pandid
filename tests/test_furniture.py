"""Sheet furniture placement: independent of how the interpreter sums floats.

A box's measured width or height feeds straight back into where each of its
own pieces is drawn -- a :class:`~pandid.document.TableBox` column centred at
half its width, an annotation stacked at half a run's height -- so the
measurement and the drawing have to agree on the same float, to the bit.
CPython 3.12 gave the builtin ``sum()`` Neumaier-compensated summation
(gh-100425): more accurate, and a *different* last bit from the plain running
total :func:`~pandid.render.furniture.draw_table` keeps as it walks the
columns. A column whose widest cell is 5 characters is 48,1 units wide, and
half of that -- where a centred cell's text-anchor lands -- is an exact
``.1f`` rounding tie, so the same sheet drew 0,1 unit differently depending
only on which Python drew it. See issue #334, and the golden fixture
``tests/golden/19_absorber_stripper.svg``, which used to work around it by
choosing headers off the tie.
"""

import builtins

from pandid.document import TableBox

from test_golden import SCENARIOS


def _naive_sum(iterable, start=0):
    """The plain running total every Python before 3.12 gave ``sum()``,
    and every Python still gives a hand-rolled ``+=`` loop."""
    total = start
    for v in iterable:
        total += v
    return total


def _rendered_with(sum_impl, build, **kwargs) -> str:
    real_sum = builtins.sum
    builtins.sum = sum_impl
    try:
        return build().to_svg(**kwargs)
    finally:
        builtins.sum = real_sum


# The utilities table, and a page just wide enough that a bottom-right dock
# actually lands the tie: found by sweeping page widths against this table
# until compensated and naive summation disagreed, so it is not a value
# chosen to look right -- it is one shown to matter.
_TIED_TABLE = TableBox(
    title="UTILITIES SUMMARY",
    headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in", "T_out"],
    rows=[
        ["LP Steam", "E-403", "24700", "11.30", "152 C", "151 C"],
        ["Cooling Water", "E-402", "-4540", "72.4", "25 C", "40 C"],
    ],
    col_align=["l", "l", "r", "r", "c", "c"],
    align="bottom-right",
)


def test_a_docked_tables_own_column_centres_the_same_either_way():
    """:func:`~pandid.render.furniture.dock` places the box from its total
    width (:func:`~pandid.render.furniture.measure_table`); drawing it
    (:func:`~pandid.render.furniture.draw_table`) walks the same widths
    forward one column at a time. The two used to disagree by a bit
    whenever ``sum()`` was compensated, tipping the ``T_in``/``T_out``
    columns' centring the other way."""
    from pandid.render import furniture as F

    def render(sum_impl):
        real_sum = builtins.sum
        builtins.sum = sum_impl
        try:
            w, h = F.measure_table(_TIED_TABLE)
            placed, _frame, _free = F.dock(
                [(_TIED_TABLE, "bottom-right", w, h)], (0.0, 0.0, 50.0, 100.0)
            )
            box = placed[0]
            return "\n".join(F.draw_table(_TIED_TABLE, box.x, box.y))
        finally:
            builtins.sum = real_sum

    assert render(sum) == render(_naive_sum)


def test_the_absorber_stripper_scenario_renders_the_same_either_way():
    """The real reproduction: ``19_absorber_stripper``'s utilities table
    used to move 0,1 unit between a naive and a compensated ``sum()`` --
    the only scenario in the corpus exercising the five-character case,
    per the commit that worked around it before this fix removed the
    need to."""
    build, kwargs = SCENARIOS["19_absorber_stripper"]
    compensated = _rendered_with(sum, build, **kwargs)
    naive = _rendered_with(_naive_sum, build, **kwargs)
    assert compensated == naive
