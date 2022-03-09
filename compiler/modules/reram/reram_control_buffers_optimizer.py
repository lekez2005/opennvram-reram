import numpy

import debug
from base.design import design
from characterizer.control_buffers_optimizer import ControlBufferOptimizer
from globals import OPTS


class ReramControlBuffersOptimizer(ControlBufferOptimizer):

    @staticmethod
    def get_is_precharge(buffer_stages_str):
        return buffer_stages_str == "bl_reset_buffers"

    def add_additional_configs(self, config_keys):
        """Add other Buffer stages that need optimization: precharge, wordline buffers"""
        # add precharge
        precharge = self.bank.precharge_array.child_insts[0].mod
        config_keys.append((precharge, "bl_reset", "bl", OPTS.max_precharge_size, numpy.linspace))

    def get_sorted_driver_loads(self):
        """ put br_reset_buffers at the end so bl_reset is optimized first """
        driver_loads = list(self.driver_loads.values())
        driver_loads = list(sorted(driver_loads,
                                   key=lambda x: x["buffer_stages_str"] == "br_reset_buffers"))
        return driver_loads

    def get_opt_func_map(self):
        funcs = super().get_opt_func_map()
        funcs.update({"bl_reset_buffers": self.create_precharge_optimization_func,
                      "br_reset_buffers": self.create_br_reset_optimization_func})
        return funcs

    def create_br_reset_optimization_func(self, driver_params, driver_config,
                                          loads, eval_buffer_stage_delay_slew):
        if self.bank.precharge_array.name in design.name_map:
            design.name_map.remove(self.bank.precharge_array.name)
        array = self.bank.create_module('precharge_array', columns=self.bank.num_cols,
                                        size=OPTS.precharge_size)
        br_reset_cap, _ = array.get_input_cap("br_reset")
        debug.info(2, "br_reset capacitance = %.3g", br_reset_cap)
        debug.info(2, "br_reset existing load = %.3g", loads[-1])
        loads[-1] += br_reset_cap
        return self.adjust_optimization_loads(loads, eval_buffer_stage_delay_slew)

    def post_process_buffer_sizes(self, stages, buffer_stages_str, parent_mod):
        if buffer_stages_str == "bl_reset_buffers":
            OPTS.precharge_size = stages[-1]
            return stages[:-1]
        return super().post_process_buffer_sizes(stages, buffer_stages_str, parent_mod)
