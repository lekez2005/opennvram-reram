from base.contact import m2m3, m1m2, cross_m2m3
from base.design import ACTIVE, METAL2, METAL3
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from globals import OPTS
from modules.reram.write_driver_pgate import WriteDriverPgate


class WriteDriverPgateSeparateVdd(WriteDriverPgate):
    """Note deprecated"""
    mod_name = "write_driver_sep_vdd"
    tx_count = 0  # keep track of tx count to detect when buffer tx is created

    def add_pins(self):
        # set based on the biggest vdd voltage
        self.pmos_body_vdd = getattr(OPTS, "write_driver_pmos_vdd", "vdd_write_br")
        self.add_pin_list("data data_bar mask_bar en en_bar "
                          "bl br vdd vdd_write_bl vdd_write_br gnd".split())

    def create_ptx(self, size, is_pmos=False, **kwargs):
        """Use two fingers for the buffer fets"""
        if self.tx_count in [2, 3]:
            kwargs["mults"] = 2
            kwargs["active_cont_pos"] = [0, 2]
        self.tx_count += 1
        return super().create_ptx(size, is_pmos, **kwargs)

    def add_tx(self, tx, y_offset, x_offset=None, **kwargs):
        """Create space between the fets for the buffer fets"""
        if tx in [self.buffer_pmos, self.buffer_nmos]:

            active_extension = self.buffer_pmos.active_rect.rx() - self.buffer_pmos.width
            module_space = active_extension + 0.5 * self.get_space(ACTIVE)
            x_offsets = [self.mid_x - module_space - self.buffer_pmos.width,
                         self.mid_x + module_space]
            tx_inst = super().add_tx(tx, y_offset, x_offsets[1], **kwargs)
            if tx == self.buffer_pmos:
                self.buffer_pmos_inst_1 = tx_inst
            else:
                self.buffer_nmos_inst_1 = tx_inst

            x_offset = x_offsets[0]

        return super().add_tx(tx, y_offset, x_offset, **kwargs)

    def get_buffer_tx_connections(self):
        buffer_nmos = [("bl", "en", "bl_n_mid"),
                       ("bl_n_mid", "bl_bar", "gnd"),
                       ("br", "en", "br_n_mid"),
                       ("br_n_mid", "br_bar", "gnd")]
        buffer_pmos = [("bl", "en_bar", "bl_p_mid"),
                       ("bl_p_mid", "bl_bar", "vdd_write_bl"),
                       ("br", "en_bar", "br_p_mid"),
                       ("br_p_mid", "br_bar", "vdd_write_br")]
        return buffer_nmos, buffer_pmos

    def add_ptx_spice(self, name, spice_mod, connections):
        """Correct vdd, nwell contact connections"""
        if connections[-1] == "vdd":
            connections[-1] = self.pmos_body_vdd
        super().add_ptx_spice(name, spice_mod, connections)

    def flatten_tx(self, *args):
        super().flatten_tx(self.buffer_nmos_inst_1, self.buffer_pmos_inst_1, *args)

    def get_bl_bar_bar_offsets(self, nmos_pins):
        space = (0.5 * max(m2m3.first_layer_width, m1m2.second_layer_width) +
                 self.get_parallel_space(METAL2))

        left_offset = self.buffer_pmos_inst.get_pin("S").cx() + space
        right_offset = self.buffer_nmos_inst_1.get_pin("D").cx() - space - self.m2_width
        return [left_offset, right_offset]

    def get_buffer_poly(self):
        nmos_poly = (self.get_sorted_pins(self.buffer_nmos_inst, "G") +
                     self.get_sorted_pins(self.buffer_nmos_inst_1, "G"))
        pmos_poly = (self.get_sorted_pins(self.buffer_pmos_inst, "G") +
                     self.get_sorted_pins(self.buffer_pmos_inst_1, "G"))
        return nmos_poly, pmos_poly

    def get_buffer_output_pin(self, tx_inst, pin_index):
        if pin_index == 0:
            return self.get_sorted_pins(tx_inst, "D")[0]
        if tx_inst == self.buffer_nmos_inst:
            tx_inst = self.buffer_nmos_inst_1
        else:
            tx_inst = self.buffer_pmos_inst_1
        return self.get_sorted_pins(tx_inst, "S")[0]

    def get_bitline_rail_offset(self, tx_pins):
        space = self.get_parallel_space(METAL2) + m1m2.second_layer_width
        tx_pin = tx_pins[0]
        if tx_pin.cx() < self.mid_x:
            x_offset = min(super().get_bitline_rail_offset(tx_pins)[0],
                           self.mid_x - space - self.m2_width)
        else:
            x_offset = max(super().get_bitline_rail_offset(tx_pins)[0],
                           self.mid_x + space)
        return x_offset, self.m2_width

    def get_m1_pin_power_pins(self):
        return ["gnd", self.pmos_body_vdd, "gnd"]

    def get_power_pin_combinations(self):
        return [("gnd", self.logic_nmos_inst, "S"),
                ("vdd_write_br", self.buffer_pmos_inst_1, "D"),
                ("gnd", self.buffer_nmos_inst, "S"),
                ("gnd", self.buffer_nmos_inst_1, "D")]

    def route_tx_power(self):
        super().route_tx_power()
        for tx_inst, pin_name, vdd_name in [(self.buffer_pmos_inst, "S", "vdd_write_bl"),
                                            (self.logic_pmos_inst, "D", "vdd")]:
            pin = tx_inst.get_pin(pin_name)
            num_contacts = calculate_num_contacts(self, pin.height(),
                                                  layer_stack=m1m2.layer_stack)
            self.add_contact_center(m1m2.layer_stack, pin.center(),
                                    size=[1, num_contacts])
            self.add_cross_contact_center(cross_m2m3, pin.center(), rotate=False)
            self.add_layout_pin(vdd_name, METAL3,
                                vector(0, pin.cy() - 0.5 * self.rail_height),
                                width=self.width, height=self.rail_height)
