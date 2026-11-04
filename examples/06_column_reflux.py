"""
Example 6: Distillation column with reflux and reboiler loops

A column with its overhead condenser and reflux drum, a kettle reboiler
off the bottom, and two side draws. The equipment is pinned; routing,
stream numbering and labels are automatic.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    DistillationColumn,
    Feed,
    Flowsheet,
    KettleReboiler,
    Product,
    ShellAndTubeExchanger,
    Splitter,
    Vessel,
)
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Column Overhead System")

    # --- Equipment ----------------------------------------------------
    feed = fs.add(Feed("Feed", reference="PFD-100"))
    # Trays count from the top: feed on tray 10, side draws on 6 and 8.
    col = fs.add(DistillationColumn("T-701", internals="baffle_tray", trays=10,
                                    feed_stages=[10], n_draws=2, draw_stages=[6, 8],
                                    description="Main Fractionator"))
    light = fs.add(Product("Light Cycle Oil", reference="PFD-400"))
    heavy = fs.add(Product("Heavy Cycle Oil", reference="PFD-500"))

    cond = fs.add(ShellAndTubeExchanger("E-701", variant="straight_tubes", width=120,
                                        height=36, description="Overhead Condenser"))
    drum = fs.add(Vessel("V-701", variant="horizontal", width=130, height=42,
                         description="Reflux Drum"))
    vent = fs.add(Product("Vent Gas", reference="PFD-900"))
    split = fs.add(Splitter("SP-701", n_outlets=2, description="Reflux Split"))
    dist = fs.add(Product("Distillate", reference="PFD-200"))

    reb = fs.add(KettleReboiler("E-702", width=120, height=44,
                                description="Kettle Reboiler"))
    bot = fs.add(Product("Bottoms", reference="PFD-300"))

    # --- Placement ----------------------------------------------------
    col_x, col_y = 300, 260
    col.pin(x=col_x, y=col_y)
    # Pin the flag's tip level with the column's feed nozzle.
    feed.pin(x=140, y=col_y + port_offset(col, "feed")[1])
    light.pin(x=900, y=430)
    heavy.pin(x=900, y=500)

    # Mirrored so vapour enters the top shell nozzle at x + 0.25w and
    # the condensate leaves the bottom one at x + 0.75w, over the drum.
    cond_x, cond_y, cond_w = 560, 70, 120
    cond.pin(x=cond_x, y=cond_y, mirrored="x")
    cond_drain_x = cond_x + 0.75 * cond_w

    # Drum's top inlet (20/91.5 along the shell) under the condenser drain.
    drum_w, drum_y = 130, 170
    drum.pin(x=cond_drain_x - (20 / 91.5) * drum_w, y=drum_y)
    drum_x = cond_drain_x - (20 / 91.5) * drum_w
    drum_draw_x = drum_x + (68 / 91.5) * drum_w        # bottom liquid draw
    vent.pin(x=880, y=125)                             # flag tip clears the condenser

    # Splitter turned inlet up, under the drum's draw.
    split_y = 240
    split.pin(x=drum_draw_x - 25, y=split_y, orientation=90)
    dist.pin(x=900, y=340)

    # Kettle off the tower bottom.
    reb.pin(x=660, y=512)
    bot.pin(x=900, y=645)                              # below the kettle's draw

    # --- Connections --------------------------------------------------
    feed_in = fs.connect(feed.outlet, col.feed)

    fs.connect(col.overhead, cond.shell_in)
    fs.connect(cond.shell_out, drum.inlet)
    vent_out = fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.outlet, split.inlet)
    dist_out = fs.connect(split.out_1, dist.inlet)
    fs.connect(split.out_2, col.reflux_in, draw_as_recycle=True)

    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in, draw_as_recycle=True)
    bot_out = fs.connect(reb.bottoms, bot.inlet)
    light_out = fs.connect(col.draws[0], light.inlet)
    heavy_out = fs.connect(col.draws[1], heavy.inlet)

    # The products add up to the feed.
    feed_in.properties = {"Flow (kg/h)": "10000"}
    vent_out.properties = {"Flow (kg/h)": "200"}
    dist_out.properties = {"Flow (kg/h)": "4000"}
    light_out.properties = {"Flow (kg/h)": "1200"}
    heavy_out.properties = {"Flow (kg/h)": "800"}
    bot_out.properties = {"Flow (kg/h)": "3800"}

    fs.render(out("column_reflux.svg"), show_stream_table=True)
    print("Generated column_reflux.svg")


if __name__ == "__main__":
    main()
