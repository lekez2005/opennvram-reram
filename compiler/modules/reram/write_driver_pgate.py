import tech
from base.contact import cross_m1m2, m1m2, poly as poly_contact, cross_poly, cross_m2m3
from base.design import METAL2, POLY, METAL1, METAL3, NWELL
from base.geometry import MIRROR_X_AXIS
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from modules.reram.bitcell_aligned_pgate import BitcellAlignedPgate


class WriteDriverPgate(BitcellAlignedPgate):
    mod_name = "write_driver"

    @classmethod
    def get_name(cls, logic_size, buffer_size, name=None):
        name = name or f"{cls.mod_name}_{logic_size:.4g}_{buffer_size:.4g}"
        name = name.replace(".", "__")
        return name

    def __init__(self, logic_size, buffer_size, name=None):
        name = self.get_name(logic_size, buffer_size, name)
        self.logic_size = logic_size
        self.buffer_size = buffer_size
        super().__init__(size=None, name=name)

    def is_delay_primitive(self):
        return True

    def create_layout(self):
        self.add_pins()
        self.create_modules()
        self.place_logic_insts()
        self.place_buffer_insts()
        self.add_ptx_connections()
        self.route_logic_insts()
        self.route_buffer_insts()
        self.add_power_and_taps()
        self.route_tx_power()
        self.add_boundary()
        self.flatten_tx(self.logic_nmos_inst, self.logic_pmos_inst,
                        self.buffer_nmos_inst, self.buffer_pmos_inst)
        tech.add_tech_layers(self)

    def add_pins(self):
        self.add_pin_list("data data_bar mask_bar en en_bar bl br vdd gnd".split())

    def create_modules(self):
        super().create_modules()
        kwargs = {
            "mults": 4,
            "independent_poly": False
        }
        self.logic_nmos = self.create_ptx(self.logic_size, **kwargs)
        kwargs["active_cont_pos"] = [0, 2, 4]

        self.logic_pmos = self.create_ptx(self.logic_size * 1.5, True, **kwargs)
        self.buffer_nmos = self.create_ptx(self.buffer_size, **kwargs)
        self.buffer_pmos = self.create_ptx(self.buffer_size, True, **kwargs)

        self.logic_nmos_spice = self.create_ptx_spice(self.logic_nmos, mults=1)
        self.logic_pmos_spice = self.create_ptx_spice(self.logic_pmos, mults=1)
        self.buffer_nmos_spice = self.create_ptx_spice(self.buffer_nmos, mults=1)
        self.buffer_pmos_spice = self.create_ptx_spice(self.buffer_pmos, mults=1)

    def add_tx(self, tx, y_offset, x_offset=None, **kwargs):
        if x_offset is None:
            x_offset = 0.5 * self.width - 0.5 * self.logic_nmos.width
        inst = self.add_inst(tx.name, mod=tx, offset=vector(x_offset, y_offset), **kwargs)
        self.connect_inst([], check=False)
        return inst

    def place_logic_insts(self):
        self.bottom_space = self.calculate_bottom_space()
        logic_nmos_y = self.bottom_space - self.logic_nmos.active_rect.by()

        self.logic_nmos_inst = self.add_tx(self.logic_nmos, logic_nmos_y)

        active_top = logic_nmos_y + self.logic_nmos.active_rect.uy()
        self.logic_cont_y = active_top + self.calculate_active_to_poly_cont_mid("nmos")

        active_bottom = self.logic_cont_y + self.calculate_active_to_poly_cont_mid("pmos")
        y_offset = active_bottom + (self.logic_pmos.height - self.logic_pmos.active_rect.by())

        self.logic_pmos_inst = self.add_tx(self.logic_pmos, y_offset, mirror=MIRROR_X_AXIS)

        active_pmos_top = active_bottom + self.logic_pmos.active_rect.height
        vdd_rail_top = active_pmos_top + self.bottom_space
        self.vdd_y = vdd_rail_top - self.rail_height

    def get_buffer_pmos_y(self):
        return self.vdd_y + self.bottom_space - self.buffer_pmos.active_rect.by()

    def place_buffer_insts(self):
        y_offset = self.get_buffer_pmos_y()
        self.buffer_pmos_inst = self.add_tx(self.buffer_pmos, y_offset)
        pmos_active_top = y_offset + self.buffer_pmos.active_rect.uy()
        self.buffer_p_cont_y = (pmos_active_top +
                                self.calculate_active_to_poly_cont_mid("pmos") -
                                0.5 * poly_contact.first_layer_height)
        pmos_cont_top = self.buffer_p_cont_y + poly_contact.first_layer_height

        self.buffer_n_cont_y = pmos_cont_top + self.poly_vert_space
        nmos_active_bottom = (self.buffer_n_cont_y + 0.5 * poly_contact.first_layer_height +
                              self.calculate_active_to_poly_cont_mid("nmos"))

        nmos_y_top = nmos_active_bottom + (self.buffer_nmos.height -
                                           self.buffer_nmos.active_rect.by())
        self.buffer_nmos_inst = self.add_tx(self.buffer_nmos, nmos_y_top,
                                            mirror=MIRROR_X_AXIS)
        active_to_top = self.buffer_nmos.height - self.buffer_nmos.active_rect.uy()

        self.height = nmos_y_top - active_to_top + self.bottom_space

        self.buffer_mid_y = 0.5 * (self.buffer_pmos_inst.get_pins("G")[0].uy() +
                                   self.buffer_nmos_inst.get_pins("G")[0].by())

    def add_ptx_spice(self, name, spice_mod, connections):
        self.add_inst(name, spice_mod, vector(0, 0))
        self.connect_inst(connections)

    def get_buffer_tx_connections(self):
        buffer_nmos = [("bl", "bl_bar", "bl_n_mid"),
                       ("bl_n_mid", "en", "gnd"),
                       ("br", "br_bar", "br_n_mid"),
                       ("br_n_mid", "en", "gnd")]
        buffer_pmos = [("bl", "bl_bar", "bl_p_mid"),
                       ("bl_p_mid", "en_bar", "vdd"),
                       ("br", "br_bar", "br_p_mid"),
                       ("br_p_mid", "en_bar", "vdd")]
        return buffer_nmos, buffer_pmos

    def add_ptx_connections(self):
        logic_nmos = [("gnd", "data", "bl_bar"),
                      ("gnd", "mask_bar", "bl_bar"),
                      ("gnd", "data_bar", "br_bar"),
                      ("gnd", "mask_bar", "br_bar")]
        logic_pmos = [("bl_bar", "data", "bl_log_mid"),
                      ("bl_log_mid", "mask_bar", "vdd"),
                      ("br_bar", "data_bar", "br_log_mid"),
                      ("br_log_mid", "mask_bar", "vdd")]
        buffer_nmos, buffer_pmos = self.get_buffer_tx_connections()

        combinations = [(logic_nmos, self.logic_nmos_spice, "gnd"),
                        (logic_pmos, self.logic_pmos_spice, "vdd"),
                        (buffer_nmos, self.buffer_nmos_spice, "gnd"),
                        (buffer_pmos, self.buffer_pmos_spice, "vdd")]
        inst_index = 0
        for connections, spice_mod, body in combinations:
            for conn in connections:
                name = f"M{inst_index}"
                self.add_ptx_spice(name, spice_mod, list(conn) + [body])
                inst_index += 1

    def route_logic_insts(self):
        self.route_logic_inputs()
        self.route_logic_outputs()

    def route_logic_inputs(self):
        nmos_poly = self.get_sorted_pins(self.logic_nmos_inst, "G")
        pmos_poly = self.get_sorted_pins(self.logic_pmos_inst, "G")
        nmos_pins = self.get_sorted_pins(self.logic_nmos_inst, "D")

        left_x = (nmos_pins[0].cx() - 0.5 * m1m2.second_layer_width -
                  self.get_parallel_space(METAL2) - self.m2_width)
        right_x = (nmos_pins[1].cx() + 0.5 * m1m2.second_layer_width +
                   self.get_parallel_space(METAL2))
        pin_offsets = [left_x, self.mid_x - 0.5 * self.m2_width, right_x]
        pin_names = ["data", "mask_bar", "data_bar"]
        poly_rects = [nmos_poly[i] for i in [0, 1, 3]]

        cont_mid_y = self.logic_cont_y

        mid_cont_x = 0.5 * (nmos_poly[1].cx() + nmos_poly[2].cx())

        for i in range(3):
            pin = self.add_layout_pin(pin_names[i], METAL2, vector(pin_offsets[i], 0),
                                      width=self.m2_width,
                                      height=cont_mid_y + 0.5 * self.m2_width)
            if i == 1:
                cont_x = self.add_mid_poly_via(nmos_poly, cont_mid_y, mid_cont_x)
            else:
                if i == 0:
                    cont_x = poly_rects[i].rx() - 0.5 * poly_contact.first_layer_width
                else:
                    cont_x = poly_rects[i].lx() + 0.5 * poly_contact.first_layer_width
                self.add_cross_contact_center(cross_poly, vector(cont_x, cont_mid_y))

            self.add_cross_contact_center(cross_m1m2, vector(pin.cx(), cont_mid_y),
                                          rotate=True)
            join_height = max(self.m1_width, m1m2.first_layer_width)
            self.add_rect(METAL1, vector(pin.cx(), cont_mid_y - 0.5 * join_height),
                          width=cont_x - pin.cx(), height=join_height)

        for i in range(4):
            self.add_rect(POLY, nmos_poly[i].ul(), width=nmos_poly[i].width(),
                          height=pmos_poly[i].by() - nmos_poly[i].uy())

    def get_bl_bar_bar_offsets(self, nmos_pins):
        return [pin.cx() - 0.5 * self.m2_width for pin in nmos_pins]

    def route_logic_outputs(self):
        nmos_pins = self.get_sorted_pins(self.logic_nmos_inst, "D")
        pmos_pins = self.get_sorted_pins(self.logic_pmos_inst, "S")

        num_contacts = calculate_num_contacts(self, pmos_pins[0].height(),
                                              layer_stack=m1m2.layer_stack)

        bl_br_bar_offsets = self.get_bl_bar_bar_offsets(nmos_pins)

        self.bitline_bar_offsets = []
        for i in range(2):
            nmos_pin = nmos_pins[i]
            pmos_pin = pmos_pins[i]

            self.add_cross_contact_center(cross_m1m2, nmos_pin.center(), rotate=True)
            x_offset = nmos_pin.cx() - 0.5 * self.m2_width
            self.add_rect(METAL2, vector(x_offset, nmos_pin.cy()),
                          height=pmos_pin.by() + self.m2_width - nmos_pin.cy())
            self.add_rect(METAL2, vector(pmos_pin.cx(), pmos_pin.by()),
                          width=x_offset - pmos_pin.cx())
            self.add_contact_center(m1m2.layer_stack, pmos_pin.center(),
                                    size=[1, num_contacts])
            x_offset_ = pmos_pin.cx() - 0.5 * m1m2.second_layer_width
            self.add_rect(METAL2, vector(x_offset_, pmos_pin.by()),
                          width=m1m2.second_layer_width,
                          height=pmos_pin.height())

            y_offset = pmos_pin.uy() - self.m2_width
            x_offset = bl_br_bar_offsets[i]
            self.add_rect(METAL2, vector(x_offset_, y_offset),
                          width=x_offset - x_offset_)
            self.add_rect(METAL2, vector(x_offset, y_offset),
                          height=self.buffer_mid_y - y_offset)
            self.bitline_bar_offsets.append(x_offset)

    def route_buffer_insts(self):
        self.route_buffer_inputs()
        self.route_buffer_outputs()

    def get_buffer_poly(self):
        nmos_poly = self.get_sorted_pins(self.buffer_nmos_inst, "G")
        pmos_poly = self.get_sorted_pins(self.buffer_pmos_inst, "G")
        return nmos_poly, pmos_poly

    def route_buffer_inputs(self):
        nmos_poly, pmos_poly = self.get_buffer_poly()

        fill_width = m1m2.second_layer_width
        _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL2)

        # enable pins
        mid_cont_x = 0.5 * (nmos_poly[1].cx() + nmos_poly[2].cx())

        mid_y = self.buffer_mid_y
        pin_y_offsets = [mid_y - 0.5 * self.bus_space - self.bus_width,
                         mid_y + 0.5 * self.bus_space]
        cont_offsets = [self.buffer_p_cont_y, self.buffer_n_cont_y]
        pin_names = ["en_bar", "en"]
        all_poly = [pmos_poly, nmos_poly]
        for i in range(2):
            self.add_layout_pin(pin_names[i], METAL3, vector(0, pin_y_offsets[i]),
                                width=self.width, height=self.bus_width)
            cont_mid_y = cont_offsets[i] + 0.5 * poly_contact.first_layer_height
            cont_x = self.add_mid_poly_via(nmos_poly, cont_mid_y, mid_cont_x)

            offset = vector(cont_x, cont_mid_y)
            if i == 0:
                self.add_cross_contact_center(cross_m1m2, offset, rotate=True)
                self.add_contact_center(cross_m2m3.layer_stack, offset, rotate=90)
                fill_width_, fill_height_ = fill_width, fill_height
            else:
                self.add_contact_center(m1m2.layer_stack, offset, rotate=90)
                self.add_contact_center(cross_m2m3.layer_stack, offset, rotate=90)
                fill_width_ = fill_height
                fill_height_ = max(fill_width, cross_m2m3.first_layer_width)
            self.add_rect_center(METAL2, vector(offset.x, cont_mid_y),
                                 width=fill_width_, height=fill_height_)

            poly_rects = all_poly[i][1:3]
            if i == 0:
                top_y = cont_mid_y + 0.5 * poly_contact.first_layer_height
                bot_y = poly_rects[0].uy()
            else:
                top_y = poly_rects[1].by()
                bot_y = cont_mid_y - 0.5 * poly_contact.first_layer_height
            for poly_rect in poly_rects:
                self.add_rect(POLY, vector(poly_rect.lx(), bot_y),
                              width=poly_rect.width(), height=top_y - bot_y)

        # bl_bar and br_bar inputs
        poly_indices = [0, 3]
        for i in range(2):

            nmos_poly_rect = nmos_poly[poly_indices[i]]
            pmos_poly_rect = pmos_poly[poly_indices[i]]
            self.add_rect(POLY, pmos_poly_rect.ul(), width=pmos_poly_rect.width(),
                          height=nmos_poly_rect.by() - pmos_poly_rect.uy())

            rail_x = self.bitline_bar_offsets[i]

            if i == 0:
                cont_x = nmos_poly_rect.rx() - 0.5 * poly_contact.first_layer_width
                m1m2_x = rail_x + self.m2_width - 0.5 * m1m2.second_layer_width
            else:
                cont_x = nmos_poly_rect.lx() + 0.5 * poly_contact.first_layer_width
                m1m2_x = rail_x + 0.5 * m1m2.second_layer_width
            self.add_cross_contact_center(cross_poly, vector(cont_x, mid_y))

            self.add_contact_center(m1m2.layer_stack, vector(m1m2_x, mid_y), rotate=0)
            self.add_rect(METAL1, vector(cont_x, mid_y - 0.5 * self.m1_width),
                          width=m1m2_x - cont_x)

    def get_buffer_output_pin(self, tx_inst, pin_index):
        return self.get_sorted_pins(tx_inst, "S")[pin_index]

    def get_bitline_rail_offset(self, tx_pins):
        return tx_pins[0].cx() - 0.5 * m1m2.second_layer_width, m1m2.second_layer_width

    def route_buffer_outputs(self):
        pin_names = ["bl", "br"]
        for i in range(2):
            bitcell_pin = self.bitcell.get_pin(pin_names[i])
            tx_pins = []
            conts = []
            for tx_inst in [self.buffer_pmos_inst, self.buffer_nmos_inst]:
                tx_pin = self.get_buffer_output_pin(tx_inst, i)
                tx_pins.append(tx_pin)
                num_contacts = calculate_num_contacts(self, tx_pin.height(),
                                                      layer_stack=m1m2.layer_stack)
                cont = self.add_contact_center(m1m2.layer_stack, tx_pin.center(),
                                               size=[1, num_contacts])
                conts.append(cont)

            y_bottom = conts[0].by()
            y_top = conts[1].uy() + self.m2_space
            rail_offset, rail_width = self.get_bitline_rail_offset(tx_pins)
            self.add_rect(METAL2, vector(rail_offset, y_bottom), width=rail_width,
                          height=y_top - y_bottom + self.m2_width)
            x_offset = conts[1].lx() if i == 0 else conts[1].rx()
            self.add_rect(METAL2, vector(x_offset, y_top),
                          width=bitcell_pin.cx() - x_offset)
            self.add_layout_pin(pin_names[i], METAL2, vector(bitcell_pin.lx(), y_top),
                                width=bitcell_pin.width(), height=self.height - y_top)

    def get_power_pin_combinations(self):
        return [("gnd", self.logic_nmos_inst, "S"),
                ("vdd", self.logic_pmos_inst, "D"),
                ("vdd", self.buffer_pmos_inst, "D"),
                ("gnd", self.buffer_nmos_inst, "D")]

    def route_tx_power(self):
        pin_combinations = self.get_power_pin_combinations()
        for i, (power_pin_name, tx_inst, pin_name) in enumerate(pin_combinations):
            for pin in tx_inst.get_pins(pin_name):
                self.route_pin_to_power(power_pin_name, pin)
                if i in [1, 2, 3]:
                    num_contacts = calculate_num_contacts(self, pin.height(),
                                                          layer_stack=m1m2.layer_stack)
                    cont = self.add_contact_center(m1m2.layer_stack, pin.center(),
                                                   size=[1, num_contacts])
                    fill_width = cont.mod.second_layer_width
                    _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL2)
                    self.add_rect_center(METAL2, pin.center(), width=fill_width,
                                         height=fill_height)

    def get_m1_pin_power_pins(self):
        return ["gnd", "vdd", "gnd"]

    def add_power_and_taps(self):
        pin_names = self.get_m1_pin_power_pins()
        y_offsets = [0, self.vdd_y, self.height - self.rail_height]
        ptx_insts = [self.logic_nmos_inst, self.logic_pmos_inst, self.buffer_nmos_inst]

        for i in range(3):
            self.add_power_tap(y_offsets[i], pin_names[i], ptx_insts[i])

        vdd_pin = self.get_pins("vdd")[0]
        self.extend_tx_well(self.buffer_pmos_inst, NWELL, vdd_pin)
