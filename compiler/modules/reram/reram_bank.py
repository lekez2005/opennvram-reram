import debug
from base import utils
from base.contact import m1m2, cross_m2m3, cross_m3m4, m2m3, m3m4
from base.design import METAL3, METAL4, METAL2, design
from base.layout_clearances import find_clearances, VERTICAL
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from base.well_implant_fills import evaluate_vertical_metal_spacing
from globals import OPTS
from modules.bank_mixins import WordlineVoltageMixin
from modules.baseline_bank import BaselineBank, EXACT, LEFT_FILL, RIGHT_FILL


class ReRamBank(WordlineVoltageMixin, BaselineBank):

    def add_pins(self):
        super().add_pins()
        self.add_pin_list(["vref", "vclamp", "vclampp"])
        for i in range(self.word_size):
            self.add_pin("DATA_OUT[{0}]".format(i))

        if OPTS.separate_vdd_write:
            self.vdd_write_pins = ["vdd_write_bl", "vdd_write_br"]
        else:
            self.vdd_write_pins = ["vdd_write"]
        self.add_pin_list(self.vdd_write_pins + ["vdd_wordline"])

    def route_all_instance_power(self, inst, via_rotate=90):
        if inst == self.write_driver_array_inst:
            self.route_write_driver_power()
            if not OPTS.separate_vdd_write:
                return
        super().route_all_instance_power(inst, via_rotate)

    def calculate_control_buffers_y(self, num_top_rails, num_bottom_rails, module_space):
        control_top = super().calculate_control_buffers_y(num_top_rails,
                                                          num_bottom_rails, module_space)
        # to add room for data out
        self.data_out_y = self.trigate_y + 0.5 * max(m2m3.h_2, m3m4.h_1, m3m4.h_2)

        space = self.m4_space + m3m4.h_2

        self.trigate_y = self.data_out_y + space
        return control_top

    def get_bitcell_array_y_offset(self):
        # add space for bl_reset
        bl_reset = self.precharge_array_inst.get_pin("bl_reset")
        y_offset = (bl_reset.cy() + 0.5 * m2m3.h_1 +
                    self.get_parallel_space(METAL2) + 0.5 * self.rail_height)
        return y_offset

    def get_column_mux_array_y(self):
        metal_space = evaluate_vertical_metal_spacing(self.column_mux_array,
                                                      self.sense_amp_array.child_mod, 0)
        return self.sense_amp_array_inst.uy() + metal_space

    def get_wordline_offset(self):
        offset = super().get_wordline_offset()
        return WordlineVoltageMixin.update_wordline_offset(self, offset)

    def get_wordline_driver_connections(self):
        connections = BaselineBank.get_wordline_driver_connections(self)
        return WordlineVoltageMixin.update_wordline_driver_connections(self, connections)

    def get_tri_state_connection_replacements(self):
        return [("out[", "DATA_OUT["),
                ("in_bar[", "sense_out_bar["), ("in[", "sense_out["),
                ("en", "tri_en", EXACT), ("en_bar", "tri_en_bar", EXACT)]

    def get_custom_net_destination(self, net):
        if net == "wordline_en":
            return self.precharge_array_inst.get_pins("br_reset")
        return super().get_custom_net_destination(net)

    def route_precharge_to_sense_or_mux(self):
        if not self.col_mux_array_inst:
            super().route_precharge_to_sense_or_mux()
            return
        y_offset = self.get_m2_m3_below_instance(self.precharge_array_inst, 0)
        all_pins = self.get_bitline_pins(self.precharge_array_inst, self.col_mux_array_inst,
                                         word_size=self.num_cols)
        alignments = [LEFT_FILL, RIGHT_FILL]
        for i in range(2):
            top_pins, bottom_pins = all_pins[i]
            mid_rects = []
            for j, top_pin in enumerate(top_pins):
                mid_rects.append(self.add_rect(METAL4, vector(top_pin.lx(), y_offset),
                                               width=top_pin.width(),
                                               height=top_pin.by() - y_offset))
            self.join_rects(mid_rects, top_pins[0].layer, bottom_pins, bottom_pins[0].layer,
                            via_alignment=alignments[i])

    def route_sense_amp(self):
        """Routes sense amp power and connects write driver bitlines to sense amp bitlines"""
        debug.info(1, "Route sense amp")
        self.route_all_instance_power(self.sense_amp_array_inst)
        # write driver to sense amp

        sense_mod = self.sense_amp_array.child_mod
        clearances = find_clearances(sense_mod, METAL3, direction=VERTICAL)
        lowest = min(clearances, key=lambda x: x[0])

        sample_pin = sense_mod.get_pin("bl")
        y_shift = lowest[0] - sample_pin.by() + self.m3_space

        self.join_bitlines(top_instance=self.sense_amp_array_inst, top_suffix="",
                           bottom_instance=self.write_driver_array_inst,
                           bottom_suffix="", y_shift=y_shift)

        self.right_edge = self.right_gnd.rx() + self.m3_space

        for pin_name in ["vclamp", "vclampp", "vref"]:
            sense_pin = self.sense_amp_array_inst.get_pin(pin_name)
            self.add_layout_pin(pin_name, sense_pin.layer, sense_pin.lr(),
                                height=sense_pin.height(),
                                width=self.right_edge - sense_pin.rx())

    def route_bitcell(self):
        """wordline driver wordline to bitcell array wordlines"""
        for pin in self.bitcell_array_inst.get_pins("gnd"):
            x_offset = self.mid_gnd.lx()
            self.add_rect(pin.layer, vector(x_offset, pin.by()), height=pin.height(),
                          width=self.right_gnd.rx() - x_offset)
            self.add_power_via(pin, self.right_gnd)

    def get_data_in_m2m3_x_offset(self, data_in, word):
        mask_out = self.get_mask_flop_out(word)
        if mask_out.lx() > data_in.lx():
            return min(data_in.lx(), mask_out.lx() - self.m2_space - m2m3.w_1)
        return data_in.lx()

    def get_write_driver_array_connection_replacements(self):
        replacements = super().get_write_driver_array_connection_replacements()
        if not OPTS.separate_vdd_write:
            replacements.append(("vdd", "vdd_write"))
        return replacements

    def route_write_driver_power(self):
        for pin in self.write_driver_array_inst.get_pins("gnd"):
            self.route_gnd_pin(pin)

        if OPTS.separate_vdd_write:
            vdd_write_pins = self.vdd_write_pins, self.vdd_write_pins
        else:
            vdd_write_pins = ["vdd"], self.vdd_write_pins

        for driver_pin_name, bank_pin_name in zip(vdd_write_pins[0], vdd_write_pins[1]):
            for driver_pin in self.write_driver_array_inst.get_pins(driver_pin_name):
                if driver_pin.layer == METAL3:
                    self.add_layout_pin(bank_pin_name, driver_pin.layer, driver_pin.ll(),
                                        height=driver_pin.height(),
                                        width=self.right_edge - driver_pin.lx())

    def connect_tri_output_to_data(self, word, fill_width, fill_height):
        tri_out_pin = self.tri_gate_array_inst.get_pin("out[{}]".format(word))
        y_offset = self.data_out_y

        self.add_rect(METAL2, vector(tri_out_pin.lx(), y_offset), width=tri_out_pin.width(),
                      height=tri_out_pin.by() - y_offset)

        x_offset = tri_out_pin.cx() - 0.5 * self.m4_width

        self.add_layout_pin(f"DATA_OUT[{word}]", METAL4, vector(x_offset, self.min_point),
                            height=y_offset - self.min_point)
        via_offset = vector(tri_out_pin.cx(), y_offset)
        self.add_cross_contact_center(cross_m2m3, via_offset)
        self.add_cross_contact_center(cross_m3m4, via_offset, rotate=True, fill=False)

    def route_wordline_driver(self):
        self.route_wordline_in()
        self.route_wordline_enable()
        self.route_wl_to_bitcell()
        self.route_wordline_power()

    def get_decoder_enable_y(self):
        return self.precharge_array_inst.get_pin("br_reset").by() - self.bus_pitch

    def route_wl_to_bitcell(self):
        for row in range(self.num_rows):
            pin_name = f"wl[{row}]"
            bitcell_pin = self.bitcell_array_inst.get_pin(pin_name)
            wl_pin = self.wordline_driver_inst.get_pin(pin_name)
            closest_y = min([wl_pin.uy(), wl_pin.by()],
                            key=lambda x: abs(bitcell_pin.cy() - x))

            via_x = wl_pin.lx() + 0.5 * m2m3.w_1
            design.add_cross_contact_center(self, cross_m2m3, vector(via_x, closest_y))
            path_x = bitcell_pin.lx() - self.m3_space - 0.5 * self.m3_width
            self.add_path(METAL3, [vector(via_x, closest_y),
                                   vector(path_x, closest_y),
                                   vector(path_x, bitcell_pin.cy()),
                                   vector(bitcell_pin.lx(), bitcell_pin.cy())])

    def route_wordline_power(self):
        WordlineVoltageMixin.route_wordline_power_pins(self, self.wordline_driver_inst)

    def add_m2m4_power_rails_vias(self):
        power_pins = [self.mid_vdd, self.right_vdd, self.mid_gnd, self.right_gnd,
                      self.vdd_wordline]

        for pin in power_pins:
            self.add_layout_pin(pin.name, METAL4, offset=pin.ll(),
                                width=pin.width(),
                                height=pin.height())

            open_spaces = find_clearances(self, METAL3, direction=VERTICAL,
                                          region=(pin.lx(), pin.rx()),
                                          existing=[(pin.by(), pin.uy())],
                                          recursive=False)
            # TODO: sky_tapeout: remove duplicated logic
            for open_space in open_spaces:
                available_space = open_space[1] - open_space[0] - 2 * self.m3_space
                if available_space <= 0:
                    continue
                mid_via_y = 0.5 * (open_space[0] + open_space[1])
                for via in [m2m3, m3m4]:
                    sample_contact = calculate_num_contacts(self, available_space,
                                                            layer_stack=via.layer_stack,
                                                            return_sample=True)
                    if available_space > sample_contact.h_1:
                        self.add_contact_center(via.layer_stack,
                                                vector(pin.cx(), mid_via_y),
                                                size=[1, sample_contact.dimensions[1]])

    def connect_control_buffers_power_to_grid(self, grid_pin):
        pass

    def connect_m4_grid_instance_power(self, instance_pin, power_rail):
        related_pin = self.m4_pin_map[self.hash_m4_pin(power_rail)]
        for rail in [power_rail, related_pin]:
            if rail.by() <= instance_pin.cy() <= rail.uy():
                super().connect_m4_grid_instance_power(instance_pin, rail)

    def get_intra_array_grid_y(self):
        top_gnd = max(self.write_driver_array_inst.get_pins("gnd"), key=lambda x: x.uy())
        return top_gnd.by() + self.m4_width

    def get_intra_array_grid_top(self):
        return self.bitcell_array_inst.uy()

    @staticmethod
    def hash_m4_pin(pin):
        return f"{utils.round_to_grid(pin.lx()):.3g}"

    def add_related_m4_grid_pin(self, original_pin):
        if not hasattr(self, "m4_pin_map"):
            self.m4_pin_map = {}
        pin_bottom = self.tri_gate_array_inst.get_pins("gnd")[0].cy() - 0.5 * m3m4.h_2

        if original_pin.name == "gnd":
            pin_top = max(self.write_driver_array_inst.get_pins("gnd"), key=lambda x: x.uy()).uy()
        elif OPTS.separate_vdd_write:
            # TODO potential clash with write vdd
            top_vdd = max(self.write_driver_array_inst.get_pins("vdd"), key=lambda x: x.uy())
            pin_top = top_vdd.cy() + 0.5 * m3m4.h_2
        else:
            bot_gnd = min(self.write_driver_array_inst.get_pins("gnd"), key=lambda x: x.uy())
            pin_top = bot_gnd.uy() + self.m4_width
        pin = self.add_layout_pin(original_pin.name, original_pin.layer,
                                  vector(original_pin.lx(), pin_bottom),
                                  width=original_pin.width(),
                                  height=pin_top - pin_bottom)
        self.m4_pin_map[self.hash_m4_pin(original_pin)] = pin
