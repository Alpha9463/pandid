"""
Example 12: Block flow diagram (pinned)

The drawing a level above the PFD: one labelled box per plant section, the
streams between them named, and nothing inside them drawn. `units.Block` is the
only symbol on such a sheet.

Two things it shows that no other example can.

**Connections on all four sides.** `inputs=` and `outputs=` are one face per
connection, in order, so air and steam enter the reformer from *above* while the
gas comes in from the left, the CO2 leaves the top of the removal section, and
the synthesis loop takes its recycle back in from *below*. A plain count is the
shorthand for the usual case: `inputs=1` is one connection on the west.

**The box sizes itself.** Nothing here carries a `width` or a `height`. Each box
is as wide as its own name and as tall as the connections on its walls need,
spread at a pitch that keeps two arrowheads from touching. `Shift & CO2 Removal`
comes out wider than `Reforming` because its name is longer, not because anyone
said so.

**Why it is pinned.** The layout engine ranks units by process flow order and
does not yet know that a connection on the north face wants its source *above*
it (issue #168), so a BFD left to lay itself out sends those streams up and over
the sheet. Pinning is the answer until that is fixed, and a BFD is the drawing
most worth pinning anyway: the reader is meant to see the plant in a row.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units


def main():
    fs = Flowsheet("Ammonia Plant - Block Flow Diagram")

    # --- The sections ----------------------------------------------------
    # One box per section, in a row, at one elevation. Each declares the side
    # of the box every connection is on; nothing declares a size.
    reforming = fs.add(
        units.Block("Reforming", inputs=["W", "N", "N"], outputs=["E"])
    ).pin(x=260, y=340)
    shift = fs.add(
        units.Block("Shift & CO2 Removal", inputs=1, outputs=["E", "N"])
    ).pin(x=520, y=340)
    synthesis = fs.add(
        units.Block("Synthesis Loop", inputs=["W", "S"], outputs=["E", "S"])
    ).pin(x=830, y=340)
    refrigeration = fs.add(
        units.Block("Refrigeration", inputs=1, outputs=["E", "W"])
    ).pin(x=1080, y=340)

    # --- Where the sheet ends --------------------------------------------
    # The two above the row feed the reformer's north wall; the two below take
    # what the loop rejects.
    natural_gas = fs.add(units.Feed("Natural Gas")).pin(x=60, y=355)
    air = fs.add(units.Feed("Air")).pin(x=180, y=180)
    steam = fs.add(units.Feed("Steam")).pin(x=330, y=180)
    co2 = fs.add(units.Product("CO2 to Urea")).pin(x=560, y=170)
    ammonia = fs.add(units.Product("Liquid NH3")).pin(x=1300, y=355)
    purge = fs.add(units.Product("Purge Gas")).pin(x=1000, y=560)

    # --- The streams -----------------------------------------------------
    # A BFD numbers its streams and says nothing else about them; the flow
    # rates and compositions live in a mass balance table beside the drawing.
    fs.connect(natural_gas.outlet, reforming.in_1)
    fs.connect(air.outlet, reforming.in_2)               # in on the north face
    fs.connect(steam.outlet, reforming.in_3)             # ...and the second one
    fs.connect(reforming.out_1, shift.in_1)
    fs.connect(shift.out_2, co2.inlet)                   # out of the top
    fs.connect(shift.out_1, synthesis.in_1)
    fs.connect(synthesis.out_1, refrigeration.in_1)
    fs.connect(refrigeration.out_1, ammonia.inlet)
    fs.connect(refrigeration.out_2, synthesis.in_2)      # recycle, in from below
    fs.connect(synthesis.out_2, purge.inlet)

    fs.render(out("block_flow_diagram.svg"))
    print("Generated block_flow_diagram.svg")


if __name__ == "__main__":
    main()
