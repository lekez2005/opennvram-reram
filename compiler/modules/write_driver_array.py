from globals import OPTS
from modules.bitcell_aligned_array import BitcellAlignedArray


class write_driver_array(BitcellAlignedArray):
    """
    Array of tristate drivers to write to the bitlines through the column mux.
    Dynamically generated write driver array of all bitlines.
    """

    def get_name(self):
        return "write_driver_array"

    @property
    def mod_name(self):
        return OPTS.write_driver

    @property
    def tap_name(self):
        return getattr(OPTS, "write_driver_tap", None)

    @property
    def bus_pins(self):
        return ["bl", "br", "din", "data", "data_bar", "mask", "mask_bar"]

    def create_modules(self):
        super().create_modules()
        self.driver = self.child_mod

    def add_pins(self):
        # these pin orders are for historical reasons
        for i in range(self.word_size):
            if "din" in self.child_mod.pins:
                self.add_pin("din[{0}]".format(i))
            if "data" in self.child_mod.pins:
                self.add_pin("data[{0}]".format(i))
            if "data_bar" in self.child_mod.pins:
                self.add_pin("data_bar[{0}]".format(i))

        for i in range(self.word_size):
            self.add_pin("bl[{0}]".format(i))
            self.add_pin("br[{0}]".format(i))

        for i in range(self.word_size):
            if "mask_bar" in self.child_mod.pins:
                self.add_pin("mask_bar[{0}]".format(i))
            if "mask" in self.child_mod.pins:
                self.add_pin("mask[{0}]".format(i))
        if "en" in self.child_mod.pins:
            self.add_pin("en")
        if "en_bar" in self.child_mod.pins:
            self.add_pin("en_bar")
        self.add_pin("vdd")
        self.add_pin("gnd")
