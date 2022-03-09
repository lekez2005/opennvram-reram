from base import design
from base.library_import import library_import
from globals import OPTS
from tech import layer as tech_layers


@library_import
class bitcell(design.design):
    """
    A single bit cell (6T, 8T, etc.)  This module implements the
    single memory cell used in the design. It is a hand-made cell, so
    the layout and netlist should be available in the technology
    library.
    """

    pin_names = ["BL", "BR", "WL", "Q", "QBAR", "vdd", "gnd"]
    lib_name = OPTS.bitcell_mod

    def get_nwell_top(self):
        return self.get_top_rect("nwell")

    def get_top_rect(self, layer_):
        rects = self.gds.getShapesInLayer(tech_layers[layer_])

        return max(map(lambda x: x[1], map(lambda x: x[1], rects)))

    def analytical_delay(self, slew, load=0, swing=0.5):
        # delay of bit cell is not like a driver(from WL)
        # so the slew used should be 0
        # it should not be slew dependent?
        # because the value is there
        # the delay is only over half transsmission gate
        from tech import spice
        r = spice["min_tx_r"] * 3
        c_para = spice["min_tx_drain_c"]
        result = self.cal_delay_with_rc(r=r, c=c_para + load, slew=slew, swing=swing)
        return result

    def analytical_power(self, proc, vdd, temp, load):
        """Bitcell power in nW. Only characterizes leakage."""
        from tech import spice
        leakage = spice["bitcell_leakage"]
        dynamic = 0  # temporary
        total_power = self.return_power(dynamic, leakage)
        return total_power
