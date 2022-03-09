from base import design
from base.hierarchy_spice import INPUT, OUTPUT, INOUT
from base.library_import import library_import
from globals import OPTS


@library_import
class ms_flop(design.design):
    """
    Memory address flip-flop
    """
    lib_name = OPTS.ms_flop_mod

    def get_pin_dir(self, name):
        if name in ["din", "clk"]:
            return INPUT
        elif name in ["dout", "dout_bar"]:
            return OUTPUT
        else:
            return INOUT

    def analytical_delay(self, slew, load=0.0):
        # dont know how to calculate this now, use constant in tech file
        from tech import spice
        result = self.return_delay(spice["msflop_delay"], spice["msflop_slew"])
        return result

    def analytical_power(self, proc, vdd, temp, load):
        """Returns dynamic and leakage power. Results in nW"""
        from tech import spice
        c_eff = self.calculate_effective_capacitance(load)
        f = spice["default_event_rate"]
        power_dyn = c_eff * vdd * vdd * f
        power_leak = spice["msflop_leakage"]

        total_power = self.return_power(power_dyn, power_leak)
        return total_power

    def calculate_effective_capacitance(self, load):
        """Computes effective capacitance. Results in fF"""
        from tech import spice
        c_load = load
        c_para = spice["flop_para_cap"]  # ff
        transistion_prob = spice["flop_transisition_prob"]
        return transistion_prob * (c_load + c_para)
