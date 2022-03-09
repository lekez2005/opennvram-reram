from base.contact import m1m2, m2m3, cross_m2m3
from base.design import METAL1, METAL2, METAL3, design, ACTIVE
from base.vector import vector
from base.well_implant_fills import create_wells_and_implants_fills
from globals import OPTS
from modules.logic_buffer import LogicBuffer
from modules.wordline_driver_array import wordline_driver_array


class stacked_wordline_driver_array(wordline_driver_array):
    """Wordline Driver array with two adjacent rows stacked horizontally
        so the total height per module is 2x the bitcell height"""

    def __init__(self, rows, buffer_stages, name=None):
        design.__init__(self, name)
        self.rows = self.num_rows = rows
        self.buffer_stages = buffer_stages

        self.buffer_insts = []
        self.module_insts = []

        self.add_pins()
        self.create_layout()
        self.DRC_LVS()

    def create_layout(self):
        super().create_layout()
        self.fill_horizontal_module_space()
        self.width = self.buffer_insts[1].rx()
        self.create_power_pins()

    def create_modules(self):
        self.bitcell = self.create_mod_from_str(OPTS.bitcell)
        self.logic_buffer = LogicBuffer(self.buffer_stages, logic="pnand2",
                                        height=2 * self.bitcell.height, route_outputs=False,
                                        route_inputs=False,
                                        contact_pwell=False, contact_nwell=False,
                                        align_bitcell=True)
        self.add_mod(self.logic_buffer)

    def get_row_y_offset(self, row):
        row_index = row - (row % 2)
        y_offset = self.bitcell_offsets[row_index]
        if (row % 4) < 2:
            y_offset += self.logic_buffer.height
            mirror = "MX"
        else:
            mirror = "R0"
        return y_offset, mirror

    def add_modules(self):
        self.calculate_y_offsets()

        en_pin_x = self.get_parallel_space(METAL1) + self.m1_width
        self.en_pin_clearance = en_pin_clearance = (en_pin_x + self.m2_width +
                                                    self.get_parallel_space(METAL2))

        rail_y = - 0.5 * self.rail_height
        en_rail = self.add_rect(METAL2, offset=vector(en_pin_x, rail_y), width=self.m2_width,
                                height=self.height)

        en_pin = self.add_layout_pin(text="en", layer="metal2",
                                     offset=vector(en_pin_clearance + self.logic_buffer.width +
                                                   en_pin_x, rail_y),
                                     width=self.m2_width, height=self.height)

        self.en_pin, self.en_rail = en_pin, en_rail

        self.join_en_pin_rail()

        x_offsets = [en_pin_clearance, 2 * en_pin_clearance + self.logic_buffer.width]

        m3_clearance = 0.5 * m2m3.w_2 + self.get_parallel_space(METAL3)

        out_pin = self.get_out_pin_name()

        for row in range(self.rows):
            y_offset, mirror = self.get_row_y_offset(row)
            x_offset = x_offsets[row % 2]
            # add logic buffer
            buffer_inst = self.add_inst("driver{}".format(row), mod=self.logic_buffer,
                                        offset=vector(x_offset, y_offset), mirror=mirror)
            self.connect_inst(self.get_connections(row))

            b_pin = buffer_inst.get_pin("B")

            if row % 2 == 1:
                in_y_offset = b_pin.cy() + m3_clearance
            else:
                in_y_offset = b_pin.cy() - m3_clearance - self.m3_width

            # decoder in
            pin_right = b_pin.cx() - 0.5 * m2m3.h_2 + self.m3_width
            self.add_layout_pin("in[{}]".format(row), METAL3,
                                offset=vector(0, in_y_offset),
                                width=pin_right)
            self.add_rect(METAL3, offset=vector(pin_right - self.m3_width, in_y_offset),
                          height=b_pin.cy() - in_y_offset)
            self.add_contact_center(m1m2.layer_stack, offset=b_pin.center())
            self.add_cross_contact_center(cross_m2m3, offset=b_pin.center())
            fill_width = self.logic_buffer.logic_mod.gate_fill_width
            fill_height = self.logic_buffer.logic_mod.gate_fill_height
            self.add_rect_center(METAL2, offset=b_pin.center(),
                                 width=fill_width, height=fill_height)

            # route en input pin
            rail = en_rail if row % 2 == 0 else en_pin
            self.route_en_pin(buffer_inst, rail)

            self.copy_layout_pin(buffer_inst, out_pin, "wl[{}]".format(row))

            self.buffer_insts.append(buffer_inst)

    def get_en_rail_y(self, en_rail):
        return en_rail.by() - self.m3_width

    def join_en_pin_rail(self):
        # join en rail and en_pin
        en_rail, en_pin = self.en_rail, self.en_pin
        y_offset = self.get_en_rail_y(en_rail)
        for rect in [en_rail, en_pin]:
            self.add_rect(METAL2, vector(rect.lx(), y_offset), width=rect.rx() - rect.lx(),
                          height=rect.by() - y_offset)
            offset = vector(rect.cx(), y_offset + 0.5 * self.m3_width)
            self.add_cross_contact_center(cross_m2m3, offset)
        self.add_rect(METAL3, offset=vector(en_rail.lx(), y_offset),
                      width=en_pin.lx() - en_rail.lx())

    def fill_horizontal_module_space(self):
        fill_rects = create_wells_and_implants_fills(
            self.logic_buffer.buffer_mod.module_insts[-1].mod,
            self.logic_buffer.logic_mod)

        for row in range(0, self.rows, 2):
            buffer_inst = self.buffer_insts[row]
            adjacent_x_offset = self.buffer_insts[row + 1].lx()
            # Join adjacent rects between left and right buffers
            for fill_rect in fill_rects:
                if fill_rect[0] == ACTIVE:
                    continue
                elif row % 4 == 0:
                    #
                    fill_rect = (fill_rect[0], self.logic_buffer.height - fill_rect[2],
                                 self.logic_buffer.height - fill_rect[1])
                elif row % 4 == 2:
                    pass
                else:
                    continue
                y_shift, _ = self.get_row_y_offset(row)
                if row % 4 == 0:
                    y_shift -= self.logic_buffer.height
                self.add_rect(fill_rect[0], offset=vector(buffer_inst.rx(),
                                                          y_shift + fill_rect[1]),
                              height=fill_rect[2] - fill_rect[1],
                              width=adjacent_x_offset - buffer_inst.rx())

    def create_power_pins(self):
        all_pins = []
        for i in range(0, self.rows, 2):
            all_pins.append(self.buffer_insts[i].get_pin("vdd"))
            all_pins.append(self.buffer_insts[i].get_pin("gnd"))
        all_pins.append(self.buffer_insts[-2].get_pin("vdd"))

        pin_right = self.buffer_insts[1].get_pin("vdd").rx()
        for pin in all_pins:
            self.add_layout_pin(pin.name, pin.layer, pin.ll(),
                                height=pin.height(), width=pin_right - pin.lx())
