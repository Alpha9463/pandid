"""
Example 8: Building a flowsheet from data

Every other example writes Python. This one writes *data*: one plain mapping —
the same thing you would keep in a YAML or JSON file next to the equipment list
it came from — handed to ``Flowsheet.from_dict``. Nothing else about the engine
changes; layout, routing and stream numbering all run exactly as before.

    fs = Flowsheet.from_dict(SPEC)      # a dict, from anywhere
    fs = Flowsheet.from_json("bfw.json")
    fs = Flowsheet.from_yaml("bfw.yaml")   # needs: pip install 'chem-pfd[yaml]'
    spec = fs.to_dict()                 # writes the same spec back out

The process is a boiler feedwater package: makeup water is strained and joins
returning condensate in the pump suction header, a spillback keeps the pump
above its minimum flow, and the deaerator's level controller throttles the feed
to the boiler.

Placement is left to the engine here, because that is the point of authoring
from data — you supply the equipment list and the connectivity, not pixel
coordinates. The format does carry ``pin`` (with ``orientation``, ``mirrored``
and ``col``/``row``) and ``port_faces`` for sheets drawn to a convention; see
the README, and examples 03, 06 and 07 for what those overrides are for.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pfd import Flowsheet

SPEC = {
    "name": "Boiler Feedwater Package",
    # --- Equipment list --------------------------------------------------
    # ``kind`` is the equipment class, ``variant`` the drawn style within it.
    # Boundary flags carry the drawing their stream comes from / goes to.
    "units": [
        {"kind": "Feed", "name": "Makeup Water", "reference": "PFD-100"},
        {"kind": "Fitting", "name": "ST-201", "variant": "strainer",
         "description": "Makeup Water Strainer"},
        {"kind": "Feed", "name": "Condensate Return", "reference": "PFD-400"},
        {"kind": "Mixer", "name": "M-201", "n_inlets": 3, "description": "BFW Suction Header"},
        {"kind": "Pump", "name": "P-201A/B", "description": "Boiler Feedwater Pump"},
        {"kind": "Splitter", "name": "SP-201", "n_outlets": 2, "description": "Minimum-Flow Tee"},
        {"kind": "Valve", "name": "FV-201", "variant": "control",
         "description": "Minimum-Flow Spillback Valve"},
        # The drum is fed over the top tray rather than through its left head,
        # so its inlet is moved to the north face.
        {"kind": "Vessel", "name": "V-201", "variant": "horizontal", "width": 150, "height": 48,
         "description": "Deaerator Drum", "port_faces": {"inlet": "N"}},
        {"kind": "Vent", "name": "VT-201", "description": "Deaerator Vent Stack"},
        {"kind": "Valve", "name": "LV-201", "variant": "control",
         "description": "Deaerator Level Control Valve"},
        {"kind": "Product", "name": "To Boiler", "reference": "PFD-500"},
    ],
    # --- Instrumentation -------------------------------------------------
    # ``on``/``at``/``offset`` anchor the balloon to what it measures; its tag
    # is "LIC-201", so that is how the connection below names it.
    "instruments": [
        {"type": "LIC", "number": 201, "variant": "panel",
         "description": "Deaerator Level Control", "on": "V-201", "at": "S", "offset": 110},
    ],
    # --- Stream table ----------------------------------------------------
    # Each connection is a pair of named nozzles, plus whatever the simulation
    # reported for that line. Property values carry their own units.
    "streams": [
        {"from": ["Makeup Water", "outlet"], "to": ["ST-201", "inlet"],
         "properties": {"Temperature": "25 C", "Pressure": "4.0 barg",
                        "Mass Flow": "12.0 t/h", "Dissolved O2": "8000 ppb"}},
        {"from": ["ST-201", "outlet"], "to": ["M-201", "in_1"],
         "properties": {"Temperature": "25 C", "Pressure": "3.8 barg",
                        "Mass Flow": "12.0 t/h", "Dissolved O2": "8000 ppb"}},
        {"from": ["Condensate Return", "outlet"], "to": ["M-201", "in_2"],
         "properties": {"Temperature": "88 C", "Pressure": "3.5 barg",
                        "Mass Flow": "48.0 t/h", "Dissolved O2": "150 ppb"}},
        {"from": ["M-201", "outlet"], "to": ["P-201A/B", "suction"],
         "properties": {"Temperature": "76 C", "Pressure": "3.4 barg",
                        "Mass Flow": "66.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["P-201A/B", "discharge"], "to": ["SP-201", "inlet"],
         "properties": {"Temperature": "77 C", "Pressure": "12.0 barg",
                        "Mass Flow": "66.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["SP-201", "out_1"], "to": ["V-201", "inlet"],
         "properties": {"Temperature": "77 C", "Pressure": "11.6 barg",
                        "Mass Flow": "60.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["SP-201", "out_2"], "to": ["FV-201", "inlet"],
         "properties": {"Temperature": "77 C", "Pressure": "11.6 barg",
                        "Mass Flow": "6.0 t/h", "Dissolved O2": "1600 ppb"}},
        # The spillback closes the loop, so nominate it as the tear: without the
        # hint the cycle could be broken at the pump instead.
        {"from": ["FV-201", "outlet"], "to": ["M-201", "in_3"], "tear_hint": True,
         "properties": {"Temperature": "77 C", "Pressure": "3.4 barg",
                        "Mass Flow": "6.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["V-201", "vent"], "to": ["VT-201", "inlet"],
         "properties": {"Temperature": "105 C", "Pressure": "0.2 barg",
                        "Mass Flow": "0.3 t/h", "Dissolved O2": "-"}},
        {"from": ["V-201", "outlet"], "to": ["LV-201", "inlet"],
         "properties": {"Temperature": "105 C", "Pressure": "0.2 barg",
                        "Mass Flow": "59.7 t/h", "Dissolved O2": "7 ppb"}},
        {"from": ["LV-201", "outlet"], "to": ["To Boiler", "inlet"],
         "properties": {"Temperature": "105 C", "Pressure": "0.1 barg",
                        "Mass Flow": "59.7 t/h", "Dissolved O2": "7 ppb"}},
        # The controller output lands on the valve's actuator, as a signal line.
        {"from": ["LIC-201", "sig_out"], "to": ["LV-201", "actuator"], "kind": "electric"},
    ],
    "stream_table_sections": [["Dissolved O2", "Water Quality"]],
    # --- Sheet furniture -------------------------------------------------
    "title_block": {
        "title": "Utilities U200",
        "subtitle": "Boiler Feedwater Package",
        "drawing_number": "PFD-2001",
        "project": "Steam System Upgrade",
        "company": "THE UNIVERSITY OF QUEENSLAND",
        "status": "ISSUED FOR REVIEW",
        "sheet": "1", "of_sheets": "2",
        "drawn_by": "A. Anderson", "checked_by": "J. Smith", "approved_by": "R. Lee",
        "revisions": [
            {"rev": "A", "date": "2026-05-18", "description": "Issued for internal review",
             "by": "AA"},
            {"rev": "B", "date": "2026-07-02", "description": "Added minimum-flow spillback",
             "by": "AA", "checked": "JS", "approved": "RL"},
        ],
    },
    "annotations": [
        {"type": "equipment_list", "align": "top-right"},
        {"type": "notes", "align": "top-right", "items": [
            "Deaerator vent to atmosphere; no isolation permitted.",
            "FV-201 maintains P-201A/B above 10% of rated flow.",
            "Dissolved oxygen sampled downstream of LV-201.",
        ]},
        {"type": "legend", "align": "top-left", "margin": 6, "entries": {
            "BFW": "Boiler Feedwater",
            "DA": "Deaerator",
            "NTS": "Not To Scale",
        }},
    ],
}


def main():
    fs = Flowsheet.from_dict(SPEC)

    # The format round-trips, so a sheet tweaked in Python can be handed back to
    # whoever maintains the data file — ``json.dump(fs.to_dict(), f)`` and done.
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()

    fs.render(out("from_data.svg"), show_stream_table=True, styling="pid")
    print("Generated from_data.svg")


if __name__ == "__main__":
    main()
