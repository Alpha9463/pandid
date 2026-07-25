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
    # The tower sets the datum; everything else hangs off it. Nozzle offsets are
    # spelled out so the runs come out straight rather than stepping: a symbol's
    # port sits at a fixed fraction of its box, so aligning two pieces of
    # equipment means matching those offsets, not their top-left corners.
    col_x, col_y, col_h = 300, 260, 200

    feed.pin(x=90, y=col_y + 105)            # feed flag's tip is at y+25; nozzle y+130
    col.pin(x=col_x, y=col_y)

    # Condenser: vapour in the top shell nozzle (x + 0.75w), condensate out the
    # bottom one (x + 0.25w). Sits above the drum, both right of the tower.
    cond.pin(x=560, y=70)
    cond_out_x = 560 + 0.25 * 120            # = 590

    # Drum inlet is on its top face (see port_face above), 20/91.5 along.
    drum.pin(x=cond_out_x - 0.219 * 130, y=200)   # top inlet lands under cond_out
    drum_out_x = (cond_out_x - 0.219 * 130) + 0.743 * 130   # bottom draw, 68/91.5
    vent.pin(x=880, y=178)

    # Turned a quarter turn so the inlet faces up and both outlets face down:
    # the drum drains straight into it, and reflux drops out and runs back to
    # the tower instead of leaving sideways and doubling around.
    split.pin(x=drum_out_x - 25, y=300, orientation=90)
    dist.pin(x=900, y=395)

    bsplit.pin(x=520, y=col_y + col_h + 60)  # sump draw splits below the tower
    reb.pin(x=660, y=col_y + col_h + 52)     # kettle off the tower bottom
    bot.pin(x=900, y=col_y + col_h + 150)

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
