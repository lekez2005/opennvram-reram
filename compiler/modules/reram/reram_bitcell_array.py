from base import utils
from base.vector import vector
from globals import OPTS
from modules.bitcell_array import bitcell_array


class ReRamBitcellArray(bitcell_array):
    def get_bitcell_connections(self, row, col):
        return f"bl[{col}] br[{col}] wl[{row}] gnd".split()

    def add_layout_pins(self):
        self.add_bitline_layout_pins()
        for row in range(self.row_size):
            wl_pin = self.cell_inst[row][0].get_pin("WL")
            self.add_layout_pin(text="wl[{0}]".format(row),
                                layer=wl_pin.layer,
                                offset=vector(0, wl_pin.by()),
                                width=self.width,
                                height=wl_pin.height())
        if not OPTS.use_y_body_taps or not self.body_tap_insts:
            return
        for pin_name in ["vdd", "gnd"]:
            if pin_name not in self.body_tap.pin_map:
                continue
            for pin in self.body_tap.get_pins(pin_name):
                y_offsets = set([utils.round_to_grid(x.by()) for x in self.body_tap_insts])
                for y_offset in y_offsets:
                    self.add_layout_pin(pin_name, pin.layer, pin.ll() + vector(0, y_offset),
                                        width=self.width, height=pin.height())
