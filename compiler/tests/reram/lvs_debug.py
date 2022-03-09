#!env python3

import reram_test_base
from base.spice_parser import SpiceParser

num_rows = 64
spice = f"/scratch/ota2/openram/hierarchical_decoder_{num_rows}rows.lvs.spice"
mod_name = f"hierarchical_decoder_{num_rows}rows"

parser = SpiceParser(spice)
mod = parser.get_module(mod_name)


def get_net_lines(net_):
    for line in mod.contents:
        line_split = line.split()
        if net_ in line_split:
            yield line_split[1:-1], line_split[0], line_split[-1]


# check inverters
trace = []
inverter_inputs = []
for row in range(num_rows):
    out_net = f"decode[{row}]"
    lines = list(get_net_lines(out_net))
    assert len(lines) == 1
    connections, _, _ = lines[0]
    assert connections[2:] == "vdd gnd gnd vdd".split()
    inverter_inputs.append(connections[0])

assert len(set(inverter_inputs)) == num_rows

# check nands
nand_inputs = {}
for row in range(num_rows):
    nand_out = inverter_inputs[row]
    lines = list(get_net_lines(nand_out))
    assert len(lines) == 2
    line = [x for x in lines if "pnand" in x[1]][0]
    connections, _, _ = line
    assert connections[4:] == "vdd gnd gnd vdd".split()
    in_nets = connections[:3]
    for net in in_nets:
        if net not in nand_inputs:
            nand_inputs[net] = 0
        nand_inputs[net] += 1

print(nand_inputs)




