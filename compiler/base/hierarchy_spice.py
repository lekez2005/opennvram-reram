import io
import math
import os
from typing import Union, List, Tuple

import debug
from base import verilog
from base.spice_parser import SpiceParser
from characterizer.characterization_data import load_data

INPUT = "INPUT"
INOUT = "INOUT"
OUTPUT = "OUTPUT"
POWER = "POWER"
GROUND = "GROUND"


class spice(verilog.verilog):
    """
    This provides a set of useful generic types for hierarchy
    management. If a module is a custom designed cell, it will read from
    the GDS and spice files and perform LVS/DRC. If it is dynamically
    generated, it should implement a constructor to create the
    layout/netlist and perform LVS/DRC.
    Class consisting of a set of modules and instances of these modules
    """

    def __init__(self, name):
        self.name = name

        self.mods = []  # Holds subckts/mods for this module
        self.pins = []  # Holds the pins for this module
        self.pin_type = {} # The type map of each pin: INPUT, OUTPUT, INOUT, POWER, GROUND
        # for each instance, this is the set of nets/nodes that map to the pins for this instance
        # THIS MUST MATCH THE ORDER OF THE PINS (restriction imposed by the
        # Spice format)
        self.conns = []

        self.sp_read()
        # string representation of spice_content
        self.spice_content = None  # type: Union[None, str]
        self.spice_parser = None  # type: Union[None, SpiceParser]

############################################################
# Spice circuit
############################################################

    def add_pin(self, name, pin_type=None):
        """ Adds a pin to the pins list. Default type is INOUT signal. """
        self.pins.append(name)
        self.pin_type[name]=pin_type

    def add_pin_list(self, pin_list, pin_type_list=None):
        """ Adds a pin_list to the pins list """
        # The type list can be a single type for all pins
        # or a list that is the same length as the pin list.
        if type(pin_type_list) == str or pin_type_list is None:
            for pin in pin_list:
                self.add_pin(pin, pin_type_list)
        elif len(pin_type_list) == len(pin_list):
            for (pin, ptype) in zip(pin_list, pin_type_list):
                self.add_pin(pin, ptype)
        else:
            debug.error("Mismatch in type and pin list lengths.", -1)

    def get_pin_type(self, name: str):
        """ Returns the type of the signal pin.
            If pin type is not specified when pin was added uses heuristic to determine type
            vdd is POWER, gnd, vss are GND
            Otherwise, if attached to at least one gate, it's input, else OUTPUT
        """
        lower_case_pins = [x.lower() for x in self.pins]
        name_lower = name.lower()
        if name_lower not in lower_case_pins:
            raise ValueError("Invalid pin name {} for module {}".format(name, self.__class__.__name__))

        pin_index = lower_case_pins.index(name_lower)
        actual_pin_name = self.pins[pin_index]

        if actual_pin_name in self.pin_type and self.pin_type[actual_pin_name] is not None:
            return self.pin_type[actual_pin_name]

        if name_lower in ["vss", "gnd"]:
            return GROUND
        elif name_lower in ["vdd"]:
            return POWER
        debug.info(3, "Loading pin type for pin {0} type for module {1} from file".format(name, self.name))
        spice_parser = self.get_spice_parser()
        pin_caps = spice_parser.extract_caps_for_pin(name_lower, self.name)
        if ((pin_caps["n"]["g"][1] or pin_caps["p"]["g"][1]) and
                (pin_caps["n"]["d"][1] or pin_caps["p"]["d"][1])):  # connected to both drains and gates
            pin_type = INOUT
        elif pin_caps["n"]["g"][1] or pin_caps["p"]["g"][1]:
            pin_type = INPUT
        else:
            pin_type = OUTPUT
        self.pin_type[actual_pin_name] = pin_type

        debug.info(3, "Loaded pin type for pin {0} in module {1}  = {2}".format(actual_pin_name,
                                                                                self.__class__.__name__,
                                                                                self.pin_type[actual_pin_name]))

        return self.pin_type[actual_pin_name]

    def get_pin_dir(self, name):
        """ Returns the direction of the pin. (Supply/ground are INOUT). """
        name_lower = name.lower()
        all_types = set()
        conns = [(conn_index, conn) for conn_index, conn in enumerate(self.conns)
                 if name_lower in [y.lower() for y in conn]]
        if conns:
            for conn_index, conn in conns:
                conn = [y.lower() for y in conn]
                pin = self.insts[conn_index].mod.pins[conn.index(name_lower)]
                all_types.add(self.insts[conn_index].mod.get_pin_dir(pin))
        if all_types:
            if len(all_types) == 1:
                return all_types.pop()
            else:
                return INOUT
        pin_type = self.get_pin_type(name)
        if pin_type in [POWER, GROUND]:
            return INOUT
        else:
            return pin_type

    def get_input_pins(self):
        return [pin for pin in self.pins if self.get_pin_dir(pin) == INPUT]

    def get_output_pins(self):
        return [pin for pin in self.pins if self.get_pin_dir(pin) == OUTPUT]

    def get_in_out_pins(self):
        return [pin for pin in self.pins if self.get_pin_dir(pin) == INOUT]

    def get_inputs_for_pin(self, out_pin):
        """Get input pins that control the specified output pin"""
        conns = [(conn_index, conn) for conn_index, conn in enumerate(self.conns)
                 if out_pin in conn]
        if not conns:
            return self.get_input_pins()
        input_pins = set()
        for conn_index, conn in conns:
            inst_mod = self.insts[conn_index].mod
            inst_mod_pin = inst_mod.pins[conn.index(out_pin)]
            inst_in_pins = inst_mod.get_inputs_for_pin(inst_mod_pin)
            for in_pin in inst_in_pins:
                pin_index = inst_mod.pins.index(in_pin)
                input_pins.add(conn[pin_index])
        input_pins = input_pins.intersection(self.pins)
        return list(input_pins)

    def add_mod(self, mod):
        """Adds a subckt/submodule to the subckt hierarchy"""
        self.mods.append(mod)

    def connect_inst(self, args, check=True):
        """Connects the pins of the last instance added
        It is preferred to use the function with the check to find if
        there is a problem. The check option can be set to false
        where we dynamically generate groups of connections after a
        group of modules are generated."""

        if check and (len(self.insts[-1].mod.pins) != len(args)):
            debug.error("Number of net connections ({0}) does not match last module instance connections ({1})"
                        .format(len(args), len(self.insts[-1].mod.pins)), 1)
        self.conns.append(args)

        if check and (len(self.insts)!=len(self.conns)):
            debug.error("{0} : Not all instance pins ({1}) are connected ({2}).".format(self.name,
                                                                                        len(self.insts),
                                                                                        len(self.conns)))
            debug.error("Instances: \n"+str(self.insts))
            debug.error("-----")
            debug.error("Connections: \n"+str(self.conns),1)



    def sp_read(self):
        """Reads the sp file (and parse the pins) from the library 
           Otherwise, initialize it to null for dynamic generation"""
        if os.path.isfile(self.sp_file):
            debug.info(3, "opening {0}".format(self.sp_file))
            self.spice_parser = SpiceParser(self.sp_file)
            self.pins = self.spice_parser.get_pins(self.name)
            self.spice = self.spice_parser.all_lines
        else:
            self.spice = []

    def contains(self, mod, modlist):
        for x in modlist:
            if x.name == mod.name:
                return True
        return False

    def sp_write_file(self, sp, usedMODS):
        """ Recursive spice subcircuit write;
            Writes the spice subcircuit from the library or the dynamically generated one"""
        if not self.spice:
            # recursively write the modules
            for i in self.mods:
                if self.contains(i, usedMODS):
                    continue
                usedMODS.append(i)
                i.sp_write_file(sp, usedMODS)

            if len(self.insts) == 0:
                return
            if self.pins == []:
                return

            # every instance must have a set of connections, even if it is empty.
            if  len(self.insts)!=len(self.conns):
                debug.error("{0} : Not all instance pins ({1}) are connected ({2}).".format(self.name,
                                                                                            len(self.insts),
                                                                                            len(self.conns)))
                debug.error("Instances: \n"+str(self.insts))
                debug.error("-----")
                debug.error("Connections: \n"+str(self.conns),1)

            # write out the first spice line (the subcircuit)
            pins_str = " ".join(self.pins)
            spice = [f"\n.SUBCKT {self.name} {pins_str}"]
            for i in range(len(self.insts)):
                # we don't need to output connections of empty instances.
                # these are wires and paths
                if self.conns[i] == []:
                    continue
                conn_str = " ".join(self.conns[i])
                inst_name = self.insts[i].name
                if hasattr(self.insts[i].mod,"spice_device"):
                    device_spice = self.insts[i].mod.spice_device
                    spice.append(device_spice.format(inst_name, conn_str))
                else:
                    mod_name = self.insts[i].mod.name
                    spice.append(f"X{inst_name} {conn_str} {mod_name}")

            spice.append(f".ENDS {self.name}")

        else:
            # write the subcircuit itself
            # Including the file path makes the unit test fail for other users.
            # if os.path.isfile(self.sp_file):
            #    sp.write("\n* {0}\n".format(self.sp_file))
            spice = self.spice
        sp.write("\n".join(spice))

        sp.write("\n")

    def sp_write(self, spname):
        """Writes the spice to files"""
        debug.info(3, "Writing to {0}".format(spname))
        spfile = open(spname, 'w')
        spfile.write("*FIRST LINE IS A COMMENT\n")
        usedMODS = list()
        self.sp_write_file(spfile, usedMODS)
        del usedMODS
        spfile.close()

    def is_delay_primitive(self):
        """Whether to descend into this module to evaluate sub-modules for delay"""
        return not (self.conns and next(filter(len, self.conns)))

    def get_spice_content(self):
        """Content of spice file
        If module is a custom module, then returns the content of original spice file
        Else exports netlist to in memory-spice string
        """
        if self.spice_content is None:
            spring_writer = io.StringIO("")
            used_mods = []
            self.sp_write_file(spring_writer, used_mods)
            del used_mods
            self.spice_content = spring_writer.getvalue()
            spring_writer.close()
        return self.spice_content

    def get_spice_parser(self):
        """gets spice parser"""
        if self.spice_parser is None:
            if self.spice_content is None:
                self.get_spice_content()
            self.spice_parser = SpiceParser(self.spice_content)
        return self.spice_parser

    def get_char_data_file_suffixes(self, **kwargs) -> List[Tuple[str, float]]:
        """
        Get filters for characterized data file name to guide choice of look up table file
        :return: list of (filter_name, filter_value) tuples
        """
        return []

    def get_char_data_size_suffixes(self, **kwargs) -> List[Tuple[str, float]]:
        """
        Get filters for characterized size look up table
        :return: list of (filter_name, filter_value) tuples
        """
        return [(key, value) for key, value in kwargs.items()]

    def get_char_data_size(self):
        """Size to use for characterization data look up table"""
        return 1

    def get_char_data_name(self, **kwargs) -> str:
        """
        name by which module was characterized
        :return:
        """
        return self.name

    def get_input_cap_from_char(self, pin_name, num_elements: int = 1,
                                wire_length: float = 0.0, interpolate=True, **kwargs):
        """Loads input cap from characterized data"""
        module_name = self.get_char_data_name(**kwargs)

        file_suffixes = self.get_char_data_file_suffixes(**kwargs)

        kwargs["cols"] = num_elements
        kwargs["wire"] = wire_length
        size_suffixes = self.get_char_data_size_suffixes(**kwargs)
        return load_data(cell_name=module_name, pin_name=pin_name,
                         size=self.get_char_data_size(), file_suffixes=file_suffixes,
                         size_suffixes=size_suffixes, interpolate_size_suffixes=interpolate)

    def compute_pin_wire_cap(self, pin_name, wire_length=0.0):
        """Computes wire cap due to pin only"""
        wire_cap = 0
        for pin in self.get_pins(pin_name):
            pin_width = min(pin.width(), pin.height())

            pin_length = max(pin.width(), pin.height(), wire_length)

            wire_cap += self.get_wire_cap(pin.layer, pin_width, pin_length)
        return wire_cap

    def compute_input_cap(self, pin_name, wire_length: float = 0.0):
        """Compute unit capacitance in F for pin_name and wire_length"""

        from pgates.ptx import ptx
        from tech import spice as tech_spice

        wire_cap = self.compute_pin_wire_cap(pin_name, wire_length)

        transistor_connections = self.get_spice_parser().extract_caps_for_pin(pin_name,
                                                                              self.name)
        total_caps = wire_cap
        for tx_type in transistor_connections:
            for terminal in transistor_connections[tx_type]:
                for m, nf, width in transistor_connections[tx_type][terminal][1]:
                    if tech_spice["scale_tx_parameters"]:
                        width *= 1e6
                    total_caps += ptx.get_tx_cap(tx_type, terminal, width, nf, m)

        debug.info(4, "Computed input cap for {} module {} = {:.4g}fF".
                   format(pin_name, self.name, total_caps * 1e15))

        return total_caps

    def get_wire_res(self, wire_layer: str, wire_width: float, wire_length: float):
        """
        Return resistance in ohm for given
        :param wire_layer: layer name
        :param wire_width: in um
        :param wire_length: in um
        :return: res in ohm
        """
        from tech import delay_params_class
        unit_cap, res = delay_params_class().get_rc(layer=wire_layer, width=wire_width)
        return res * wire_length

    def get_wire_cap(self, wire_layer: str, wire_width: float, wire_length: float):
        """
        Return cap in F for given
        :param wire_layer: layer name
        :param wire_width: in um
        :param wire_length: in um
        :return: cap in F
        """
        from tech import delay_params_class
        unit_cap, res = delay_params_class().get_rc(layer=wire_layer, width=wire_width)
        return unit_cap * wire_length

    def group_pin_instances_by_mod(self, pin_name):
        # Group by instance mod
        instances_groups = {}
        for i in range(len(self.conns)):
            conn = self.conns[i]
            if pin_name not in conn:
                continue
            child_module = self.insts[i].mod
            child_module_name = child_module.name
            child_module_pin_name = child_module.pins[conn.index(pin_name)]
            if child_module_name not in instances_groups:
                instances_groups[child_module_name] = [0, child_module_pin_name, child_module]
            instances_groups[child_module_name][0] += 1
        return instances_groups

    def get_input_cap_from_instances(self, pin_name, wire_length: float = 0.0, **kwargs):
        instances_groups = self.group_pin_instances_by_mod(pin_name)

        results = []
        for module_name in instances_groups:
            module = instances_groups[module_name][2]
            num_elements = instances_groups[module_name][0]
            instance_pin_name = instances_groups[module_name][1]
            _, cap_per_stage = module.get_input_cap(instance_pin_name, 1,
                                                    0.0, interpolate=False, **kwargs)
            total_cap, _ = module.get_input_cap(instance_pin_name, num_elements, wire_length,
                                                interpolate=True, **kwargs)
            # total_cap *= num_elements
            # characterized data may be more accurate so potentially override computed
            # cap_per_stage if it's less than characterized
            cap_per_stage = max(cap_per_stage, total_cap / num_elements)
            results.append((total_cap, cap_per_stage))

        wire_cap = self.compute_pin_wire_cap(pin_name, wire_length)
        total_cap = sum(map(lambda x: x[0], results)) + wire_cap
        # cap per stage doesn't make sense when calculating from instances
        total_cap, cap_per_stage = total_cap, total_cap
        debug.info(2, "Wire cap for pin {} in module {} = {:.3g} fF".format(pin_name,
                                                                            self.name,
                                                                            wire_cap * 1e15))
        debug.info(2, "Instances cap for pin {} in module {} = {:.3g} fF".format(pin_name, self.name,
                                                                                 (total_cap - wire_cap) * 1e15))
        return total_cap, cap_per_stage

    def get_input_cap(self, pin_name, num_elements: int = 1, wire_length: float = 0.0,
                      interpolate=None, **kwargs):
        """
        Calculate input capacitance
        First check if first name was characterized
        If not, use information from instances the pin is connected to
        Otherwise, extract transistor connections from spice and calculate based on that
        :param pin_name:
        :param num_elements:
        :param wire_length:
        :param interpolate If exact match not found in characterized data,
         cin is computed rather than interpolated
        :return: tuple with content (total_cap_in, cap_per_stage)
        """
        from globals import OPTS
        if interpolate is None:
            interpolate = OPTS.interpolate_characterization_data

        if OPTS.use_characterization_data:
            cap_value = self.get_input_cap_from_char(pin_name, num_elements=num_elements,
                                                     wire_length=wire_length,
                                                     interpolate=interpolate, **kwargs)
            if cap_value is not None:
                return cap_value * num_elements, cap_value

        if self.conns and list(filter(len, self.conns)):
            # contains instances i.e. probably not an imported custom cell
            _, cap_per_stage = self.get_input_cap_from_instances(pin_name, wire_length,
                                                                 **kwargs)
            return num_elements * cap_per_stage, cap_per_stage

        # compute if not previously characterized
        cap_value = num_elements * self.compute_input_cap(pin_name, wire_length)
        return cap_value, cap_value / num_elements

    def lookup_resistance(self, pin_name, interpolate, corner):
        # try look up from characterization
        for suffix in ["_" + pin_name, ""]:
            resistance = self.get_input_cap_from_char("resistance" + suffix, interpolate=interpolate,
                                                      corner=corner)
            if resistance:
                return resistance

    def get_driver_resistance(self, pin_name, use_max_res=False, interpolate=None, corner=None):
        """
        Get driver resistance for given pin_name
        :param pin_name:
        :param interpolate: Interpolate transistor properties like width and fingers
        :param corner: (process, vdd, temperature)
        :param use_max_res: Whether to return individual resistances or just the largest
        :return: {"p": <pull_up_resistance>, "n": <pull_down_resistance>} or max_res if use_max_res
        """
        from pgates.ptx import ptx
        from globals import OPTS

        if interpolate is None:
            interpolate = OPTS.interpolate_characterization_data
        resistance = self.lookup_resistance(pin_name, interpolate, corner)
        if resistance:
            return resistance
        # compute
        resistance_paths = self.get_spice_parser().extract_res_for_pin(pin_name, self.name)

        resistances = {}
        for tx_type, paths in resistance_paths.items():
            if len(paths) > 0:
                resistances[tx_type] = 0
            else:
                resistances[tx_type] = math.inf
                continue
            for path in paths:
                resistance = 0
                for m, nf, width in path:
                    resistance += ptx.get_tx_res(tx_type, width*1e6, nf, m, interpolate=interpolate,
                                                 corner=corner)
                resistances[tx_type] = max(resistance, resistances[tx_type])
        if use_max_res:
            removed_inf = [x if not x == math.inf else 0 for x in resistances.values()]
            return max(removed_inf)
        else:
            return resistances

    def evaluate_driver_gm(self, pin_name, interpolate=None, corner=None):
        from tech import spice as tech_spice

        resistance_paths = self.get_spice_parser().extract_res_for_pin(pin_name, self.name)
        gm = math.inf

        if tech_spice["scale_tx_parameters"]:
            tx_scale = 1e-6
        else:
            tx_scale = 1

        dick_keys = ["p", "n"]
        for i in range(2):
            key = dick_keys[i]
            if resistance_paths[key]:
                flat_list = [x for sublist in resistance_paths[key] for x in sublist]
                min_tx = min(flat_list, key=lambda x: x[0] * x[1] * x[2])
                total_width = min_tx[0] * min_tx[1] * min_tx[2]
                gm_key = "{}mos_unit_gm".format(key)
                min_tx_gm = tech_spice[gm_key] * total_width / (tech_spice["minwidth_tx"] * tx_scale)
                gm = min(min_tx_gm, gm)
        return gm

    @staticmethod
    def horowitz_delay(tau, beta, alpha, switch_threshold=0.5):
        """
        From http://www-vlsi.stanford.edu/people/alum/pdf/8401_Horowitz_TimingModels.pdf Pg 76
        :param tau: time constant (RC)
        :param beta: 1/ (gm * driver_res) (unitless)
        :param alpha: ratio of input slew to tau
        :param switch_threshold: Switch threshold
        :return: delay, slew_out
        """
        delay = tau * math.sqrt((math.log(switch_threshold))**2 +
                                2 * alpha * beta * (1 - switch_threshold))
        slew_out = delay / (1 - switch_threshold)
        return delay, slew_out

    @staticmethod
    def distributed_delay(cap_per_stage, res_per_stage, num_stages,
                          driver_res, driver_gm, other_caps, slew_in):
        """http://bwrcs.eecs.berkeley.edu/Classes/icdesign/ee141_f01/Notes/chapter4.pdf Pg. 125, 127"""
        total_r = res_per_stage * num_stages
        total_distributed_c = cap_per_stage * num_stages
        total_c = total_distributed_c + other_caps

        tau = driver_res * total_c + 0.5 * total_r * total_distributed_c
        beta = 1 / (driver_gm * driver_res)
        alpha = slew_in / tau
        delay, slew_out = spice.horowitz_delay(tau, beta, alpha)

        delay = 0.69 * driver_res * total_c + 0.38 * total_r * total_distributed_c
        slew_out = total_r * total_c
        return delay, slew_out

    @staticmethod
    def simple_rc_delay(tau, switch_threshold=0.5):
        delay = math.log(1/(1 - switch_threshold)) * tau
        slew_out = tau * math.log(0.9 / 0.1)
        return delay, slew_out

    def analytical_delay(self, slew, load=0.0):
        """Inform users undefined delay module while building new modules"""
        debug.warning("Design Class {0} delay function needs to be defined"
                      .format(self.__class__.__name__))
        debug.warning("Class {0} name {1}"
                      .format(self.__class__.__name__,
                              self.name))
        # return 0 to keep code running while building
        return delay_data(0.0, 0.0)

    def cal_delay_with_rc(self, r, c ,slew, swing = 0.5):
        """ 
        Calculate the delay of a mosfet by 
        modeling it as a resistance driving a capacitance
        """
        swing_factor = abs(math.log(1-swing)) # time constant based on swing
        delay = swing_factor * r * c #c is in ff and delay is in fs
        delay = delay * 0.001 #make the unit to ps

        # Output slew should be linear to input slew which is described 
        # as 0.005* slew.

        # The slew will be also influenced by the delay.
        # If no input slew(or too small to make impact) 
        # The mimum slew should be the time to charge RC. 
        # Delay * 2 is from 0 to 100%  swing. 0.6*2*delay is from 20%-80%.
        slew = delay * 0.6 * 2 + 0.005 * slew
        return delay_data(delay = delay, slew = slew)


    def return_delay(self, delay, slew):
        return delay_data(delay, slew)

    def generate_rc_net(self,lump_num, wire_length, wire_width):
        return wire_spice_model(lump_num, wire_length, wire_width)

    def return_power(self, dynamic=0.0, leakage=0.0):
        return power_data(dynamic, leakage)

class delay_data:
    """
    This is the delay class to represent the delay information
    Time is 50% of the signal to 50% of reference signal delay.
    Slew is the 10% of the signal to 90% of signal
    """
    def __init__(self, delay=0.0, slew=0.0):
        """ init function support two init method"""
        # will take single input as a coordinate
        self.delay = delay
        self.slew = slew

    def __str__(self):
        """ override print function output """
        return "Delay Data: Delay "+str(self.delay)+", Slew "+str(self.slew)+""

    def __repr__(self):
        return self.__str__()

    def __add__(self, other):
        """
        Override - function (left), for delay_data: a+b != b+a
        """
        assert isinstance(other,delay_data)
        return delay_data(other.delay + self.delay,
                          other.slew)

    def __radd__(self, other):
        """
        Override - function (right), for delay_data: a+b != b+a
        """
        assert isinstance(other,delay_data)
        return delay_data(other.delay + self.delay,
                          self.slew)

class power_data:
    """
    This is the power class to represent the power information
    Dynamic and leakage power are stored as a single object with this class.
    """
    def __init__(self, dynamic=0.0, leakage=0.0):
        """ init function support two init method"""
        # will take single input as a coordinate
        self.dynamic = dynamic
        self.leakage = leakage

    def __str__(self):
        """ override print function output """
        return "Power Data: Dynamic "+str(self.dynamic)+", Leakage "+str(self.leakage)+" in nW"

    def __add__(self, other):
        """
        Override - function (left), for power_data: a+b != b+a
        """
        assert isinstance(other,power_data)
        return power_data(other.dynamic + self.dynamic,
                          other.leakage + self.leakage)

    def __radd__(self, other):
        """
        Override - function (left), for power_data: a+b != b+a
        """
        assert isinstance(other,power_data)
        return power_data(other.dynamic + self.dynamic,
                          other.leakage + self.leakage)


class wire_spice_model:
    """
    This is the spice class to represent a wire
    """
    def __init__(self, lump_num, wire_length, wire_width):
        self.lump_num = lump_num # the number of segment the wire delay has
        self.wire_c = self.cal_wire_c(wire_length, wire_width) # c in each segment
        self.wire_r = self.cal_wire_r(wire_length, wire_width) # r in each segment

    def cal_wire_c(self, wire_length, wire_width):
        from tech import spice
        total_c = spice["wire_unit_c"] * wire_length * wire_width
        wire_c = total_c / self.lump_num
        return wire_c

    def cal_wire_r(self, wire_length, wire_width):
        from tech import spice
        total_r = spice["wire_unit_r"] * wire_length / wire_width
        wire_r = total_r / self.lump_num
        return wire_r

    def return_input_cap(self):
        return 0.5 * self.wire_c * self.lump_num

    def return_delay_over_wire(self, slew, swing = 0.5):
        # delay will be sum of arithmetic sequence start from
        # rc to self.lump_num*rc with step of rc

        swing_factor = abs(math.log(1-swing)) # time constant based on swing
        sum_factor = (1+self.lump_num) * self.lump_num * 0.5 # sum of the arithmetic sequence
        delay = sum_factor * swing_factor * self.wire_r * self.wire_c
        slew = delay * 2 + slew
        result= delay_data(delay, slew)
        return result

