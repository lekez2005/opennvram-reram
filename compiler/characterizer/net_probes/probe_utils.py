import itertools
import re

import tech
from base.spice_parser import tx_extract_parameter
from characterizer.dependency_graph import get_all_drivers_for_pin, get_net_hierarchy, get_all_net_connections
from globals import OPTS


def get_inst_name(hierarchy):
    parent_module, conn = hierarchy
    for i, candidate in enumerate(parent_module.conns):
        if candidate == conn:
            return "X" + parent_module.insts[i].name


def get_voltage_connections(net, module, candidate_drivers=None, match_patterns=None):
    """If candidate_drivers not matched, then picks last added module connected to net in the module"""
    if match_patterns is None:
        match_patterns = []

    destination_net, dest_hierarchy, inst_hierarchy = get_net_hierarchy(net, module)
    ancestor_names = ["X" + x.name for x in inst_hierarchy]

    parent_module = dest_hierarchy[-1]

    child_name = []
    if parent_module.is_delay_primitive():
        child_module = parent_module
        child_pin = destination_net
    else:
        child_module = child_pin = None
        for child_pin, child_module, conn_index, _ in get_all_net_connections(destination_net,
                                                                              parent_module):
            child_inst = parent_module.insts[conn_index]
            child_name = ["X{}".format(child_inst.name)]
            if not candidate_drivers or child_inst.name in candidate_drivers:
                break

    for hierarchy in child_module.get_spice_parser().deduce_hierarchy_for_pin(child_pin,
                                                                              child_module.name):
        parents = ancestor_names + child_name + hierarchy[:-1]
        tx_pin, tx_definition = hierarchy[-1]
        tx_name = tx_definition.split()[0]
        # calibre always adds @ to
        # nf = get_num_fingers(hierarchy[-1])
        # if nf > 1:  # TODO find out finger extraction  heuristic
        #     tx_name += "@2"

        # full_net = "_".join(parents + [tx_name, tx_pin])
        full_net = ".".join(parents)
        if not match_patterns or (match_patterns and all([x in full_net for x in match_patterns])):
            yield parents, inst_hierarchy, destination_net


def get_current_drivers(net, module, source_node_nets="*", candidate_drivers=None):
    results = []
    destination_net, dest_hierarchy, inst_hierarchy = get_net_hierarchy(net, module)
    driver_module = dest_hierarchy[-1]

    ancestor_names = ["X" + x.name for x in inst_hierarchy[1:]]

    if driver_module.is_delay_primitive():
        all_tx = driver_module.get_spice_parser().deduce_hierarchy_for_pin(destination_net,
                                                                           driver_module.name)
        branch_names = [[]]
        branch_tx = [all_tx]
    else:
        branch_names = []  # keep track of for each branch
        branch_tx = []
        for driver_hierarchy in get_all_drivers_for_pin(destination_net, driver_module):
            if not candidate_drivers or driver_hierarchy[1][0].name in candidate_drivers:
                names = []
                for hierarchy in driver_hierarchy[:-1]:
                    names.append(get_inst_name(hierarchy))
                driver_mod, net, _ = driver_hierarchy[-1]
                all_tx = driver_mod.get_spice_parser().deduce_hierarchy_for_pin(net,
                                                                                driver_mod.name)
                branch_names.append(names)
                branch_tx.append(all_tx)

    for all_tx, names in zip(branch_tx, branch_names):
        for tx in all_tx:
            prefix = tx[:-1]
            tx_definition = tx[-1]
            if (source_node_nets == "*" or
                    set(tx_definition[1].split()[:4]).intersection(source_node_nets)):
                tx_name = tx_definition[1].split()[0]
                full_name = ".".join(ancestor_names + names + prefix + [tx_name])
                results.append((full_name, tx_definition[1]))
    return remove_duplicate_nmos_pmos(results)


def remove_duplicate_nmos_pmos(current_drivers):
    # if both pmos and nmos are attached to the same node, select just the pmos
    # heuristic: if body is connected to gnd then nmos otherwise pmos
    results = []

    def prefix_key(x):
        return x[0][:x[0].rfind(".")]

    def body_tap_key(x):
        return x[1].split()[4]

    current_drivers = list(sorted(current_drivers, key=prefix_key))
    for prefix, values in itertools.groupby(current_drivers, prefix_key):
        values = list(sorted(values, key=body_tap_key))
        values = {key: list(val) for key, val in itertools.groupby(values, body_tap_key)}
        if len(values) == 1:
            results.extend(list(values.values())[0])
        else:
            results.extend(values["vdd"])
    return results


def get_num_fingers(tx_def):
    nf = tx_extract_parameter("nf", tx_def[1])
    m = tx_extract_parameter("m", tx_def[1])
    if nf and m:
        nf = nf * m
    elif m:
        nf = m
    else:
        nf = 1
    return int(nf)


def get_all_tx_fingers(current_driver, replacements):
    nf = get_num_fingers(current_driver)
    drivers = [current_driver[0]]
    if OPTS.use_pex and nf > 1:
        drivers += [current_driver[0] + "@{}".format(x + 1) for x in range(1, nf)]
    for (src, dest) in replacements:
        drivers = [re.sub(src, dest, x) for x in drivers]
    return drivers


def add_prefix(probes, prefix):
    results = []
    for probe in probes:
        if isinstance(probe, tuple):
            tx = prefix + probe[1]
        else:
            tx = prefix + probe
        if OPTS.use_pex:
            tx = tx.replace(".", "_")
        tx = "Xsram." + tx
        if isinstance(probe, tuple):
            results.append((probe[0], tx))
        else:
            results.append(tx)
    return results


def get_extracted_prefix(child_net, inst_hierarchy):
    # if an internal net is in a module's pins,
    # Calibre doesn't include the child net in the extraction name
    inst_hierarchy = list(reversed(inst_hierarchy))
    prefix = ""
    for i, inst in enumerate(inst_hierarchy):
        if child_net in inst.mod.pins:
            if i == len(inst_hierarchy) - 1:
                return "", child_net
            # find corresponding net in parent
            pin_index = inst.mod.pins.index(child_net)
            parent_inst = inst_hierarchy[i + 1]
            child_inst_index = parent_inst.mod.insts.index(inst)
            child_conn = parent_inst.mod.conns[child_inst_index]
            child_net = child_conn[pin_index]
        else:
            remnant = list(reversed(inst_hierarchy[i:]))
            separator = "_" if OPTS.use_pex else "."
            prefix = separator.join(["X" + x.name for x in remnant])
            break
    return prefix, child_net


def format_bank_probes(probes, bank):
    if OPTS.use_pex:
        prefix = tech.spice["tx_pex_prefix"]
    else:
        prefix = ""
    prefix = prefix + "Xbank{0}.".format(bank)
    return add_prefix(probes, prefix)
