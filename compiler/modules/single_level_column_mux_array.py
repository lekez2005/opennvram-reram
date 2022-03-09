import re

import debug
from base import design
from base.contact import m1m2, cross_m1m2, cross_m2m3, m2m3
from base.design import METAL2, METAL1, METAL3
from base.geometry import MIRROR_Y_AXIS, NO_MIRROR
from base.hierarchy_layout import GDS_ROT_90
from base.vector import vector
from globals import OPTS


class single_level_column_mux_array(design.design):
    """
    Dynamically generated column mux array.
    Array of column mux to read the bitlines through the 6T.
    """

    def __init__(self, columns, word_size):
        design.design.__init__(self, "columnmux_array")
        debug.info(1, "Creating {0}".format(self.name))
        self.columns = columns
        self.word_size = word_size
        self.words_per_row = int(self.columns / self.word_size)
        self.create_layout()
        self.DRC_LVS()

    def add_pins(self):
        for i in range(self.columns):
            self.add_pin("bl[{}]".format(i))
            self.add_pin("br[{}]".format(i))
        for i in range(self.words_per_row):
            self.add_pin("sel[{}]".format(i))
        for i in range(self.word_size):
            self.add_pin("bl_out[{}]".format(i))
            self.add_pin("br_out[{}]".format(i))

        self.power_nets = []
        for pin_name in ["vdd", "gnd"]:
            if pin_name in self.mux.pins:
                self.power_nets.append(pin_name)
                self.add_pin(pin_name)

    def get_inputs_for_pin(self, name):
        reg_pattern = re.compile(r"(\S+)\[([0-9]+)\]")
        match = reg_pattern.match(name)
        if match:
            pin_name, index = match.groups()
            index = int(index)
            if "_out" in pin_name:
                sel_pins = ["sel[{}]".format(i) for i in range(self.words_per_row)]
                pin_name = pin_name.replace("_out", "")
                base_col = index * self.words_per_row
                return ["{}[{}]".format(pin_name, i + base_col)
                        for i in range(self.words_per_row)] + sel_pins
            else:
                bit = int(index / self.words_per_row)
                sel_index = index % self.words_per_row
                return ["{}_out[{}]".format(pin_name, bit), "sel[{}]".format(sel_index)]
        return super(design.design, self).get_inputs_for_pin(name)

    def is_delay_primitive(self):
        return True

    def create_layout(self):
        self.create_modules()
        self.add_pins()
        self.setup_layout_constants()
        self.create_array()
        self.add_routing()
        # Find the highest shapes to determine height before adding well
        highest = self.find_highest_coords()
        self.height = highest.y
        self.width = self.child_insts[-1].rx()
        self.add_layout_pins()
        self.add_dummy_poly(self.child_mod, self.child_insts, words_per_row=1)
        self.add_boundary()

    def create_modules(self):
        self.mux = self.create_mod_from_str(OPTS.column_mux)
        self.child_mod = self.mux
        self.add_mod(self.mux)

    def setup_layout_constants(self):
        self.column_addr_size = int(self.words_per_row / 2)
        self.bus_pitch = self.bus_width + self.bus_space
        # one set of metal1 routes for select signals and a pair to interconnect the mux outputs bl/br
        # two extra route pitch is to space from the sense amp

        self.route_height = (self.words_per_row + 3) * self.bus_pitch
        self.mirror = OPTS.mirror_bitcell_y_axis and not OPTS.symmetric_bitcell
        self.swap_output = False
        if self.swap_output:
            self.route_height += self.bus_pitch  # extra space to cross br

    def create_array(self):
        self.child_insts = []

        bitcell_array_cls = self.import_mod_class_from_str(OPTS.bitcell_array)
        offsets = bitcell_array_cls.calculate_x_offsets(num_cols=self.columns)

        (self.bitcell_offsets, self.tap_offsets, _) = offsets

        # For every column, add a pass gate
        for col_num in range(self.columns):
            name = "mod_{0}".format(col_num)
            offset = vector(self.bitcell_offsets[col_num], self.route_height)

            if (col_num + OPTS.num_bitcell_dummies) % 2 == 0 and self.mirror:
                mirror = MIRROR_Y_AXIS
                offset.x += self.mux.width
            else:
                mirror = NO_MIRROR
            bitline_nets = "bl[{0}] br[{0}] "
            bitline_nets += (bitline_nets.replace("bl", "bl_out").replace("br", "br_out")
                             .replace("{0}", "{1}"))
            bitline_conns = bitline_nets.format(col_num, int(col_num / self.words_per_row)).split()

            self.child_insts.append(self.add_inst(name=name, mod=self.mux, offset=offset,
                                                  mirror=mirror))

            self.connect_inst(bitline_conns +
                              ["sel[{}]".format(col_num % self.words_per_row)] +
                              self.power_nets)

    def add_layout_pins(self):
        """ Add the pins after we determine the height. """
        # For every column, add a pass gate
        for col_num in range(self.columns):
            child_insts = self.child_insts[col_num]
            for pin_name in ["bl", "br"]:
                self.copy_layout_pin(child_insts, pin_name, f"{pin_name}[{col_num}]")
        for pin_name in self.power_nets:
            for pin in self.child_insts[0].get_pins(pin_name):
                self.add_layout_pin(pin_name, pin.layer, offset=pin.ll(),
                                    width=self.width - pin.lx(), height=pin.height())

    def add_routing(self):
        self.add_horizontal_input_rail()
        self.add_vertical_gate_rail()
        self.route_bitlines()

    def add_horizontal_input_rail(self):
        """ Create address input rails on M1 below the mux transistors  """
        for j in range(self.words_per_row):
            offset = vector(0, self.route_height - (j + 1) * self.bus_pitch)
            self.add_layout_pin(text="sel[{}]".format(j),
                                layer="metal1",
                                offset=offset,
                                width=self.child_insts[-1].get_pin("sel").rx() + 0.5 * m1m2.height,
                                height=self.bus_width)

    def add_vertical_gate_rail(self):
        """  Connect the selection gate to the address rails """

        # Offset to the first transistor gate in the pass gate
        for col in range(self.columns):
            # which select bit should this column connect to depends on the position in the word
            sel_index = col % self.words_per_row
            # Add the column x offset to find the right select bit

            gate_pin = self.child_insts[col].get_pin("sel")

            sel_pos = vector(gate_pin.lx(), self.get_pin("sel[{}]".format(sel_index)).cy())

            self.add_rect("metal2", offset=sel_pos, height=gate_pin.by() - sel_pos.y)

            self.add_cross_contact_center(cross_m1m2, offset=vector(gate_pin.cx(), sel_pos.y),
                                          rotate=True)

    def get_output_bitlines(self, col):
        return self.child_insts[col].get_pin("bl_out"), self.child_insts[col].get_pin("br_out")

    def route_bitlines(self):
        """  Connect the output bit-lines to form the appropriate width mux """
        bl_out_y = self.get_pin("sel[{}]".format(self.words_per_row - 1)).by() - self.bus_pitch
        br_out_y = bl_out_y - self.bus_pitch

        bl_out, br_out = self.get_output_bitlines(0)
        if bl_out.lx() > br_out.lx():
            bl_out_y, br_out_y = br_out_y, bl_out_y

        cross_via_extension = max(0.5 * cross_m1m2.height, 0.5 * cross_m2m3.width)

        m2_fill_height = self.bus_width
        _, m2_fill_width = self.calculate_min_area_fill(m2_fill_height, layer=METAL2)
        m2_fill_width = max(m1m2.h_2, m2_fill_width)

        for j in range(self.columns):
            bl_out, br_out = self.get_output_bitlines(j)
            if self.swap_output and (j + OPTS.num_bitcell_dummies) % 2 == 0:
                bl_out, br_out = br_out, bl_out

            bl_out_offset = vector(bl_out.cx() - cross_via_extension, bl_out_y)
            br_out_offset = vector(br_out.cx() - cross_via_extension, br_out_y)

            bl_via_offset = vector(bl_out.cx(), bl_out_y + 0.5 * self.bus_width)
            br_via_offset = vector(br_out.cx(), br_out_y + 0.5 * self.bus_width)

            for pin, via_offset in zip([bl_out, br_out], [bl_via_offset, br_via_offset]):
                if self.swap_output and j % self.words_per_row == 0:
                    rect_y = via_offset.y
                else:
                    rect_y = via_offset.y - 0.5 * m1m2.h_2
                self.add_rect(METAL2, offset=vector(pin.lx(), rect_y),
                              width=pin.width(), height=pin.by() - rect_y)

            if (j % self.words_per_row) == 0:
                # Create the metal1 to connect the n-way mux output from the pass gate
                # These will be located below the select lines.

                last_bl_out, last_br_out = self.get_output_bitlines(j + self.words_per_row - 1)
                # add m1 rect to extend from beginning to end of bitline connected to it
                bl_width = last_bl_out.cx() - bl_out.cx() + 2 * cross_via_extension
                br_width = last_br_out.cx() - br_out.cx() + 2 * cross_via_extension
                for rect_offset, width in zip([bl_out_offset, br_out_offset],
                                              [bl_width, br_width]):
                    for layer in [METAL1, METAL3]:
                        self.add_rect(layer, offset=rect_offset, width=width,
                                      height=self.bus_width)

                if self.swap_output:
                    # prevent clash with bl pin below it
                    self.add_via_center(m1m2.layer_stack, bl_via_offset, rotate=GDS_ROT_90)
                    self.add_via_center(m2m3.layer_stack, bl_via_offset, rotate=GDS_ROT_90)
                    self.add_via_center(m1m2.layer_stack, br_via_offset, rotate=GDS_ROT_90)
                    self.add_via_center(m2m3.layer_stack, br_via_offset, rotate=GDS_ROT_90)

                    _, adjacent_br_pin = self.get_output_bitlines(j + 1)
                    bl_top_y = bl_via_offset.y
                    bl_x_offset = br_out.lx()
                    br_x_offset = bl_out.lx()
                    br_top_y = bl_top_y - self.bus_pitch

                    m2_y = br_top_y - 0.5 * m1m2.h_2
                    self.add_rect(METAL2, offset=vector(adjacent_br_pin.lx(), m2_y),
                                  width=adjacent_br_pin.width(), height=br_out_y - m2_y)
                    self.add_cross_contact_center(cross_m1m2, rotate=True,
                                                  offset=vector(adjacent_br_pin.cx(), br_top_y))
                    self.add_cross_contact_center(cross_m2m3, rotate=False,
                                                  offset=vector(adjacent_br_pin.cx(), br_top_y))

                    for bitline_pin, pin_top, adj_pin in zip([br_out, bl_out], [bl_top_y, br_top_y],
                                                             [bl_out, adjacent_br_pin]):
                        rect_x = bitline_pin.cx() - cross_via_extension
                        via_offset = vector(bitline_pin.cx(), pin_top)
                        for layer, via in zip([METAL1, METAL3], [m1m2, m2m3]):
                            self.add_rect(layer, offset=vector(rect_x,
                                                               pin_top - 0.5 * self.bus_width),
                                          height=self.bus_width,
                                          width=adj_pin.cx() + cross_via_extension - rect_x)

                            self.add_via_center(via.layer_stack, via_offset, rotate=GDS_ROT_90)
                        self.add_rect_center(METAL2, via_offset, width=m2_fill_width,
                                             height=m2_fill_height)

                else:
                    self.add_cross_contact_center(cross_m1m2, bl_via_offset, rotate=True)
                    self.add_cross_contact_center(cross_m2m3, bl_via_offset, rotate=False)
                    bl_top_y = bl_via_offset.y
                    br_top_y = br_via_offset.y
                    bl_x_offset = bl_out.lx()
                    br_x_offset = br_out.lx()
                    self.add_cross_contact_center(cross_m1m2, br_via_offset, rotate=True)
                    self.add_cross_contact_center(cross_m2m3, br_via_offset, rotate=False)
                for top_y, pin_x, pin_name in zip([bl_top_y, br_top_y], [bl_x_offset, br_x_offset],
                                                  ["bl_out", "br_out"]):
                    pin_name += "[{}]".format(int(j / self.words_per_row))
                    # self.add_rect(METAL3, offset=vector(pin_x, 0),
                    #               width=bl_out.width(), height=top_y)
                    self.add_layout_pin(pin_name, METAL3, offset=vector(pin_x, 0),
                                        width=bl_out.width(), height=top_y)
            else:
                # add via to the connection rect
                for via_offset in [bl_via_offset, br_via_offset]:
                    self.add_cross_contact_center(cross_m1m2, rotate=True, offset=via_offset)
                    self.add_cross_contact_center(cross_m2m3, rotate=False, offset=via_offset)
