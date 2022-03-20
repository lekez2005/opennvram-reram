import os


def add_tech_layers(obj):
    try:
        from .sky130_enhancements import enhance_module
    except ImportError:
        from sky130_enhancements import enhance_module
    enhance_module(obj)


def delay_params_class():
    from delay_params import DelayParams
    return DelayParams

info = {}
info["name"] = "sky130"
info["has_pwell"] = False
info["has_nwell"] = True

drc_name = "klayout"
lvs_name = "netgen"
pex_name = "magic"

#########################
# GDS Map

# GDS file info
GDS = {}
# gds units
GDS["unit"] = (0.001, 1e-9)
# default label zoom
GDS["zoom"] = 0.05

has_local_interconnect = True

# create the GDS layer map
layer = {
    "active": 65,
    "tap_active": 65,
    "nwell": 64,
    "nimplant": 93,
    "pimplant": 94,
    "poly": 66,
    "active_contact": 66,
    "contact": 66,
    "metal1": 67,
    "via1": 67,
    "metal2": 68,
    "via2": 68,
    "metal3": 69,
    "via3": 69,
    "metal4": 70,
    "via4": 70,
    "metal5": 71,
    "via5": 71,
    "metal6": 72,
    "boundary": 235,
    "npc": 95,
    "stdc": 81,
    "reram_ox": 201,
    "diode": 81,
    "res_metal3": 69,
    "res_metal4": 70,
    "cap2m": 97,
}

purpose = {
    "drawing": 20,
    "nimplant": 44,
    "tap_active": 44,
    "contact": 44,
    "active_contact": 44,
    "via1": 44,
    "via2": 44,
    "via3": 44,
    "via4": 44,
    "via5": 44,
    "cap2m": 44,
    "diode": 23,
    "res_metal3": 13,
    "res_metal4": 13,
    "stdc": 4,
    "boundary": 4
}

layer_pin_map_ = {}

layer_pin_purpose = {"default": 5}

layer_pin_map = {layer[key]: value for key, value in layer_pin_map_.items()}
layer_pin_map["text_layers"] = []

power_grid_layers = ["metal5", "metal6"]
power_grid_width = 4

power_grid_y_space = 3.5
power_grid_x_space = 3.5

# MIM cap
mim_cap_top_layer = "metal6"
mim_cap_bottom_layer = "metal5"
mim_cap_via_layer = "via5"
mim_cap_cap_layer = "cap2m"
mim_cap_bottom_enclosure = 0.14
mim_cap_top_enclosure = 0.0

#########################
# Parameter
parameter = {"min_tx_size": 0.36, "beta": 2.5}

#########################
# DRC Rules
drc = {
    "grid": 0.005,
    "minwidth_tx": parameter["min_tx_size"],
    "minlength_channel": 0.15,
    "latchup_spacing": 15,
    "medium_width": 0.225,
    "bus_space": 0.225
}

drc["rail_height"] = 0.3

drc["pwell_to_nwell"] = 0.22
drc["nwell_to_nwell"] = 1.27
drc["same_net_line_space_nwell"] = 1.27
drc["pwell_to_pwell"] = 0.0
drc["minwidth_well"] = 0.84
# poly
drc["minwidth_poly"] = 0.15
drc["poly_to_poly"] = 0.21
drc["poly_end_to_end"] = 0.21
drc["poly_extend_active"] = 0.13
drc["active_enclosure_gate"] = 0.075
drc["poly_to_active"] = 0.075
drc["poly_to_field_poly"] = 0.21
drc["poly_contact_to_active"] = 0.19
drc["poly_contact_to_p_active"] = 0.235
drc["npc_enclose_poly"] = 0.1
drc["minarea_poly"] = 0.0
# active
drc["active_to_body_active"] = 0.27
drc["minwidth_active"] = 0.15
drc["active_to_active"] = 0.27
drc["well_enclosure_active"] = 0.18
drc["well_extend_active"] = 0.18
drc["minarea_active"] = 0
drc["minarea_tap_active"] = 0.07011
drc["nwell_to_active_space"] = 0.34
drc["nwell_to_tap_active_space"] = 0.13
# implant
drc["implant_to_channel"] = 0.135
drc["implant_enclosure_active"] = 0.0
drc["implant_enclosure_diode"] = 0.05  # arbitrary. magic seems to use 0.125 but DRC is fine with 0!
drc["ptx_implant_enclosure_active"] = 0.0
drc["implant_enclosure_contact"] = 0
drc["implant_to_contact"] = 0.07
drc["implant_to_implant"] = 0.38
drc["minwidth_implant"] = 0.38
# contact
drc["minwidth_contact"] = 0.17
drc["contact_to_contact"] = 0.17
drc["tap_active_enclosure_contact"] = 0
drc["tap_active_extend_contact"] = 0.12
drc["active_enclosure_contact"] = 0.06
drc["active_extend_contact"] = 0.06
drc["poly_enclosure_contact"] = 0.08
drc["poly_extend_contact"] = 0.05
drc["contact_to_gate"] = 0.055
# metal layers and vias
# M1
drc["minwidth_metal1"] = 0.17
drc["metal1_to_metal1"] = 0.17
drc["metal1_enclosure_contact"] = 0
drc["metal1_extend_contact"] = 0.08
drc["metal1_extend_via1"] = 0.08
drc["metal1_enclosure_via1"] = 0
drc["minarea_metal1"] = 0
# M2
drc["minwidth_via1"] = 0.17
drc["via1_to_via1"] = 0.21
drc["minwidth_metal2"] = 0.14
drc["metal2_to_metal2"] = 0.14
drc["metal2_extend_via1"] = 0.06
drc["metal2_enclosure_via1"] = 0.03
drc["metal2_extend_via2"] = 0.085
drc["metal2_enclosure_via2"] = 0.055
drc["minarea_metal2"] = 0.083
# M3
drc["minwidth_via2"] = 0.15
drc["via2_to_via2"] = 0.17
drc["minwidth_metal3"] = 0.14
drc["metal3_to_metal3"] = 0.14
drc["metal3_extend_via2"] = 0.085
drc["metal3_enclosure_via2"] = 0.055
drc["metal3_extend_via3"] = 0.085
drc["metal3_enclosure_via3"] = 0.04
drc["minarea_metal3"] = 0.0676
# M4
drc["minwidth_via3"] = 0.2
drc["via3_to_via3"] = 0.2
drc["minwidth_metal4"] = 0.3
drc["metal4_to_metal4"] = 0.3
drc["metal4_extend_via3"] = 0.065
drc["metal4_enclosure_via3"] = 0.065
drc["metal4_enclosure_via4"] = 0.06
drc["metal4_extend_via4"] = 0.09
drc["minarea_metal4"] = 0.24
# M5
drc["minwidth_via4"] = 0.2
drc["via4_to_via4"] = 0.2
drc["minwidth_metal5"] = 0.3
drc["metal5_to_metal5"] = 0.3
drc["metal5_extend_via4"] = 0.065
drc["metal5_enclosure_via4"] = 0.065
drc["metal5_enclosure_via5"] = 0.19
drc["metal5_extend_via5"] = 0.19
drc["minarea_metal5"] = 0.24
# M6
drc["minwidth_via5"] = 0.8
drc["via5_to_via5"] = 0.8
drc["minwidth_metal6"] = 1.6
drc["metal6_to_metal6"] = 1.6
drc["metal6_extend_via5"] = 0.31
drc["metal6_enclosure_via5"] = 0.31
drc["minarea_metal6"] = 4

#########################
# DRC Rules Exceptions
drc_exceptions = {}
if drc_name == "magic":
    drc_exceptions["latchup"] = ["N-diff distance to P-tap must be < 15.0um (LU.2)",
                                 "P-diff distance to N-tap must be < 15.0um (LU.3)",
                                 "All nwells must contain metal-connected N+ taps (nwell.4)"]
else:
    drc_exceptions["latchup"] = []

drc_exceptions["ptx"] = drc_exceptions["latchup"]
drc_exceptions["reram_bitcell"] = drc_exceptions["latchup"]
drc_exceptions["Diode"] = ["met1.6"]

#########################
# Spice Simulation Parameters
spice = {}
spice["minwidth_tx"] = drc["minwidth_tx"]
spice["minwidth_tx_pmos"] = 0.42
spice["channel"] = drc["minlength_channel"]
spice["tx_instance_prefix"] = "X"
spice["scale_tx_parameters"] = False
spice["nmos"] = "sky130_fd_pr__nfet_01v8"
spice["pmos"] = "sky130_fd_pr__pfet_01v8"
spice["p_diode_name"] = "sky130_fd_pr__diode_pw2nd_05v5"
spice["n_diode_name"] = "sky130_fd_pr__diode_pd2nw_05v5"
spice["mim_cap_name"] = "sky130_fd_pr__cap_mim_m3_2"
spice["metal3_res_name"] = "sky130_fd_pr__res_generic_m2"
spice["metal4_res_name"] = "sky130_fd_pr__res_generic_m3"
spice["subckt_nmos"] = "msky130_fd_pr__nfet_01v8"
spice["subckt_pmos"] = "msky130_fd_pr__pfet_01v8"
spice["vdd_name"] = "vdd"
spice["gnd_name"] = "gnd"
spice["gmin"] = 1e-13


def create_corner(model_dir_, corner):
    return [(os.path.join(model_dir_, "sky130.lib.spice"), corner.lower())]


all_corners = ["TT", "FF", "SS", "SF", "FS"]
model_dir = os.environ.get("SPICE_MODEL_DIR")
spice["fet_models_ngspice"] = {corner: create_corner(model_dir, corner) for corner in all_corners}

model_dir = os.environ.get("SPICE_MODEL_HSPICE")
spice["fet_models_hspice"] = {corner: create_corner(model_dir, corner) for corner in all_corners}
spice["fet_models"] = spice["fet_models_hspice"]

# spice stimulus related variables
spice["feasible_period"] = 8  # estimated feasible period in ns
spice["supply_voltages"] = [1.7, 1.8, 1.9]  # Supply voltage corners in [Volts]
spice["nom_supply_voltage"] = 1.8  # Nominal supply voltage in [Volts]
spice["rise_time"] = 0.01  # rise time in [Nano-seconds]
spice["fall_time"] = 0.01  # fall time in [Nano-seconds]
spice["temperatures"] = [0, 25, 100]  # Temperature corners (celcius)
spice["nom_temperature"] = 25  # Nominal temperature (celcius)
spice["clk"] = "clk"

# analytical delay parameters TODO
spice["wire_unit_r"] = 0.4675  # Unit wire resistance in ohms/square
spice["wire_unit_c"] = 0.3  # Unit wire capacitance ff/um^2
spice["min_tx_r"] = 9000  # Minimum transistor on resistance in ohms
spice["min_tx_r_p"] = 9000  # Minimum transistor on resistance in ohms
spice["min_tx_r_n"] = 11000  # Minimum transistor on resistance in ohms
spice["min_tx_drain_c"] = 0.092  # Minimum transistor drain capacitance in ff
spice["min_tx_gate_c"] = 0.101  # Minimum transistor gate capacitance in ff
spice["pmos_unit_gm"] = 109e-6
spice["nmos_unit_gm"] = 32e-6
