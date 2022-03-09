from abc import ABC

from base.design import design, NWELL
from base.vector import vector
from globals import OPTS


class BitcellVerticalAligned(design, ABC):
    """Helper class for modules that are vertically to the side of the bitcell array"""

    def create_bitcell(self):
        self.bitcell = self.create_mod_from_str(OPTS.bitcell)

    def calculate_y_offsets(self):
        bitcell_array_cls = self.import_mod_class_from_str(OPTS.bitcell_array)
        offsets = bitcell_array_cls.calculate_y_offsets(num_rows=self.num_rows)
        self.bitcell_offsets, self.tap_offsets, self.dummy_offsets = offsets
        self.height = max(self.bitcell_offsets + self.dummy_offsets) + self.bitcell.height

    def get_row_y_offset(self, row):
        y_offset = self.bitcell_offsets[row]
        if (row % 2) == 0:
            y_offset += self.bitcell.height
            mirror = "MX"
        else:
            mirror = "R0"
        return y_offset, mirror

    def _add_body_taps(self, logic_inst, adjacent_insts, x_shift=0):
        body_tap = logic_inst.mod.create_pgate_tap()
        x_offset = logic_inst.lx() + x_shift - body_tap.width

        for row in range(self.num_rows):
            y_offset, mirror = self.get_row_y_offset(row)
            self.add_inst(body_tap.name, body_tap, vector(x_offset, y_offset),
                          mirror=mirror)
            self.connect_inst([])
            if x_offset < 0:
                adjacent_inst = adjacent_insts[row]
                for pin_name in ["vdd", "gnd"]:
                    pin = adjacent_inst.get_pin(pin_name)
                    self.add_rect(pin.layer, vector(x_offset, pin.by()),
                                  height=pin.height(), width=pin.lx() - x_offset)

    @staticmethod
    def calculate_nwell_y_fills(self):
        bitcell_offsets = list(sorted(self.bitcell_offsets))

        def find_closest_index(y_offset_):
            valid_indices = [i for i in range(self.num_rows)
                             if bitcell_offsets[i] >= y_offset_]
            return valid_indices[0]

        for y_offset in self.tap_offsets:
            closest_index = find_closest_index(y_offset)
            if closest_index % 4 in [0, 3]:
                if closest_index % 4 == 3:
                    y_offset = y_offset + self.bitcell.height
                    closest_index += 1
                y_top = max(bitcell_offsets[closest_index],
                            y_offset + self.get_min_layer_width(NWELL))
                yield y_offset, y_top
