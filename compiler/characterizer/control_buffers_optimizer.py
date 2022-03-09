import copy
from typing import Dict, Any

import numpy as np

import debug
import tech
from base.design import METAL3, METAL2
from base.geometry import instance, rectangle
from base.pin_layout import pin_layout
from base.vector import vector
from globals import OPTS
from modules.baseline_bank import BaselineBank
from modules.buffer_stage import BufferStage
from modules.control_buffers import ControlBuffers
from modules.logic_buffer import LogicBuffer
from modules.precharge import precharge_characterization


class ControlBufferOptimizer:
    """"""

    def __init__(self, bank: BaselineBank):
        self.bank = bank

    def run_optimizations(self):
        run_optimizations_ = getattr(OPTS, 'run_optimizations', False)
        if not run_optimizations_:
            return False

        # copy to prevent side effects
        self.backups = ["objs", "insts", "conns", "occupied_m4_bitcell_indices", "m2_rails"]
        for name in self.backups:
            setattr(self, name + "_backup", copy.copy(getattr(self.bank, name)))

        self.control_buffer = self.bank.control_buffers  # type: ControlBuffers
        self.place_bank_modules_and_rails()
        self.extract_loads()
        self.optimize_all()

        # restore initial bank
        for name in self.backups:
            setattr(self.bank, name, getattr(self, name + "_backup"))
        return True

    def place_bank_modules_and_rails(self):
        """Place bank modules so we can estimate loads"""
        self.bank.calculate_rail_offsets()
        self.bank.add_modules()

    def extract_loads(self):
        """Create all the buffer stages that will be optimized"""
        self.driver_loads = {}
        self.extract_control_buffer_loads()
        self.extract_wordline_driver_loads()
        self.extract_row_decoder_loads()
        self.extract_col_decoder_loads()
        self.extract_control_flop_loads()

    def create_buffer_stages_config(self, driver_conn_index):
        """Given a buffer stage inst's conn index, derive the parent mod and the logic driving the buffer stage"""
        driver_inst = self.control_buffer.insts[driver_conn_index]
        if isinstance(driver_inst.mod, LogicBuffer):
            buffer_stages_inst = driver_inst.mod.buffer_inst
            logic_driver_inst = driver_inst.mod.logic_inst
            parent_mod = driver_inst.mod
        else:
            driver_conn = self.control_buffer.conns[driver_conn_index]
            input_net = driver_conn[0]
            logic_driver_inst, _ = self.control_buffer.get_output_driver(input_net)
            buffer_stages_inst = driver_inst
            parent_mod = self.control_buffer
        if hasattr(driver_inst.mod, "buffer_stages_str"):
            buffer_stages_inst.mod.buffer_stages_str = driver_inst.mod.buffer_stages_str
        return buffer_stages_inst, logic_driver_inst, parent_mod

    def get_internal_loads(self, driver_conn_index, net):
        """Get loads connected to a net within the control buffer"""
        buffer_conns = self.control_buffer.conns
        loads = []
        rails = []
        # internal loads
        for load_index, load_inst in enumerate(self.control_buffer.insts):
            if not load_index == driver_conn_index and net in buffer_conns[load_index]:
                load_pin_name = load_inst.mod.pins[buffer_conns[load_index].index(net)]
                loads.append((load_inst, load_pin_name))
        if net in self.control_buffer.rails:
            rails.append(self.control_buffer.rails[net].rect)
        return loads, rails

    def eval_load_rail_cap(self, loads, rails):
        """Evaluate the total capacitance given the loads and the rails"""
        total_cap = 0
        # evaluate loads
        for load in loads:
            total_cap += self.get_load_cap(load)
        # evaluate rails
        for rail in rails:
            total_cap += self.get_rail_cap(rail)
        return total_cap

    def extract_control_buffer_loads(self):
        """Map control buffer pins to total load capacitance in F"""
        driver_loads = self.driver_loads
        buffer_conns = self.control_buffer.conns
        for driver_index, driver_inst in enumerate(self.control_buffer.insts):
            if driver_inst.name not in self.control_buffer.buffer_str_dict:
                continue
            _, output_nets = self.control_buffer.get_module_connections(driver_inst.name)
            for output_net in output_nets:
                pin_index = buffer_conns[driver_index].index(output_net)
                mod_pin_name = driver_inst.mod.pins[pin_index]
                debug.info(2, "Extracting control buffers load for %s, pin %s",
                           driver_inst.name, output_net)

                # internal loads
                loads, rails = self.get_internal_loads(driver_index, output_net)
                # external loads
                if output_net in self.control_buffer.pins:
                    loads.extend(self.bank.get_net_loads(output_net))
                rail = getattr(self.bank, output_net + "_rail", None)
                if rail:
                    rails.append(rail)
                    # M3 rail to actual rail
                    rect = rectangle(tech.layer[METAL3], vector(0, 0), width=self.bank.bus_width,
                                     height=self.control_buffer.get_pin(output_net).cx() - rail.cx())
                    rails.append(rect)
                total_cap = self.eval_load_rail_cap(loads, rails)
                if total_cap > 0:
                    if driver_inst.name not in driver_loads:
                        config = self.create_buffer_stages_config(driver_index)
                        load_config = {"config": config, "loads": [],
                                       "buffer_stages_str":
                                           self.control_buffer.buffer_str_dict[driver_inst.name]}
                        driver_loads[driver_inst.name] = load_config
                    if isinstance(driver_inst.mod, LogicBuffer):
                        # swap back the pins on the buffer stage
                        mod_pin_name = "out" if mod_pin_name == "out_inv" else "out_inv"
                    driver_loads[driver_inst.name]["loads"].append((mod_pin_name, total_cap))

    def get_rail_cap(self, rail):
        """Evaluate capacitance of a rectangle"""
        if isinstance(rail, pin_layout):
            rail_layer = rail.layer
            rail_length, rail_width = rail.height(), rail.width()
        else:
            rail_layer = next(key for key, value in tech.layer.items()
                              if value == rail.layerNumber)
            rail_length, rail_width = rail.height, rail.width
        rail_width, rail_length = sorted([rail_length, rail_width])
        return self.bank.get_wire_cap(rail_layer, wire_width=rail_width,
                                      wire_length=rail_length)

    @staticmethod
    def get_load_cap(load):
        """Input capacitance of load
            load is tuple of (mod, pin_name)"""
        mod, pin_name = load
        if isinstance(mod, instance):
            mod = mod.mod
        # precharge load is dynamic and will be part of optimization
        if mod.name == "precharge_array":
            return 0
        cap, _ = mod.get_input_cap(pin_name)
        return cap

    def extract_row_decoder_loads(self):
        """Selects one predecoder rail (out[0]) and evaluates the loads connected to it"""
        # sample predecocder output net
        net = "out[0]"
        loads = {}
        for conn_index, conn in enumerate(self.bank.decoder.conns):
            if net not in conn:
                continue
            inst = self.bank.decoder.insts[conn_index]
            if inst.name.startswith("pre"):  # this should be the predecoder driver itself
                continue
            mod_name = inst.mod.name
            mod_pin_name = inst.mod.pins[conn.index(net)]
            if mod_name not in loads:
                loads[mod_name] = {"mod": inst.mod, "count": 0, "pin_name": mod_pin_name}
            loads[mod_name]["count"] += 1
        rail = rectangle(tech.layer[METAL2], vector(0, 0), width=self.bank.decoder.bus_width,
                         height=self.bank.decoder.row_decoder_height)
        total_cap = self.get_rail_cap(rail)
        for load in loads.values():
            total_cap += load["count"] * self.get_load_cap((load["mod"], load["pin_name"]))

        predecoder = (self.bank.decoder.pre2x4_inst + self.bank.decoder.pre3x8_inst)[0].mod
        parent_mod = predecoder
        buffer_stages_inst = predecoder.inv_inst[0]
        driver_inst = predecoder.nand_inst[0]

        config = (buffer_stages_inst, driver_inst, parent_mod)

        self.driver_loads["row_decoder"] = {"loads": [("out[0]", total_cap)], "config": config,
                                            "buffer_stages_str": "predecoder_buffers"}

    def extract_col_decoder_loads(self):
        # add col mux
        if self.bank.words_per_row == 1:
            return
        # optimize using flop buffer
        parent_mod = self.bank.control_flop_insts[0][2].mod
        buffer_stages_inst = parent_mod.buffer_inst

        driver_inst = parent_mod.flop_inst
        config = (buffer_stages_inst, driver_inst, parent_mod)

        sel_in_cap, _ = self.bank.column_mux_array.get_input_cap("sel[0]")
        driver_load = {
            "loads": [("out", sel_in_cap), ("out_inv", sel_in_cap)],
            "config": config,
            "buffer_stages_str": "column_decoder_buffers"
        }
        self.driver_loads["col_decoder"] = driver_load

    def extract_wordline_buffer_load(self, driver_mod, net, buffer_stages_str):
        if len(driver_mod.buffer_stages) % 2 == 1:
            mod_pin_name = "out_inv"
        else:
            mod_pin_name = "out"
        parent_mod = driver_mod.logic_buffer
        driver_inst = parent_mod.logic_mod
        buffer_stages_inst = parent_mod.buffer_inst
        config = (buffer_stages_inst, driver_inst, parent_mod)

        wl_in_cap, _ = self.bank.bitcell_array.get_input_cap("{}[0]".format(net))
        driver_load = {
            "loads": [(mod_pin_name, wl_in_cap)],
            "config": config,
            "buffer_stages_str": buffer_stages_str
        }
        return driver_load

    def extract_wordline_driver_loads(self):
        """Create config for optimizing wordline driver"""

        driver_load = self.extract_wordline_buffer_load(self.bank.wordline_driver, "wl",
                                                        "wordline_buffers")
        self.driver_loads["wordline_driver"] = driver_load

    def extract_control_flop_loads(self):
        """For each bank control flop, evaluate the output load (corresponding control_buffers input)"""
        control_buffer_conn = next(conn for index, conn in enumerate(self.bank.conns)
                                   if self.bank.insts[index].name == self.bank.control_buffers_inst.name)
        for net_in, net_out, flop_inst in self.bank.control_flop_insts:
            for index, inst in enumerate(self.bank.insts):
                if inst.name == flop_inst.name:
                    flop_buffer_pin_name = flop_inst.mod.pins[
                        self.bank.conns[index].index(net_out)]
                    control_buffer_pin_name = self.control_buffer.pins[control_buffer_conn.index(net_out)]
                    cin, _ = self.control_buffer.get_input_cap(control_buffer_pin_name)

                    parent_mod = flop_inst.mod
                    buffer_stages_inst = parent_mod.buffer_inst
                    driver_inst = parent_mod.flop_inst
                    stages_str = "{}_buffers".format(flop_inst.name)
                    config = (buffer_stages_inst, driver_inst, parent_mod)

                    self.driver_loads[flop_inst.name] = {
                        "buffer_stages_str": stages_str,
                        "loads": [(flop_buffer_pin_name, cin)],
                        "config": config
                    }
                    break

    def create_parameter_convex_spline_fit(self, num_sizes):
        """Create a convex/spline fit for unique mod, suffix combinations"""
        unique_config_keys = self.create_config_keys()  # type: Dict[str, Dict[str, Dict]]
        self.unique_config_keys = unique_config_keys
        for key in unique_config_keys.keys():
            config = unique_config_keys[key]["config"]
            class_name, suffix_key, buffer_mod, in_pin, out_pin, max_buffer_size, size_func = config
            debug.info(1, " {}".format(key))

            cin, cout, resistance, gm = [], [], [], []
            actual_sizes = []
            size_data = [actual_sizes, cin, cout, resistance, gm]
            if size_func == np.logspace:
                size_range = (0, np.log10(max_buffer_size))
            else:
                size_range = (1, max_buffer_size)
            sizes = size_func(*size_range, num_sizes)

            for size in sizes:
                parameters = self.characterize_instance_by_size(buffer_mod, size,
                                                                in_pin, out_pin)
                # size may change due to grid rounding or min tx size requirements
                size_ = parameters[0]
                if size_ in actual_sizes:
                    continue
                for index, list_ in enumerate(size_data):
                    list_.append(parameters[index])

            data = size_data[1:]
            actual_sizes = np.array(actual_sizes)
            data_keys = ["cin", "cout", "resistance", "gm"]
            unique_config_keys[key]["data"] = {}
            unique_config_keys[key]["convex_data"] = {}
            unique_config_keys[key]["spline"] = {}
            debug.info(3, "Characterization data for %s", key)
            debug.info(3, "Sizes: %s", list(map(lambda x: f"{x:3.3g}", actual_sizes)))

            for i in range(len(data_keys)):
                debug.info(3, "%10s: %s", data_keys[i], list(map(lambda x: f"{x:3.3g}", data[i])))

                fit_sizes, fit_data = self.create_convex_fit(actual_sizes, data[i])

                unique_config_keys[key]["convex_data"][data_keys[i]] = (fit_sizes, fit_data)
                unique_config_keys[key]["data"][data_keys[i]] = (actual_sizes, data[i])
                # TODO smooth vs convex vs original fit?
                spline_fit = self.create_spline_fit(fit_sizes, fit_data)
                # smooth_x, smooth_y = self.remove_slope_changes(actual_sizes, data[i])
                # spline_fit = self.create_spline_fit(smooth_x, smooth_y)
                # spline_fit = self.create_spline_fit(actual_sizes, data[i])
                unique_config_keys[key]["spline"][data_keys[i]] = spline_fit

    @staticmethod
    def create_convex_fit(x_data, y_data):
        """Create convex fit for y_data.
         Data oscillations get smoothened out to prevent local maxima/minima
            when data is used for convex optimizations"""
        from scipy.spatial import ConvexHull
        x_data = np.array(x_data)
        y_data = np.array(y_data)
        fit_y_data = np.array(y_data) / max(y_data)
        np_arr = np.array((x_data, fit_y_data)).transpose()
        try:
            hull = ConvexHull(np_arr)
            # find monotonically increasing vertices starting from zero
            valid_vertices = []
            valid = False
            prev_vertex = hull.vertices[0]
            for vertex in hull.vertices:
                if vertex == 0 and not valid:
                    valid = True
                elif valid and vertex < prev_vertex:
                    break
                if valid:
                    valid_vertices.append(vertex)
                prev_vertex = vertex
            # add the last vertex
            last_vertex = len(x_data) - 1
            if last_vertex not in valid_vertices:
                valid_vertices.append(last_vertex)
        except RuntimeError as ex:
            if "Initial simplex is flat" in str(ex):  # just a linear fit
                valid_vertices = [0, len(x_data) - 1]
            elif "The initial hull is narrow" in str(ex):  # just a linear fit
                valid_vertices = [0, len(x_data) - 1]
            else:
                raise ex

        return x_data[valid_vertices], y_data[valid_vertices]

    @staticmethod
    def remove_slope_changes(x_data, y_data):
        # check if trending up or down
        trend_up = y_data[-1] > y_data[0]
        prev_y = y_data[0]
        new_x_data = [x_data[0]]
        new_y_data = [y_data[0]]
        for index, y in enumerate(y_data):
            add = False
            if trend_up and y > prev_y:
                add = True
            elif not trend_up and y < prev_y:
                add = True
            if add:
                prev_y = y
                new_y_data.append(y_data[index])
                new_x_data.append(x_data[index])
        return np.array(new_x_data), np.array(new_y_data)

    @staticmethod
    def create_spline_fit(x_data, y_data):
        from scipy import interpolate
        order = min(len(x_data) - 1, 3)
        return interpolate.splrep(np.array(x_data), np.array(y_data), s=0, k=order)

    @staticmethod
    def linear_interpolate(x, x_data, y_data):
        """Linear interpolation using closest points to x"""
        index = (np.abs(x_data - x)).argmin()
        if index == 0:
            indices = [0, 1]
        elif index == len(x_data) - 1:
            indices = [index - 1, index]
        elif x < x_data[index]:
            indices = [index - 1, index]
        else:
            indices = [index, index + 1]
        x0, x1 = indices
        return y_data[x0] + (x - x_data[x0]) * (y_data[x1] - y_data[x0]) / (x_data[x1] - x_data[x0])

    def evaluate_instance_params(self, size, config_key):
        """Get (cin, resistance, gm) for a size and config_key.
            They will be retrieved from lookup table and extrapolated for the given size
            config_key is unique by module type and 'get_char_data_file/size_suffixes'
        """
        from scipy import interpolate
        convex_data = self.unique_config_keys[config_key]["convex_data"]
        spline = self.unique_config_keys[config_key]["spline"]

        keys = ["cin", "cout", "resistance", "gm"]
        results = []
        for i in range(len(keys)):
            spline_sizes = spline[keys[i]][0]
            if size > spline_sizes[-1] or size < spline_sizes[0]:
                # TODO use spline slope at extremities for extrapolation
                sizes = convex_data[keys[i]][0]
                data = convex_data[keys[i]][1]
                interp = self.linear_interpolate(size, sizes, data)
            else:
                interp = interpolate.splev(size, spline[keys[i]], der=0)
            results.append(interp)
        return results

    def evaluate_driver_parameters(self, driver_index, buffer_index, parent_mod):
        """Evaluate res, gm and fixed load of the driver to the buffer stage"""
        buffer_input_net = parent_mod.conns[buffer_index][0]
        # gm and driver resistance
        driver_mod = parent_mod.insts[driver_index].mod
        driver_pin_index = parent_mod.conns[driver_index].index(buffer_input_net)
        driver_pin_name = driver_mod.pins[driver_pin_index]
        if isinstance(driver_mod, LogicBuffer):
            # is already driving another cap, so use min size to minimize additional load
            driver_mod = self.control_buffer.inv
        res = driver_mod.get_driver_resistance(pin_name=driver_pin_name, use_max_res=True)
        gm = driver_mod.evaluate_driver_gm(pin_name=driver_pin_name)
        # loads except buffer input
        loads = []
        for index, conns in enumerate(parent_mod.conns):
            if index == buffer_index:
                continue
            if buffer_input_net in conns:
                mod = parent_mod.insts[index].mod
                pin_index = conns.index(buffer_input_net)
                loads.append((mod, mod.pins[pin_index]))
        rails = []
        if parent_mod.name == self.control_buffer.name:
            if buffer_input_net in self.control_buffer.rails:
                rails.append(self.control_buffer.rails[buffer_input_net].rect)
        total_cap = self.eval_load_rail_cap(loads, rails)
        return res, gm, total_cap

    def get_opt_func_map(self):
        return {
            "precharge_buffers": self.create_precharge_optimization_func
        }

    def create_dynamic_opt_func(self, config_key, loads, fixed_load, num_elements,
                                eval_buffer_stage_delay_slew):
        penalty = OPTS.buffer_optimization_size_penalty

        def eval_precharge_delays(stages_list):
            precharge_size = stages_list[-1]
            cin, cout, res, gm = self.evaluate_instance_params(precharge_size, config_key)
            enable_in = cin * num_elements
            stage_loads = [x for x in loads]
            stage_loads[-1] += enable_in
            delays, slew = eval_buffer_stage_delay_slew(stages_list[:-1], stage_loads)
            tau = res * (fixed_load + cout)
            beta = 1 / (gm * res)
            alpha = slew / tau
            delay, slew = self.bank.horowitz_delay(tau, beta, alpha)
            delays.append(delay)
            return delays

        def eval_precharge_delay(stage_list):
            return sum(eval_precharge_delays(stage_list)) * 1e12 + penalty * sum(stage_list)

        return (eval_precharge_delay, eval_precharge_delays), loads

    @staticmethod
    def adjust_optimization_loads(new_loads, eval_buffer_stage_delay_slew):
        """Modify optimization objective function 'eval_buffer_stage_delay_slew'
            to use 'new_loads'"""
        penalty = OPTS.buffer_optimization_size_penalty

        def evaluate_delays(stages_list):
            stage_loads = [x for x in new_loads]
            delays, slew = eval_buffer_stage_delay_slew(stages_list, stage_loads)
            return delays

        def total_delay(stage_list):
            return sum(evaluate_delays(stage_list)) * 1e12 + penalty * sum(stage_list)

        return (total_delay, evaluate_delays), new_loads

    def create_precharge_optimization_func(self, driver_params, driver_config, loads, eval_buffer_stage_delay_slew):

        precharge_cell = self.bank.precharge_array.child_insts[0].mod
        self.precharge_cell = precharge_cell
        precharge_config_key, _, _ = self.get_buffer_mod_key(precharge_cell)
        bitline_in_cap, _ = self.bank.bitcell_array.get_input_cap("bl[0]")

        num_cols = self.bank.num_cols

        return self.create_dynamic_opt_func(config_key=precharge_config_key, loads=loads,
                                            fixed_load=bitline_in_cap, num_elements=num_cols,
                                            eval_buffer_stage_delay_slew=
                                            eval_buffer_stage_delay_slew)

    def create_optimization_func(self, initial_stages, slew_in, driver_params,
                                 buffer_mod, buffer_loads, driver_config):
        """Create optimization function
        :param initial_stages: initial guess, also used to determine number of stages that will be optimized
        :param slew_in: input slew
        :param driver_params: tuple of (drive_res, drive_gm, driver_load)
        :param buffer_mod: The module that will be optimized, delays/caps/resistance will be evaluated for instance
                            of buffer_mod with variable size
        :param buffer_loads: The fixed loads for each buffer stage
        :param driver_config: full driver config
        :returns (optimization_func, delays_func)
            cost_function = sum(delays) + OPTS.buffer_optimization_size_penalty * sum(sizes)
            optimization_func evaluates the cost function
            delays_func evaluate the delays for each stage
        """
        drive_res, drive_gm, driver_load = driver_params
        penalty = OPTS.buffer_optimization_size_penalty

        slew_in = drive_res * driver_load
        num_stages = len(initial_stages)
        loads = [0] * (num_stages + 1)
        loads[0] = driver_load

        for pin_name, cap_val in buffer_loads:
            if num_stages == 1:
                # e.g. flop buffers in which polarity of dout can be flipped by flipping flop output
                load_index = -1
            elif pin_name in ["out_inv", "Z"]:
                if num_stages % 2 == 0:
                    load_index = -2
                else:
                    load_index = -1
            else:
                if num_stages % 2 == 0:
                    load_index = -1
                else:
                    load_index = -2
            loads[load_index] += cap_val

        config_key, _, _ = self.get_buffer_mod_key(buffer_mod)

        def eval_buffer_stage_delay_slew(stages_list, stage_loads):

            resistances = [drive_res] + [0] * num_stages
            gms = [drive_gm] + [0] * num_stages
            delays = [0] * (num_stages + 1)
            slew = slew_in
            for i in range(num_stages + 1):
                if i < num_stages:
                    size = stages_list[i]
                    cin, cout, res, gm = self.evaluate_instance_params(size, config_key)
                    stage_loads[i] += cin
                    stage_loads[i + 1] += cout
                    resistances[i + 1] = res
                    gms[i + 1] = gm

                tau = stage_loads[i] * resistances[i]
                beta = 1 / (gms[i] * resistances[i])
                alpha = slew / tau
                delay, slew = buffer_mod.horowitz_delay(tau, beta, alpha)
                delays[i] = delay
            return delays, slew

        def eval_buffer_stage_delays(stages_list):
            stage_loads = [x for x in loads]
            delays, _ = eval_buffer_stage_delay_slew(stages_list, stage_loads)
            return delays

        def eval_buffer_stage_delay(stage_list):
            return sum(eval_buffer_stage_delays(stage_list)) * 1e12 + penalty * sum(stage_list)

        buffer_stages_str = driver_config["buffer_stages_str"]
        opt_func = self.get_opt_func_map().get(buffer_stages_str, None)
        if opt_func is not None:
            return opt_func(driver_params, driver_config, loads, eval_buffer_stage_delay_slew)
        else:
            return (eval_buffer_stage_delay, eval_buffer_stage_delays), loads

    def adjust_optimization_bounds(self, lower_bounds, upper_bounds, buffer_stages_str):
        is_precharge = self.get_is_precharge(buffer_stages_str)
        if is_precharge:
            upper_bounds[-1] = OPTS.max_precharge_size

    def optimize_config(self, optimization_func, buffer_stages_str, initial_stages, is_precharge,
                        method):
        """Run actual optimization using scipy.minimize
            Upper bound is evaluated using 'getattr(OPTS, "max_" + buffer_stages_str, default_max_size)'
        """
        from scipy.optimize import Bounds, minimize
        if is_precharge:
            initial_stages.append(self.precharge_cell.size)
        # define bounds
        default_max_size = OPTS.max_buf_size
        max_buffer_size = getattr(OPTS, "max_" + buffer_stages_str, default_max_size)
        lower_bounds = np.ones(len(initial_stages))
        upper_bounds = max_buffer_size * lower_bounds
        self.adjust_optimization_bounds(lower_bounds, upper_bounds, buffer_stages_str)
        bounds = Bounds(lower_bounds, upper_bounds)
        stages = minimize(optimization_func, initial_stages, method=method, bounds=bounds)
        return stages, initial_stages

    def get_sorted_driver_loads(self):
        """Optimization order may be important so permit re-ordering"""
        return list(self.driver_loads.values())

    def get_config_num_stages(self, buffer_mod, buffer_stages_str, buffer_loads):
        initial_stages = buffer_mod.buffer_stages
        default_num_stages = len(initial_stages)
        all_num_stages = {default_num_stages}
        if default_num_stages >= 4:
            all_num_stages.add(default_num_stages - 2)
        if default_num_stages >= 4 and len(buffer_loads) == 2:
            all_num_stages.update(range(3, default_num_stages))
        if buffer_stages_str == "column_decoder_buffers":
            if self.bank.words_per_row > 2:
                all_num_stages = {1}
            else:
                all_num_stages = {2}
        return all_num_stages

    @staticmethod
    def get_is_precharge(buffer_stages_str):
        return buffer_stages_str == "precharge_buffers"

    def optimize_all(self):

        self.create_parameter_convex_spline_fit(num_sizes=60)  # TODO make configurable

        inv1_cin, _ = self.control_buffer.inv.get_input_cap("A")  # reference input capacitance

        for driver_config in self.get_sorted_driver_loads():
            buffer_stages_inst, driver_inst, parent_mod = driver_config["config"]

            # find buffer and driver index
            buffer_index = 0
            driver_index = 0
            buffer_mod = buffer_stages_inst.mod
            for index, inst in enumerate(parent_mod.insts):
                if inst.name == buffer_stages_inst.name:
                    buffer_index = index
                if inst.name == driver_inst.name:
                    driver_index = index
            # create optimization function
            driver_params = self.evaluate_driver_parameters(driver_index, buffer_index,
                                                            parent_mod)
            drive_res, drive_gm, driver_load = driver_params
            slew_in = drive_res * driver_load

            buffer_loads = driver_config["loads"]
            if not buffer_loads:
                assert False, "Deal with no load"

            buffer_stages_str = driver_config["buffer_stages_str"]
            is_precharge = self.get_is_precharge(buffer_stages_str)

            initial_stages = buffer_mod.buffer_stages
            all_num_stages = self.get_config_num_stages(buffer_mod, buffer_stages_str, buffer_loads)

            min_criteria, min_stages = np.inf, None

            def list_format(list_, scale=1.0):
                return "[{}]".format(", ".join(["{:4.3g}".format(x * scale) for x in list_]))

            for iteration, num_stages in enumerate(sorted(all_num_stages)):
                initial_guess = [1] * num_stages

                funcs, stage_loads = self.create_optimization_func(initial_guess, slew_in,
                                                                   driver_params, buffer_mod, buffer_loads,
                                                                   driver_config)
                max_load = max(stage_loads)
                effort = max_load / inv1_cin
                initial_guess = [effort ** ((x + 1) / (num_stages + 1)) for x in range(num_stages)]

                if iteration == 0:
                    debug.info(1, "{}: {}".format(buffer_stages_str, stage_loads))
                    debug.info(1, "\t Default: {}".format(initial_stages))
                    debug.info(2, "\t Initial guess: {}".format(initial_guess))

                optimization_func, delays_func = funcs
                # run optimization
                method = 'SLSQP'
                sol, initial_guess = self.optimize_config(optimization_func, buffer_stages_str,
                                                          initial_guess, is_precharge, method)
                final_stages = sol.x
                optimum_val = optimization_func(final_stages)
                if optimum_val < min_criteria:
                    min_criteria = optimum_val
                    min_stages = final_stages

                delays = delays_func(final_stages)
                debug.info(1, "\t {:4.3g}\t stages: {}\t delays: {}".format(sum(delays) * 1e12,
                                                                            list_format(final_stages),
                                                                            list_format(delays, 1e12)))
            min_stages = min_stages.tolist()
            if len(all_num_stages) > 1:
                debug.info(1, "\t Selected: {}".format(list_format(min_stages)))

            min_stages = self.post_process_buffer_sizes(min_stages, buffer_stages_str, parent_mod)

            setattr(OPTS, buffer_stages_str + "_old", initial_stages)
            setattr(OPTS, buffer_stages_str, min_stages)

    def post_process_buffer_sizes(self, stages, buffer_stages_str, parent_mod):
        is_precharge = self.get_is_precharge(buffer_stages_str)
        if is_precharge:
            OPTS.precharge_size = stages[-1]
            stages = stages[:-1]
        elif buffer_stages_str == "predecoder_buffers":
            OPTS.predecode_sizes = parent_mod.buffer_sizes[:1] + stages
        return stages

    def create_config_keys(self):
        """Create all unique module types and configurations
        Uniqueness is determined by 'get_char_data_file_suffixes' and 'get_char_data_size_suffixes'
            which determine which properties make physical layouts different except for size
        """
        max_size = OPTS.max_buf_size

        driver_loads = self.driver_loads
        # get config keys
        config_keys = []
        for driver_load in driver_loads.values():
            buffer_stages_inst, _, _ = driver_load["config"]
            buffer_stages_str = driver_load["buffer_stages_str"]
            buffer_mod = buffer_stages_inst.mod
            max_buffer_size = getattr(OPTS, "max_" + buffer_stages_str, max_size)
            if isinstance(buffer_mod, BufferStage):
                buffer_mod = buffer_mod.buffer_invs[-1]
            config_keys.append((buffer_mod, "A", "Z", max_buffer_size, np.logspace))
        self.add_additional_configs(config_keys)

        # make configs unique
        unique_config_keys = {}  # type: Dict[str, Dict[str, Any]]
        for buffer_mod, in_pin, out_pin, max_buffer_size, sizes_func in config_keys:
            full_key, suffix_key, class_name = self.get_buffer_mod_key(buffer_mod)
            if full_key in unique_config_keys:
                max_buffer_size = max(max_buffer_size,
                                      unique_config_keys[full_key]["config"][5])
            config = (class_name, suffix_key, buffer_mod, in_pin, out_pin, max_buffer_size, sizes_func)
            unique_config_keys[full_key] = {"config": config}
        return unique_config_keys

    @staticmethod
    def get_buffer_mod_key(buffer_mod):
        """Given 'buffer_mod', find the key for the characterized data look up table"""

        def format_val(val):
            if isinstance(val, float):
                return "{:.5g}".format(val)
            return str(val)

        if isinstance(buffer_mod, BufferStage):
            buffer_mod = buffer_mod.buffer_invs[-1]

        suffixes = (buffer_mod.get_char_data_file_suffixes() +
                    buffer_mod.get_char_data_size_suffixes())
        class_name = buffer_mod.__class__.__name__
        suffix_key = "_".join(["{}_{}".format(key, format_val(val))
                               for key, val in suffixes])
        full_key = class_name + "_" + suffix_key
        return full_key, suffix_key, class_name

    def add_additional_configs(self, config_keys):
        """Add other Buffer stages that need optimization: precharge, wordline buffers"""
        from globals import OPTS
        # add precharge
        precharge = self.bank.precharge_array.child_insts[0].mod
        config_keys.append((precharge, "en", "bl", OPTS.max_precharge_size, np.linspace))

    def get_mod_args(self, buffer_mod, size):
        class_name = buffer_mod.__class__.__name__
        if class_name == "pinv":
            args = {"height": buffer_mod.height, "size": size, "beta": buffer_mod.beta,
                    "contact_nwell": buffer_mod.contact_nwell,
                    "contact_pwell": buffer_mod.contact_pwell,
                    "align_bitcell": buffer_mod.align_bitcell,
                    "same_line_inputs": buffer_mod.same_line_inputs}
        elif class_name == "pinv_wordline":
            args = {"size": size, "beta": buffer_mod.beta}
        elif isinstance(buffer_mod, precharge_characterization):
            name = "precharge_{:.5g}".format(size)
            args = {"name": name, "size": size}
        else:
            raise NotImplementedError("Please supply arguments for class {}".format(class_name))
        return args

    def characterize_instance_by_size(self, buffer_mod, size, in_pin, out_pin):
        """Create an instance of buffer_mod with size, evaluate its actual size, cin, resistance and gm"""
        args = self.get_mod_args(buffer_mod, size)
        mod = buffer_mod.__class__(**args)

        cin, _ = mod.get_input_cap(in_pin)
        cout, _ = mod.get_input_cap(out_pin)
        resistance = mod.get_driver_resistance(pin_name=out_pin, use_max_res=True)
        gm = mod.evaluate_driver_gm(pin_name=out_pin)
        return mod.size, cin, cout, resistance, gm
