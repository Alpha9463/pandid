"""
Example 6: Distillation column with reflux and reboiler loops

The column stands tall on the left, its overhead condenser high and to
the right with the reflux drum beneath it, and the kettle reboiler off
the bottom of the tower. Both loops close on the column's ``reflux_in``
and ``boilup_in`` nozzles, and the bottoms leaves from the reboiler's
own weir draw.

That arrangement is a drawing convention rather than something a
topological layout can infer, so the equipment is pinned. Routing,
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
    # Baffle trays: a main fractionator takes a hot, wide-boiling,
    # coke-forming feed, and a shed deck is what goes in there because
    # it has no perforation to plug and no valve to stick. They are
    # inefficient, so the tower is few decks and tall sections.
    col = fs.add(DistillationColumn("T-701", internals="baffle_tray", trays=10,
                                    description="Main Fractionator"))

    # width/height stay close to each symbol's native proportions:
    # scaling one far past its drawn aspect is what makes a sheet look
    # wrong.
    cond = fs.add(ShellAndTubeExchanger("E-701", variant="straight_tubes", width=120,
                                        height=36, description="Overhead Condenser"))
    # The drum's inlet is authored on three faces and the engine picks
    # the top one unaided, so nothing here has to override it.
    drum = fs.add(Vessel("V-701", variant="horizontal", width=130, height=42,
                         description="Reflux Drum"))
    vent = fs.add(Product("Vent Gas", reference="PFD-900"))
    split = fs.add(Splitter("SP-701", n_outlets=2, description="Reflux Split"))
    dist = fs.add(Product("Distillate", reference="PFD-200"))

    reb = fs.add(KettleReboiler("E-702", width=120, height=44,
                                description="Kettle Reboiler"))
    bot = fs.add(Product("Bottoms", reference="PFD-300"))

    # --- Placement ----------------------------------------------------
    # A port sits at a fixed fraction of its symbol's box, so lining two
    # items up means matching those fractions rather than measuring.
    col_x, col_y = 300, 260
    col.pin(x=col_x, y=col_y)
    # The feed nozzle's elevation is asked of the symbol rather than
    # measured, and the flag is pinned by its own tip, so the two meet
    # without any arithmetic in between.
    feed.pin(x=140, y=col_y + port_offset(col, "feed")[1])

    # Mirrored so vapour enters the top shell nozzle at x + 0.25w and
    # the condensate leaves the bottom one at x + 0.75w, over the drum.
    cond_x, cond_y, cond_w = 560, 70, 120
    cond.pin(x=cond_x, y=cond_y, mirrored="x")
    cond_drain_x = cond_x + 0.75 * cond_w

    # Drum hung so its top inlet (20/91.5 along the shell) sits directly
    # under the condenser drain, which makes that run a straight drop.
    drum_w, drum_y = 130, 170
    drum.pin(x=cond_drain_x - (20 / 91.5) * drum_w, y=drum_y)
    drum_x = cond_drain_x - (20 / 91.5) * drum_w
    drum_draw_x = drum_x + (68 / 91.5) * drum_w        # bottom liquid draw
    vent.pin(x=880, y=125)                             # flag tip clears the condenser

    # Turned a quarter turn: inlet up, both outlets down. Placed so its
    # inlet is under the drum's draw, and high enough that reflux drops
    # to the tower's reflux nozzle rather than climbing back up.
    split_y = 240
    split.pin(x=drum_draw_x - 25, y=split_y, orientation=90)
    dist.pin(x=900, y=340)

    # Kettle off the tower bottom. Its shell inlet faces down, so the
    # sump line drops out of the tower, runs across and rises into the
    # nozzle.
    reb.pin(x=660, y=512)
    bot.pin(x=900, y=645)                              # below the kettle's draw

    # --- Connections --------------------------------------------------
    fs.connect(feed.outlet, col.feed)

    fs.connect(col.overhead, cond.shell_in)
    fs.connect(cond.shell_out, drum.inlet)
    fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.outlet, split.inlet)
    fs.connect(split.out_1, dist.inlet)
    fs.connect(split.out_2, col.reflux_in, draw_as_recycle=True)

    fs.connect(col.bottoms, reb.shell_in)
    fs.connect(reb.shell_out, col.boilup_in, draw_as_recycle=True)
    fs.connect(reb.bottoms, bot.inlet)

    fs.render(out("column_reflux.svg"))
    print("Generated column_reflux.svg")


if __name__ == "__main__":
    main()
