"""
Example 11: Block flow diagram (pinned)

One `units.Block` per plant section, sized to its name and connections.
`inputs=` and `outputs=` give one face per connection (a count puts
them all on the west or east); `order_on` orders a wall's connections.
`diagram="bfd"` has `validate()` check the sheet as a block flow diagram.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Block, Feed, Flowsheet, Product


def main():
    fs = Flowsheet("Ammonia Plant - Block Flow Diagram")

    # --- The sections -------------------------------------------------
    reforming = fs.add(
        Block("Reforming", inputs=["W", "N", "N"], outputs=["E"])
    ).pin(x=260, y=340)
    shift = fs.add(
        Block("Shift & CO2 Removal", inputs=1, outputs=["E", "N"])
    ).pin(x=520, y=340)
    synthesis = fs.add(
        Block("Synthesis Loop", inputs=["W", "S"], outputs=["E", "S"])
    ).pin(x=830, y=340)
    # Purge west of the recycle on the south wall.
    synthesis.order_on("S", [synthesis.out_2, synthesis.in_2])
    refrigeration = fs.add(
        Block("Refrigeration", inputs=1, outputs=["E", "S"])
    ).pin(x=1080, y=340)

    # --- Where the sheet ends -----------------------------------------
    natural_gas = fs.add(Feed("Natural Gas")).pin(x=110, y=380)
    air = fs.add(Feed("Air")).pin(x=230, y=205)
    steam = fs.add(Feed("Steam")).pin(x=380, y=205)
    co2 = fs.add(Product("CO2 to Urea")).pin(x=560, y=195)
    ammonia = fs.add(Product("Liquid NH3")).pin(x=1300, y=380)
    purge = fs.add(Product("Purge Gas")).pin(x=975, y=515)

    # --- The streams --------------------------------------------------
    fs.connect(natural_gas.outlet, reforming.in_1)
    fs.connect(air.outlet, reforming.in_2)               # in on the north face
    fs.connect(steam.outlet, reforming.in_3)             # ...and the second one
    fs.connect(reforming.out_1, shift.in_1)
    fs.connect(shift.out_2, co2.inlet)                   # out of the top
    fs.connect(shift.out_1, synthesis.in_1)
    fs.connect(synthesis.out_1, refrigeration.in_1)
    fs.connect(refrigeration.out_1, ammonia.inlet)
    fs.connect(refrigeration.out_2, synthesis.in_2)      # recycle, bottom to bottom
    fs.connect(synthesis.out_2, purge.inlet)

    fs.render(out("block_flow_diagram.svg"), diagram="bfd")
    print("Generated block_flow_diagram.svg")


if __name__ == "__main__":
    main()
