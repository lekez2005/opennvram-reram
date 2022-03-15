"""
Implements a simple spice parser to enable constructing cell hierarchy
"""
import os
import re
from typing import Union, TextIO, List

import debug
from tech import spice as tech_spice

SUFFIXES = {
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15
}


def tx_extract_parameter(param_name, statement):
    pattern = r"{}\s*=\s*(?P<value>[0-9e\.\-]+)(?P<suffix>[munpf]?)".format(param_name)
    debug.info(4, "Search for parameter {} in {}".format(param_name, statement))
    match = re.search(pattern, statement)
    if not match:
        return None
    value = float(match.groups()[0])
    if match.groups()[1]:
        value *= SUFFIXES[match.groups()[1]]
    debug.info(4, "extracted transistor parameter {} = {:.3g}".format(param_name, value))
    return value


def load_source(source: Union[str, TextIO]):
    if isinstance(source, str):
        if "\n" not in source and os.path.exists(source):
            debug.info(3, "Loading spice from source file: {}".format(source))
            with open(source, "r") as f:
                source = f.read()
    else:
        source.seek(0)
        source = source.read()
    return source


def extract_lines(source: str):
    all_lines = []
    for line in source.splitlines():
        if not line or not line.strip() or line.strip().startswith("*"):
            continue
        line = line.strip().lower()
        if '*' not in line:
            all_lines.append(line)
        else:  # strip comment from end if applicable

            end_index = len(line)
            for i in range(len(line)):
                if line[i] == "*" and end_index <= len(line):
                    end_index = min(i, end_index)
                elif line[i] in ["'", '"']:  # to prevent removing expressions
                    end_index = len(line)
            all_lines.append(line[:end_index].strip())

    return all_lines


MODE_INIT = 0
MODE_PARSING = 1
MODE_END = 2


def group_lines_by_mod(all_lines: List[str]):
    line_counter = 0

    lines_by_module = []

    mode = MODE_INIT

    current_mod = []

    while line_counter < len(all_lines):
        # construct a full line
        line = all_lines[line_counter]
        line_counter += 1
        while line_counter < len(all_lines):
            if all_lines[line_counter].startswith("+"):
                line += all_lines[line_counter][1:]
                line_counter += 1
            else:
                break

        if line.startswith(".subckt"):
            if len(current_mod) > 0:
                lines_by_module.append(current_mod)
            current_mod = [line]
            mode = MODE_PARSING
            continue
        elif line.startswith(".ends"):
            mode = MODE_END
            continue
        if mode == MODE_PARSING:
            current_mod.append(line)

    if len(current_mod) > 0:
        lines_by_module.append(current_mod)

    return lines_by_module  # List[List[str]]


class SpiceMod:
    def __init__(self, name: str, pins: List[str], contents: List[str]):
        self.name = name
        self.pins = pins
        self.contents = contents
        self.sub_modules = []  # type: List[SpiceMod]

    def __str__(self):
        return f"SpiceMod: ({self.name}: [{', '.join(self.pins)}])"

    def __repr__(self):
        return str(self)


class SpiceParser:

    def __init__(self, source: Union[str, TextIO]):
        self.mods = []  # type: List[SpiceMod]

        source = load_source(source)
        self.all_lines = all_lines = extract_lines(source)

        mods_by_lines = group_lines_by_mod(all_lines)
        for mod_lines in mods_by_lines:
            subckt_line = mod_lines[0].split()
            mod_name = subckt_line[1]
            mod_pins = subckt_line[2:]
            self.mods.append(SpiceMod(mod_name, mod_pins,
                                      contents=[] if len(mod_lines) == 1 else mod_lines[1:]))

    def get_module(self, module_name):
        module_name = module_name.lower()
        for mod in self.mods:
            if mod.name == module_name:
                return mod
        assert False, module_name + " not in spice deck"

    def get_pins(self, module_name):
        return self.get_module(module_name).pins

    @staticmethod
    def line_contains_tx(line: str):
        return (line.startswith("m") or tech_spice["nmos"] in line.split() or
                tech_spice["pmos"] in line.split())

    def deduce_hierarchy_for_pin(self, pin_name, module_name):
        pin_name = pin_name.lower()
        module = self.get_module(module_name)
        nested_hierarchy = []
        # breadth first and then go deep in each
        for line in module.contents:
            if pin_name not in line.split():
                continue

            pin_index = line.split().index(pin_name) - 1
            if self.line_contains_tx(line):  # end of hierarchy
                pin_index = line.split().index(pin_name) - 1
                yield [(["d", "g", "s", "b"][pin_index], line)]
            else:
                child_module_name = line.split()[-1]
                child_module = self.get_module(child_module_name)
                child_pin_name = child_module.pins[pin_index]
                instance_name = line.split()[0]

                nested_hierarchy.append((instance_name, child_module_name, child_pin_name))

        # Now go deep into each branch
        for branch in nested_hierarchy:
            instance_name, child_module_name, child_pin_name = branch
            for child in self.deduce_hierarchy_for_pin(child_pin_name, child_module_name):
                yield [instance_name] + child

    def deduce_hierarchy_for_node(self, node_name, module_name):
        node_name = node_name.lower()
        hierarchy = node_name.split(".")
        for child in hierarchy[:-1]:
            module = self.get_module(module_name)
            found = False
            for line in module.contents:
                if line.split()[0] == child:
                    found = True
                    module_name = line.split()[-1]

            assert found, "Node {} not found in hierarchy".format(node_name)

        target_pin = hierarchy[-1]
        return [hierarchy[:-1] + x for x in self.deduce_hierarchy_for_pin(target_pin, module_name)]

    @staticmethod
    def extract_all_tx_properties(spice_statement):
        """Extract tx_type, m, nf, width from spice statement
        TODO: Careful divides width by nf
        """
        assert SpiceParser.line_contains_tx(spice_statement), "Line must contain tx"
        line_elements = spice_statement.split()
        if line_elements[5] == tech_spice["nmos"]:
            tx_type = "n"
        elif line_elements[5] == tech_spice["pmos"]:
            tx_type = "p"
        else:
            assert False, f"Invalid tx name {line_elements[5]} in {spice_statement}"
        m = int(tx_extract_parameter("m", spice_statement) or 1)
        nf = int(tx_extract_parameter("nf", spice_statement) or 1)

        width = tx_extract_parameter("w", spice_statement)
        return tx_type, m, nf, width / nf

    def extract_caps_for_pin(self, pin_name, module_name):
        """
        Return caps attached to pin.
        Assumes transistor model name starts with n for nmos and p for pmos
        Note: Doesn't consider transistor length
        :param pin_name:
        :param module_name:
        :return: dict for each of nmos, pmos for gate/drain with list: [total, [(m, nf, w)]]
        """

        results = {
            "n": {
                "d": [0, []],
                "g": [0, []]
            },
            "p": {
                "d": [0, []],
                "g": [0, []]
            }
        }
        for child in self.deduce_hierarchy_for_pin(pin_name, module_name):
            spice_statement = child[-1][1]
            if not self.line_contains_tx(spice_statement):
                continue
            tx_type, m, nf, width = self.extract_all_tx_properties(spice_statement)
            num_drains = 1 + int((nf - 1) / 2)

            pin_name = child[-1][0]
            pin_name = "d" if pin_name == "s" else pin_name

            results[tx_type][pin_name][0] += width * m * num_drains
            results[tx_type][pin_name][1].append((m, nf, width))

        return results

    def extract_res_for_pin(self, pin_name, module_name, vdd_name="vdd", gnd_name="gnd",
                            max_depth=5):
        """

        :param pin_name: pin to evaluate
        :param module_name: parent module
        :param vdd_name: to count as a a path, pmos must terminate on "vdd_name"
        :param gnd_name: to count as a path, nmos must terminate on "gnd_name"
        :param max_depth: This is used as a termination condition to prevent infinite cycles
        :return: max resistance in path
        """
        resistance_paths = self.extract_res_paths_for_pin(pin_name, module_name, "", vdd_name, gnd_name,
                                                          0, max_depth)
        elements = {
            "p": [],
            "n": []
        }
        for path in resistance_paths:
            path_elements = []
            tx_type = "p"  # will be overridden by last element on path
            for i in range(len(path)):
                tx_type, m, nf, width = self.extract_all_tx_properties(path[i])
                path_elements.append((m, nf, width))
            elements[tx_type].append(path_elements)
        return elements

    def extract_res_paths_for_pin(self, pin_name, module_name, adjacent_in="",
                                  vdd_name="vdd", gnd_name="gnd",
                                  depth=0, max_depth=5):

        final_paths = []
        intermediate_paths = []

        hierarchy = self.deduce_hierarchy_for_node(pin_name, module_name)

        for child in hierarchy:
            tx_terminal, spice_statement = child[-1]
            if tx_terminal not in ['d', 's']:
                continue

            line_elements = spice_statement.split()

            tx_type, _, _, _ = self.extract_all_tx_properties(spice_statement)

            adjacent_net = line_elements[1] if tx_terminal == 's' else line_elements[3]
            original_net = line_elements[3] if tx_terminal == 's' else line_elements[1]

            if adjacent_net == adjacent_in:
                continue
            elif tx_type == "p" and adjacent_net == vdd_name:  # valid pmos
                final_paths.append([spice_statement])
            elif tx_type == "n" and adjacent_net == gnd_name:  # valid nmos
                final_paths.append([spice_statement])
            elif adjacent_net in [vdd_name, gnd_name]:  # invalid pull up or pull down
                continue
            elif depth >= max_depth:
                continue
            else:  # intermediate node
                if len(child[:-1]) > 0:
                    next_route = ".".join(child[:-1]) + "." + adjacent_net
                else:
                    next_route = adjacent_net
                intermediate_paths.append((spice_statement, original_net, next_route))
        # process intermediate paths (i.e. series transisors)
        for spice_statement, original_net, next_route in intermediate_paths:
            next_route_paths = self.extract_res_paths_for_pin(next_route, module_name, original_net,
                                                              vdd_name, gnd_name, depth + 1, max_depth)
            for path in next_route_paths:
                final_paths.append([spice_statement] + path)

        return final_paths

    def add_module_suffix(self, suffix, exclusions=None):
        exclusions = exclusions or []
        # rename mods
        for mod in self.mods:
            if mod.name not in exclusions:
                mod.name += suffix
            for i, spice_statement in enumerate(mod.contents):
                if self.line_contains_tx(spice_statement):
                    continue
                child_module_name = spice_statement.split()[-1]
                new_line = spice_statement.split()[:-1] + [(child_module_name + suffix)]
                mod.contents[i] = " ".join(new_line)

    def export_spice(self):
        content = []
        for mod in self.mods:
            content.append(f".subckt {mod.name} {' '.join(mod.pins)}")
            content.extend(mod.contents)
            content.append(".ends\n")
        return content
