#!env python3
import os
import re
import sys

sys.path.append(os.getenv("OPENRAM_HOME"))
import setup_openram
from base.spice_parser import SpiceParser, tx_extract_parameter


def parse_bins(in_file_name):
    current_dir = os.path.dirname(__file__)
    in_file = os.path.join(current_dir, f"{in_file_name}.txt")

    tx_length = 0.15e-6

    pattern = re.compile(r"(\S+)=(\S+)")
    bins = []

    with open(in_file, "r") as f:
        for line in f:
            matches = pattern.findall(line)
            if not matches:
                continue
            matches = {key: float(value) for key, value in matches}
            l_min, l_max = matches["lmin"], matches["lmax"]
            w_min, w_max = matches["wmin"], matches["wmax"]
            if l_min <= tx_length <= l_max:
                bins.append((w_min, w_max))

    bins = list(sorted(bins))
    return bins


def locate_bad_bins(netlist):
    """Locate tx in netlist that are outside the defined bins"""
    tx_types = {"n": "sky130_fd_pr__nfet_01v8", "p": "sky130_fd_pr__pfet_01v8"}
    bin_dict = {}
    for tx_type, mos_name in tx_types.items():
        bins = parse_bins(mos_name)
        bin_dict[tx_type] = (bins[0][0], bins[-1][-1])

    parser = SpiceParser(netlist)
    for mod in parser.mods:
        for spice_statement in mod.contents:
            if not parser.line_contains_tx(spice_statement):
                continue
            tx_type, m, nf, finger_width = parser.extract_all_tx_properties(spice_statement)
            finger_width = finger_width * 1e-6
            min_width, max_width = bin_dict[tx_type]
            if finger_width < min_width or finger_width > max_width:
                print(f"Invalid tx statement: {spice_statement}")


# parse_bins("sky130_fd_pr__pfet_01v8")

netlist_path = "openram/sky130/cmos/cmos_32_c_8_w8_schem/sram.sp"


locate_bad_bins(os.path.join(os.getenv("SCRATCH", "/tmp"), netlist_path))



