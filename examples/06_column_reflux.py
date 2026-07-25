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
    cond = fs.add(units.HeatExchanger("E-701", variant="shell_tube", width=110,
                                      height=110, description="Overhead Condenser"))
    drum = fs.add(units.Vessel("V-701", variant="horizontal", width=130, height=44,
                               description="Reflux Drum"))
    # The condenser drains straight down into the drum, so take the inlet on the
    # drum's top face instead of its left head — otherwise the line has to hook
    # back on itself to reach the head.
    drum.port_face("inlet", "N")
    vent = fs.add(units.Product("Vent Gas", reference="PFD-900"))
    pump = fs.add(units.Pump("P-701", description="Reflux Pump"))
    split = fs.add(units.Splitter("SP-701", n_outlets=2, description="Reflux Split"))
    dist = fs.add(units.Product("Distillate", reference="PFD-200"))

    # Bottoms: the sump draw splits — most of it recirculates through the kettle
    # reboiler and returns as boilup, the rest leaves as bottoms product.
    bsplit = fs.add(units.Splitter("SP-702", n_outlets=2, description="Bottoms Split"))
    reb = fs.add(units.HeatExchanger("E-702", variant="kettle", width=150, height=54,
                                     description="Kettle Reboiler"))
    bot = fs.add(units.Product("Bottoms", reference="PFD-300"))

    # --- Placement -------------------------------------------------------
    # The tower sets the datum; everything else hangs off it.
    col_x, col_y, col_h = 300, 260, 200

    feed.pin(x=90, y=col_y + 105)           # the feed nozzle sits at col_y + 130
    col.pin(x=col_x, y=col_y)

    ovhd_y = col_y - 190                    # condenser rides above the tower top
    cond.pin(x=620, y=ovhd_y)
    drum.pin(x=600, y=ovhd_y + 150)         # drum directly under the condenser
    vent.pin(x=900, y=ovhd_y + 138)

    # Pump sits under the drum's bottom draw so the suction line drops straight.
    pump.pin(x=690, y=ovhd_y + 260)
    split.pin(x=860, y=ovhd_y + 252)
    dist.pin(x=1020, y=ovhd_y + 257)

    bsplit.pin(x=520, y=col_y + col_h + 55)  # sump draw splits below the tower
    reb.pin(x=680, y=col_y + col_h + 35)     # reboiler off the tower bottom
    bot.pin(x=940, y=col_y + col_h + 130)

    # --- Connections -----------------------------------------------------
    fs.connect(feed.outlet, col.feed)

    fs.connect(col.distillate, cond.hot_in)
    fs.connect(cond.hot_out, drum.inlet)
    fs.connect(drum.vent, vent.inlet)
    fs.connect(drum.outlet, pump.suction)
    fs.connect(pump.discharge, split.inlet)
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
