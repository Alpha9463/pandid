"""Check that furniture placement does not depend on how the interpreter sums floats."""

import builtins

from pandid.document import TableBox

from test_golden import SCENARIOS


def _naive_sum(iterable, start=0):
    """Return the running total a plain ``+=`` loop gives."""
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


# The utilities table, and a page width at which the bottom-right dock lands the tie.
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
    """Check that a docked table's own column centres the same either way."""
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
    """Check that the absorber-stripper sheet renders the same either way."""
    build, kwargs = SCENARIOS["19_absorber_stripper"]
    compensated = _rendered_with(sum, build, **kwargs)
    naive = _rendered_with(_naive_sum, build, **kwargs)
    assert compensated == naive
