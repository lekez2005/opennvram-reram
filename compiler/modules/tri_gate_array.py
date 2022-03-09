import debug
from base import design
from base.library_import import library_import
from globals import OPTS
from modules.bitcell_aligned_array import BitcellAlignedArray


@library_import
class tri_gate_tap(design.design):
    """
    Contains two bitline logic cells stacked vertically
    """
    pin_names = []
    lib_name = getattr(OPTS, "tri_gate_tap_mod", "tri_gate_tap")


class tri_gate_array(BitcellAlignedArray):
    """
    Dynamically generated tri gate array of all bitlines.  words_per_row
    """

    def get_name(self):
        return "tri_gate_array"

    @property
    def mod_name(self):
        return OPTS.tri_gate

    @property
    def bus_pins(self):
        return ["in", "in_bar", "out"]

    def add_pins(self):
        """create the name of pins depend on the word size"""
        self.add_pin_if_exist("in")
        self.add_pin_if_exist("in_bar")
        self.add_pin_if_exist("out")
        self.add_pin_if_exist("en")
        self.add_pin_if_exist("en_bar")
        self.add_pin_list(["vdd", "gnd"])

    def create_body_tap(self):
        if OPTS.use_x_body_taps:
            self.body_tap = tri_gate_tap()
            debug.info(1, "Using body tap {} for {}".format(self.body_tap.name,
                                                            self.name))
