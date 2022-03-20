from modules.bitcell_aligned_array import BitcellAlignedArray
from modules.write_driver_array import write_driver_array


class write_driver_mask_array(write_driver_array):
    """
    Array of Masked write drivers
    """
    def add_pins(self):
        BitcellAlignedArray.add_pins(self)
