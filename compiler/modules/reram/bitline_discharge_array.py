import debug
from globals import OPTS
from modules.bitcell_aligned_array import BitcellAlignedArray


class BitlineDischargeArray(BitcellAlignedArray):

    def __init__(self, columns, size=1):
        self.size = size
        debug.info(1, "Creating {0} with precharge size {1:.3g}".format(self.get_name(), size))
        BitcellAlignedArray.__init__(self, columns=columns, word_size=columns)

    @property
    def mod_name(self):
        return OPTS.precharge

    def get_name(self):
        return "precharge_array"

    @property
    def bus_pins(self):
        return ["bl", "br"]

    def create_child_mod(self):
        self.child_mod = self.create_mod_from_str(self.mod_name, size=self.size)
        debug.info(1, "Using module {} for {}".format(self.child_mod.name,
                                                      self.name))
        self.pc_cell = self.child_mod
        self.height = self.child_mod.height
