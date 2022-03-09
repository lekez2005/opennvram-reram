import debug
from base import utils
from base.contact import m2m3, m1m2, m3m4, contact
from base.contact_full_stack import ContactFullStack
from base.vector import vector
from base.well_implant_fills import get_default_fill_layers
from globals import OPTS
from modules.baseline_bank import BaselineBank
from modules.buffer_stage import BufferStage
from pgates.pgate import pgate
from tech import drc, power_grid_layers


class InternalDecoderBank(BaselineBank):
    control_buffers = control_buffers_inst = data_in_flops_inst = write_driver_array_inst = None
    sense_amp_array_inst = None

    external_vdds = ["vdd_buffers", "vdd_data_flops", "vdd_wordline"]

    def compute_sizes(self):
        super().compute_sizes()
        # Number of control lines in the bus
        self.num_control_lines = 6
        # The order of the control signals on the control bus:
        self.input_control_signals = ["clk_buf", "tri_en", "w_en", "s_en"]
        self.control_signals = list(map(lambda x: self.prefix + x,
                                        ["s_en", "clk_bar", "clk_buf", "tri_en_bar", "tri_en", "w_en"]))

        # Overall central bus gap. It includes all the column mux lines,
        # control lines, address flop to decoder lines and a GND power rail in M2
        # 1.5 pitches on the right on the right of the control lines for vias (e.g. column mux addr lines)
        self.start_of_right_central_bus = -self.m2_pitch * (self.num_control_lines + 1.5)
        # one pitch on the right on the addr lines and one on the right of the gnd rail

        self.gnd_x_offset = self.start_of_right_central_bus - self.gnd_rail_width - self.m2_pitch

        self.start_of_left_central_bus = self.gnd_x_offset - self.m2_pitch * (self.num_addr_lines + 1)
        # add a pitch on each end and around the gnd rail
        self.overall_central_bus_width = - self.start_of_left_central_bus + self.m2_width

    def create_modules(self):
        super().create_modules()
        self.m9m10 = ContactFullStack(start_layer=8, stop_layer=-1, centralize=False)

    def add_pins(self):
        """ Adding pins for Bank module"""
        for i in range(self.word_size):
            self.add_pin("DATA[{0}]".format(i))
            self.add_pin("MASK[{0}]".format(i))
        for i in range(self.addr_size):
            self.add_pin("ADDR[{0}]".format(i))

        if self.mirror_sense_amp:
            control_pins = ["bank_sel", "read", "clk", "vdd", "gnd"]
        else:
            control_pins = ["bank_sel", "read", "clk", "sense_trig", "vdd", "gnd"]
        for pin in control_pins:
            self.add_pin(pin)

        if self.mirror_sense_amp and OPTS.sense_trigger_delay > 0:
            self.add_pin("sense_trig")

    def calculate_dimensions(self):
        self.width = self.bitcell_array_inst.rx() - self.row_decoder_inst.lx()
        self.height = self.row_decoder_inst.uy() - min(self.row_decoder_inst.by(), self.control_buffers_inst.by())

    def add_modules(self):
        self.add_control_buffers()
        self.add_read_flop()

        self.add_tri_gate_array()
        self.add_data_mask_flops()
        self.add_write_driver_array()
        self.add_sense_amp_array()
        self.add_precharge_array()
        self.add_bitcell_array()

        self.add_control_rails()

        self.add_wordline_driver()
        self.add_row_decoder()

        self.add_vdd_gnd_rails()

    def route_layout(self):
        self.connect_buffer_rails()
        self.route_control_buffers()
        self.route_read_buf()
        self.route_precharge()
        self.route_sense_amp()
        self.route_bitcell()
        self.route_write_driver()
        self.route_flops()
        self.route_tri_gate()
        self.route_wordline_driver()

        self.route_decoder()
        self.route_wordline_in()

        self.calculate_rail_vias()  # horizontal rail vias

        self.add_decoder_power_vias()
        self.add_right_rails_vias()

        self.route_body_tap_supplies()
        self.route_control_buffers_power_to_flop_power()

    def add_control_buffers(self):
        offset = vector(self.control_buffers.width, self.logic_buffers_bottom)
        self.control_buffers_inst = self.add_inst("control_buffers", mod=self.control_buffers,
                                                  offset=offset, mirror="MY")
        self.connect_control_buffers()

    def connect_control_buffers(self):
        vdd_name = "vdd_buffers" if OPTS.separate_vdd else "vdd"
        if self.mirror_sense_amp:
            connections = ["bank_sel", "read_buf", "clk", "clk_buf", "clk_bar", "wordline_en", "precharge_en_bar",
                           "write_en", "write_en_bar",
                           "sense_en", "sense_en_bar", vdd_name, "gnd"]
            if OPTS.sense_trigger_delay > 0:
                connections.append("sense_trig")
            self.connect_inst(connections)
        else:
            if OPTS.baseline:

                extra_pins = ["tri_en", "tri_en_bar"]
            else:
                extra_pins = ["sense_precharge_bar"]
            self.connect_inst(["bank_sel", "read_buf", "clk", "sense_trig", "clk_buf", "clk_bar", "wordline_en",
                               "precharge_en_bar", "write_en", "write_en_bar",
                               "sense_en"] + extra_pins + ["sample_en_bar", vdd_name, "gnd"])

    def get_enable_names(self):
        """For decoder enables"""
        return []

    def get_right_vdd_offset(self):
        return max(self.control_buffers_inst.rx(), self.bitcell_array_inst.rx(),
                   self.read_buf_inst.rx()) + self.wide_m1_space

    def add_read_flop(self):

        x_offset = self.control_buffers_inst.rx() + self.poly_pitch + self.control_flop.width
        offset = vector(x_offset, self.logic_buffers_bottom + self.control_buffers.height - self.control_flop.height)
        self.add_operation_flop(offset)

        # fill implants between read_buf and logic_buffers
        flop_inverter = self.control_flop.buffer.buffer_invs[-1]
        control_instances = self.control_buffers.insts
        first_control_instance = min(control_instances, key=lambda x: x.lx())

        if isinstance(first_control_instance.mod, pgate):
            control_mod = first_control_instance.mod
            control_mod_offset = 0
        elif isinstance(first_control_instance.mod, BufferStage):
            control_mod = first_control_instance.mod.module_insts[0].mod
            control_mod_offset = first_control_instance.mod.module_insts[0].offset.x
        else:
            control_mod = first_control_instance.mod.logic_inst.mod
            control_mod_offset = first_control_instance.mod.logic_inst.offset.x

        flop_y_offset = self.read_buf_inst.by() + self.control_flop.buffer_inst.by()
        flop_x_offset = (self.read_buf_inst.rx() - self.control_flop.buffer_inst.lx()
                         - self.control_flop.buffer.module_insts[-1].lx())

        control_y_offset = self.control_buffers_inst.by() + first_control_instance.by()
        control_x_offset = (self.control_buffers_inst.rx() - first_control_instance.lx() - control_mod_offset)

        for layer in ["pimplant", "nimplant"]:
            flop_rect = self.rightmost_largest_rect(flop_inverter.get_layer_shapes(layer))
            control_rect = self.rightmost_largest_rect(control_mod.get_layer_shapes(layer))

            bottom = max(flop_rect.by() + flop_y_offset, control_rect.by() + control_y_offset)
            top = min(flop_rect.uy() + flop_y_offset, control_rect.uy() + control_y_offset)

            left = control_x_offset - control_rect.lx()
            right = flop_x_offset - flop_rect.rx()
            self.add_rect(layer, offset=vector(left, bottom), width=right - left, height=top - bottom)

    def add_row_decoder(self):
        """  Add the hierarchical row decoder  """

        enable_rail_space = len(self.get_enable_names()) * self.control_rail_pitch

        x_offset = min((self.wordline_driver_inst.lx() - self.decoder.row_decoder_width),
                       self.leftmost_rail.lx() - self.m2_pitch - self.decoder.width - enable_rail_space)
        offset = vector(x_offset, self.bitcell_array_inst.by() - self.decoder.predecoder_height)

        self.row_decoder_inst = self.add_inst(name="right_row_decoder", mod=self.decoder, offset=offset)

        temp = []
        for i in range(self.row_addr_size):
            temp.append("ADDR[{0}]".format(i))
        for j in range(self.num_rows):
            temp.append("dec_out[{0}]".format(j))
        vdd_name = "vdd_wordline" if OPTS.separate_vdd else "vdd"
        temp.extend([self.get_decoder_clk(), vdd_name, "gnd"])
        self.connect_inst(temp)

        self.min_point = min(self.control_buffers_inst.by(), self.row_decoder_inst.by())
        self.top = self.bitcell_array_inst.uy()

    def get_mask_flops_y_offset(self):
        return self.tri_gate_array_inst.uy()

    def get_precharge_mirror(self):
        return "MX"

    def get_data_flops_y_offset(self):
        gnd_pins = self.msf_mask_in.get_pins("gnd")
        top_mask_gnd_pin = max(gnd_pins, key=lambda x: x.uy())

        bottom_data_gnd_pin = min(self.msf_data_in.get_pins("gnd"), key=lambda x: x.uy())

        implant_space = drc["parallel_implant_to_implant"]

        return self.mask_in_flops_inst.by() + implant_space + top_mask_gnd_pin.uy() - bottom_data_gnd_pin.by()

    def get_precharge_y(self):
        return self.sense_amp_array_inst.uy() + self.precharge_array.height

    def add_operation_flop(self, offset):
        vdd_name = "vdd_buffers" if OPTS.separate_vdd else "vdd"
        self.read_buf_inst = self.add_inst("read_buf", mod=self.control_flop, offset=offset, mirror="MY")
        self.connect_inst(["read", "clk", "read_buf", vdd_name, "gnd"])

        self.copy_layout_pin(self.read_buf_inst, "din", "read")

    def add_vdd_gnd_rails(self):
        self.height = self.top - self.min_point

        right_vdd_offset = self.get_right_vdd_offset()
        right_gnd_offset = right_vdd_offset + self.vdd_rail_width + self.wide_m1_space
        left_vdd_offset = self.row_decoder_inst.lx() - self.wide_m1_space - self.vdd_rail_width
        left_gnd_offset = left_vdd_offset - self.wide_m1_space - self.vdd_rail_width

        offsets = [self.mid_gnd_offset, right_gnd_offset, self.mid_vdd_offset, right_vdd_offset,
                   left_vdd_offset, left_gnd_offset]
        left_vdd_name = "vdd_wordline" if OPTS.separate_vdd else "vdd"
        pin_names = ["gnd", "gnd", "vdd", "vdd", left_vdd_name, "gnd"]
        pin_layers = self.get_vdd_gnd_rail_layers()
        attribute_names = ["mid_gnd", "right_gnd", "mid_vdd", "right_vdd", "left_vdd", "left_gnd"]
        for i in range(6):
            pin = self.add_layout_pin(pin_names[i], pin_layers[i],
                                      vector(offsets[i], self.min_point), height=self.height,
                                      width=self.vdd_rail_width)
            setattr(self, attribute_names[i], pin)
        # for IDE assistance
        self.mid_gnd = getattr(self, "mid_gnd")
        self.right_gnd = getattr(self, "right_gnd")
        self.mid_vdd = getattr(self, "mid_vdd")
        self.right_vdd = getattr(self, "right_vdd")
        self.left_vdd = getattr(self, "left_vdd")
        self.left_gnd = getattr(self, "left_gnd")

    def route_control_buffers(self):
        """Route control buffers and flops power pins, copy control_buffers pins"""
        super().route_control_buffers()
        # vdd
        vdd_name = "vdd_buffers" if OPTS.separate_vdd else "vdd"

        if OPTS.separate_vdd:
            self.copy_layout_pin(self.control_buffers_inst, "vdd", vdd_name)
        else:
            self.route_vdd_pin(self.control_buffers_inst.get_pin("vdd"))

        # gnd
        read_flop_gnd = self.read_buf_inst.get_pin("gnd")
        control_buffers_gnd = self.control_buffers_inst.get_pin("gnd")

        # join grounds
        # control_buffers gnd to read gnd
        offset = vector(control_buffers_gnd.rx() - read_flop_gnd.height(), read_flop_gnd.by())
        self.add_rect("metal1", offset=offset, width=read_flop_gnd.lx() - offset.x, height=read_flop_gnd.height())
        self.add_rect("metal1", offset=offset, width=read_flop_gnd.height(),
                      height=control_buffers_gnd.by() - read_flop_gnd.by())

        # control_buffers to rail
        self.add_rect("metal1", offset=vector(self.mid_gnd.lx(), control_buffers_gnd.by()),
                      width=control_buffers_gnd.lx() - self.mid_gnd.lx(), height=control_buffers_gnd.height())
        self.add_power_via(control_buffers_gnd, self.mid_gnd, via_rotate=90)

        # read flop gnd to rail
        self.add_rect("metal1", offset=read_flop_gnd.lr(), height=read_flop_gnd.height(),
                      width=self.right_gnd.rx() - read_flop_gnd.rx())

    def route_control_buffers_power_to_flop_power(self):
        """Join control buffers vdd and gnd with other peripherals vdd and gnd at the bitcell_tap locations"""
        obstructions = [(self.control_buffers_inst.lx() - self.wide_m1_space,
                         self.read_buf_inst.rx() + self.wide_m1_space)]
        if hasattr(self, "max_right_buffer_x"):
            obstructions.append((self.min_right_buffer_x - self.wide_m1_space,
                                 self.max_right_buffer_x + self.wide_m1_space))

        rails = utils.get_libcell_pins(["vdd", "gnd"], OPTS.body_tap)
        tap_width = self.bitcell_array.body_tap.width
        vdd_rail = rails["vdd"][0]
        gnd_rail = rails["gnd"][0]

        def filter_func(offset):
            for obstruction in obstructions:
                if obstruction[0] <= offset <= obstruction[1] or offset <= obstruction[0] <= offset + tap_width:
                    return False
            return True

        tap_offsets = [self.bitcell_array_inst.lx() + x for x in self.bitcell_array.tap_offsets]
        tap_offsets = list(filter(filter_func, tap_offsets))
        vdd_pin = self.control_buffers.get_pin("vdd")
        gnd_pin = self.control_buffers.get_pin("gnd")

        via_size = [2, 1]
        dummy_via = contact(m1m2.layer_stack, dimensions=via_size)
        fill_width = vdd_rail.width()
        min_area = drc["minarea_metal1_contact"]

        fill_height = max(utils.ceil(min_area / fill_width), dummy_via.width)

        for tap_offset in tap_offsets:
            for (pin, rail) in [(vdd_pin, vdd_rail), (gnd_pin, gnd_rail)]:
                x_offset = rail.lx() + tap_offset
                self.add_rect("metal4", offset=vector(x_offset, pin.by()),
                              height=self.data_in_flops_inst.by() - pin.by(), width=rail.width())
                if rail == vdd_rail:
                    y_offset = pin.uy() - fill_height
                else:
                    y_offset = pin.by()
                for via in [m1m2, m2m3, m3m4]:
                    self.add_contact(via.layer_stack,
                                     offset=vector(x_offset + 0.5 * (rail.width() + dummy_via.height),
                                                   y_offset), size=via_size, rotate=90)

    def route_read_buf(self):
        # route clk in from control_buffers clk in
        flop_clk_pin = self.read_buf_inst.get_pin("clk")
        control_clk_pin = self.control_buffers_inst.get_pin("clk")
        read_pin = self.read_buf_inst.get_pin("din")

        x_offset = max(flop_clk_pin.rx() + m1m2.second_layer_height - self.m2_width,
                       read_pin.rx() + self.line_end_space)

        self.add_rect("metal3", offset=control_clk_pin.lr(), width=x_offset - control_clk_pin.rx())
        self.add_contact(m2m3.layer_stack, offset=vector(x_offset, control_clk_pin.by()))

        self.add_rect("metal2", offset=vector(x_offset, control_clk_pin.by()),
                      height=flop_clk_pin.uy() - control_clk_pin.by())
        self.add_contact(m1m2.layer_stack, offset=vector(x_offset + self.m2_width, flop_clk_pin.by()),
                         rotate=90)
        self.add_rect("metal1", offset=flop_clk_pin.lr(), width=x_offset - flop_clk_pin.rx())

        # read output to control buffers read
        read_out = self.read_buf_inst.get_pin("dout")
        read_in = self.control_buffers_inst.get_pin("read")
        offset = read_in.lr()
        self.add_rect("metal3", offset=offset, width=read_out.lx() - offset.x)
        self.add_contact(m2m3.layer_stack, offset=vector(read_out.rx(), offset.y), rotate=90)
        self.add_rect("metal2", offset=vector(read_out.lx(), offset.y), height=read_out.by() - offset.y)

    def route_sense_amp_common(self):

        for col in range(self.num_cols):
            # route bitlines
            for pin_name in ["bl", "br"]:
                bitcell_pin = self.bitcell_array_inst.get_pin(pin_name + "[{}]".format(col))
                sense_pin = self.sense_amp_array_inst.get_pin(pin_name + "[{}]".format(col))
                precharge_pin = self.precharge_array_inst.get_pin(pin_name + "[{}]".format(col))

                self.add_rect("metal4", offset=sense_pin.ul(), height=precharge_pin.uy() - sense_pin.uy())
                offset = precharge_pin.ul() - vector(0, m2m3.second_layer_height)
                self.add_contact(m2m3.layer_stack, offset=offset)
                self.add_contact(m3m4.layer_stack, offset=offset)
                via_extension = drc["wide_metal_via_extension"]
                if pin_name == "bl":
                    x_offset = bitcell_pin.lx() - via_extension
                else:
                    x_offset = bitcell_pin.rx() - self.fill_width + via_extension
                self.add_rect("metal3", offset=vector(x_offset, precharge_pin.uy() - self.fill_height),
                              width=self.fill_width, height=self.fill_height)
                self.add_rect("metal2", offset=precharge_pin.ul(), height=bitcell_pin.by() - precharge_pin.uy())
        # route ground
        if self.mirror_sense_amp:
            for pin in self.sense_amp_array_inst.get_pins("gnd"):
                self.route_gnd_pin(pin)

    def route_sense_amp(self):
        debug.info(1, "Route sense amp")
        self.route_sense_amp_common()

        # route vdd

        if self.mirror_sense_amp:
            for pin in self.sense_amp_array_inst.get_pins("vdd"):
                self.route_vdd_pin(pin, via_rotate=0)
        else:
            vdd_pins = self.sense_amp_array_inst.get_pins("vdd")
            pin = max(vdd_pins, key=lambda x: x.uy())
            self.add_rect("metal1", offset=vector(self.mid_vdd.lx(), pin.by()),
                          width=self.right_vdd.rx() - self.mid_vdd.lx(), height=pin.height())

            self.add_contact(m1m2.layer_stack, offset=vector(self.right_vdd.lx() + 0.2, pin.by()),
                             size=[2, 1], rotate=90)
            self.add_contact(m1m2.layer_stack, offset=vector(self.mid_vdd.lx() + 0.2, pin.by()),
                             size=[2, 1], rotate=90)

    def route_write_driver(self):
        """Route mask, data and data_bar from flops to write driver"""
        debug.info(1, "Route write driver")
        for col in range(0, self.word_size):
            # route data_bar
            flop_pin = self.data_in_flops_inst.get_pin("dout_bar[{}]".format(col))
            driver_pin = self.write_driver_array_inst.get_pin("data_bar[{}]".format(col))
            self.add_rect("metal2", offset=flop_pin.ul(), height=driver_pin.by() - flop_pin.uy())
            self.add_contact(m2m3.layer_stack, offset=driver_pin.ll() - vector(0, m2m3.second_layer_height))

            # route data
            flop_pin = self.data_in_flops_inst.get_pin("dout[{}]".format(col))
            driver_pin = self.write_driver_array_inst.get_pin("data[{}]".format(col))
            offset = vector(driver_pin.lx(), flop_pin.uy() - self.m2_width)
            self.add_rect("metal2", offset=offset, width=flop_pin.rx() - offset.x)
            self.add_contact(m2m3.layer_stack, offset=offset)
            self.add_rect("metal3", offset=offset, height=driver_pin.by() - offset.y)

            # route mask_bar
            flop_pin = self.mask_in_flops_inst.get_pin("dout_bar[{}]".format(col))
            driver_pin = self.get_write_driver_mask_in(col)

            self.add_contact(m2m3.layer_stack, offset=flop_pin.ul())
            x_offset = driver_pin.rx() + self.parallel_line_space

            data_in = self.data_in_flops_inst.get_pin("din[{}]".format(col))
            y_bend = data_in.by() + m2m3.height + self.line_end_space

            self.add_rect("metal3", offset=flop_pin.ul(), height=y_bend - flop_pin.uy())
            self.add_rect("metal3", offset=vector(x_offset, y_bend), width=flop_pin.rx() - x_offset)

            self.add_rect("metal3", offset=vector(x_offset, y_bend), height=driver_pin.by() - y_bend)
            self.add_rect("metal3", offset=driver_pin.ll(), width=x_offset + self.m3_width - driver_pin.lx())

        self.route_all_instance_power(self.write_driver_array_inst)

    def route_flops(self):
        debug.info(1, "Route mask and data flops")
        if OPTS.separate_vdd:
            self.copy_layout_pin(self.data_in_flops_inst, "vdd", "vdd_data_flops")
            self.copy_layout_pin(self.mask_in_flops_inst, "vdd", "vdd_data_flops")
        else:
            for pin in self.data_in_flops_inst.get_pins("vdd") + self.mask_in_flops_inst.get_pins("vdd"):
                self.route_vdd_pin(pin)
        for pin in self.mask_in_flops_inst.get_pins("gnd"):
            self.route_gnd_pin(pin, via_rotate=0)

        data_in_gnds = list(sorted(self.data_in_flops_inst.get_pins("gnd"), key=lambda x: x.by()))
        self.route_gnd_pin(data_in_gnds[0], via_rotate=0)
        self.route_gnd_pin(data_in_gnds[1], via_rotate=90)

        for col in range(self.num_cols):
            self.copy_layout_pin(self.mask_in_flops_inst, "din[{}]".format(col), "MASK[{}]".format(col))

    def get_sense_amp_dout(self):
        return "data"

    def route_tri_gate(self):
        debug.info(1, "Route tri state array")
        self.route_vdd_pin(self.tri_gate_array_inst.get_pin("vdd"))
        self.route_gnd_pin(self.tri_gate_array_inst.get_pin("gnd"))

        mid_flop_y = 0.5 * (self.mask_in_flops_inst.by() + self.mask_in_flops_inst.uy())

        for col in range(self.num_cols):
            # route tri-gate output to data flop
            tri_gate_out = self.tri_gate_array_inst.get_pin("out[{}]".format(col))
            flop_in = self.data_in_flops_inst.get_pin("din[{}]".format(col))

            self.add_contact(m2m3.layer_stack, offset=flop_in.ll())

            # bypass mask din overlap

            x_offset = tri_gate_out.rx() + self.wide_m1_space
            self.add_rect("metal3", offset=vector(flop_in.lx(), mid_flop_y), height=flop_in.by() - mid_flop_y)
            self.add_rect("metal3", offset=vector(flop_in.lx(), mid_flop_y),
                          width=x_offset + self.m3_width - flop_in.lx())

            y_offset = tri_gate_out.uy() - self.m3_width

            self.add_rect("metal3", offset=vector(x_offset, y_offset), height=mid_flop_y - y_offset)
            self.add_rect("metal3", offset=vector(tri_gate_out.lx(), y_offset), width=x_offset - tri_gate_out.lx())
            self.add_contact(m2m3.layer_stack, offset=tri_gate_out.ul() - vector(0, m2m3.second_layer_height))

            self.copy_layout_pin(self.tri_gate_array_inst, "out[{}]".format(col), "DATA[{}]".format(col))

            # route sense amp output to tri-gate input
            sense_pin = self.sense_amp_array_inst.get_pin(self.get_sense_amp_dout() + "[{}]".format(col))
            tri_gate_in = self.tri_gate_array_inst.get_pin("in[{}]".format(col))
            self.add_rect("metal4", offset=vector(tri_gate_in.lx(), sense_pin.by()),
                          width=sense_pin.rx() - tri_gate_in.lx())
            self.add_rect("metal4", offset=tri_gate_in.ul(), height=sense_pin.by() - tri_gate_in.uy() + self.m4_width)
            self.add_contact(m2m3.layer_stack, offset=tri_gate_in.ul() - vector(0, m2m3.second_layer_height))
            self.add_contact(m3m4.layer_stack, offset=tri_gate_in.ul() - vector(0, m3m4.second_layer_height))
            self.add_rect("metal3",
                          offset=vector(tri_gate_in.rx() - self.fill_width, tri_gate_in.uy() - self.fill_height),
                          width=self.fill_width, height=self.fill_height)

    def get_wordline_power_x_offset(self):
        return self.row_decoder_inst.rx()

    def route_decoder(self):
        self.route_right_decoder_power()
        self.join_right_decoder_nwell()
        # route clk
        clk_rail = self.clk_buf_rail
        clk_pins = self.row_decoder_inst.get_pins("clk")
        # find closest
        target_y = clk_rail.by() + m2m3.second_layer_height
        clk_pin = min(clk_pins, key=lambda x: min(abs(target_y - x.by() + m2m3.height),
                                                  abs(target_y - x.uy() - m2m3.height)))

        self.add_rect("metal3", offset=vector(clk_pin.lx(), target_y), width=clk_rail.rx() - clk_pin.lx())

        if target_y < clk_pin.by():
            self.add_rect("metal2", offset=vector(clk_pin.lx(), target_y), height=clk_pin.by() - target_y)

        # find closest vdd-gnd pin to add via, otherwise via in between cell may clash with decoder address pin via
        y_offset = clk_rail.by() + m2m3.second_layer_height
        vdd_gnd = self.row_decoder_inst.get_pins("vdd") + self.row_decoder_inst.get_pins("gnd")
        valid_vdd_gnd = filter(lambda x: x.by() > y_offset + self.line_end_space, vdd_gnd)
        closest_vdd_gnd = min(valid_vdd_gnd, key=lambda x: x.by() - y_offset)

        self.add_contact(m2m3.layer_stack, offset=vector(clk_pin.lx(), closest_vdd_gnd.by()))
        self.add_rect("metal3", offset=vector(clk_pin.lx(), target_y),
                      height=closest_vdd_gnd.by() - target_y)

        if closest_vdd_gnd.cy() - 0.5 * m2m3.height > clk_pin.uy():
            self.add_rect("metal2", offset=clk_pin.ul(), height=closest_vdd_gnd.cy() - clk_pin.uy())

        # copy address ports
        for i in range(self.addr_size):
            self.copy_layout_pin(self.row_decoder_inst, "A[{}]".format(i), "ADDR[{}]".format(i))

    def route_wordline_in(self):
        # route decoder in
        for row in range(self.num_rows):
            decoder_out = self.row_decoder_inst.get_pin("decode[{}]".format(row))
            wl_in = self.wordline_driver_inst.get_pin("in[{}]".format(row))

            self.add_contact(m2m3.layer_stack, offset=vector(decoder_out.ul() - vector(0, m2m3.second_layer_height)))
            x_offset = wl_in.cx() + 0.5 * self.m3_width
            self.add_rect("metal3", offset=decoder_out.ul(), width=x_offset - decoder_out.lx())
            self.add_rect("metal3", offset=vector(x_offset - self.m3_width, wl_in.cy()),
                          height=decoder_out.uy() - wl_in.cy())
            self.add_contact_center(m2m3.layer_stack, wl_in.center())
            self.add_contact_center(m1m2.layer_stack, wl_in.center())

            self.add_rect_center("metal2", offset=wl_in.center(), width=self.fill_width, height=self.fill_height)

    def route_right_decoder_power(self):
        for pin in self.row_decoder_inst.get_pins("gnd"):
            self.add_rect("metal1", offset=vector(self.left_gnd.lx(), pin.by()),
                          width=pin.lx() - self.left_gnd.lx(), height=pin.height())
            if self.left_gnd.layer == "metal2":
                self.add_power_via(pin, self.left_gnd)

        for pin in self.row_decoder_inst.get_pins("vdd"):  # ensure decoder vdd is connected to wordline driver's
            if pin.uy() > self.wordline_driver_inst.by():
                pin_right = self.wordline_driver_inst.lx()
            else:
                pin_right = pin.lx()
            self.add_rect("metal1", offset=vector(self.left_vdd.lx(), pin.by()),
                          width=pin_right - self.left_vdd.lx(), height=pin.height())
            self.add_power_via(pin, self.left_vdd)

    def join_right_decoder_nwell(self):

        layers, purposes = get_default_fill_layers()

        decoder_inverter = self.decoder.inv_inst[-1].mod
        driver_nand = self.wordline_driver.logic_buffer.logic_mod

        row_decoder_right = self.row_decoder_inst.lx() + self.decoder.row_decoder_width
        x_shift = self.wordline_driver.buffer_insts[-1].lx()

        for i in range(3):
            decoder_rect = max(decoder_inverter.get_layer_shapes(layers[i], purposes[i]),
                               key=lambda x: x.height)
            logic_rect = max(driver_nand.get_layer_shapes(layers[i], purposes[i]),
                             key=lambda x: x.height)
            top_most = max([decoder_rect, logic_rect], key=lambda x: x.by())
            fill_height = driver_nand.height - top_most.by()
            # extension of rect past top of cell
            rect_y_extension = top_most.uy() - driver_nand.height
            fill_width = self.wordline_driver_inst.lx() - row_decoder_right + x_shift

            for vdd_pin in self.row_decoder_inst.get_pins("vdd"):
                if utils.round_to_grid(vdd_pin.cy()) == utils.round_to_grid(
                        self.wordline_driver_inst.by()):  # first row
                    self.add_rect(layers[i], offset=vector(row_decoder_right, vdd_pin.cy() - rect_y_extension),
                                  width=fill_width, height=top_most.height)
                elif vdd_pin.cy() > self.wordline_driver_inst.by():  # row decoder
                    self.add_rect(layers[i], offset=vector(row_decoder_right, vdd_pin.cy() - fill_height),
                                  width=fill_width, height=2 * fill_height)

    def calculate_rail_vias(self):
        """Calculates positions of power grid rail to M1/M2 vias. Avoids internal metal3 control pins"""
        # need to avoid the metal3 control signals

        via_positions = []

        self.m1mtop = m1mtop = ContactFullStack.m1mtop()
        self.add_mod(m1mtop)
        self.m2mtop = m2mtop = ContactFullStack.m2mtop()
        self.add_mod(m2mtop)

        self.bottom_power_layer = power_grid_layers[0]
        self.top_power_layer = power_grid_layers[1]

        self.grid_rail_height = grid_rail_height = max(m1mtop.first_layer_height, m2mtop.first_layer_height)
        self.grid_rail_width = m1mtop.second_layer_width

        grid_space = drc["power_grid_space"]
        grid_pitch = grid_space + grid_rail_height
        via_space = self.wide_m1_space

        bank_top = self.min_point + self.height

        collisions = list(sorted(self.get_collisions() +
                                 [(self.min_point, self.min_point + 2 * self.wide_m1_space),
                                  (bank_top - grid_pitch, bank_top)],
                                 key=lambda x: x[0]))

        # combine/collapse overlapping collisions
        while True:
            i = 0
            num_overlaps = 0
            num_iterations = len(collisions)
            new_collisions = []
            while i < num_iterations:

                collision = collisions[i]
                if i < num_iterations - 1:
                    next_collision = collisions[i + 1]
                    if next_collision[0] <= collision[1]:
                        collision = (collision[0], max(collision[1], next_collision[1]))
                        num_overlaps += 1
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
                new_collisions.append(collision)
            collisions = new_collisions
            if num_overlaps == 0:
                break

        # calculate via positions
        prev_y = -1.0e100
        for i in range(len(collisions) - 1):
            collision = collisions[i]
            current_y = max(collision[1] + self.wide_m1_space, prev_y + grid_pitch)
            next_collision = collisions[i + 1][0]
            while True:
                via_top = current_y + grid_rail_height
                if via_top > bank_top or via_top + via_space > next_collision:
                    break
                via_positions.append(current_y)
                prev_y = current_y
                current_y += grid_pitch

        self.power_grid_vias = via_positions

    def calculate_body_tap_rails_vias(self):
        self.m4m9 = ContactFullStack(start_layer=3, stop_layer=-2, centralize=False)
        self.m5m9 = ContactFullStack(start_layer=4, stop_layer=-2, centralize=False)

        wide_m10_space = drc["wide_metal10_to_metal10"]

        self.bitcell_power_vias = []
        self.vertical_power_rails_pos = []

        m4_via_width = self.m4m9.first_layer_width

        rails = utils.get_libcell_pins(["vdd", "gnd"], OPTS.body_tap)
        vdd_rail = rails["vdd"][0]
        gnd_rail = rails["gnd"][0]

        collisions = list(sorted(self.bitcell_array.tap_offsets))

        for x_offset in collisions:
            real_x_offset = self.bitcell_array_inst.lx() + x_offset
            vdd_x_offset = real_x_offset + vdd_rail.rx() - m4_via_width
            gnd_x_offset = real_x_offset + gnd_rail.lx()

            self.bitcell_power_vias.append((vdd_x_offset, gnd_x_offset))

        max_x_offset = self.right_gnd.rx() - self.m1mtop.width - wide_m10_space

        grid_collisions = self.bitcell_power_vias + [(self.right_vdd.lx(), self.right_gnd.lx())]

        for i in range(len(grid_collisions) - 1):
            offsets = grid_collisions[i]
            next_offset = grid_collisions[i + 1][0]
            current_offset = offsets[1] + self.m4m9.width + wide_m10_space
            while True:
                rail_right_x = current_offset + self.grid_rail_width
                if rail_right_x > max_x_offset or rail_right_x > next_offset - wide_m10_space:
                    break
                self.vertical_power_rails_pos.append(current_offset)
                current_offset += wide_m10_space + self.grid_rail_width

        # remove first via since it clashes with middle rails
        if self.bitcell_power_vias[-1][0] > max_x_offset - wide_m10_space - self.m4m9.width:
            self.bitcell_power_vias = self.bitcell_power_vias[1:-1]
        else:
            self.bitcell_power_vias = self.bitcell_power_vias[1:]

    def get_body_taps_bottom(self):
        return self.tri_gate_array_inst.by()

    def route_body_tap_supplies(self):
        # TODO fix top layer

        self.calculate_body_tap_rails_vias()

        rails = utils.get_libcell_pins(["vdd", "gnd"], OPTS.body_tap)
        vdd_rail = rails["vdd"][0]
        gnd_rail = rails["gnd"][0]

        for x_offset in self.bitcell_array.tap_offsets:
            # join bitcell body tap power/gnd to bottom module tap power/gnd
            rail_y = self.get_body_taps_bottom()

            rail_height = self.bitcell_array_inst.by() - rail_y

            vdd_rail_x = x_offset + vdd_rail.lx()
            self.add_rect(vdd_rail.layer, offset=vector(vdd_rail_x, rail_y), width=vdd_rail.width(),
                          height=rail_height)

            gnd_rail_x = x_offset + gnd_rail.lx()
            self.add_rect(gnd_rail.layer, offset=vector(gnd_rail_x, rail_y), width=gnd_rail.width(),
                          height=rail_height)

        def get_via(rect):
            if rect.by() < self.bitcell_array_inst.by():
                via_mod = self.m5m9
            else:
                via_mod = self.m4m9
            return via_mod

        dummy_contact = contact(layer_stack=("metal4", "via4", "metal5"), dimensions=[1, 5])

        def connect_m4(via_inst, is_vdd):
            if via_inst.mod == self.m5m9:
                if is_vdd:
                    x_offset = via_inst.lx() + 0.11
                else:
                    x_offset = via_inst.lx()
                self.add_contact(layers=dummy_contact.layer_stack, size=dummy_contact.dimensions,
                                 offset=vector(x_offset, via_inst.by()))

        for vdd_via_x, gnd_via_x in self.bitcell_power_vias:

            # add m4m9 via
            for rect in self.vdd_grid_rects:
                via = get_via(rect)

                via_inst = self.add_inst(via.name, mod=via, offset=vector(vdd_via_x, rect.by()))
                self.connect_inst([])
                connect_m4(via_inst, is_vdd=True)

            for rect in self.gnd_grid_rects:
                via = get_via(rect)
                via_inst = self.add_inst(via.name, mod=via, offset=vector(gnd_via_x, rect.by()))
                self.connect_inst([])
                connect_m4(via_inst, is_vdd=False)

        # add vertical rails across bitcell array
        for i in range(len(self.vertical_power_rails_pos)):
            x_offset = self.vertical_power_rails_pos[i]
            self.add_rect(self.top_power_layer, offset=vector(x_offset, self.min_point),
                          width=self.grid_rail_width, height=self.height)

            if i % 2 == 0:
                for rect in self.vdd_grid_rects:
                    self.add_inst(self.m9m10.name, mod=self.m9m10,
                                  offset=vector(x_offset, rect.by()))
                    self.connect_inst([])
            else:
                for rect in self.gnd_grid_rects:
                    self.add_inst(self.m9m10.name, mod=self.m9m10,
                                  offset=vector(x_offset, rect.by()))
                    self.connect_inst([])

    def add_decoder_power_vias(self):
        self.vdd_grid_rects = []
        self.gnd_grid_rects = []

        # for leftmost rails, power vias might clash with decoder metal3's
        m4m10 = ContactFullStack(start_layer=3, stop_layer=-1, centralize=False)
        max_left_power_y = self.wordline_driver_inst.by() - 3 * self.control_rail_pitch - self.m2mtop.second_layer_height
        for i in range(len(self.power_grid_vias)):
            via_y_offset = self.power_grid_vias[i]
            if i % 2 == 0:  # vdd
                # add vias to top
                via_x = [self.left_vdd.lx(), self.mid_vdd.lx()]
                for j in range(2):
                    if j == 0 and via_y_offset > max_left_power_y:
                        self.add_inst(m4m10.name, m4m10, offset=vector(self.left_vdd.lx(), via_y_offset))
                        self.connect_inst([])
                    else:
                        self.add_inst(self.m2mtop.name, self.m2mtop,
                                      offset=vector(via_x[j] + 0.5 * self.vdd_rail_width, via_y_offset))
                        self.connect_inst([])
                # connect rails horizontally
                if OPTS.separate_vdd:
                    start_x = via_x[1]
                    self.add_rect(self.bottom_power_layer, offset=vector(via_x[0], via_y_offset),
                                  height=self.grid_rail_height, width=self.vertical_power_rail_offsets[1] - via_x[0])
                else:
                    start_x = via_x[0]
                self.vdd_grid_rects.append(self.add_rect(self.bottom_power_layer,
                                                         offset=vector(start_x, via_y_offset),
                                                         height=self.grid_rail_height,
                                                         width=self.right_gnd.rx() - start_x))
            else:  # gnd
                via_x = [self.left_gnd.lx() + 0.5 * self.vdd_rail_width, self.mid_gnd.lx() + 0.5 * self.vdd_rail_width]
                for j in range(2):
                    if j == 0 and via_y_offset > max_left_power_y:
                        self.add_inst(m4m10.name, m4m10, offset=vector(self.left_gnd.lx(), via_y_offset))
                        self.connect_inst([])
                    else:
                        self.add_inst(self.m2mtop.name, self.m2mtop,
                                      offset=vector(via_x[j], self.power_grid_vias[i]))
                        self.connect_inst([])
                self.gnd_grid_rects.append(self.add_rect(self.bottom_power_layer,
                                                         offset=vector(self.left_gnd.lx(), self.power_grid_vias[i]),
                                                         height=self.grid_rail_height,
                                                         width=self.right_gnd.rx() - self.left_gnd.lx()))
        # Add m4 rails along existing m2 rails
        for rail in [self.left_gnd, self.left_vdd]:
            self.add_rect("metal4", offset=vector(rail.lx(), self.min_point), width=rail.width(),
                          height=self.wordline_driver_inst.uy() - self.min_point)
        # add m2-m4 via
        for row in range(self.num_rows):
            y_offset = self.wordline_driver_inst.by() + (row + 0.5) * self.bitcell_array.cell.height
            for x_offset in [self.left_gnd.cx(), self.left_vdd.cx()]:
                self.add_via_center(m2m3.layer_stack, offset=vector(x_offset, y_offset), size=[2, 2])
                self.add_via_center(m3m4.layer_stack, offset=vector(x_offset, y_offset), size=[2, 2])
                if x_offset == self.left_gnd.cx() and row > 0:
                    self.add_via_center(m1m2.layer_stack, offset=vector(x_offset, y_offset), size=[2, 2])

        # add Mtop vdd/gnd rails within decoder
        wide_m10_space = drc["wide_metal10_to_metal10"]
        vdd_x = self.left_vdd.lx() + self.m2mtop.width + wide_m10_space
        gnd_x = vdd_x + self.grid_rail_width + wide_m10_space
        vdd_name = "vdd_wordline" if OPTS.separate_vdd else "vdd"

        self.add_layout_pin(vdd_name, layer=self.top_power_layer, offset=vector(vdd_x, self.min_point),
                            width=self.grid_rail_width, height=self.height)

        # avoid clash with middle vdd vias
        if gnd_x + self.grid_rail_width + wide_m10_space < self.mid_vdd.cx() - 0.5 * self.m2mtop.width:
            self.add_layout_pin("gnd", layer=self.top_power_layer, offset=vector(gnd_x, self.min_point),
                                width=self.grid_rail_width, height=self.height)

            for rect in self.gnd_grid_rects:
                self.add_inst(self.m9m10.name, mod=self.m9m10,
                              offset=vector(gnd_x, rect.by()))
                self.connect_inst([])

        for rect in self.vdd_grid_rects:
            self.add_inst(self.m9m10.name, mod=self.m9m10,
                          offset=vector(vdd_x, rect.by()))
            self.connect_inst([])

    def add_right_rails_vias(self):
        vdd_x = self.right_vdd.cx()
        gnd_x = self.right_gnd.rx()

        for rect in self.vdd_grid_rects:
            self.add_inst(self.m2mtop.name, mod=self.m2mtop,
                          offset=vector(vdd_x, rect.by()))
            self.connect_inst([])

        for rect in self.gnd_grid_rects:
            self.add_inst(self.m1mtop.name, mod=self.m1mtop,
                          offset=vector(gnd_x, rect.by()), mirror="MY")
            self.connect_inst([])

    @staticmethod
    def rightmost_largest_rect(rects):
        """Biggest rect to the right of the cell"""
        right_x = max([x.rx() for x in rects])
        return max(filter(lambda x: x.rx() >= 0.75 * right_x, rects), key=lambda x: x.height)
