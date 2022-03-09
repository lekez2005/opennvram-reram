"""
Create Graph consisting of nodes from one driver to the next
TODO
    - More accurate gm evaluation, characterization or calculation
    - Handle case with multiple input pins in layout
    - More systematic pin length computation, currently uses max(pin_length, min(cell_width, cell_height))
    - Distributed loads are not detected if the nesting hierarchy is greater than one -> Implement flatenning load hierarchy to fix
"""
import math
from typing import List, Tuple, Dict, Union

import debug
from base.design import design
from base.hierarchy_spice import OUTPUT, INOUT, INPUT, delay_data


class ModuleConn(tuple):
    # tuple of Module and connection
    def __new__(cls, module, conn):
        return super(ModuleConn, cls).__new__(ModuleConn, (module, conn))

    def __str__(self):
        if len(self[1]) > 5:
            suffix = " ... {}".format(self[1][-1])
        else:
            suffix = ""
        return "({}, [{}{}])".format(self[0], ", ".join(self[1][:5]), suffix)

    def __repr__(self):
        return self.__str__()


class GraphLoad:

    def __init__(self, pin_name: str, module: design, wire_length: float = 0.0, count: int = 1):
        self.pin_name = pin_name
        self.module = module
        self.count = count
        self.wire_length = wire_length
        self.cin = 0.0

    def is_distributed(self):
        from globals import OPTS
        if self.count >= OPTS.distributed_load_threshold:
            return True
        if self.module.is_delay_primitive():
            return False
        instances_groups = self.module.group_pin_instances_by_mod(self.pin_name)
        return instances_groups and max(map(lambda x: x[0],
                                            instances_groups.values())) > OPTS.distributed_load_threshold

    def increment(self):
        self.count += 1

    def evaluate_cin(self):
        self.cin, _ = self.module.get_input_cap(pin_name=self.pin_name, num_elements=self.count,
                                                wire_length=self.wire_length)
        return self.cin

    def __str__(self):
        if self.cin > 0:
            suffix = " c={:.3g}f".format(self.cin * 1e15)
        else:
            suffix = ""
        return "({}:{} count={}{})".format(self.module.name, self.pin_name, self.count, suffix)


class GraphLoads:

    def __init__(self):
        self.loads = {}  # type: Dict[str, GraphLoad]

    def add_load(self, pin_name: str, module: design, wire_length: float = 0.0,
                 count: int = 1, is_branch=False):
        key = module.name + "_" + pin_name
        if key not in self.loads:
            self.loads[key] = GraphLoad(pin_name, module, wire_length=wire_length,
                                        count=count)
        else:
            self.loads[key].increment()
            self.loads[key].wire_length = max(wire_length, self.loads[key].wire_length)

    def items(self):
        return self.loads.items()

    def __str__(self):
        return "\n".join([str(x) for x in self.loads.values()])


class GraphNode:
    """Represent a node on a graph. Includes
            node net name
             the module it's an input to on the relevant path
             the pin it's an input to on the path"""

    def __init__(self, in_net: str, out_net: str, module: design,
                 parent_in_net: str, parent_out_net: str,
                 all_parent_modules: List[Tuple[design, List[str]]],
                 conn: List[str]):
        self.in_net = in_net
        self.out_net = out_net
        self.module = module
        self.parent_in_net = parent_in_net
        self.parent_out_net = parent_out_net

        self.parent_module = all_parent_modules[-1][0]
        self.original_parent_module = self.parent_module  # for when parent module is overridden at higher level
        self.all_parent_modules = [x for x in all_parent_modules]  # make a copy
        self.conn = conn

        conn_index = self.parent_module.conns.index(conn)
        self.instance = self.parent_module.insts[conn_index]
        self.instance_name = self.instance.name

        self.loads = GraphLoads()
        self.output_cap = 0.0
        self.driver_res = math.inf
        self.delay = None  # type: Union[None, delay_data]

        debug.info(3, "Created GraphNode: %s", self)

    def get_next_load(self, next_node: 'GraphNode') -> Tuple[List[GraphLoad], Union[None, GraphLoad]]:

        if next_node is None:
            all_loads = list(self.loads.loads.values())
            if all_loads:
                return all_loads[1:], all_loads[0]
            return [], None

        other_loads = []

        next_node_load = None
        all_next_hierarchy = [x[0] for x in next_node.all_parent_modules] + [next_node.module]

        for load in self.loads.loads.values():
            load_name = load.module.name
            if next_node_load is not None:
                other_loads.append(load)
            else:
                # go from top of hierarchy to lowest. For example, check bank, then precharge array
                for module in all_next_hierarchy:
                    if module.name == load_name:
                        next_node_load = load
                        break
        return other_loads, next_node_load

    def evaluate_caps(self):
        total_cap = 0.0
        for _, load in self.loads.items():
            total_cap += load.evaluate_cin()
        self.output_cap = total_cap
        return total_cap

    def extract_loads(self, top_level_module: design, estimate_wire_lengths=True):
        """estimate_wire_lengths determines whether to estimate wire length based on physical distance
        # FIXME: Careful with this, some wires will be shared and this would "double-count" them
        """

        def get_loads_at_net(net: str, conn: List[str], module: design):
            """Gets all the nodes at net except the one at conn"""

            conn_index = module.conns.index(conn)
            net_index = conn.index(net)

            loads = []

            driver_inst = module.insts[conn_index]

            if net in module.pins:
                input_pin = module.get_pin(net)
                driver_pin = input_pin
            else:
                driver_pin_name = driver_inst.mod.pins[net_index]
                driver_pin = driver_inst.get_pin(driver_pin_name)
            for inst_index in range(len(module.conns)):
                module_conn = module.conns[inst_index]
                if net not in module_conn:
                    continue
                net_indices = [j for j, x in enumerate(module_conn) if x == net]
                for conn_net_index in net_indices:
                    if inst_index == conn_index and conn_net_index == net_index:
                        # original net we're tracing
                        continue
                    inst_mod = module.insts[inst_index].mod
                    pin_index = module_conn.index(net)
                    input_pin_name = inst_mod.pins[pin_index]
                    if estimate_wire_lengths:
                        inst_pin = module.insts[inst_index].get_pin(input_pin_name)
                        x_distance, y_distance = inst_pin.distance_from(driver_pin)
                        wire_length = x_distance + y_distance
                    else:
                        wire_length = 0.0
                    loads.append((input_pin_name, inst_mod, wire_length))
            return loads

        all_loads = []
        driver_conn = self.conn
        output_net = self.parent_out_net
        all_loads.extend(get_loads_at_net(output_net, driver_conn, self.original_parent_module))

        current_module = self.original_parent_module

        for ancestor_module, ancestor_conn in reversed(self.all_parent_modules[:-1]):
            if output_net not in current_module.pins:
                break
            # find corresponding output net
            output_pin_index = current_module.pins.index(output_net)
            output_net = ancestor_conn[output_pin_index]
            all_loads.extend(get_loads_at_net(output_net, ancestor_conn, ancestor_module))
            current_module = ancestor_module

            if ancestor_module.name == top_level_module.name:
                break
        for input_pin_name_, inst_mod_, wire_length_ in all_loads:
            self.loads.add_load(pin_name=input_pin_name_, module=inst_mod_, wire_length=wire_length_)

    def evaluate_resistance(self, corner=None):
        self.driver_res = self.module.get_driver_resistance(pin_name=self.out_net, corner=corner,
                                                            use_max_res=True)
        return self.driver_res

    def evaluate_delay(self, next_node: 'GraphNode', slew_in, corner=None, swing=0.5):
        other_loads, next_node_load = self.get_next_load(next_node)

        # Determine if this is a distributed load
        is_distributed = False
        if next_node_load:
            if next_node_load.is_distributed():
                is_distributed = True
                # only one of them will be on the critical path so add the others as regular loads
                if next_node_load.count > 1:
                    other_loads.extend([next_node_load] * (next_node_load.count - 1))
            else:
                is_distributed = False
                other_loads.append(next_node_load)
        # estimate non distributed cap
        load_caps = 0.0
        for load in other_loads:
            load_caps += load.evaluate_cin()

        intrinsic_cap, _ = self.module.get_input_cap(pin_name=self.out_net, num_elements=1,
                                                     wire_length=0)
        load_caps += intrinsic_cap

        # driver res
        driver_res = self.evaluate_resistance(corner=corner)
        driver_gm = self.module.evaluate_driver_gm(pin_name=self.out_net, corner=corner)

        if is_distributed:
            return self.evaluate_distributed_delay(driver_res, driver_gm, load_caps,
                                                   next_node_load, next_node, slew_in)
        else:  # Horowitz

            tau = load_caps * driver_res
            beta = 1 / (driver_gm * driver_res)
            alpha = slew_in / tau

            delay, slew_out = self.module.horowitz_delay(tau, beta, alpha)

            self.delay = delay_data(delay, slew_out)
            return self.delay

    def evaluate_distributed_delay(self, driver_res: float, driver_gm: float, load_caps: float,
                                   next_node_load: GraphLoad, next_node: 'GraphNode',
                                   slew_in: float):
        instances_groups = next_node_load.module.group_pin_instances_by_mod(next_node_load.pin_name)
        # find the most relevant instance group.
        # Just a heuristic, getting more deterministic result is more complicated
        # If only one instance group, then answer is obvious
        # If one of the groups's module matches the module of the next_node, then choose that group
        # Otherwise choose the group with the maximum number of loads and add the others to regular caps
        if len(instances_groups) == 1:
            distributed_load = next(iter(instances_groups.values()))
        else:
            distributed_load = None
            other_internal_loads = []
            # use module name
            if next_node:
                for load in instances_groups.values():
                    if load[2].name == next_node.module.name:
                        distributed_load = load
                    else:
                        other_internal_loads.append(load)
            # still not found use count
            if distributed_load is None:
                other_internal_loads.clear()
                instance_groups_list = list(instances_groups.values())
                max_count_index = max(range(len(instance_groups_list)),
                                      key=lambda x: instance_groups_list[x][0])
                distributed_load = instance_groups_list[max_count_index]
                other_internal_loads = (instance_groups_list[:max_count_index] +
                                        instance_groups_list[max_count_index + 1:])
            # add other internal loads as regular caps
            for other_internal in other_internal_loads:
                graph_load = GraphLoad(pin_name=other_internal[1], module=other_internal[2],
                                       count=other_internal[0], wire_length=0.0)
                load_caps += graph_load.evaluate_cin()
            #
            input_pin = next_node_load.module.get_pin(next_node_load.pin_name)
            connecting_wire_length = next_node_load.wire_length
            connecting_wire_width = min(input_pin.width(), input_pin.height())
            additional_wire_cap = next_node_load.module.get_wire_cap(wire_layer=input_pin.layer,
                                                                     wire_width=connecting_wire_width,
                                                                     wire_length=connecting_wire_length)
            load_caps += additional_wire_cap
            additional_wire_res = next_node_load.module.get_wire_res(wire_layer=input_pin.layer,
                                                                     wire_width=connecting_wire_width,
                                                                     wire_length=connecting_wire_length)
            driver_res += additional_wire_res

        num_elements, pin_name, module = distributed_load
        input_pin = module.get_pin(pin_name)
        pin_length = max(max(input_pin.width(), input_pin.height()),
                         min(module.width, module.height))
        pin_width = min(input_pin.width(), input_pin.height())
        cap_per_unit, _ = module.get_input_cap(pin_name, num_elements=1, wire_length=pin_length,
                                               interpolate=False)
        res_per_stage = module.get_wire_res(wire_layer=input_pin.layer,
                                            wire_width=pin_width, wire_length=pin_length)
        delay, slew_out = module.distributed_delay(cap_per_unit, res_per_stage, num_elements,
                                                   driver_res, driver_gm, load_caps, slew_in)
        self.delay = delay_data(delay, slew_out)
        return self.delay

    def get_full_net(self, in_net=True):
        net = self.parent_in_net if in_net else self.parent_out_net
        net = net.lower()

        all_parent_modules = [x for x in self.all_parent_modules]

        while len(all_parent_modules) > 0:
            module, conn = all_parent_modules.pop(-1)
            module_pins = [x.lower() for x in module.pins]
            if net in module_pins:
                pin_index = module_pins.index(net)
                if len(all_parent_modules) > 0:
                    net = all_parent_modules[-1][1][pin_index]
                else:
                    break
            else:
                break
        if len(all_parent_modules) == 0:
            return net
        full_net = ""
        for parent_module, conn in all_parent_modules:
            inst_name = parent_module.insts[parent_module.conns.index(conn)].name
            full_net += "X{}.".format(inst_name)
        full_net += net
        return full_net

    def __str__(self):
        if self.delay is not None:
            delay_suffix = " ({:.3g} p) ".format(self.delay.delay * 1e12)
        else:
            delay_suffix = ""
        return " {}:{}-> | {}:{} | -> {}:{} {} ".format(self.get_full_net(), self.in_net,
                                                        self.instance_name,
                                                        self.module.name, self.get_full_net(in_net=False),
                                                        self.out_net, delay_suffix)

    def __repr__(self):
        return self.__str__()


class GraphPath:
    """Represent a path of GraphNode from a source net to a destination net"""

    def __init__(self, nodes=None):
        self.nodes = nodes if nodes is not None else []  # type: List[GraphNode]
        debug.info(3, "Created GraphPath: %s", self)

    def prepend_node(self, node: GraphNode):
        return GraphPath([node] + self.nodes)

    def prepend_nodes(self, path: "GraphPath"):
        nodes = path.nodes + self.nodes
        return GraphPath(nodes)

    def traverse_loads(self, estimate_wire_lengths=True, top_level_module=None):
        """
        :param estimate_wire_lengths: Use distance between pins as pin length
        :param top_level_module: check for loads to pins at hierarchies up to 'top_level_module'
        """
        if top_level_module is None:
            top_level_module = self.nodes[0].parent_module
        for graph_node in self.nodes:
            graph_node.extract_loads(estimate_wire_lengths=estimate_wire_lengths,
                                     top_level_module=top_level_module)

    def evaluate_delays(self, slew_in):
        for i in range(len(self.nodes)):
            if i == len(self.nodes) - 1:
                next_node = None
            else:
                next_node = self.nodes[i + 1]
            graph_node = self.nodes[i]
            delay_val = graph_node.evaluate_delay(next_node=next_node, slew_in=slew_in)
            slew_in = delay_val.slew

    def get_cin(self, pin_name):
        """Assumes first node's parent module is the real parent module"""
        # evaluate instance inputs
        source_node = self.nodes[0]
        parent_module = source_node.parent_module

        return parent_module.get_input_cap_from_instances(pin_name=pin_name)

    @property
    def source_node(self):
        return self.nodes[0]

    @source_node.setter
    def source_node(self, value):
        self.nodes[0] = value

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        result = ""
        for i in range(len(self.nodes)):
            start_node = self.nodes[i]
            if i < len(self.nodes) - 1:
                end_node = self.nodes[i + 1]
                end_internal_net = end_node.in_net
                end_net = end_node.get_full_net(in_net=True)
            else:
                end_node = self.nodes[i]
                end_internal_net = end_node.out_net
                end_net = end_node.get_full_net(in_net=False)
            if start_node.delay is not None:
                delay_suffix = " ({:.3g} p) ".format(start_node.delay.delay * 1e12)
            else:
                delay_suffix = ""
            result += "\n" + 4 * (i + 1) * " " + " {}:{}-> | {}:{} | -> {}:{} {} ".format(
                start_node.get_full_net(), start_node.in_net, start_node.instance_name,
                start_node.module.name, end_net, end_internal_net, delay_suffix
            )
        return result

    def __len__(self):
        return len(self.nodes)


def get_instance_module(instance_name: str, parent_module: design):
    """Get module for instance given the instance name"""
    instance_name = instance_name.lower()

    def name_matches(inst):
        candidate_name = inst.name.lower().strip()  # type: str
        return (candidate_name == instance_name or
                (instance_name and instance_name.startswith("x") and
                 instance_name[1:] == candidate_name))

    matches = list(filter(name_matches, parent_module.insts))
    if not matches:
        raise ValueError("Invalid instance name {} in module {}".format(instance_name, parent_module.name))

    return matches[0]


def get_net_hierarchy(net: str, parent_module: design):
    """Split net into hierarchy of parent modules
    e.g. inst1.inst2.out will split into [int1_mod, inst2_mod]
    :return [list of hierarchy]
    """
    net = net.lower()
    net_split = net.split(".")
    hierarchy = [parent_module]
    inst_hierarchy = []

    current_module = parent_module
    for index, branch in enumerate(net_split[:-1]):
        if current_module.is_library_cell:
            # TODO handle nested library cell
            remnant = ".".join(net_split[index:])
            debug.error(f"Invalid nested net {remnant} in primitive"
                        f" module {current_module.name}")
        child_inst = get_instance_module(branch, current_module)
        child_module = child_inst.mod
        hierarchy.append(child_module)
        inst_hierarchy.append(child_inst)
        current_module = child_module

    return net_split[-1], hierarchy, inst_hierarchy


def get_all_net_connections(net: str, module: design):
    net = net.lower()
    # first check if there is an instance whose output is the pin, otherwise, settle for inout
    for i in range(len(module.conns)):
        conn = [x.lower() for x in module.conns[i]]
        if net not in conn:
            continue
        child_module = module.insts[i].mod  # type: design
        pin_index = conn.index(net)
        child_pin = child_module.pins[pin_index]
        pin_dir = child_module.get_pin_dir(child_pin)
        yield child_pin, child_module, i, pin_dir


def get_net_driver(net: str, module: design):
    out_drivers, in_out_drivers = get_all_net_drivers(net, module)
    driver = None
    if out_drivers:
        driver = out_drivers[0]
    if in_out_drivers:
        driver = in_out_drivers[0]
    debug.info(4, "Driver for net %s in module %s is %s", net, module.name, driver[1].name)
    return driver


def get_all_net_drivers(net: str, module: design):
    all_connections = list(get_all_net_connections(net, module))
    all_connections = [(x[0], x[1], module.conns[x[2]], x[3]) for x in all_connections]
    output_drivers = [tuple(x[:3]) for x in all_connections if x[3] == OUTPUT]
    inout_drivers = [tuple(x[:3]) for x in all_connections if x[3] == INOUT]
    if not output_drivers + inout_drivers:
        raise ValueError("net {} not driven by an output or inout pin"
                         " in module {}".format(net, module.name))

    return output_drivers, inout_drivers


def get_all_drivers_for_pin(net: str, parent_module: design):
    output_drivers, inout_drivers = get_all_net_drivers(net, parent_module)
    all_drivers = output_drivers + inout_drivers
    results = []
    for child_pin, child_module, conn in all_drivers:
        if child_module.is_delay_primitive():
            results.append([ModuleConn(parent_module, conn), (child_module, child_pin, net)])
        else:
            descendants = get_all_drivers_for_pin(child_pin, child_module)
            for desc_ in descendants:
                results.append([ModuleConn(parent_module, conn)] + desc_)
    return results


def get_driver_for_pin(net: str, parent_module: design):
    """Get hierarchy of modules driving a pin """
    child_pin, child_module, conn = get_net_driver(net, parent_module)

    if child_module.is_delay_primitive():
        return [parent_module, child_module, (child_pin, net, conn)]
    descendants = get_driver_for_pin(child_pin, child_module)
    return [(parent_module, conn)] + descendants


def remove_path_loops(paths: List[GraphPath]):
    valid_paths = []
    for path in paths:
        has_loop = False
        existing_nodes = []
        for node in path.nodes:
            node_tuple = (node.all_parent_modules, node.module, node.in_net, node.out_net,
                          node.conn)
            if node_tuple in existing_nodes:
                has_loop = True
                break
            existing_nodes.append(node_tuple)
        if not has_loop:
            valid_paths.append(path)
    return valid_paths


def flatten_paths(paths, module, current_depth, max_depth, max_adjacent_modules,
                  driver_exclusions):
    # Process derived inputs by descending into modules that created them
    processing_queue = [x for x in paths]  # quick copy
    processed_paths = []

    sibling_iterations_count = 0
    while len(processing_queue) > 0:
        # remove cycles
        processing_queue = remove_path_loops(processing_queue)
        if not processing_queue:
            break

        path = processing_queue[0]

        source_node = path.source_node
        if source_node.parent_in_net in module.pins:  # not a derived node
            # check if it's explicitly an input
            if module.get_pin_dir(source_node.parent_in_net) == INPUT:
                processed_paths.append(path)
                processing_queue.remove(path)
                continue

        # find module that drives this net within the current hierarchy
        sibling_out_pin, sibling_module, sibling_conn = get_net_driver(
            source_node.parent_in_net, module)
        if sibling_module.name in driver_exclusions:
            processing_queue.remove(path)
            continue

        if sibling_module.is_delay_primitive():
            sibling_input_pins = sibling_module.get_inputs_for_pin(sibling_out_pin)
            for sibling_input_pin in sibling_input_pins:
                if sibling_input_pin == sibling_out_pin:
                    continue
                sibling_pin_index = sibling_module.pins.index(sibling_input_pin)
                all_parent_modules = source_node.all_parent_modules[:-1] + [(module, sibling_conn)]
                sibling_node = GraphNode(in_net=sibling_input_pin, out_net=sibling_out_pin,
                                         module=sibling_module,
                                         parent_in_net=sibling_conn[sibling_pin_index],
                                         parent_out_net=source_node.parent_in_net,
                                         all_parent_modules=all_parent_modules, conn=sibling_conn)
                new_path = path.prepend_node(sibling_node)
                processing_queue.append(new_path)
        else:
            sibling_hierarchy = get_all_drivers_for_pin(sibling_out_pin, sibling_module)[0]
            sibling_paths = construct_paths(sibling_hierarchy, current_depth=current_depth + 1,
                                            max_depth=max_depth,
                                            max_adjacent_modules=max_adjacent_modules,
                                            driver_exclusions=driver_exclusions)
            if len(source_node.all_parent_modules) > 0:
                module_conn = [ModuleConn(source_node.all_parent_modules[-1][0], sibling_conn)]
            else:
                module_conn = []

            # fix hierarchy of sibling source node
            for sibling_path in sibling_paths:
                sibling_source_node = sibling_path.source_node
                all_sibling_parents = module_conn + sibling_source_node.all_parent_modules
                for i in range(len(all_sibling_parents) - 1, 0, -1):
                    _, parent_conn = all_sibling_parents[i - 1]
                    parent_mod, _ = all_sibling_parents[i]
                    if sibling_source_node.parent_in_net not in parent_mod.pins:
                        break
                    pin_index = parent_mod.pins.index(sibling_source_node.parent_in_net)
                    sibling_source_node.parent_in_net = parent_conn[pin_index]
                sibling_source_node.all_parent_modules = []

            # some nodes are shared between paths: prevent double updates
            all_nodes = set([node for sibling_path in sibling_paths for node in sibling_path.nodes])
            for node in all_nodes:
                node.all_parent_modules = (source_node.all_parent_modules[:-1] + module_conn +
                                           node.all_parent_modules)

            for sibling_path in sibling_paths:
                new_path = path.prepend_nodes(sibling_path)
                processing_queue.append(new_path)

        processing_queue.remove(path)

        sibling_iterations_count += 1
        if sibling_iterations_count > max_adjacent_modules:
            raise ValueError("max_adjacent_modules exceeded. Netlist potentially contains cycles"
                             " or try increasing max_adjacent_modules from {}".format(max_adjacent_modules))
    return processed_paths


def construct_paths(driver_hierarchy, current_depth=0, max_depth=20, max_adjacent_modules=100,
                    driver_exclusions=None):
    """
    Construct list of GraphPath for all input pins to outputs
    :param driver_hierarchy: [mod1, mod2, ..., modn, (pin_name, net, conn)]
    :param current_depth: hierarchy depth
    :param max_depth: Max hierarchical depth, prevents infinite cyclic routes
    :param max_adjacent_modules: Max number of sibling modules to derive from. Prevents cyclic routes
    :param driver_exclusions: Check 'create_graph' for documentation
    :return: List[GraphPath]
    """

    if current_depth >= max_depth:
        raise ValueError("Max depth exceeded. Netlist potentially contains cycles"
                         " or try increasing max_depth from {}".format(max_depth))

    paths = []  # type: List[GraphPath]

    driver_module, instance_pin_name, output_net = driver_hierarchy[-1]  # type: (design, str, str)
    immediate_parent_module, conn = driver_hierarchy[-2]
    original_parent = immediate_parent_module

    parent_modules = driver_hierarchy[:-2]  # type: List[Tuple[design, List[str]]]

    input_pins = driver_module.get_inputs_for_pin(instance_pin_name)
    for pin in input_pins:
        pin_index = driver_module.pins.index(pin)
        parent_module_net = conn[pin_index]

        all_parent_modules = parent_modules + [(immediate_parent_module, conn)]
        graph_node = GraphNode(in_net=pin, out_net=instance_pin_name, module=driver_module,
                               parent_in_net=parent_module_net, parent_out_net=output_net,
                               all_parent_modules=all_parent_modules, conn=conn)
        paths.append(GraphPath([graph_node]))

    processed_paths = flatten_paths(paths, immediate_parent_module, current_depth,
                                    max_depth, max_adjacent_modules,
                                    driver_exclusions=driver_exclusions)

    # Process ancestors
    all_ancestors = list(reversed(parent_modules))
    for i in range(len(all_ancestors)):
        ancestor_module, ancestor_conn = all_ancestors[i]
        for path in processed_paths:
            source_node = path.source_node
            # derive parent nets
            in_pin_index = immediate_parent_module.pins.index(source_node.parent_in_net)
            ancestor_in_net = ancestor_conn[in_pin_index]
            # update hierarchy
            source_node.parent_in_net = ancestor_in_net
            source_node.parent_module = ancestor_module
            source_node.all_parent_modules = source_node.all_parent_modules[:-1]

        processed_paths = flatten_paths(processed_paths, ancestor_module, current_depth, max_depth,
                                        max_adjacent_modules, driver_exclusions=driver_exclusions)

        immediate_parent_module = ancestor_module

    debug.info(2, "Derived path for %s in %s:", output_net, original_parent.name)
    for path in processed_paths:
        debug.info(2, "%s", path)
    return processed_paths


def create_graph(destination_net, module: design, driver_exclusions=None,
                 driver_inclusions=None):
    """
    Create a list of GraphPath from all input pins to destination_net
    :param destination_net: destination_net
    :param module: The module to derive. Should be a subclass of 'design'
    :param driver_exclusions: the drivers to exclude from derivation.
            This is useful for nets that are driven by multiple nodes
            For example, bitlines are driven by precharge, bitcells, write_driver etc
            Exclude bitcells from path by adding e.g. cell_6t to driver_exclusions
    :param driver_inclusions: Only include these drivers.
            Only used at initial driver driver determination stage
            Ignored if empty or None
    :return: List[GraphPath]
    """
    if driver_exclusions is None:
        driver_exclusions = []
    if driver_inclusions is None:
        driver_inclusions = []
    destination_net, dest_hierarchy, inst_hier = get_net_hierarchy(destination_net, module)

    # Attach parent insts to path nodes
    parent_modules = []
    for child_inst, parent_module in zip(inst_hier, dest_hierarchy):
        child_conn = parent_module.conns[parent_module.insts.index(child_inst)]
        parent_modules.append(ModuleConn(parent_module, child_conn))

    all_paths = []
    all_hierarchies = get_all_drivers_for_pin(destination_net, dest_hierarchy[-1])
    # breakpoint()
    for driver_hierarchy in all_hierarchies:
        exclude = False
        include = not bool(driver_inclusions)  # empty inclusions will include all

        for sub_hier in driver_hierarchy:
            mod, _ = sub_hier[:2]
            if mod.name in driver_exclusions:
                exclude = True
            if mod.name in driver_inclusions:
                include = True

        if include and not exclude:
            all_paths.extend(construct_paths(parent_modules + driver_hierarchy,
                                             driver_exclusions=driver_exclusions))

    return all_paths
