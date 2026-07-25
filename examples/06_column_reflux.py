"""
Example 6: Distillation column with reflux and reboiler loops

Laid out the way a fractionation sheet is actually drawn: the column stands tall
on the left, its overhead condenser sits high and to the right with the reflux
drum beneath it, and the kettle reboiler hangs off the bottom of the tower. Both
loops close on the column itself, through its ``reflux_in`` and ``boilup_in``
return nozzles.

That arrangement is a drawing convention rather than something a topological
layout can infer, so the equipment is pinned. Everything else — routing, stream
numbering, labels — is automatic.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pfd import Flowsheet, units


def main():
    fs = Flowsheet("Column Overhead System")

    # --- Equipment -------------------------------------------------------
    feed = fs.add(units.Feed("Feed", reference="PFD-100"))
    col = fs.add(units.Column("T-701", description="Main Fractionator"))

    # Overhead: a horizontal shell-and-tube condenser over a horizontal drum.
    # Both keep close to their symbols' native proportions — scaling a symbol
    # far past its drawn aspect is what makes a sheet look wrong.
    cond = fs.add(units.HeatExchanger("E-701", variant="straight_tubes", width=120,
                                      height=36, description="Overhead Condenser"))
    drum = fs.add(units.Vessel("V-701", variant="horizontal", width=130, height=42,
                               description="Reflux Drum"))
    # The condenser drains straight down into the drum, so take the inlet on the
    # drum's top face instead of its left head — otherwise the line has to hook
    # back on itself to reach the head.
    drum.port_face("inlet", "N")
    vent = fs.add(units.Product("Vent Gas", reference="PFD-900"))
    split = fs.add(units.Splitter("SP-701", n_outlets=2, description="Reflux Split"))
    dist = fs.add(units.Product("Distillate", reference="PFD-200"))

    # Bottoms: the sump draw splits — most of it recirculates through the kettle
    # reboiler and returns as boilup, the rest leaves as bottoms product.
    bsplit = fs.add(units.Splitter("SP-702", n_outlets=2, description="Bottoms Split"))
    reb = fs.add(units.HeatExchanger("E-702", variant="kettle", width=120, height=44,
                                     description="Kettle Reboiler"))
    bot = fs.add(units.Product("Bottoms", reference="PFD-300"))

    # --- Placement -------------------------------------------------------
    # Equipment is positioned by NOZZLE, not by its top-left corner: a port sits
    # at a fixed fraction of its symbol's box, so lining two items up means
    # matching those fractions. Every run below is either dead straight or a
    # single corner — the only two-corner run is the tower overhead, where both
    # the distillate and the condenser inlet face upward and the line has no
    # choice but to rise, cross and drop.
    col_x, col_y = 300, 260
    col.pin(x=col_x, y=col_y)
    feed.pin(x=90, y=col_y + 105)            # flag tip y+25 meets the feed nozzle

    # Condenser, mirrored so it drains towards the drum: vapour enters the top
    # shell nozzle at x + 0.25w, condensate leaves the bottom one at x + 0.75w.
    cond_x, cond_y, cond_w = 560, 70, 120
    cond.pin(x=cond_x, y=cond_y, mirrored="x")
    cond_drain_x = cond_x + 0.75 * cond_w

    # Drum hung so its top inlet (20/91.5 along the shell) sits directly under
    # the condenser drain — that run is then a straight drop.
    drum_w, drum_y = 130, 170
    drum.pin(x=cond_drain_x - (20 / 91.5) * drum_w, y=drum_y)
    drum_x = cond_drain_x - (20 / 91.5) * drum_w
    drum_draw_x = drum_x + (68 / 91.5) * drum_w        # bottom liquid draw
    vent.pin(x=880, y=100)                             # flag tip clears the condenser

    # Turned a quarter turn: inlet up, both outlets down. Placed so its inlet is
    # under the drum's draw (another straight drop), and high enough that reflux
    # drops to the tower's reflux nozzle rather than having to climb back up.
    split_y = 240
    split.pin(x=drum_draw_x - 25, y=split_y, orientation=90)
    dist.pin(x=900, y=315)

    # Kettle off the tower bottom. Its shell inlet faces down, so the sump
    # splitter sits below it and the line rises into the nozzle.
    reb_x, reb_y = 660, 512
    reb.pin(x=reb_x, y=reb_y)
    bsplit.pin(x=520, y=590)
    bot.pin(x=900, y=600)                              # level with the sump draw

    # --- Connections -----------------------------------------------------
    fs.connect(feed.outlet, col.feed)

    fs.connect(col.distillate, cond.hot_in)
    fs.connect(cond.hot_out, drum.inlet)
    fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.outlet, split.inlet)
    fs.connect(split.out_1, dist.inlet)
    fs.connect(split.out_2, col.reflux_in, tear_hint=True)   # reflux to the tower

    fs.connect(col.bottoms, bsplit.inlet)
    fs.connect(bsplit.out_1, reb.cold_in)                    # recirculate to the kettle
    fs.connect(reb.cold_out, col.boilup_in, tear_hint=True)  # boilup to the tower
    fs.connect(bsplit.out_2, bot.inlet)

    fs.render(out("column_reflux.svg"))
    print("Generated column_reflux.svg")


if __name__ == "__main__":
    main()
