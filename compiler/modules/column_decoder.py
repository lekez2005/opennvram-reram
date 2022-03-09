from importlib import reload

import numpy as np

import debug
from base import contact
from base import design
from base.vector import vector
from globals import OPTS
from pgates.pinv import pinv
from pgates.pnand2 import pnand2
from pgates.pnand3 import pnand3


class ColumnDecoder(design.design):
    """
    Creates a column decoder for the  top col_addr_size MSBs and regular flip flops for the other address bits
    """
    def __init__(self, row_addr_size, col_addr_size):
        self.row_addr_size = row_addr_size  # type: int
        self.col_addr_size = col_addr_size  # type: int
        self.num_sel_outputs = 2**col_addr_size

        name = "column_decoder"
        design.design.__init__(self, name)
        debug.info(2, "Create Column decoder")

        self.column_rail_y = {}  # save y location of the column addresses
        self.pin_x_offset = {}  # save x location of the flip flop pins
        self.nand_insts = {}
        self.inv_insts = {}

        self.setup_layout_constants()
        self.create_pins()
        self.create_layout()
        self.offset_all_coordinates()
        coords = self.find_highest_coords()
        self.width = coords[0]
        self.height = coords[1]
        self.DRC_LVS()

    def setup_layout_constants(self):

        self.rail_pitch = self.m1_width + self.parallel_line_space

        self.total_ff = self.row_addr_size+self.col_addr_size

        self.no_bottom_rails = self.row_addr_size + 2*self.col_addr_size  # create space for complements of col

        self.bottom_space = self.line_end_space + self.rail_height

        self.ff_y_offset = (self.no_bottom_rails - 1) * self.rail_pitch + self.m1_width + self.bottom_space

        self.top_space = self.line_end_space


    def create_pins(self):
        for i in range(self.row_addr_size + self.col_addr_size):
            self.add_pin("din[{}]".format(i))
        for i in range(self.row_addr_size):
            self.add_pin("dout[{}]".format(i))
        if self.col_addr_size > 0:
            for i in range(2**self.col_addr_size):
                self.add_pin("sel[{}]".format(i))
        for pin_name in ["clk", "vdd", "gnd"]:
            self.add_pin(pin_name)

    def create_layout(self):
        self.add_flip_flops()
        self.route_ff_inputs()
        self.route_ff_power()
        self.route_ff_outputs()
        self.route_decoders()
        self.copy_layout_pin(self.msf_addr_inst, "clk")

    def add_flip_flops(self):

        # find flip flop module
        config_mod_name = getattr(OPTS, "ms_flop_array")
        class_file = reload(__import__(config_mod_name))
        mod_class = getattr(class_file, config_mod_name)
        # create ff array
        self.msf_addr_in = mod_class(name="msf_address_in", columns=self.total_ff, word_size=self.total_ff)
        self.add_mod(self.msf_addr_in)
        out_pins = []
        for i in range(self.row_addr_size):
            out_pins.append("dout[{}]".format(i))
            out_pins.append("dout_bar[{}]".format(i))
        if self.col_addr_size == 1:
            out_pins += ["sel[1]", "sel[0]"]
        else:
            for i in range(self.col_addr_size):
                out_pins.append("dout[{}]".format(i+self.row_addr_size))
                out_pins.append("dout_bar[{}]".format(i+self.row_addr_size))

        din_pins = list(map(lambda x: "din[{}]".format(x), range(self.total_ff)))

        self.msf_addr_inst = self.add_inst("msf_addr_in", mod=self.msf_addr_in,
                                           offset=vector(0, self.ff_y_offset + self.msf_addr_in.height),
                                           mirror="MX")
        self.connect_inst(din_pins + out_pins + ["clk", "vdd", "gnd"])

    def route_ff_inputs(self):
        y_base = self.msf_addr_inst.uy() + self.top_space
        for i in range(self.total_ff):
            pin_name = "din[{}]".format(i)
            din_pin = self.msf_addr_inst.get_pin(pin_name)
            y_offset = y_base + i*self.rail_pitch
            self.add_rect("metal2", offset=din_pin.ul(), height=y_offset - din_pin.uy())
            pin_offset = vector(0, y_offset)
            self.add_layout_pin(pin_name, "metal1", offset=pin_offset,
                                width=din_pin.rx())
            self.add_contact(layers=contact.m1m2.layer_stack,
                             offset=vector(din_pin.rx(), y_offset), rotate=90)

    def route_ff_power(self):
        rail_space = self.wide_m1_space
        # connect vdd's
        vdd_pins = sorted(self.msf_addr_inst.get_pins("vdd"), key=lambda x: x.by())
        lower_vdd = vdd_pins[0]
        self.top_vdd = top_vdd = vdd_pins[-1]
        rail_width = self.rail_height
        for pin in vdd_pins:
            self.add_rect("metal1", offset=vector(pin.lx() - rail_space, pin.by()),
                          width=rail_space, height=pin.height())
        self.add_rect("metal1", offset=vector(lower_vdd.lx() - rail_space - rail_width, lower_vdd.by()),
                      width=rail_width, height=top_vdd.uy() - lower_vdd.by())

        self.add_layout_pin("vdd", "metal1", offset=lower_vdd.ll(), width=lower_vdd.width(), height=lower_vdd.height())

        gnd_pins = sorted(self.msf_addr_inst.get_pins("gnd"), key=lambda x: x.by())
        self.lower_gnd = lower_gnd = gnd_pins[0]
        top_gnd = gnd_pins[-1]
        for pin in gnd_pins:
            self.add_rect("metal1", offset=vector(pin.rx(), pin.by()),
                          width=rail_space, height=pin.height())
        self.add_rect("metal1", offset=vector(lower_gnd.rx() + rail_space, lower_gnd.by()),
                      width=rail_width, height=top_gnd.uy() - lower_gnd.by())
        if self.col_addr_size < 2:
            self.add_layout_pin("gnd", "metal1", offset=top_gnd.ll(), width=top_gnd.width(),
                                height=top_gnd.height())
        self.gnd_connection_rx = lower_gnd.rx() + rail_space + rail_width

    def route_ff_outputs(self):
        for i in range(self.no_bottom_rails):
            if i < self.row_addr_size:
                data_index = i
            else:
                data_index = self.row_addr_size + int((i - self.row_addr_size) / 2)
            if i < self.row_addr_size or (i - self.row_addr_size) % 2 == 0:
                pin_name = "dout[{}]".format(data_index)
            else:
                pin_name = "dout_bar[{}]".format(data_index)



            dout_pin = self.msf_addr_inst.get_pin(pin_name)
            y_offset = i * self.rail_pitch
            self.add_rect("metal2", offset=vector(dout_pin.lx(), y_offset), height=dout_pin.by()-y_offset)
            if not (self.col_addr_size == 1 and i >= self.row_addr_size):
                self.add_contact(layers=contact.m1m2.layer_stack,
                                 offset=vector(dout_pin.lx() + contact.m1m2.second_layer_height, y_offset),
                                 rotate=90)

            self.column_rail_y[pin_name] = y_offset
            self.pin_x_offset[pin_name] = dout_pin.lx()

    def route_decoders(self):
        if self.col_addr_size < 1:
            self.extend_dout_rails(self.gnd_connection_rx)
            return
        elif self.col_addr_size == 1:
            self.extend_dout_rails(self.gnd_connection_rx)
            self.route_single_sel()
            return
        else:
            self.add_instances()
            self.extend_dout_rails(self.inv_insts[0].rx())
            self.extend_sel_rails()
            self.route_nand_inputs()
            self.route_invs()
            self.add_power_pins()



    def route_single_sel(self):
        """Create sel pins for 1->2 decoder"""
        sel_names = ["dout[{}]".format(self.row_addr_size), "dout_bar[{}]".format(self.row_addr_size)]
        pin_names = ["sel[1]", "sel[0]"]
        bottom_dout_pin = self.get_pin("dout[{}]".format(0)).by()
        for i in range(2):
            x_offset = self.pin_x_offset[sel_names[i]]
            y_offset = self.column_rail_y[sel_names[i]]

            self.add_layout_pin(pin_names[i], "metal2", offset=vector(x_offset, bottom_dout_pin),
                                height=y_offset - bottom_dout_pin)

    def extend_dout_rails(self, right_x):
        """Add dout layout pins for row_addr_size"""
        for i in range(self.row_addr_size):
            pin_name = "dout[{}]".format(i)
            x_offset = self.pin_x_offset[pin_name]
            y_offset = self.column_rail_y[pin_name]
            self.add_layout_pin(pin_name, "metal1", offset=vector(x_offset, y_offset), width=right_x - x_offset)

    def extend_sel_rails(self):
        """Connect the col_addr_size dout and dout_bar to the decoder"""
        rails = set()
        for i in range(self.num_sel_outputs):
            rails.update(self.get_rail_names(i))
        for pin_name in rails:
            x_offset = self.pin_x_offset[pin_name]
            y_offset = self.column_rail_y[pin_name]
            self.add_rect("metal1", offset=vector(x_offset, y_offset), width=self.inv_insts[0].rx() - x_offset)


    def add_instances(self):
        """Add nand and inverters"""
        y_offset = self.lower_gnd.by() + 0.5*self.rail_height
        x_offset = self.gnd_connection_rx + self.get_parallel_space("nwell")

        if self.num_sel_outputs == 4:
            nand_mod = pnand2(size=1.5)
        else:
            nand_mod = pnand3()
        self.add_mod(nand_mod)
        inv_mod = pinv(size=2)
        self.add_mod(inv_mod)

        for i in reversed(range(self.num_sel_outputs)):
            rail_names = self.get_rail_names(i)
            if len(rail_names) == 2:
                rail_indices = [1, 0]
            else:
                rail_indices = [1, 0, 2]
            rail_names = [rail_names[j] for j in rail_indices]
            sel_name = "sel[{}]".format(i)
            inv_in = "inv_in[{}]".format(i)
            nand_inst = self.add_inst("nand{}".format(i), nand_mod, offset=vector(x_offset, y_offset))
            self.nand_insts[i] = nand_inst
            self.connect_inst(rail_names + [inv_in, "vdd", "gnd"])

            x_offset += nand_mod.width
            inv_inst = self.add_inst("inv{}".format(i), inv_mod, offset=vector(x_offset, y_offset))
            self.inv_insts[i] = inv_inst
            self.connect_inst([inv_in, sel_name, "vdd", "gnd"])

            x_offset += inv_mod.width


    def get_rail_names(self, i):
        """Find input combination for i.
        For example  for i = 5 = 101, output is dout[8] dout_bar[7] dout[6] when row_addr_size=6
        """
        binary_list = list(reversed(list(np.binary_repr(i, self.col_addr_size))))
        rail_names = []
        for bit in range(len(binary_list)):
            if binary_list[bit] == '0':
                bar_string = "_bar"
            else:
                bar_string = ""
            rail_name = "dout{}[{}]".format(bar_string, self.row_addr_size + bit)
            rail_names.append(rail_name)
        return rail_names

    def route_nand_inputs(self):
        """Connect NAND inputs to rails"""
        for i in range(self.num_sel_outputs):
            rail_names = self.get_rail_names(i)
            in_pins = ["B", "A"]

            x_base_offset = self.nand_insts[i].lx() + 0.5 * self.m2_width

            for j in range(len(in_pins)):
                x_offset = x_base_offset + j*self.rail_pitch
                rail_y = self.column_rail_y[rail_names[j]]
                self.add_contact(contact.m1m2.layer_stack,
                                 offset=vector(x_offset + contact.m1m2.second_layer_height, rail_y),
                                 rotate=90)
                pin = self.nand_insts[i].get_pin(in_pins[j])
                self.add_rect("metal2", offset=vector(x_offset, rail_y), height=pin.cy()-rail_y)
                self.add_rect("metal2", offset=vector(x_offset, pin.cy()-0.5*self.m2_width),
                              width=pin.lx()-x_offset)
                self.add_contact_center(contact.m1m2.layer_stack, offset=pin.center())
            if len(rail_names) == 3:  # nand3 C pin needs to be routed differently because of spacing rules
                rail_y = self.column_rail_y[rail_names[2]]
                x_offset = self.nand_insts[i].rx() + 0.5*self.m2_width
                self.add_contact(contact.m1m2.layer_stack,
                                 offset=vector(x_offset + contact.m1m2.second_layer_height, rail_y),
                                 rotate=90)
                pin = self.nand_insts[i].get_pin("C")
                self.add_rect("metal2", offset=vector(x_offset, rail_y), height=pin.cy() - rail_y)
                self.add_rect("metal2", offset=vector(pin.lx(), pin.cy() - 0.5 * self.m2_width),
                              width=x_offset - pin.lx() + self.m2_width)
                self.add_contact_center(contact.m1m2.layer_stack, offset=pin.center())

    def route_invs(self):
        """Connect inverter inputs and add sel pins to inverter outputs"""
        for i in range(self.num_sel_outputs):
            inv_inst = self.inv_insts[i]
            # connect Z to A
            a_pin = inv_inst.get_pin("A")
            z_pin = self.nand_insts[i].get_pin("Z")
            self.add_rect("metal1", offset=vector(z_pin.rx(), a_pin.cy()-0.5*self.m1_width),
                          width=a_pin.lx() - z_pin.rx())

            z_pin = inv_inst.get_pin("Z")

            bottom_dout_pin = self.get_pin("dout[{}]".format(0)).by()

            self.add_layout_pin("sel[{}]".format(i), "metal2", offset=vector(z_pin.lx(), bottom_dout_pin),
                                height=z_pin.by()-bottom_dout_pin)

    def add_power_pins(self):
        """Add gnd pin and connect flip flop vdd to decoder vdd"""
        # add gnd pin
        last_inverter = self.inv_insts[0]
        gnd_pin = last_inverter.get_pin("gnd")
        self.add_layout_pin("gnd", "metal1", offset=vector(self.gnd_connection_rx, gnd_pin.by()),
                            width=last_inverter.rx() - self.gnd_connection_rx, height=gnd_pin.height())

        # connect ff vdd to inverter/nand vdd
        vdd_pin = self.nand_insts[self.num_sel_outputs - 1].get_pin("vdd")
        self.add_rect("metal1", offset=vdd_pin.ul(), width=vdd_pin.height(), height=self.top_vdd.by() - vdd_pin.uy())
        self.add_rect("metal1", offset=self.top_vdd.lr(), height=vdd_pin.height(),
                      width=vdd_pin.lx() - self.top_vdd.rx() + vdd_pin.height())














