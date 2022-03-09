import json
import os
from abc import ABC
from collections import namedtuple

import numpy as np

import debug
from characterizer.delay_loads import DistributedLoad, WireLoad, NandLoad
from characterizer.delay_optimizer import LoadOptimizer
from globals import OPTS
from modules.logic_buffer import LogicBuffer
from pgates.pinv import pinv


class BaseDelayStrategy(ABC):

    buffer_rail_length = 1
    MIN_SIZE = 'min_size'  # minimize the delay given a maximum size
    MIN_DELAY = 'min_delay'  # minimize the size given a maximum delay
    FIXED = 'fixed'

    def __init__(self, bank):
        self.bank = bank

        self.num_cols = bank.num_cols
        self.num_rows = bank.num_rows

        if not isinstance(bank, tuple):  # in case entire bank isn't built, just properties
            self.estimate_rail_length()
            self.bitcell_width = bank.bitcell.width
            self.bitcell_height = bank.bitcell.height

        # wrap methods for caching
        if OPTS.cache_optimization:
            for method in ["get_clk_buffer_sizes", "get_wordline_driver_sizes",
                           "get_wordline_en_sizes", "get_write_en_sizes", "get_sense_en_sizes",
                           "get_precharge_sizes", "get_predecoder_sizes"]:
                setattr(self, method, wrap_method_for_cache(self, method, getattr(self, method)))

    def execute_delay_strategy(self, strategy_, optimization_spec):
        initial_guess, opt_func, total_delay, stage_delays = optimization_spec
        strategy, arg = strategy_

        if strategy == self.MIN_DELAY:
            result = LoadOptimizer.minimize_delays(opt_func, initial_guess, max_size=arg)
            return [1] + list(result.x)
        elif strategy == self.MIN_SIZE:
            result = LoadOptimizer.minimize_sizes(opt_func, initial_guess, max_delay=arg,
                                                  all_stage_delays=stage_delays, final_stage=False,
                                                  equalize_final_stages=False)
            return [1] + list(result.x)
        elif strategy == self.FIXED:
            return getattr(OPTS, arg)
        else:
            debug.error("Invalid strategy {}".format(strategy), debug.ERROR_CODE)

    @staticmethod
    def print_list(l):
        return "[{}]".format(', '.join(["{:.2g}".format(x) for x in l]))

    @staticmethod
    def scale_delays(d):
        return [1e12 * x for x in d]

    def run_optimizations(self):
        run_optimizations = hasattr(OPTS, 'run_optimizations') and OPTS.run_optimizations
        if hasattr(OPTS, 'configure_modules'):
            getattr(OPTS, 'configure_modules')(self, OPTS)
        if run_optimizations:

            OPTS.clk_buffers = self.get_clk_buffer_sizes()

            OPTS.wordline_buffers = self.get_wordline_driver_sizes()

            OPTS.wordline_en_buffers = self.get_wordline_en_sizes()

            OPTS.write_buffers = self.get_write_en_sizes()

            OPTS.sense_amp_buffers = self.get_sense_en_sizes()

            precharge_sizes = self.get_precharge_sizes()
            OPTS.precharge_buffers = precharge_sizes[:-1]
            OPTS.precharge_size = precharge_sizes[-1]

            predecode_sizes = self.get_predecoder_sizes()
            OPTS.predecode_sizes = predecode_sizes[1:]

    @staticmethod
    def print_optimization_result(solution, optimization_spec, net_names, en_en_bar=True):
        initial_guess, _, total_delay, stage_delays = optimization_spec

        solution_str = BaseDelayStrategy.print_list(solution)
        debug.info(1, "Buffer sizes for {} = {}".format(' and '.join(net_names), solution_str))

        delays = BaseDelayStrategy.scale_delays(stage_delays(solution[1:]))

        debug.info(1, "Delays for each stage for net {} = {}".format(', '.join(net_names),
                                                                     BaseDelayStrategy.print_list(delays)))

        if len(net_names) == 1:  # only en/en_bar
            debug.info(1, "Delay for net {} = {:.2g}\n".format(net_names[0], 1e12*total_delay(solution[1:])))
        else:
            delays = BaseDelayStrategy.scale_delays(stage_delays(solution[1:]))
            pen_delay = sum(delays[:-1])
            if en_en_bar:
                fin_delay = sum(delays[:-2]) + delays[-1]
            else:
                fin_delay = sum(delays)

            debug.info(1, "Delay for net {} = {:.2g}".format(net_names[0], pen_delay))
            debug.info(1, "Delay for net {} = {:.2g}\n".format(net_names[1], fin_delay))

    def estimate_rail_length(self):
        """Rough estimate of predicted rail length"""
        rail_height = (self.bank.tri_gate_array.height + 2*self.bank.msf_data_in.height +
                       2*self.bank.sense_amp_array.height)
        rail_length = 0.5*self.prototype_buffer_width()
        self.buffer_rail_length = rail_length + rail_height

    def prototype_buffer_width(self):
        """
        Get estimated width of buffers.
         We estimate initial horizontal rail length as get_num_buffers()*width of buffer stage
        """
        stages = [1, 2, 4]
        prototype_buffer = LogicBuffer(buffer_stages=stages, height=OPTS.logic_buffers_height,
                                       contact_nwell=True, contact_pwell=True)
        return prototype_buffer.width * self.get_num_buffers()

    def get_num_buffers(self):
        """
        Get number of buffer stages. This is used for estimating the horizontal rail length
        :return:
        """
        return OPTS.num_buffers

    # strategies

    def get_clk_strategy(self):
        return self.MIN_DELAY, OPTS.max_clk_buffers
        # return self.MIN_SIZE, OPTS.max_clk_buffer_delay

    def get_wordline_en_strategy(self):
        return self.MIN_DELAY, OPTS.max_wordline_en_buffers

    def get_wordline_driver_strategy(self):
        return self.MIN_DELAY, OPTS.max_wordline_en_buffers

    def get_write_en_strategy(self):
        return self.MIN_DELAY, OPTS.max_write_buffers

    def get_sense_en_strategy(self):
        return self.MIN_DELAY, OPTS.max_write_buffers

    def get_precharge_strategy(self):
        return self.MIN_DELAY, OPTS.max_precharge_en_size

    def get_predecoder_strategy(self):
        assert OPTS.max_predecoder_inv_size % 2 == 1, "Predecoder buffer length should be odd"
        return self.MIN_DELAY, OPTS.max_predecoder_nand, OPTS.max_predecoder_inv_size

    # buffer size evaluations

    def get_en_en_bar_sizes(self, num_stages, en_loads_func, en_bar_loads_func, strategy_func, net_names):
        en_loads = [x() for x in getattr(self, en_loads_func)()]
        en_bar_loads = [x() for x in getattr(self, en_bar_loads_func)()]

        if num_stages % 2 == 0:
            penultimate_loads = en_bar_loads
            final_loads = en_loads
        else:
            penultimate_loads = en_loads
            final_loads = en_bar_loads
            net_names = list(reversed(net_names))

        optimization_spec = LoadOptimizer. \
            generate_en_en_bar_delay(num_stages - 1, final_loads, penultimate_loads, 1)
        strategy_ = getattr(self, strategy_func)()

        stages = self.execute_delay_strategy(strategy_, optimization_spec)

        self.print_optimization_result(stages, optimization_spec, net_names)

        return stages

    def get_en_sizes(self, num_stages, loads_func, strategy_func, net_name, driver_c_drain=1):
        loads = [x() for x in getattr(self, loads_func)()]
        optimization_spec = LoadOptimizer.generate_en_delay(num_stages - 1, loads, final_stage=True,
                                                            driver_c_drain=driver_c_drain)
        strategy_ = getattr(self, strategy_func)()

        stages = self.execute_delay_strategy(strategy_, optimization_spec)

        self.print_optimization_result(stages, optimization_spec, [net_name])
        return stages

    def get_clk_buffer_sizes(self):

        num_stages = OPTS.num_clk_buf_stages

        return self.get_en_en_bar_sizes(num_stages, 'get_clk_loads', 'get_clk_bar_loads',
                                        'get_clk_strategy', ["clk_bar", "clk_buf"])

    def get_wordline_en_sizes(self):
        num_stages = OPTS.num_wordline_en_stages

        return self.get_en_sizes(num_stages, 'get_wordline_en_loads', 'get_wordline_en_strategy',
                                 "wordline_en")

    def get_wordline_driver_sizes(self):
        num_stages = OPTS.num_wordline_driver_stages
        assert num_stages % 2 == 1, "Number of wordline buffers should be odd"
        # add 1 to num_stages because the driving NAND is considered part of the buffer stage
        stages = self.get_en_sizes(num_stages+1, 'get_wordline_driver_loads', 'get_wordline_driver_strategy',
                                   "wl", driver_c_drain=2)
        return stages[1:]

    def get_write_en_sizes(self):
        num_stages = OPTS.num_write_en_stages

        return self.get_en_en_bar_sizes(num_stages, 'get_write_en_loads', 'get_write_en_bar_loads',
                                        'get_write_en_strategy', ["write_en", "write_en_bar"])

    def get_sense_en_sizes(self):
        num_stages = OPTS.num_sense_en_stages
        # output is sense_en for odd number of stages but get_en_en_bar_sizes assumes even => sense_en so switch
        return self.get_en_en_bar_sizes(num_stages, 'get_sense_en_bar_loads', 'get_sense_en_loads',
                                        'get_sense_en_strategy', ["sense_en_bar", "sense_en"])

    def get_precharge_sizes(self):
        num_stages = OPTS.num_precharge_stages

        bitline_load = self.bitline_load()
        wire_driver = WireLoad(None, self.bitcell_height)
        optimization_spec = LoadOptimizer.\
            generate_precharge_delay(num_stages-1, self.num_cols, wire_driver, bitline_load, 1)
        strategy_ = self.get_precharge_strategy()

        stages = self.execute_delay_strategy(strategy_, optimization_spec)

        self.print_optimization_result(stages, optimization_spec, ["precharge_en", "bl"], en_en_bar=False)

        return stages

    def get_predecoder_sizes(self):
        from scipy.optimize import Bounds
        num_stages = OPTS.num_predecoder_stages
        load = self.row_decoder_load()
        optimization_spec = LoadOptimizer.generate_decoder_delay(num_stages, load)

        num_variables = 2 + num_stages
        bounds_list = [OPTS.max_predecoder_nand] + [OPTS.max_predecoder_inv_size]*num_stages
        bounds = Bounds(np.ones(num_variables), np.asarray(bounds_list), keep_feasible=True)

        initial_guess, opt_func, total_delay, stage_delays = optimization_spec

        result = LoadOptimizer.minimize_delays(opt_func, initial_guess, max_size=-1, bounds=bounds)

        stages = [1] + list(result.x)

        self.print_optimization_result(stages, optimization_spec, ["decoder_in"])

        return stages

    # loads as list

    def get_clk_loads(self):
        return [self.mask_flops_load, self.decoder_load]

    def get_clk_bar_loads(self):
        return [self.data_flops_load]

    def get_wordline_en_loads(self):
        return [self.wordline_driver_en_load]

    def get_wordline_driver_loads(self):
        return [self.bitcell_wordline_load]

    def get_write_en_loads(self):
        return [self.write_en_load]

    def get_write_en_bar_loads(self):
        return [self.write_en_bar_load]

    def get_sense_en_loads(self):
        return [self.sense_en_load, self.tri_en_load]

    def get_sense_en_bar_loads(self):
        return [self.sense_en_bar_load, self.tri_en_bar_load]

    # actual loads definitions
    def bitcell_aligned_load(self, cap_per_stage):
        driver = WireLoad(None, self.buffer_rail_length)
        load = DistributedLoad(driver, cap_per_stage=cap_per_stage, stage_width=self.bitcell_width,
                               num_stages=self.num_cols)
        return load

    def wordline_driver_en_load(self):
        driver = WireLoad(None, self.buffer_rail_length)
        input_nand = self.bank.wordline_driver.logic_buffer.logic_mod

        min_size_inverter = pinv(1)
        inverter_width = min_size_inverter.pmos_width + min_size_inverter.nmos_width

        nand_width = input_nand.pmos_width + input_nand.nmos_width

        input_cap = driver.delay_params.c_gate * (nand_width/inverter_width)

        wire_cap = driver.wire_cap * self.bitcell_height / self.buffer_rail_length

        cap_per_stage = input_cap + wire_cap

        load = DistributedLoad(driver, cap_per_stage=cap_per_stage, stage_width=self.bitcell_height,
                               num_stages=self.num_rows)
        return load

    def row_decoder_load(self):
        driver = WireLoad(None, self.bitcell_height)

        nand_load = NandLoad(1, None)
        cap_per_stage = nand_load.total_cap + driver.wire_cap

        load = DistributedLoad(driver, cap_per_stage=cap_per_stage, stage_width=self.bitcell_height,
                               num_stages=self.num_rows)
        return load


def wrap_method_for_cache(obj, method_name, original_func):

    cache_file = os.path.join(OPTS.openram_temp,
                              "{}optimization_results_{}.json".
                              format(OPTS.cache_optimization_prefix, OPTS.tech_name))

    def wrapped():
        existing_data = {}
        if os.path.exists(cache_file):
            try:
                with open(cache_file) as f:
                    existing_data = json.load(f)
            except:
                pass
        num_cols = obj.bank.num_cols
        num_rows = obj.bank.num_rows
        key = "{}_{}_{}".format(method_name, num_rows, num_cols)
        if key in existing_data:
            return existing_data[key]
        with open(cache_file, "w") as f:
            computed_data = original_func()
            existing_data[key] = computed_data
            json.dump(existing_data, f, indent=4, sort_keys=True)
            return computed_data
    return wrapped
