setup_time = 0.15  # in nanoseconds
tech_name = "sky130"
process_corners = ["TT"]
supply_voltages = [1.8]
temperatures = [25]

diode = "diode.Diode"

logic_buffers_height = 3.9

control_buffers_num_rows = 1

# technology
analytical_delay = False
spice_name = "spectre"
tran_options = " errpreset=moderate "

# characterization parameters
default_char_period = 4e-9
enhance_pgate_pins = True

flat_lvs = True
flat_drc = True

klayout_drc_options = {
    "feol": 1, "beol": 1, "offgrid": 1, "seal": 1, "floating_met": 0
}

klayout_report_name = "report"


def configure_char_timing(options, class_name):
    if class_name == "FO4DelayCharacterizer":
        return 800e-12
    return default_char_period
