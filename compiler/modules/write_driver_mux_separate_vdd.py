import debug
from base.analog_cell_mixin import AnalogMixin
from base.contact import well_contact, poly_contact, m1m2, m2m3, cross_m1m2
from base.design import design, NWELL, METAL1, ACTIVE, POLY, TAP_ACTIVE, METAL2, METAL3, BOUNDARY
from base.utils import round_to_grid as round_g
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from globals import OPTS
from modules.reram.bitcell_aligned_pgate import BitcellAlignedPgate
from modules.write_driver_mux_logic import WriteDriverMuxLogic
from tech import parameter, add_tech_layers


class WriteDriverMuxSeparateVdd(BitcellAlignedPgate, AnalogMixin, design):

    @classmethod
    def get_name(cls, size=None, name=None):
        size = OPTS.write_driver_buffer_size
        return name or f"write_driver_sep_vdd_{size:.4g}".replace(".", "__")

    def __init__(self, size=None, name=None):
        super().__init__(size, name)

    def create_layout(self):
        self.size = OPTS.write_driver_buffer_size
        self.create_modules()
        self.add_logic()
        self.add_buffer_pmos()
        self.add_buffer_nmos()
        self.route_nmos_inputs()
        self.add_vdd_pins()
        self.create_netlist()
        self.flatten_tx()
        add_tech_layers(self)
        self.add_boundary()

    def create_modules(self):
        super().create_modules()
        self.bottom_space = self.calculate_bottom_space()
        self.write_driver_logic = WriteDriverMuxLogic(size=None)
        self.add_mod(self.write_driver_logic)

        nmos_width = round_g(self.size * self.min_tx_width / 2)
        self.nmos = self.create_ptx_by_width(nmos_width, is_pmos=False, mults=2)
        pmos_width = round_g(nmos_width * parameter["beta"])
        self.pmos = self.create_ptx_by_width(pmos_width, is_pmos=True, mults=2)

    def create_netlist(self):
        self.add_pin_list("data data_bar mask en bl br vdd vdd_write_bl vdd_write_br gnd".split())

        input_suffixes = ["_n", "_p"]
        power_names = ["vdd_write_bl", "vdd_write_br"]
        for j, insts in enumerate([self.nmos_insts, self.pmos_insts]):
            suffix = input_suffixes[j]
            for i, pin_name in enumerate(["bl", "br"]):
                if j == 0:
                    body = power_name = "gnd"
                else:
                    body = "vdd_write_bl"
                    power_name = power_names[i]
                tx_inst = insts[i]
                gate_pin = f"{pin_name}{suffix}"
                self.connect_ptx_spice(tx_inst.name, tx_inst, [pin_name, gate_pin, power_name, body])

    def add_logic(self):
        self.logic_inst = self.add_inst("logic", self.write_driver_logic, vector(0, 0))
        self.connect_inst(self.write_driver_logic.pins)
        for pin_name in ["data", "data_bar", "mask", "en", "vdd", "gnd"]:
            self.copy_layout_pin(self.logic_inst, pin_name)

    def add_buffer_pmos(self):
        logic_nwell = self.logic_inst.get_max_shape(NWELL, "uy")
        logic_top_vdd = max(self.logic_inst.get_pins("vdd"), key=lambda x: x.uy())
        nwell_extension = logic_nwell.uy() - logic_top_vdd.cy()

        nwell_space = self.get_space(NWELL, prefix="different")
        # this will be nwell contact y
        mid_tx_vdd = logic_top_vdd.cy() + nwell_extension + nwell_space + nwell_extension
        # add space to prevent clash between nmos input via and drains
        nmos_mid_via = mid_tx_vdd + 0.5 * well_contact.w_2 + self.m1_space + 0.5 * m1m2.w_1
        self.nmos_input_via_y = nmos_mid_via
        pmos_source_y = nmos_mid_via + 0.5 * m1m2.w_1 + self.get_line_end_space(METAL1)
        sample_pmos_source = self.pmos.get_pins("S")[0]
        pmos_y = pmos_source_y - sample_pmos_source.by()

        min_pmos_contact_y = (nmos_mid_via - 0.5 * m1m2.w_1 - self.m1_space -
                              0.5 * poly_contact.w_2)

        pmos_sources = self.get_sorted_pins(self.pmos, "S")
        x_offsets = [-pmos_sources[0].cx(), self.width - pmos_sources[-1].cx()]
        pin_names = ["bl", "br"]
        self.pmos_insts = pmos_insts = []

        pmos_contact_space = self.calculate_active_to_poly_cont_mid("pmos")
        contact_y = None

        logic_pins = ["bl_p", "br_p"]
        for i in range(2):
            pin_name = pin_names[i]
            pmos_inst = self.add_inst(f"{pin_name}_pmos", self.pmos,
                                      vector(x_offsets[i], pmos_y))
            pmos_insts.append(pmos_inst)
            self.connect_inst([], check=False)

            contact_y = min(pmos_inst.get_max_shape(ACTIVE, "by").by() - pmos_contact_space,
                            min_pmos_contact_y)
            mid_x = self.add_tx_poly_contacts(pmos_inst, contact_y)

            logic_pin = self.logic_inst.get_pin(logic_pins[i])
            self.add_path(METAL2, [logic_pin.uc(),
                                   vector(logic_pin.cx(), contact_y),
                                   vector(mid_x, contact_y)])

        self.add_buffer_pmos_tap(mid_tx_vdd, contact_y)

    def add_buffer_nmos(self):
        poly_top = self.pmos_insts[0].get_max_shape(POLY, "uy").uy()
        nmos_poly_bottom = poly_top + self.poly_vert_space
        self.nmos_contact_y = contact_y = nmos_poly_bottom + 0.5 * poly_contact.h_1
        nmos_contact_space = self.calculate_active_to_poly_cont_mid("nmos")

        y_offset = contact_y + nmos_contact_space - self.nmos.active_rect.by()
        x_offsets = [x.lx() for x in self.pmos_insts]

        pin_names = ["bl", "br"]
        self.nmos_insts = nmos_insts = []

        for i in range(2):
            pin_name = pin_names[i]
            nmos_inst = self.add_inst(f"{pin_name}_nmos", self.nmos,
                                      vector(x_offsets[i], y_offset))
            nmos_insts.append(nmos_inst)
            self.connect_inst([], check=False)

        gnd_y = nmos_insts[0].get_max_shape(ACTIVE, "uy").uy() + self.bottom_space - self.rail_height
        gnd_pin, _, _ = self.add_power_tap(gnd_y, "gnd", nmos_insts[0], add_m3=False)
        x_offset = - self.m1_width
        self.add_rect(METAL1, vector(x_offset, gnd_pin.by()),
                      width=self.width - 2 * x_offset,
                      height=gnd_pin.height())
        self.height = gnd_y + self.rail_height

        m2_contacts = self.add_m1_m2_drain_contacts(nmos_insts)
        contact_m2_top = m2_contacts[0].get_max_shape(METAL2, "uy").uy()

        for i, tx_inst in enumerate(nmos_insts):
            self.route_tx_to_power(tx_inst, "S")
            for pin in tx_inst.get_pins("D") + tx_inst.get_pins("S"):
                if pin.name == "S":
                    bottom = pin.by()
                    top = contact_m2_top
                else:
                    bottom = self.pmos_insts[0].cy()

                    bitcell_pin = self.bitcell.get_pin(pin_names[i])
                    top = pin_y = contact_m2_top + self.m2_space

                    x_offset = pin.cx() + 0.5 * m1m2.w_2 if i == 0 else pin.cx() - 0.5 * m1m2.w_2
                    self.add_rect(METAL2, vector(x_offset, pin_y),
                                  width=bitcell_pin.cx() - x_offset)
                    self.add_layout_pin(pin_names[i], METAL2, vector(bitcell_pin.lx(), pin_y),
                                        width=bitcell_pin.width(), height=self.height - pin_y)

                self.add_rect(METAL2, vector(pin.cx() - 0.5 * m1m2.w_2, bottom),
                              width=m1m2.w_2, height=top - bottom)

    def route_nmos_inputs(self):
        poly_contact_y = self.nmos_contact_y
        logic_pins = ["bl_n", "br_n"]
        left_source = self.get_sorted_pins(self.pmos_insts[0], "S")[-1]
        right_source = self.get_sorted_pins(self.pmos_insts[1], "S")[0]
        via_width = max(m1m2.w_2, m2m3.w_1)
        x_offsets = [left_source.cx() + 0.5 * via_width + self.get_parallel_space(METAL2),
                     right_source.cx() - 0.5 * m1m2.w_1 - self.m1_space - self.m1_width]

        via_x = x_offsets[0] + self.m2_width + self.m2_space + 0.5 * m1m2.w_2
        via_y = self.nmos_input_via_y
        self.add_cross_contact_center(cross_m1m2, vector(via_x, via_y),
                                      rotate=True)

        for i, nmos_inst in enumerate(self.nmos_insts):
            logic_pin = self.logic_inst.get_pin(logic_pins[i])

            mid_x = self.add_tx_poly_contacts(nmos_inst, poly_contact_y, add_m1_m2=False)
            if i == 0:
                x_offset = x_offsets[0] + 0.5 * self.m2_width
                layer = METAL2
                y_offset = via_y - 0.5 * self.m2_width
            else:
                x_offset = via_x
                y_offset = via_y - 0.5 * self.m1_width
                layer = METAL1
            self.add_path(METAL2, [logic_pin.uc(),
                                   vector(logic_pin.cx(), via_y),
                                   vector(x_offset, via_y)])
            self.add_rect(layer, vector(x_offsets[i], y_offset),
                          height=poly_contact_y - y_offset)
            if i == 0:
                top_via_x = x_offsets[1] - self.m1_space - 0.5 * m1m2.h_1
                self.add_rect(METAL2, vector(top_via_x, poly_contact_y - 0.5 * m1m2.w_2),
                              width=x_offsets[0] + self.m2_width - top_via_x,
                              height=m1m2.w_2)
                self.add_contact_center(m1m2.layer_stack, vector(top_via_x, poly_contact_y),
                                        rotate=90)
                self.add_rect(METAL1, vector(top_via_x, poly_contact_y
                                             - 0.5 * poly_contact.w_2),
                              width=mid_x - top_via_x, height=poly_contact.w_2)
            else:
                self.add_rect(METAL1, vector(x_offsets[i], poly_contact_y
                                             - 0.5 * poly_contact.w_2),
                              width=mid_x - x_offsets[i], height=poly_contact.w_2)

    def add_tx_poly_contacts(self, tx_inst, contact_y, add_m1_m2=True):
        gate_pins = self.get_sorted_pins(tx_inst, "G")
        gate_pins = [gate_pins[0]] + gate_pins + [gate_pins[-1]]
        mid_x = WriteDriverMuxLogic.add_m2_to_mid_poly_contacts(self, gate_pins, contact_y,
                                                                add_m1_m2=add_m1_m2)

        bottom_y = contact_y - 0.5 * poly_contact.h_1
        for gate_pin in gate_pins[1: 3]:
            self.add_rect(POLY, vector(gate_pin.lx(), bottom_y), width=gate_pin.width(),
                          height=gate_pin.by() - bottom_y)
        return mid_x

    def add_buffer_pmos_tap(self, mid_tx_vdd, contact_y):
        """Add body tap + extend NWELL"""
        # add pmos tap
        vdd_height = round_g(1.5 * self.rail_height)
        vdd_y = contact_y - 0.5 * poly_contact.w_1 - self.get_wide_space(METAL1) - vdd_height
        vdd_write_bl = self.add_layout_pin("vdd_write_bl", METAL1, vector(0, vdd_y),
                                     width=self.width, height=vdd_height)
        tap_offset = vector(self.mid_x, mid_tx_vdd)
        cont = self.add_contact_center(layers=well_contact.layer_stack, offset=tap_offset,
                                       rotate=90, size=[1, 2],
                                       well_type=NWELL, implant_type=NWELL[0])
        self.nwell_contact = cont
        cont_m1 = cont.get_max_shape(METAL1, "by")
        self.add_rect(METAL1, vector(cont_m1.lx(), vdd_write_bl.cy()), width=cont_m1.width,
                      height=cont_m1.by() - vdd_write_bl.cy())
        cont_active = cont.get_max_shape(TAP_ACTIVE, "by")
        nwell_y = cont_active.by() - self.well_enclose_active
        nwell_top = self.pmos_insts[0].get_max_shape(NWELL, "uy").uy()
        self.add_rect(NWELL, vector(0, nwell_y), height=nwell_top - nwell_y,
                      width=self.width)

    def add_m1_m2_drain_contacts(self, tx_insts, y_shift=0):
        sample_pin = self.get_sorted_pins(tx_insts[0], "S")[0]
        num_contacts = calculate_num_contacts(self, sample_pin.height(),
                                              layer_stack=m1m2.layer_stack)
        all_contacts = []
        for tx_inst in tx_insts:
            for pin in tx_inst.get_pins("S") + tx_inst.get_pins("D"):
                offset = pin.center() + vector(0, y_shift)
                all_contacts.append(self.add_contact_center(m1m2.layer_stack, offset,
                                                            size=[1, num_contacts]))
        return all_contacts

    def add_vdd_pins(self):
        pmos_insts = self.pmos_insts
        # add m1m2 vias to source + drain
        sample_pin = self.get_sorted_pins(pmos_insts[0], "S")[0]
        via_m2_top = self.nmos_input_via_y + 0.5 * m1m2.h_2
        y_shift = max(0, self.m2_space - (sample_pin.by() - via_m2_top))
        self.pmos_contacts = self.add_m1_m2_drain_contacts(pmos_insts, y_shift=y_shift)

        # add m3 pins and connect to pmos source pins
        rail_height = getattr(OPTS, "write_vdd_rail_height")
        rail_space = rail_height
        debug.info(2, "Write vdd height = %.3g", rail_height)
        debug.info(2, "Write vdd space = %.3g", rail_space)

        pin_names = ["vdd_write_bl", "vdd_write_br"]
        y_offsets = [sample_pin.cy() - 0.5 * rail_space - rail_height,
                     sample_pin.cy() + 0.5 * rail_space]
        x_offset = sample_pin.cx() - m2m3.w_2
        for i in range(2):
            pin = self.add_layout_pin(pin_names[i], METAL3, vector(x_offset, y_offsets[i]),
                                      height=rail_height, width=self.width - 2 * x_offset)
            for source_pin in pmos_insts[i].get_pins("S"):
                self.add_contact_center(m2m3.layer_stack, vector(source_pin.cx(), pin.cy()),
                                        size=[1, 2])

        # source pin to nwell_tap_m1
        source_pin = self.get_sorted_pins(pmos_insts[0], "S")[-1]
        vdd_pin = min(self.get_pins("vdd_write_bl"), key=lambda x: x.by())
        self.add_rect(METAL1, vector(source_pin.lx(), vdd_pin.cy()),
                      width=source_pin.width(),
                      height=source_pin.by() - vdd_pin.cy())

        gnd_pin = max(self.get_pins("gnd"), key=lambda x: x.uy())
        self.add_m1_m3_power_via(self, gnd_pin)

        vdd_pin = [x for x in self.get_pins("vdd_write_bl") if x.layer == METAL1][0]
        self.add_m1_m3_power_via(self, vdd_pin)

    def add_boundary(self):
        super().add_boundary()
        # magic doesn't like tx boundaries extending past boundary so add 'fake' boundary to include tx
        left_x = self.get_max_shape(BOUNDARY, "lx").lx()
        right_x = self.get_max_shape(BOUNDARY, "rx").rx()
        self.add_rect("boundary", offset=vector(left_x, 0), width=right_x - left_x,
                      height=self.height)
