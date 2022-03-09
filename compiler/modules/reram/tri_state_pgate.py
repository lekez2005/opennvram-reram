import tech
from base.contact import poly as poly_contact, m1m2, cross_poly, m2m3
from base.design import METAL1, POLY, METAL2
from base.geometry import MIRROR_X_AXIS
from base.vector import vector
from modules.reram.bitcell_aligned_pgate import BitcellAlignedPgate


class TriStatePgate(BitcellAlignedPgate):
    mod_name = "tri_state"

    @classmethod
    def get_name(cls, size, name=None):
        name = name or f"{cls.mod_name}_{size:.4g}"
        return name

    def is_delay_primitive(self):
        return True

    def create_layout(self):
        self.add_pins()
        self.create_modules()
        self.setup_layout_constants()
        self.place_modules()
        self.add_ptx_connections()
        self.route_data_input()
        self.route_output_pin()
        self.route_enable_input()
        self.add_power_and_taps()
        self.route_tx_power()
        self.flatten_tx(self.nmos_inst, self.pmos_inst)
        self.add_boundary()
        tech.add_tech_layers(self)

    def add_pins(self):
        self.add_pin_list("in_bar out en en_bar vdd gnd".split())

    def create_modules(self):
        super().create_modules()

        kwargs = {
            "mults": 4,
            "independent_poly": False,
            "active_cont_pos": [0, 2, 4]
        }

        self.nmos = self.create_ptx(self.size / 2, False, **kwargs)
        self.nmos_spice = self.create_ptx_spice(self.nmos, mults=1)
        self.pmos = self.create_ptx(self.size / 2, True, **kwargs)
        self.pmos_spice = self.create_ptx_spice(self.pmos, mults=1)

    def add_ptx_connections(self):
        nmos_connections = [("gnd", "en", "left_mid_n"),
                            ("left_mid_n", "in_bar", "out"),
                            ("gnd", "en", "right_mid_n"),
                            ("right_mid_n", "in_bar", "out")]
        pmos_connections = [("vdd", "en_bar", "left_mid_p"),
                            ("left_mid_p", "in_bar", "out"),
                            ("vdd", "en_bar", "right_mid_p"),
                            ("right_mid_p", "in_bar", "out")]
        for tx, connections, body in zip([self.nmos_spice, self.pmos_spice],
                                         [nmos_connections, pmos_connections],
                                         ["gnd", "vdd"]):
            for index, connection in enumerate(connections):
                name = f"{tx.tx_type}{index}"
                self.add_inst(name, tx, vector(0, 0))
                self.connect_inst(list(connection) + [body])

    def setup_layout_constants(self):
        self.bottom_space = self.calculate_bottom_space()

        self.nmos_y = self.bottom_space - self.nmos.active_rect.by()

        nmos_active_top = self.nmos_y + self.nmos.active_rect.uy()
        self.nmos_poly_cont_y = (nmos_active_top + self.calculate_active_to_poly_cont_mid("nmos") -
                                 0.5 * poly_contact.first_layer_height)
        nmos_cont_top = self.nmos_poly_cont_y + poly_contact.first_layer_height

        self.pmos_poly_cont_y = nmos_cont_top + self.poly_vert_space
        pmos_active_bottom = (self.pmos_poly_cont_y + 0.5 * poly_contact.first_layer_height +
                              self.calculate_active_to_poly_cont_mid("pmos"))

        self.pmos_y_top = pmos_active_bottom + (self.pmos.height -
                                                self.pmos.active_rect.by())

        active_to_top = self.pmos.height - self.pmos.active_rect.uy()

        self.height = self.pmos_y_top - active_to_top + self.bottom_space

    def place_modules(self):
        x_offset = 0.5 * self.width - 0.5 * self.nmos.width
        self.nmos_inst = self.add_inst("nmos_layout", mod=self.nmos,
                                       offset=vector(x_offset, self.nmos_y))
        self.connect_inst([], check=False)

        self.pmos_inst = self.add_inst("pmos_layout", mod=self.pmos, mirror=MIRROR_X_AXIS,
                                       offset=vector(x_offset, self.pmos_y_top))
        self.connect_inst([], check=False)

    def route_data_input(self):
        nmos_poly = self.get_sorted_pins(self.nmos_inst, "G")
        pmos_poly = self.get_sorted_pins(self.pmos_inst, "G")

        drain_pin = self.pmos_inst.get_pin("D")
        space = max(self.m1_width, m1m2.first_layer_width) + self.get_parallel_space(METAL1)
        poly_right = (nmos_poly[0].rx() + self.poly_vert_space +
                      0.5 * poly_contact.first_layer_width)
        poly_cont_left_m1 = max(drain_pin.lx() - space, poly_right)

        # add poly contact at mid_y
        mid_y = 0.5 * (self.nmos_inst.uy() + self.pmos_inst.by())
        self.mid_data_in_x = self.add_mid_poly_via(nmos_poly, mid_y, poly_cont_left_m1)

        for i in [1, 2]:
            # join nmos poly to pmos poly
            self.add_rect(POLY, offset=nmos_poly[i].ul(), width=nmos_poly[i].width(),
                          height=pmos_poly[i].by() - nmos_poly[i].uy())

        # poly contact to mid active y
        offset = vector(drain_pin.lx() - space, mid_y - 0.5 * self.m1_width)
        self.add_rect(METAL1, offset, width=self.mid_data_in_x - offset.x)
        y_offset = drain_pin.cy()
        rect = self.add_rect(METAL1, offset, height=y_offset - offset.y)

        # mid active y to top
        self.add_contact_center(m1m2.layer_stack, vector(rect.cx(), y_offset))
        self.add_layout_pin("in_bar", METAL2,
                            vector(rect.cx() - 0.5 * self.m2_width, rect.uy()),
                            height=self.height - rect.uy())

    def route_output_pin(self):
        x_offset = (self.mid_data_in_x + 0.5 * poly_contact.second_layer_height +
                    self.get_line_end_space(METAL1))

        drain_pins = [x.get_pin("D") for x in [self.nmos_inst, self.pmos_inst]]

        for pin_index, pin in enumerate(drain_pins):
            if pin_index == 0:
                y_offset = pin.uy() - self.m1_width
            else:
                y_offset = pin.by()
            self.add_rect(METAL1, vector(pin.lx(), y_offset),
                          width=x_offset + self.m1_width - pin.lx())
        y_offset = drain_pins[0].uy()
        self.add_rect(METAL1, vector(x_offset, y_offset),
                      height=drain_pins[1].by() - y_offset)

        # nmos drain to output
        pin = drain_pins[0]
        self.add_contact_center(m1m2.layer_stack, pin.center())
        self.add_layout_pin("out", METAL2, vector(pin.cx() - 0.5 * self.m2_width, 0),
                            height=pin.cy())

    def route_enable_input(self):
        nmos_poly = self.get_sorted_pins(self.nmos_inst, "G")
        pmos_poly = self.get_sorted_pins(self.pmos_inst, "G")
        pin_names = ["en", "en_bar"]

        all_poly = [nmos_poly, pmos_poly]
        all_contact_y = [self.nmos_poly_cont_y, self.pmos_poly_cont_y]

        in_bar_x = (self.get_pin("in_bar").cx() - 0.5 * self.m1_width -
                    self.get_line_end_space(METAL1))

        for inst_index, inst in enumerate([self.nmos_inst, self.pmos_inst]):
            for poly_index in [0, 3]:
                poly_rect = all_poly[inst_index][poly_index]
                if poly_index == 0:
                    x_offset = in_bar_x - 0.5 * (max(poly_contact.second_layer_height,
                                                     m1m2.first_layer_height))
                else:
                    x_offset = poly_rect.lx() + 0.5 * poly_contact.first_layer_width
                y_offset = all_contact_y[inst_index] + 0.5 * poly_contact.first_layer_height

                offset = vector(x_offset, y_offset)

                self.add_cross_contact_center(cross_poly, offset)
                if inst_index == 0:
                    top = y_offset + 0.5 * poly_contact.first_layer_height
                    bottom = poly_rect.uy()
                else:
                    top = poly_rect.by()
                    bottom = y_offset - 0.5 * poly_contact.first_layer_height
                self.add_rect(POLY, vector(poly_rect.lx(), bottom),
                              width=poly_rect.width(), height=top - bottom)

                self.add_contact_center(m1m2.layer_stack, offset, rotate=90)
                # move closer to the poly contact to prevent m2 space issue
                if poly_index == 0:
                    pin_x = offset.x - 0.5 * m1m2.h_2
                    self.add_layout_pin(pin_names[inst_index], METAL2,
                                        vector(pin_x, offset.y - 0.5 * self.bus_width),
                                        width=self.width - pin_x, height=self.bus_width)

    def add_power_and_taps(self):
        pin_names = ["gnd", "vdd"]
        y_offsets = [0, self.height - self.rail_height]
        ptx_insts = [self.nmos_inst, self.pmos_inst]

        for i in range(2):
            self.add_power_tap(y_offsets[i], pin_names[i], ptx_insts[i])

    def route_tx_power(self):
        pin_names = ["gnd", "vdd"]
        insts = [self.nmos_inst, self.pmos_inst]
        for i in range(2):
            for pin in insts[i].get_pins("S"):
                self.route_pin_to_power(pin_names[i], pin)
