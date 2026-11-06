"""
Example 7: Building a flowsheet from data

The sheet is one plain mapping handed to ``Flowsheet.from_dict``; the
same spec loads from ``Flowsheet.from_json`` or ``Flowsheet.from_yaml``
(``pip install 'pandid[yaml]'``), and ``fs.to_dict()`` writes it back.

A boiler feedwater package: makeup water joins condensate in the pump
suction header, a spillback keeps the pump above its minimum flow, and
the deaerator's level controller throttles the feed to the boiler.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet

SPEC = {
    "name": "Boiler Feedwater Package",
    # --- Equipment list -----------------------------------------------
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
        {"kind": "Deaerator", "name": "V-201", "description": "Deaerator"},
        {"kind": "Vent", "name": "VT-201", "description": "Deaerator Vent Stack"},
        # Pin only the flip; the engine places the valve.
        {"kind": "Valve", "name": "CV-201", "variant": "control",
         "description": "Deaerator Level Control Valve", "pin": {"mirrored": "y"}},
        {"kind": "Product", "name": "To Boiler", "reference": "PFD-500"},
    ],
    # --- Instrumentation ----------------------------------------------
    # sensing and acting_on draw a line to the anchor; near draws none.
    "instruments": [
        {"type": "LT", "number": 201, "description": "Deaerator Level Transmitter",
         "sensing": "V-201", "face": "S", "offset": 58, "port_faces": {"sig_out": "S"}},
        # Directly below the transmitter.
        {"type": "LIC", "number": 201, "display": "central",
         "description": "Deaerator Level Control", "near": "V-201", "face": "S",
         "offset": 140, "port_faces": {"sig_in": "N"}},
        {"type": "LV", "number": 201, "description": "Level Valve I/P Transducer",
         "acting_on": "CV-201", "face": "S", "offset": 58,
         "port_faces": {"sig_in": "W", "sig_out": "N"}},
    ],
    # --- Stream table -------------------------------------------------
    "streams": [
        {"from": ["Makeup Water", "outlet"], "to": ["ST-201", "inlet"],
         "properties": {"Temperature": "25 C", "Pressure": "4.0 barg",
                        "Mass Flow": "12.0 t/h", "Dissolved O2": "8000 ppb"}},
        {"from": ["ST-201", "outlet"], "to": ["M-201", "in_2"],
         "properties": {"Temperature": "25 C", "Pressure": "3.8 barg",
                        "Mass Flow": "12.0 t/h", "Dissolved O2": "8000 ppb"}},
        {"from": ["Condensate Return", "outlet"], "to": ["M-201", "in_3"],
         "properties": {"Temperature": "88 C", "Pressure": "3.5 barg",
                        "Mass Flow": "48.0 t/h", "Dissolved O2": "150 ppb"}},
        {"from": ["M-201", "outlet"], "to": ["P-201A/B", "suction"],
         "properties": {"Temperature": "76 C", "Pressure": "3.4 barg",
                        "Mass Flow": "66.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["P-201A/B", "discharge"], "to": ["SP-201", "inlet"],
         "properties": {"Temperature": "77 C", "Pressure": "12.0 barg",
                        "Mass Flow": "66.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["SP-201", "out_2"], "to": ["V-201", "feed"],
         "properties": {"Temperature": "77 C", "Pressure": "11.6 barg",
                        "Mass Flow": "60.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["SP-201", "out_1"], "to": ["FV-201", "inlet"],
         "properties": {"Temperature": "77 C", "Pressure": "11.6 barg",
                        "Mass Flow": "6.0 t/h", "Dissolved O2": "1600 ppb"}},
        # Tear the loop at the spillback.
        {"from": ["FV-201", "outlet"], "to": ["M-201", "in_1"], "draw_as_recycle": True,
         "properties": {"Temperature": "77 C", "Pressure": "3.4 barg",
                        "Mass Flow": "6.0 t/h", "Dissolved O2": "1600 ppb"}},
        {"from": ["V-201", "vent"], "to": ["VT-201", "inlet"],
         "properties": {"Temperature": "105 C", "Pressure": "0.2 barg",
                        "Mass Flow": "0.3 t/h", "Dissolved O2": "-"}},
        {"from": ["V-201", "outlet"], "to": ["CV-201", "inlet"],
         "properties": {"Temperature": "105 C", "Pressure": "0.2 barg",
                        "Mass Flow": "59.7 t/h", "Dissolved O2": "7 ppb"}},
        {"from": ["CV-201", "outlet"], "to": ["To Boiler", "inlet"],
         "properties": {"Temperature": "105 C", "Pressure": "0.1 barg",
                        "Mass Flow": "59.7 t/h", "Dissolved O2": "7 ppb"}},
        # Signal lines; kind sets the line type.
        {"from": ["LT-201", "sig_out"], "to": ["LIC-201", "sig_in"], "kind": "electric"},
        {"from": ["LIC-201", "sig_out"], "to": ["LV-201", "sig_in"], "kind": "electric"},
        {"from": ["LV-201", "sig_out"], "to": ["CV-201", "actuator"], "kind": "pneumatic"},
    ],
    "stream_table_sections": [["Dissolved O2", "Water Quality"]],
    # --- Sheet furniture ----------------------------------------------
    "title_block": {
        "title": "Utilities U200",
        "subtitle": "Boiler Feedwater Package",
        "drawing_number": "PFD-2001",
        "project": "Steam System Upgrade",
        "company": "PANDID",
        "status": "ISSUED FOR REVIEW",
        "sheet": "1", "of_sheets": "2",
        "drawn_by": "AA", "checked_by": "JS", "approved_by": "RL",
        "revisions": [
            {"rev": "A", "date": "2026-05-18", "description": "Issued for internal review",
             "by": "AA"},
            {"rev": "B", "date": "2026-07-02", "description": "Added minimum-flow spillback",
             "by": "AA", "checked": "JS", "approved": "RL"},
        ],
    },
    "annotations": [
        {"type": "equipment_table", "align": "top-right"},
        {"type": "notes", "align": "top-right", "items": [
            "Deaerator vent to atmosphere; no isolation permitted.",
            "FV-201 maintains P-201A/B above 10% of rated flow.",
            "Dissolved oxygen sampled downstream of CV-201.",
        ]},
    ],
}


def main():
    fs = Flowsheet.from_dict(SPEC)

    # The spec round-trips.
    assert Flowsheet.from_dict(fs.to_dict()).to_dict() == fs.to_dict()

    fs.render(out("from_data.svg"), show_stream_table=True, border="zone")
    print("Generated from_data.svg")


if __name__ == "__main__":
    main()
