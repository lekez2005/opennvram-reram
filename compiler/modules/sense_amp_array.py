from globals import OPTS
from modules.bitcell_aligned_array import BitcellAlignedArray


class sense_amp_array(BitcellAlignedArray):
    """
    Array of sense amplifiers to read the bitlines through the column mux.
    Dynamically generated sense amp array for all bitlines.
    """

    amp = None
    body_tap = None
    bitcell_offsets = []
    tap_offsets = []
    amp_insts = []
    body_tap_insts = []

    def get_name(self):
        return "sense_amp_array"

    @property
    def mod_name(self):
        return OPTS.sense_amp

    @property
    def tap_name(self):
        return getattr(OPTS, "sense_amp_tap", None)

    @property
    def bus_pins(self):
        return ["bl", "br", "dout", "dout_bar"]

    def create_modules(self):
        super().create_modules()
        self.amp = self.child_mod
