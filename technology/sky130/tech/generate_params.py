#!/usr/bin/env python3
import os

header = """
from characterizer.delay_params_base import RC, DelayParamsBase


class DelayParams(DelayParamsBase):
    # width, space, res, cap
"""

resistances = {
    "poly": 48.2,
    "metal1": 12.8, "metal2": 0.125, "metal3": 0.125,
    "metal4": 0.047, "metal5": 0.047, "metal6": 0.029
}

# https://docs.google.com/spreadsheets/d/1oL6ldkQdLu-4FEQE0lX6BcgbqzYfNnd1XA8vERe0vpE/edit#gid=
# Also corresponds to magic tech file. Using only parallel plate cap <=> defaultareacap in tech file
poly_cap = 0.106
locali_cap = 0.037

current_dir = os.path.abspath(os.path.dirname(__file__))
out_file_name = os.path.join(current_dir, "delay_params.py")
cap_table = os.path.join(current_dir, "basic_cap_table.csv")

out_file = open(out_file_name, "w")

current_layer = None


def add_definition(layer, width, space, cap):
    res = resistances[layer]
    global current_layer
    if not layer == current_layer:
        if current_layer is not None:
            out_file.write("    ]\n")
        current_layer = layer

        out_file.write(f"    {layer} = [\n")
    params_str = ", ".join([f"{x:.5g}" for x in [width, space, res, cap]])
    out_file.write(f"        RC({params_str}),\n")


with open(cap_table, "r") as cap_file:
    out_file.write(header)
    add_definition("poly", 0.15, 0.21, poly_cap)
    add_definition("metal1", 0.17, 0.17, poly_cap)
    all_lines = [x for x in cap_file.readlines() if x and x.startswith("M")]
    all_lines = list(sorted(all_lines, key=lambda x: (x.split(",")[0], float(x.split(",")[1]),
                                                      float(x.split(",")[2]))))
    for line in all_lines:
        layer, width, space, cap = line.split(",")[:4]
        layer_num = int(layer[1]) + 1
        layer_name = f"metal{layer_num}"
        add_definition(layer_name, float(width), float(space), float(cap))

    out_file.write("    ]\n")

out_file.close()

with open(out_file_name, "r") as f:
    print(f.read())
