import math

import debug
from base import contact
from base import design
from base.contact import m2m3, m1m2, cross_m1m2
from base.design import METAL3, METAL1, METAL2, PIMP, NIMP
from base.utils import round_to_grid as round_g
from base.vector import vector
from base.well_implant_fills import calculate_modules_implant_space
from globals import OPTS
from modules.buffer_stage import BufferStage
from pgates.pinv import pinv
from pgates.pnand2 import pnand2
from pgates.pnand3 import pnand3
from pgates.pnor2 import pnor2
from pgates.pnor3 import pnor3
from tech import drc


class hierarchical_predecode(design.design):
    """
    Pre 2x4 and 3x8 decoder shared code.
    """

    def __init__(self, input_number, route_top_rail=True, use_flops=False, buffer_sizes=None,
                 negate=False):
        self.number_of_inputs = input_number
        self.number_of_outputs = int(math.pow(2, self.number_of_inputs))

        name = "pre{0}x{1}".format(self.number_of_inputs, self.number_of_outputs)
        if not route_top_rail:
            name += "_no_top"
        if use_flops:
            name += "_flops"
        if buffer_sizes is not None:
            self.buffer_sizes = buffer_sizes
            name += "_" + ("_".join(['{:.3g}'.format(x) for x in buffer_sizes])).replace(".", "__")
        else:
            self.buffer_sizes = OPTS.predecode_sizes
        if negate:
            name += "_neg"

        if len(self.buffer_sizes) % 2 == 1:
            negate = not negate

        self.negate = negate
        design.design.__init__(self, name=name)
        self.route_top_rail = route_top_rail
        self.use_flops = use_flops

        self.mod_bitcell = self.create_mod_from_str(OPTS.bitcell)
        self.bitcell_height = self.mod_bitcell.height

    def create_flops(self):
        self.vertical_flops = OPTS.predecoder_flop_layout == "v" and self.use_flops
        if self.use_flops:
            predecoder_flop = OPTS.predecoder_flop
            self.flop = self.create_mod_from_str(predecoder_flop)
        if self.use_flops and not self.vertical_flops:
            self.module_height = self.flop.height
        else:
            self.module_height = getattr(OPTS, "logic_buffers_height", self.bitcell_height)

    def add_pins(self):
        in_name = "flop_in[{}]" if self.use_flops else "in[{}]"
        for k in range(self.number_of_inputs):
            self.add_pin(in_name.format(k))
        for i in range(self.number_of_outputs):
            self.add_pin("out[{0}]".format(i))
        if self.use_flops:
            self.add_pin("clk")
        self.add_pin("vdd")
        self.add_pin("gnd")

    def create_modules(self):
        """ Create the INV and NAND gate """
        self.create_flops()

        inverter_size = self.buffer_sizes[1]

        self.inv = pinv(size=inverter_size, height=self.module_height)
        self.add_mod(self.inv)
        self.nand = self.create_nand(self.number_of_inputs)
        self.add_mod(self.nand)

        self.output_buffer = BufferStage(buffer_stages=self.buffer_sizes[1:], route_outputs=False,
                                         height=self.module_height)
        self.add_mod(self.output_buffer)

        if not self.route_top_rail:
            self.top_output_buffer = BufferStage(buffer_stages=self.buffer_sizes[1:],
                                                 route_outputs=False, contact_nwell=True,
                                                 contact_pwell=True, fake_contacts=True,
                                                 height=self.module_height)
            self.add_mod(self.top_output_buffer)
            self.top_nand = self.create_nand(self.number_of_inputs)
            self.add_mod(self.top_nand)
        else:
            self.top_output_buffer = self.output_buffer
            self.top_nand = self.nand

    def create_nand(self, inputs):
        """ Create the NAND for the predecode input stage """
        nand_size = self.buffer_sizes[0]
        if inputs == 2:
            nand_class = pnor2 if self.negate else pnand2
        elif inputs == 3:
            nand_class = pnor3 if self.negate else pnand3
        else:
            return debug.error("Invalid number of predecode inputs.", -1)
        while nand_size >= 1:
            # silence name clash/size errors
            def noop(*args, **kwargs):
                pass

            def silect_check(check, _):
                assert check

            debug_error = debug.error
            debug_check = debug.check
            debug.error = noop
            debug.check = silect_check
            try:
                # adjacent inverter will have body taps
                nand = nand_class(size=nand_size, contact_nwell=False,
                                  contact_pwell=False,
                                  height=self.module_height, same_line_inputs=False)
                return nand
            except (AssertionError, AttributeError):
                nand_size *= 0.98
            finally:
                debug.error = debug_error
                debug.check = debug_check

    def setup_flop_offsets(self):
        x_offset = 0

        self.clk_x_offset = x_offset + 0.5 * self.m2_width
        self.rails["clk"] = self.clk_x_offset

        self.rail_heights["clk"] = self.number_of_inputs * self.flop.height

        if not self.vertical_flops:
            x_offset += self.m2_pitch + 0.5 * self.m2_width
            for rail_index in range(self.number_of_inputs):
                rail_name = "flop_in[{}]".format(rail_index)
                self.rails[rail_name] = x_offset
                self.rail_heights[rail_name] = (rail_index + 1) * self.flop.height
                x_offset += self.m2_pitch
        if self.vertical_flops:
            module_space = self.m2_width + self.parallel_line_space - 0.5 * self.m2_width
        else:
            module_space = (self.line_end_space - self.m2_space)
        self.flop_x_offset = x_offset + module_space
        if self.vertical_flops:
            self.power_rail_x = (self.flop_x_offset + 2 * self.flop.width +
                                 self.line_end_space)
            self.mid_rail_x = self.power_rail_x + self.rail_height + self.parallel_line_space - self.m2_pitch
            self.flops_y = self.wide_m1_space
            self.address_out_y = self.flops_y + self.flop.height + self.wide_m1_space
            if self.number_of_inputs == 3:
                self.upper_flop_y = self.address_out_y + 6 * self.m3_pitch + self.wide_m1_space

        else:
            self.mid_rail_x = self.flop_x_offset + self.flop.width + self.m2_pitch

    def setup_input_inv_offsets(self):
        # Non inverted input rails
        for rail_index in range(self.number_of_inputs):
            xoffset = rail_index * self.m2_pitch + 0.5 * self.m2_width
            self.rails["in[{}]".format(rail_index)] = xoffset
        # x offset for input inverters
        left_s_d = self.inv.get_left_source_drain()
        self.x_off_inv_1 = self.number_of_inputs * self.m2_pitch - left_s_d
        self.mid_rail_x = self.x_off_inv_1 + self.inv.width

    def setup_constraints(self):
        # we are going to use horizontal vias, so use the via height
        # use a conservative douple spacing just to get rid of annoying via DRCs
        self.m1_pitch = m1m2.first_layer_width + self.get_parallel_space(METAL1)
        self.m2_pitch = m1m2.second_layer_width + self.get_parallel_space(METAL2)
        self.m3_pitch = m2m3.second_layer_width + self.get_parallel_space(METAL3)

        # The rail offsets are indexed by the label
        self.rails = {}
        self.rail_heights = {}

        if self.use_flops:
            self.setup_flop_offsets()
        else:
            self.setup_input_inv_offsets()

        # Creating the right hand side metal2 rails for output connections
        for rail_index in range(2 * self.number_of_inputs):
            xoffset = self.mid_rail_x + ((rail_index + 1) * self.m2_pitch) + 0.5 * self.m2_width
            if self.vertical_flops:
                flop_index = self.number_of_inputs - int(rail_index / 2) - 1  # rightmost flop first
                rail_name = "A{}[{}]".format("bar" * ((rail_index % 2) == 0), flop_index)
            else:
                if rail_index < self.number_of_inputs:
                    rail_name = "Abar[{}]".format(rail_index)
                else:
                    rail_name = "A[{}]".format(rail_index - self.number_of_inputs)
            self.rails[rail_name] = xoffset

        # x offset to NAND decoder includes the left rails, mid rails and inverters, plus an extra m2 pitch
        # give space to A pin

        nand_a_pin = self.nand.get_pin("A")
        via_space = self.get_line_end_space(METAL1) + m1m2.first_layer_height
        a_pin_space = max(via_space - nand_a_pin.lx(), 0)
        self.x_off_nand = self.mid_rail_x + (1 + 2 * self.number_of_inputs) * self.m2_pitch + a_pin_space

        # x offset to output inverters
        module_space = calculate_modules_implant_space(self.nand, self.output_buffer)
        self.x_off_inv_2 = self.x_off_nand + self.nand.width + module_space

        # Height width are computed 
        self.width = self.x_off_inv_2 + self.output_buffer.width
        self.height = self.number_of_outputs * self.nand.height

    def create_rails(self):
        """ Create all of the rails for the inputs and vdd/gnd/inputs_bar/inputs """
        # extend rail to highest pin
        highest_pin = "C" if self.number_of_inputs == 3 else "B"
        top_space = self.nand.height - self.nand.get_pin(highest_pin).uy()
        for label in self.rails.keys():
            # these are not primary inputs, so they shouldn't have a
            # label or LVS complains about different names on one net
            if label.startswith("in") or label.startswith("flop_in") or label == "clk":
                default_height = self.height - 2 * self.m2_space
                self.add_layout_pin(text=label,
                                    layer="metal2",
                                    offset=vector(self.rails[label] - 0.5 * self.m2_width, 0),
                                    width=self.m2_width,
                                    height=self.rail_heights.get(label, default_height))
            else:
                self.add_rect(layer="metal2",
                              offset=vector(self.rails[label] - 0.5 * self.m2_width, 0),
                              width=self.m2_width,
                              height=self.height - top_space)

    def add_input_inverters(self):
        """ Create the input inverters to invert input signals for the decode stage. """

        self.in_inst = []
        for row in range(self.number_of_inputs):
            if not self.use_flops:
                name = "pre_inv_{0}".format(row)
                if (row % 2 == 1):
                    y_off = row * (self.inv.height)
                    mirror = "R0"
                else:
                    y_off = (row + 1) * (self.inv.height)
                    mirror = "MX"
                offset = vector(self.x_off_inv_1, y_off)
                self.in_inst.append(self.add_inst(name=name,
                                                  mod=self.inv,
                                                  offset=offset,
                                                  mirror=mirror))
                self.connect_inst(["in[{0}]".format(row),
                                   "inbar[{0}]".format(row),
                                   "vdd", "gnd"])
            else:
                name = "flop_{0}".format(row)
                if self.vertical_flops:

                    if row < 2:
                        x_offset = self.flop_x_offset + (row * self.flop.width)
                        y_off = self.flops_y
                        mirror = "R0"
                    else:
                        x_offset = self.flop_x_offset + self.flop.width
                        y_off = self.upper_flop_y + self.flop.height
                        mirror = "MX"
                else:
                    x_offset = self.flop_x_offset
                    if (row % 2 == 1):
                        y_off = row * (self.flop.height)
                        mirror = "R0"
                    else:
                        y_off = (row + 1) * (self.flop.height)
                        mirror = "MX"
                offset = vector(x_offset, y_off)
                self.in_inst.append(self.add_inst(name=name,
                                                  mod=self.flop,
                                                  offset=offset,
                                                  mirror=mirror))
                self.connect_inst(["flop_in[{0}]".format(row),
                                   "in[{0}]".format(row),
                                   "inbar[{0}]".format(row),
                                   "clk", "vdd", "gnd"])

    def add_output_inverters(self):
        """ Create inverters for the inverted output decode signals. """

        self.inv_inst = []
        for inv_num in range(self.number_of_outputs):
            name = "pre_nand_inv_{}".format(inv_num)
            if (inv_num % 2 == 1):
                y_off = inv_num * self.output_buffer.height
                mirror = "R0"
            else:
                y_off = (inv_num + 1) * self.output_buffer.height
                mirror = "MX"
            offset = vector(self.x_off_inv_2, y_off)
            if inv_num < self.number_of_outputs - 1:
                output_buffer = self.output_buffer
            else:
                output_buffer = self.top_output_buffer
            self.inv_inst.append(self.add_inst(name=name,
                                               mod=output_buffer,
                                               offset=offset,
                                               mirror=mirror))
            out_net = "out[{}]".format(inv_num)
            out_bar_net = "out_bar[{}]".format(inv_num)
            z_net = "Z[{}]".format(inv_num)

            if len(output_buffer.buffer_stages) == 1:
                output_nets = [out_net, z_net]
            elif len(output_buffer.buffer_stages) % 2 == 1:
                output_nets = [out_net, out_bar_net]
            else:
                output_nets = [out_bar_net, out_net]
            self.connect_inst([z_net] + output_nets + ["vdd", "gnd"])

    def add_nand(self, connections):
        """ Create the NAND stage for the decodes """
        self.nand_inst = []
        for nand_input in range(self.number_of_outputs):
            inout = str(self.number_of_inputs) + "x" + str(self.number_of_outputs)
            name = "pre{0}_nand_{1}".format(inout, nand_input)
            if (nand_input % 2 == 1):
                y_off = nand_input * self.inv.height
                mirror = "R0"
            else:
                y_off = (nand_input + 1) * self.inv.height
                mirror = "MX"
            offset = vector(self.x_off_nand, y_off)
            if nand_input < self.number_of_outputs - 1:
                nand = self.nand
            else:
                nand = self.top_nand
            self.nand_inst.append(self.add_inst(name=name,
                                                mod=nand,
                                                offset=offset,
                                                mirror=mirror))
            nand_conns = []
            for net in connections[nand_input]:
                if self.negate and net.startswith("in["):
                    net = net.replace("in[", "inbar[")
                elif self.negate and net.startswith("inbar["):
                    net = net.replace("inbar[", "in[")
                nand_conns.append(net)
            self.connect_inst(nand_conns)

            self.join_inverter_nand_implants(nand_input)

    def route(self):
        if self.use_flops:
            if self.vertical_flops:
                self.route_vertical_input_flops()
            else:
                self.route_horizontal_input_flops()
        else:
            self.route_input_inverters()
            self.route_inputs_to_rails()
        self.route_nand_to_rails()
        self.route_output_inverters()
        self.route_vdd_gnd()

    def route_inputs_to_rails(self):
        """ Route the uninverted inputs to the second set of rails """
        for num in range(self.number_of_inputs):
            # route one signal next to each vdd/gnd rail since this is
            # typically where the p/n devices are and there are no
            # pins in the nand gates. 
            y_offset = (num + self.number_of_inputs) * self.inv.height + 0.5 * self.rail_height + \
                       contact.m1m2.height + self.m1_space
            in_pin = "in[{}]".format(num)
            a_pin = "A[{}]".format(num)
            in_pos = vector(self.rails[in_pin], y_offset)
            a_pos = vector(self.rails[a_pin], y_offset)
            self.add_path("metal1", [in_pos, a_pos])
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=[self.rails[in_pin], y_offset],
                                rotate=0)
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=[self.rails[a_pin], y_offset],
                                rotate=0)

    def route_output_inverters(self):
        """
        Route all conections of the outputs inverters 
        """
        for num in range(self.number_of_outputs):
            # route nand output to output inv input
            z_pin = self.nand_inst[num].get_pin("Z")
            a_pin = self.inv_inst[num].get_pin("in")
            self.add_rect("metal1", offset=vector(z_pin.rx(), a_pin.by()), width=a_pin.lx() - z_pin.rx())

            out_pin = "out_inv" if len(self.output_buffer.buffer_stages) % 2 == 1 else "out"
            self.copy_layout_pin(self.inv_inst[num], out_pin, "out[{}]".format(num))

    def route_horizontal_input_flops(self):
        """
        Route flip flop inputs and outputs
        """
        _, m3_min_width = self.calculate_min_area_fill(self.m3_width, layer=METAL3)
        for row in range(self.number_of_inputs):
            # connect din
            din_pin = self.in_inst[row].get_pin("din")
            rail_x = self.rails["flop_in[{}]".format(row)]
            self.add_contact_center(contact.m2m3.layer_stack, offset=vector(rail_x, din_pin.cy()))
            self.add_rect("metal3", offset=vector(rail_x, din_pin.by()), width=din_pin.lx() - rail_x)
            if row % 2 == 0:
                via_y = din_pin.uy() - m2m3.w_2
            else:
                via_y = din_pin.by()
            self.add_contact(contact.m2m3.layer_stack, offset=vector(din_pin.lx() + m2m3.height, via_y),
                             rotate=90)

            # connect clk
            if not self.vertical_flops:
                clk_pin = self.in_inst[row].get_pin("clk")
                rail_x = self.rails["clk"]
                self.add_contact_center(contact.m1m2.layer_stack, offset=vector(rail_x, clk_pin.cy()))
                self.add_rect("metal1", offset=vector(rail_x, clk_pin.by()), width=clk_pin.lx() - rail_x)

            # route dout
            pin_names = ["dout", "dout_bar"]
            out_pin_names = ["A", "Abar"]
            for i in range(2):
                flop_pin = self.in_inst[row].get_pin(pin_names[i])
                out_pin = "{}[{}]".format(out_pin_names[i], row)
                rail_x = self.rails[out_pin]
                self.add_contact(contact.m2m3.layer_stack,
                                 offset=flop_pin.lr() + vector(contact.m2m3.second_layer_height, 0),
                                 rotate=90)
                rail_width = max(rail_x - flop_pin.rx(), m3_min_width)
                # prevent mimimum extension past via problem
                if 0 < rail_width + flop_pin.rx() - (rail_x + 0.5 * m2m3.second_layer_width) < self.m3_width:
                    rail_width = rail_x + 0.5 * m2m3.second_layer_width + self.m3_width - flop_pin.rx()
                self.add_rect("metal3", offset=flop_pin.lr(), width=rail_width)
                self.add_contact_center(contact.m2m3.layer_stack, offset=vector(rail_x, flop_pin.cy()))

    def route_vertical_input_flops(self):

        # connect clk
        module_indices = [0]
        if self.number_of_inputs == 3:
            module_indices.append(2)

        for i in module_indices:
            flop_clk_pin = self.in_inst[i].get_pin("clk")
            clk_pin = self.get_pin("clk")
            self.add_contact(contact.m1m2.layer_stack, offset=vector(clk_pin.lx() + contact.m1m2.height,
                                                                     flop_clk_pin.by()), rotate=90)
            self.add_rect("metal1", offset=vector(clk_pin.lx(), flop_clk_pin.by()),
                          width=flop_clk_pin.lx() - clk_pin.lx())

        # connect dout
        for i in range(self.number_of_inputs):

            self.copy_layout_pin(self.in_inst[i], "din", "flop_in[{}]".format(i))

            flop_index = self.number_of_inputs - i - 1
            for j in range(2):

                pin_name = "dout{}".format("_bar" * (j % 2 == 0))
                out_pin = self.in_inst[flop_index].get_pin(pin_name)
                rail_name = "A{}[{}]".format("bar" * (j % 2 == 0), flop_index)

                rail_x = self.rails[rail_name]

                if self.number_of_inputs == 3 and flop_index == 2:
                    y_offset = self.address_out_y + 5 * self.m3_pitch - j * self.m3_pitch
                    self.add_rect("metal2", offset=vector(out_pin.lx(), y_offset), height=out_pin.by() - y_offset)
                    self.add_contact(contact.m2m3.layer_stack, offset=vector(rail_x - 0.5 * contact.m2m3.width,
                                                                             y_offset))
                else:
                    if self.number_of_inputs == 3:
                        y_offset = self.address_out_y + (abs(1 - i) * 2 + j) * self.m3_pitch
                    else:
                        y_offset = self.address_out_y + (i * 2 + j) * self.m3_pitch
                    self.add_rect("metal2", offset=out_pin.ul(), height=y_offset - out_pin.uy())
                    self.add_contact(contact.m2m3.layer_stack, offset=vector(rail_x - 0.5 * contact.m2m3.width,
                                                                             y_offset + self.m2_width - contact.m2m3.height))

                self.add_rect("metal3", offset=vector(out_pin.lx(), y_offset), width=rail_x - out_pin.lx())

                self.add_contact(contact.m2m3.layer_stack, offset=vector(out_pin.lx() + contact.m2m3.height,
                                                                         y_offset), rotate=90)

    def route_input_inverters(self):
        """
        Route all conections of the inputs inverters [Inputs, outputs, vdd, gnd] 
        """
        for inv_num in range(self.number_of_inputs):
            out_pin = "Abar[{}]".format(inv_num)
            in_pin = "in[{}]".format(inv_num)

            z_pin = self.in_inst[inv_num].get_pin("Z")
            y_offset = z_pin.uy()
            rail_pos = vector(self.rails[out_pin], y_offset)

            self.add_contact_center(m2m3.layer_stack, offset=vector(rail_pos.x, y_offset))
            self.add_contact_center(m2m3.layer_stack, offset=vector(z_pin.cx(), y_offset))
            self.add_rect(METAL3, offset=vector(z_pin.cx(), y_offset - 0.5 * self.m3_width),
                          width=rail_pos.x - z_pin.cx())

            # route input
            inv_in_pos = self.in_inst[inv_num].get_pin("A").lc()
            in_pos = vector(self.rails[in_pin], inv_in_pos.y)
            self.add_path("metal1", [in_pos, inv_in_pos])
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=in_pos,
                                rotate=0)

    def route_nand_to_rails(self):
        # This 2D array defines the connection mapping 
        nand_input_line_combination = self.get_nand_input_line_combination()
        for k in range(self.number_of_outputs):
            # create x offset list         
            index_lst = nand_input_line_combination[k]
            if self.negate:
                index_lst = [x.replace("A[", "Abar2[").replace("Abar[", "A[").
                                 replace("Abar2[", "Abar[") for x in index_lst]

            if self.number_of_inputs == 2:
                gate_lst = ["A", "B"]
            else:
                gate_lst = ["A", "B", "C"]

            # this will connect pins A,B or A,B,C
            max_rail = max(self.rails.values())
            via_space = self.get_line_end_space(METAL2)
            via_x = max_rail + 0.5 * self.m2_width + via_space + 0.5 * contact.m1m2.first_layer_height
            via_x = max(via_x, max_rail + 0.5 * m1m2.w_2 + via_space + 0.5 * m1m2.h_2)
            for rail_pin, gate_pin_name in zip(index_lst, gate_lst):
                gate_pin = self.nand_inst[k].get_pin(gate_pin_name)
                pin_pos = gate_pin.lc()
                rail_pos = vector(self.rails[rail_pin], pin_pos.y)

                if gate_pin_name == "A":
                    self.add_cross_contact_center(cross_m1m2, offset=rail_pos, rotate=True)
                    self.add_rect(METAL1, offset=vector(rail_pos.x, rail_pos.y - 0.5 * self.m1_width),
                                  width=gate_pin.lx() - rail_pos.x)
                else:
                    via_space = 0.5 * m1m2.h_2 + self.get_space(METAL2) + 0.5 * m1m2.h_2
                    if k % 2 == 0:
                        via_space *= -1
                        max_func = min
                    else:
                        max_func = max
                    if gate_pin_name == "B":
                        a_pin = self.nand_inst[k].get_pin("A")
                        via_y = max_func(a_pin.cy() + via_space, gate_pin.cy())
                    else:
                        b_pin = self.nand_inst[k].get_pin("B")
                        via_y = max_func(b_pin.cy() + via_space, gate_pin.cy())
                    self.add_cross_contact_center(cross_m1m2, offset=vector(rail_pos.x, via_y),
                                                  rotate=True)
                    via_offset = vector(via_x, via_y)
                    self.add_path("metal1", [vector(rail_pos.x, via_y), vector(via_x, via_y)])
                    self.add_via_center(layers=m1m2.layer_stack, offset=via_offset, rotate=90)
                    m2_end = gate_pin.cx() + 0.5 * m1m2.w_2
                    self.add_path("metal2", [via_offset, vector(m2_end, via_y)])
                    if k % 2 == 0:
                        y_offset = rail_pos.y - 0.5 * self.m2_width + 0.5 * m1m2.second_layer_height
                    else:
                        y_offset = rail_pos.y + 0.5 * self.m2_width - 0.5 * m1m2.second_layer_height
                    self.add_via_center(layers=m1m2.layer_stack,
                                        offset=vector(gate_pin.cx(), y_offset), rotate=0)

    def route_vdd_gnd(self):
        """ Add a pin for each row of vdd/gnd which are must-connects next level up. """

        for num in range(0, self.number_of_outputs):
            # this will result in duplicate polygons for rails, but who cares

            # use the inverter offset even though it will be the nand's too

            vdd_x_start = gnd_x_start = 0

            # route vdd
            vdd_pin = self.nand_inst[num].get_pin("vdd")
            if hasattr(OPTS, 'separate_vdd') and OPTS.separate_vdd and num > len(self.in_inst):
                vdd_x_start = vdd_pin.lx()

            if self.vertical_flops:
                vdd_x_start = vdd_pin.lx()
                gnd_x_start = vdd_pin.lx()

            if num == self.number_of_outputs - 1 and not self.route_top_rail:
                vdd_x_start = vdd_pin.lx()
            self.add_layout_pin(text="vdd",
                                height=self.rail_height,
                                layer="metal1",
                                offset=vector(vdd_x_start, vdd_pin.by()),
                                width=self.inv_inst[num].rx() - vdd_x_start)

            # route gnd
            gnd_offset = vector(gnd_x_start, self.nand_inst[num].get_pin("gnd").by())
            self.add_layout_pin(text="gnd",
                                layer="metal1",
                                height=self.rail_height,
                                offset=gnd_offset,
                                width=self.inv_inst[num].rx() - gnd_x_start)

        if self.vertical_flops:
            self.connect_flops_vdd_gnd()

    def connect_flops_vdd_gnd(self):
        self.add_dummy_poly(self.flop, self.in_inst[:2], 1, from_gds=True)
        if self.number_of_inputs == 3:
            self.add_dummy_poly(self.flop, [self.in_inst[-1]], 1, from_gds=True)
        self.connect_nwells()
        x_offset = self.power_rail_x
        for pin_name in ["vdd", "gnd"]:
            module_pins = self.get_pins(pin_name)
            for j in range(2):
                if j == 0:
                    flop_pins = self.in_inst[-2].get_pins(pin_name)
                else:
                    flop_pins = self.in_inst[-1].get_pins(pin_name)

                for flop_pin in flop_pins:
                    closest_pin = min(module_pins, key=lambda x: abs(x.cy() - flop_pin.cy()))
                    self.add_rect("metal1", offset=vector(x_offset, closest_pin.by()),
                                  width=closest_pin.lx() - x_offset, height=closest_pin.height())
                    self.add_rect("metal1", offset=vector(x_offset, closest_pin.cy()), width=closest_pin.height(),
                                  height=flop_pin.cy() - closest_pin.cy())
                    self.add_rect("metal1", offset=flop_pin.lr(), width=x_offset + closest_pin.height() - flop_pin.rx(),
                                  height=flop_pin.height())

    def connect_nwells(self):
        flop_nwells = self.flop.get_gds_layer_rects("nwell")
        nand_well = self.nand.get_layer_shapes("nwell")[0]
        nand_nwells = []
        for i in range(int(len(self.nand_inst) / 2)):
            y_offset = i * 2 * self.nand.height
            if i < 1:
                well_height = nand_well.height
                bot = y_offset - (nand_well.uy() - self.nand.height)
            else:
                well_height = 2 * (self.nand.height - nand_well.by())
                bot = y_offset - 0.5 * well_height
            nand_nwells.append((bot, bot + well_height))

        min_well_width = drc["minwidth_well"]
        start_x = self.in_inst[-1].rx()
        end_x = self.nand_inst[0].lx()
        mid_x = 0.5 * (start_x + end_x)
        left_x = mid_x - 0.5 * min_well_width
        right_x = mid_x + 0.5 * min_well_width

        for i in range(1 + int(self.number_of_inputs == 3)):
            for flop_well in flop_nwells:
                # find closest
                if i == 0:
                    y_offset = flop_well.by() + self.in_inst[0].by()
                else:
                    y_offset = self.in_inst[-1].uy() - flop_well.uy()

                closest_nand_well = min(nand_nwells, key=lambda x: abs(x[0] - y_offset))
                self.add_rect("nwell", offset=vector(start_x, y_offset), width=left_x - start_x,
                              height=flop_well.height)

                self.add_rect("nwell", offset=vector(right_x, closest_nand_well[0]),
                              width=end_x - right_x, height=closest_nand_well[1] - closest_nand_well[0])
                bot = min(y_offset, closest_nand_well[0])
                top = max(y_offset + flop_well.height, closest_nand_well[1])

                self.add_rect("nwell", offset=vector(left_x, bot), width=right_x - left_x, height=top - bot)

    def join_inverter_nand_implants(self, row):
        """Join body tap implants to prevent implant enclose active DRC errors
        Assumes that the output inverter includes body contacts
        """
        if not self.implant_enclose_poly:  # implant enclose active already satisfied
            return
        inv_inst = self.inv_inst[row]
        nand_inst = self.nand_inst[row]

        nand_right = round_g(nand_inst.rx())
        inv_left = round_g(inv_inst.lx())

        for layer in [NIMP, PIMP]:
            right_rects = [x for x in inv_inst.get_layer_shapes(layer, recursive=True)
                           if round_g(x.lx() <= inv_left)]
            for right_rect in right_rects:

                if (right_rect.uy() >= nand_inst.uy() or
                        right_rect.by() <= nand_inst.by()):
                    left_layer = NIMP if layer == PIMP else PIMP
                else:
                    left_layer = layer

                left_rects = nand_inst.get_layer_shapes(left_layer, recursive=True)
                left_rects = [x for x in left_rects if round_g(x.rx()) >= nand_right]
                if not left_rects:
                    continue
                left_rect = min(left_rects, key=lambda x: abs(x.cy() - right_rect.cy()))

                if left_layer == layer:
                    left_x = left_rect.rx()
                else:
                    left_x = left_rect.lx()
                right_x = right_rect.lx()
                if round_g(right_x) > round_g(left_x):
                    self.add_rect(left_layer, vector(left_x, right_rect.by()),
                                  width=right_x - left_x, height=right_rect.height)

    def get_nand_input_line_combination(self):
        raise NotImplementedError
