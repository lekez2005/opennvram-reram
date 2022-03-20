import debug
import tech
from base import well_active_contacts
from base.analog_cell_mixin import AnalogMixin
from base.contact import m1m2, m2m3, poly_contact, cross_poly, cross_m1m2, cross_m2m3, well_contact
from base.design import design, ACTIVE, METAL2, METAL1, METAL3, POLY, PWELL, NIMP, PIMP
from base.flatten_layout import flatten_rects
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from globals import OPTS
from modules.reram.bitcell_aligned_pgate import BitcellAlignedPgate
from pgates.ptx import ptx
from tech import add_tech_layers


class WriteDriverMuxLogic(BitcellAlignedPgate, design):

    @classmethod
    def get_name(cls, size=None, name=None):
        return name or OPTS.write_driver_logic_mod

    def add_inst(self, name, mod, offset=None, mirror="R0", rotate=0):
        inst = super().add_inst(name, mod, offset, mirror, rotate)
        if isinstance(mod, ptx):
            self.connect_inst([], check=False)
        return inst

    def create_layout(self):
        self.get_spice_parser()
        self.create_modules()
        self.add_mask_en()
        self.add_p_enables()
        self.add_n_enables()
        self.add_m3_power()
        self.add_boundary()
        self.flatten_tx()
        add_tech_layers(self)

    def get_all_tx_drivers(self, node_name):
        drivers = self.spice_parser.extract_res_paths_for_pin(node_name,
                                                              module_name=self.name)
        drivers_dict = {}
        for key in ["n", "p"]:
            drivers_dict[key] = []
            for driver_list in drivers:
                for spice_statement in driver_list:
                    _ = self.spice_parser.extract_all_tx_properties(spice_statement)
                    tx_type, m, nf, finger_width = _
                    if tx_type == key:
                        drivers_dict[key].append((m, nf, finger_width))
        return drivers_dict

    def get_one_nmos_pmos_driver(self, node_name):
        drivers = self.get_all_tx_drivers(node_name)
        _, nmos_nf, nmos_finger_width = drivers["n"][0]
        _, pmos_nf, pmos_finger_width = drivers["p"][0]
        debug.info(2, "%s: nmos = (%d, %.3g), pmos = (%d, %.3g)", node_name, nmos_nf,
                   nmos_finger_width, pmos_nf, pmos_finger_width)
        return (nmos_nf, nmos_finger_width), (pmos_nf, pmos_finger_width)

    def flatten_tx(self, *args):
        tx_insts = [x for x in self.insts if isinstance(x.mod, ptx)]
        tx_indices = [x for x in range(len(self.insts))
                      if isinstance(self.insts[x].mod, ptx)]
        flatten_rects(self, tx_insts, inst_indices=tx_indices, skip_export_spice=True)

    def create_modules(self):
        self.bottom_space = self.calculate_bottom_space()
        super().create_modules()
        """AND gate for mask and en"""
        # extract NAND gate parameters
        # mask_en_bar
        _ = self.get_one_nmos_pmos_driver("mask_en_bar")
        (nmos_nf, nmos_finger_width), (pmos_nf, pmos_finger_width) = _
        self.mask_en_bar_nmos = self.create_ptx_by_width(width=nmos_finger_width, mults=2,
                                                         is_pmos=False,
                                                         active_cont_pos=[0, 2])
        self.mask_en_bar_pmos = self.create_ptx_by_width(width=pmos_finger_width, mults=2,
                                                         is_pmos=True)

        # mask_en (NAND gate inverter)
        _ = self.get_one_nmos_pmos_driver("mask_en")
        (nmos_nf, nmos_finger_width), (pmos_nf, pmos_finger_width) = _
        self.mask_en_nmos = self.create_ptx_by_width(width=nmos_finger_width, mults=1,
                                                     is_pmos=False)
        self.mask_en_pmos = self.create_ptx_by_width(width=pmos_finger_width, mults=1,
                                                     is_pmos=True)

        # enable_p's
        _ = self.get_one_nmos_pmos_driver("bl_p")
        (nmos_nf, nmos_finger_width), (pmos_nf, pmos_finger_width) = _
        self.p_enable_nmos = self.create_ptx_by_width(width=nmos_finger_width, mults=4,
                                                      is_pmos=False,
                                                      active_cont_pos=[0, 2, 4])
        self.p_enable_pmos = self.create_ptx_by_width(width=pmos_finger_width, mults=4,
                                                      is_pmos=True)

        # enable_p's
        _ = self.get_one_nmos_pmos_driver("bl_n")
        (nmos_nf, nmos_finger_width), (pmos_nf, pmos_finger_width) = _
        self.n_enable_nmos = self.create_ptx_by_width(width=nmos_finger_width, mults=4,
                                                      is_pmos=False)
        self.n_enable_pmos = self.create_ptx_by_width(width=pmos_finger_width, mults=4,
                                                      is_pmos=True,
                                                      active_cont_pos=[0, 2, 4])

    def calculate_mid_y_space(self, bottom_inst, top_module: design):
        nmos_space = self.calculate_active_to_poly_cont_mid("nmos")
        pmos_space = self.calculate_active_to_poly_cont_mid("pmos")
        top_active_rect = top_module.get_max_shape(ACTIVE, "by")
        bottom_active_rect = bottom_inst.get_max_shape(ACTIVE, "uy")
        if bottom_inst.mod.tx_type[0] == "n":
            contact_y = bottom_active_rect.uy() + nmos_space
            return contact_y, contact_y + pmos_space - top_active_rect.by()
        else:
            contact_y = bottom_active_rect.uy() + pmos_space
            return contact_y, contact_y + nmos_space - top_active_rect.by()

    def add_mask_en(self):
        # mask_en_bar
        y_shift = max(0, self.mask_en_nmos.active_rect.height -
                      self.mask_en_bar_nmos.active_rect.height)
        y_offset = self.bottom_space - self.mask_en_bar_nmos.active_rect.by() + y_shift
        active_space = self.get_space(ACTIVE)
        x_offset = 0.5 * active_space
        nmos_inst = self.add_inst("mask_en_bar_n", self.mask_en_bar_nmos,
                                  offset=vector(x_offset, y_offset))
        # create space for two staggered poly contacts
        mask_contact_y = (nmos_inst.get_max_shape(ACTIVE, "uy").uy() +
                          self.calculate_active_to_poly_cont_mid("nmos"))
        self.mask_contact_y = mask_contact_y
        en_contact_y = mask_contact_y + self.get_parallel_space(METAL1) + poly_contact.w_2
        self.en_contact_y = en_contact_y
        pmos_y = (en_contact_y + self.calculate_active_to_poly_cont_mid("pmos") -
                  self.mask_en_bar_pmos.active_rect.by())

        pmos_inst = self.add_inst("mask_en_bar_p", self.mask_en_bar_pmos,
                                  offset=vector(x_offset, pmos_y))

        self.join_poly(nmos_inst, pmos_inst)

        self.mask_en_bar_n_inst, self.mask_en_bar_p_inst = nmos_inst, pmos_inst

        # mask_en
        nand_active = nmos_inst.get_max_shape(ACTIVE, "rx")
        inverter_active = self.mask_en_nmos.get_max_shape(ACTIVE, "lx")
        x_offset = nand_active.rx() + active_space - inverter_active.lx()
        y_offset = nand_active.uy() - inverter_active.uy()
        nmos_inst = self.add_inst("mask_en_n", self.mask_en_nmos,
                                  offset=vector(x_offset, y_offset))

        en_bar_contact_y, pmos_y = self.calculate_mid_y_space(nmos_inst, self.mask_en_pmos)
        self.en_bar_contact_y = en_bar_contact_y
        pmos_inst = self.add_inst("mask_en_p", self.mask_en_pmos,
                                  offset=vector(x_offset, pmos_y))

        self.join_poly(nmos_inst, pmos_inst)
        self.mask_en_n_inst, self.mask_en_p_inst = nmos_inst, pmos_inst

        self.route_mask_en_power()
        self.route_mask_en_inputs()
        self.route_mask_en_bar()
        self.extend_mask_en_implants()

    def route_mask_en_power(self):
        self.add_power_tap(0, "gnd", self.mask_en_bar_n_inst, add_m3=False)
        top_pmos_inst = max([self.mask_en_p_inst, self.mask_en_bar_p_inst],
                            key=lambda x: x.uy())
        vdd_y = top_pmos_inst.get_max_shape(ACTIVE, "uy").uy() + self.bottom_space - self.rail_height
        self.add_power_tap(vdd_y, "vdd", top_pmos_inst, add_m3=False)

        self.route_tx_to_power(self.mask_en_bar_n_inst, "S", [0])
        self.route_tx_to_power(self.mask_en_n_inst, "D")

        self.route_tx_to_power(self.mask_en_bar_p_inst, "S")
        self.route_tx_to_power(self.mask_en_p_inst, "D")

    def route_mask_en_inputs(self):
        mid_tx = self.mask_en_bar_n_inst.get_max_shape(ACTIVE, "uy").cx()
        # mask pin

        pin_height = self.mask_en_bar_n_inst.get_pin("D").height()
        sample_n_contact = calculate_num_contacts(self, pin_height, layer_stack=m1m2,
                                                  return_sample=True)
        nmos_active = self.mask_en_bar_n_inst.get_max_shape(ACTIVE, "by")
        cont_m2_y = nmos_active.cy() - 0.5 * sample_n_contact.h_2
        y_bend = cont_m2_y - self.m2_space - 0.5 * self.m2_width

        x_offset = mid_tx - 0.5 * self.m2_width
        y_offset = self.en_contact_y - 0.5 * m2m3.h_1 - self.m2_space - 0.5 * m1m2.h_2

        self.add_path(METAL2, [vector(mid_tx, y_offset),
                               vector(mid_tx, y_bend),
                               vector(self.mid_x, y_bend)])

        self.add_layout_pin("mask", METAL2, vector(self.mid_x - 0.5 * self.m2_width, 0),
                            height=y_bend + 0.5 * self.m2_width)
        offset = vector(x_offset + 0.5 * self.m2_width, y_offset)
        self.add_cross_contact_center(cross_m1m2, offset, rotate=True)

        poly_rect = self.get_sorted_pins(self.mask_en_bar_n_inst, "G")[0]

        poly_offset = vector(poly_rect.rx() - 0.5 * poly_contact.w_1, self.mask_contact_y)
        self.add_cross_contact_center(cross_poly, poly_offset)
        self.add_rect(METAL1, poly_offset - vector(0, 0.5 * poly_contact.w_2),
                      width=offset.x - poly_offset.x + 0.5 * m1m2.h_1,
                      height=poly_contact.w_2)

        # en pin
        poly_rect = self.get_sorted_pins(self.mask_en_bar_n_inst, "G")[1]
        poly_offset = vector(poly_rect.lx() + 0.5 * poly_contact.w_1, self.en_contact_y)
        self.add_cross_contact_center(cross_poly, poly_offset)
        self.add_cross_contact_center(cross_m1m2, vector(mid_tx, self.en_contact_y),
                                      rotate=True)
        self.add_cross_contact_center(cross_m2m3, vector(mid_tx, self.en_contact_y))
        self.add_rect(METAL1, poly_offset - vector(0, 0.5 * poly_contact.w_2),
                      width=mid_tx - poly_offset.x, height=poly_contact.w_2)
        self.add_layout_pin("en", METAL3, vector(0, self.en_contact_y - 0.5 * self.bus_width),
                            height=self.bus_width, width=self.width)

    def route_mask_en_bar(self):
        vdd_top = max(self.get_pins("vdd"), key=lambda x: x.uy()).uy()
        en_bar_nmos_pin = self.mask_en_bar_n_inst.get_pin("D")
        en_bar_pmos_pin = self.mask_en_bar_p_inst.get_pin("D")

        # join en_bar
        x_offset = en_bar_nmos_pin.cx() - 0.5 * self.m2_width
        height = en_bar_pmos_pin.cy() - en_bar_nmos_pin.cy() + 0.5 * self.m2_width
        self.add_rect(METAL2, vector(x_offset, en_bar_nmos_pin.cy()),
                      height=height)
        self.add_rect(METAL2, vector(en_bar_pmos_pin.cx(), en_bar_pmos_pin.cy() -
                                     0.5 * self.m2_width),
                      width=x_offset - en_bar_pmos_pin.cx())
        offset = vector(en_bar_pmos_pin.cx() - 0.5 * self.m2_width, en_bar_pmos_pin.cy())
        self.mask_en_bar_rect = self.add_rect(METAL2, offset, height=vdd_top - offset.y)

        # join en
        en_nmos_pin = self.mask_en_n_inst.get_pin("S")
        en_pmos_pin = self.mask_en_p_inst.get_pin("S")
        x_offset = en_nmos_pin.cx() - 0.5 * m1m2.w_2
        y_bend = (vdd_top - 0.5 * self.rail_height - 0.5 * max(m2m3.h_1, m1m2.h_2) -
                  self.get_line_end_space(METAL2) - self.m2_width - tech.drc["grid"])
        self.add_rect(METAL2, vector(x_offset, en_nmos_pin.cy()),
                      width=m1m2.w_2,
                      height=y_bend - en_nmos_pin.cy() + self.m2_width)
        rect_x = self.mid_x - 0.5 * self.m2_width
        self.add_rect(METAL2, vector(rect_x, y_bend), width=x_offset - rect_x)
        self.mask_en_rect = self.add_rect(METAL2, vector(rect_x, y_bend),
                                          height=vdd_top - y_bend)

        # add vias
        for pin in [en_bar_nmos_pin, en_bar_pmos_pin, en_nmos_pin, en_pmos_pin]:
            num_contacts = calculate_num_contacts(self, pin.height(), layer_stack=m1m2)
            self.add_contact_center(m1m2.layer_stack, pin.center(),
                                    size=[1, num_contacts])

        # connect en_bar to inverter input
        y_offset = self.en_bar_contact_y
        poly_rect = self.mask_en_n_inst.get_pin("G")
        self.add_cross_contact_center(cross_poly, vector(poly_rect.cx(), y_offset))
        x_offset = en_bar_nmos_pin.cx() - 0.5 * self.m2_width + 0.5 * m1m2.h_1
        self.add_cross_contact_center(cross_m1m2, vector(x_offset, y_offset), rotate=True)
        self.add_rect(METAL1, vector(x_offset, y_offset - 0.5 * poly_contact.w_2),
                      width=poly_rect.cx() - x_offset, height=poly_contact.w_2)

    def extend_mask_en_implants(self):
        pmos_insts = [self.mask_en_bar_p_inst, self.mask_en_p_inst]
        nmos_insts = [self.mask_en_bar_n_inst, self.mask_en_n_inst]
        layers = [NIMP, PIMP]
        for i, layer in enumerate(layers):
            insts = nmos_insts if i == 0 else pmos_insts
            implants = [x.get_max_shape(layer, "uy") for x in insts]
            uy = min(map(lambda x: x.uy(), implants))
            by = max(map(lambda x: x.by(), implants))
            self.add_rect(layer, vector(0, by), width=self.width, height=uy - by)

    @staticmethod
    def add_m2_to_mid_poly_contacts(self, gate_pins, contact_y, add_m1_m2=True):
        left_pin, right_pin = gate_pins[1:3]

        if poly_contact.w_1 > gate_pins[0].width():
            self.add_rect(POLY, vector(left_pin.cx(), contact_y - 0.5 * poly_contact.h_1),
                          width=right_pin.cx() - left_pin.cx(), height=poly_contact.h_1)
            poly_contact_indices = [1]
        else:
            poly_contact_indices = [1, 2]

        mid_x = 0.5 * (left_pin.cx() + right_pin.cx())
        for index in poly_contact_indices:
            gate_pin = gate_pins[index]
            if gate_pin == left_pin:
                x_offset = gate_pin.lx() + 0.5 * poly_contact.w_1
            else:
                x_offset = gate_pin.rx() - 0.5 * poly_contact.w_1
            self.add_cross_contact_center(cross_poly, vector(x_offset, contact_y))
            if add_m1_m2:
                self.add_cross_contact_center(cross_m1m2, vector(mid_x, contact_y),
                                              rotate=True)
        return mid_x

    def add_p_enables(self):
        vdd_pin = max(self.get_pins("vdd"), key=lambda x: x.uy())
        vdd_y = vdd_pin.by()

        y_offset = vdd_y + self.bottom_space - self.p_enable_pmos.active_rect.by()
        x_offset = self.mid_x - 0.5 * self.p_enable_pmos.width
        pmos_inst = self.add_inst("p_enable_pmos", self.p_enable_pmos,
                                  vector(x_offset, y_offset))

        well_active_contacts.extend_tx_well(self, pmos_inst, vdd_pin)

        contact_y, nmos_y = self.calculate_mid_y_space(pmos_inst, self.p_enable_nmos)
        nmos_inst = self.add_inst("p_enable_nmos", self.p_enable_nmos,
                                  vector(x_offset, nmos_y))

        self.join_poly(pmos_inst, nmos_inst)

        self.p_enable_nmos_inst = nmos_inst
        self.p_enable_pmos_inst = pmos_inst

        # en_bar
        en_rect = self.mask_en_rect
        bend_y = en_rect.uy() - 0.5 * self.m2_width
        self.add_path(METAL2, [vector(en_rect.cx(), bend_y),
                               vector(self.mid_x, bend_y),
                               vector(self.mid_x, contact_y)])
        gate_pins = self.get_sorted_pins(pmos_inst, "G")

        self.add_m2_to_mid_poly_contacts(self, gate_pins, contact_y)

        # data and data_bar
        pin_names = ["data", "data_bar"]
        pin_indices = [0, -1]
        drain_pins = [self.get_sorted_pins(self.mask_en_bar_n_inst, "S")[0],
                      self.get_sorted_pins(pmos_inst, "S")[-1]]
        for i in range(2):
            pin = drain_pins[i]
            self.add_layout_pin(pin_names[i], METAL2,
                                vector(pin.cx() - 0.5 * self.m2_width, 0),
                                height=contact_y)
            gate_pin = gate_pins[pin_indices[i]]
            if i == 0:
                x_offset = gate_pin.rx() - 0.5 * poly_contact.w_1
            else:
                x_offset = gate_pin.lx() + 0.5 * poly_contact.w_1
            self.add_cross_contact_center(cross_poly, vector(x_offset, contact_y))
            self.add_cross_contact_center(cross_m1m2, vector(pin.cx(), contact_y),
                                          rotate=True)

        self.route_p_enables()

    def add_mid_drain_contact(self, drain_pin):
        num_contacts = calculate_num_contacts(self, drain_pin.height(),
                                              layer_stack=m1m2.layer_stack)
        self.add_contact_center(m1m2.layer_stack, drain_pin.center(),
                                size=[1, num_contacts])

    def route_p_enables(self):
        y_offset = (self.p_enable_nmos_inst.get_max_shape(ACTIVE, "uy").uy() +
                    self.bottom_space - self.rail_height)
        self.add_layout_pin("gnd", METAL1, vector(0, y_offset), width=self.width,
                            height=self.rail_height)
        # TODO min tap area constraints should be factored into rail height
        tap_offset = vector(self.mid_x, y_offset + 0.5 * self.rail_height)
        self.add_contact_center(layers=well_contact.layer_stack, offset=tap_offset,
                                rotate=90, size=[1, 2],
                                well_type=PWELL, implant_type=PWELL[0])

        self.route_tx_to_power(self.p_enable_pmos_inst, "S")
        self.route_tx_to_power(self.p_enable_nmos_inst, "D")

        # switch mask_en_bar_rect to m3
        rect = self.mask_en_bar_rect
        vdd_pin = max(self.get_pins("vdd"), key=lambda x: x.uy())
        gnd_pin = max(self.get_pins("gnd"), key=lambda x: x.uy())
        via_y = vdd_pin.uy() + self.get_space(METAL2) + 0.5 * m2m3.h_2
        self.add_rect(METAL2, rect.ul(), width=rect.width, height=via_y - rect.uy())
        self.add_contact_center(m2m3.layer_stack, vector(rect.cx(), via_y))
        y_top = gnd_pin.by() - self.get_line_end_space(METAL3) - 0.5 * m2m3.w_2
        offset = vector(rect.cx() - 0.5 * self.m3_width, via_y)
        self.mask_en_bar_rect = self.add_rect(METAL3, offset, height=y_top - offset.y)

        # connect pmos to nmos drain
        enable_p_rects = []
        pmos_drain_pins = self.get_sorted_pins(self.p_enable_pmos_inst, "D")
        nmos_pins = self.get_sorted_pins(self.p_enable_nmos_inst, "S")
        top_y = self.p_enable_pmos_inst.get_max_shape(ACTIVE, "uy").uy()
        for i in range(2):
            drain_pin = pmos_drain_pins[i]
            if i == 0:
                bottom_y = via_y + 0.5 * m2m3.h_2 + self.get_space(METAL2)
            else:
                bottom_y = drain_pin.by()
            num_contacts = calculate_num_contacts(self, top_y - bottom_y,
                                                  layer_stack=m1m2.layer_stack)
            mid_pmos_via_y = 0.5 * (top_y + bottom_y)
            offset = vector(drain_pin.cx(), mid_pmos_via_y)
            self.add_contact_center(m1m2.layer_stack, offset, size=[1, num_contacts])

            nmos_pin = nmos_pins[i]
            self.add_mid_drain_contact(nmos_pin)
            y_top = nmos_pin.cy() - 0.5 * self.m2_width
            self.add_rect(METAL2, vector(drain_pin.cx() -
                                         0.5 * self.m2_width, mid_pmos_via_y),
                          height=y_top + self.m2_width - mid_pmos_via_y)
            self.add_rect(METAL2, vector(nmos_pin.cx(), y_top),
                          width=drain_pin.cx() - nmos_pin.cx())

            offset = vector(nmos_pin.cx() - 0.5 * self.m2_width, nmos_pin.cy())
            enable_p_rects.append(self.add_rect(METAL2, offset,
                                                height=gnd_pin.uy() - offset.y))

        self.enable_bl_p, self.enable_br_p = enable_p_rects

    def add_n_enables(self):
        gnd_pin = max(self.get_pins("gnd"), key=lambda x: x.uy())
        y_offset = gnd_pin.by() + self.bottom_space - self.n_enable_nmos.active_rect.by()
        x_offset = self.mid_x - 0.5 * self.n_enable_nmos.width
        nmos_inst = self.add_inst("n_enable_nmos", self.n_enable_nmos,
                                  vector(x_offset, y_offset))
        contact_y, pmos_y = self.calculate_mid_y_space(nmos_inst, self.n_enable_pmos)
        pmos_inst = self.add_inst("n_enable_pmos", self.n_enable_pmos,
                                  vector(x_offset, pmos_y))

        vdd_y = pmos_inst.get_max_shape(ACTIVE, "uy").uy() + self.bottom_space - self.rail_height
        vdd_pin, _, _ = self.add_power_tap(vdd_y, "vdd", pmos_inst, add_m3=False)
        self.height = vdd_pin.uy()

        self.join_poly(nmos_inst, pmos_inst)
        self.join_poly(self.p_enable_nmos_inst, nmos_inst, indices=[(0, 0), (-1, -1)])

        # mask_en_bar_rect to poly contacts
        rect = self.mask_en_bar_rect
        offset = rect.ul() - vector(0, 0.5 * self.m3_width)
        self.add_rect(METAL3, offset, width=self.mid_x - offset.x)
        self.add_cross_contact_center(cross_m2m3, vector(self.mid_x, rect.uy()))

        self.add_rect(METAL2, vector(self.mid_x - 0.5 * self.m2_width, rect.uy()),
                      height=contact_y - rect.uy())

        gate_pins = self.get_sorted_pins(nmos_inst, "G")
        self.add_m2_to_mid_poly_contacts(self, gate_pins, contact_y)

        # drains to power
        self.route_tx_to_power(nmos_inst, "S")
        self.route_tx_to_power(pmos_inst, "D")

        # join nmos to pmos drains
        nmos_pins = self.get_sorted_pins(nmos_inst, "D")
        pmos_pins = self.get_sorted_pins(pmos_inst, "S")
        pin_names = ["bl_n", "br_n"]
        for i in range(2):
            nmos_pin = nmos_pins[i]
            self.add_mid_drain_contact(nmos_pin)
            offset = vector(nmos_pin.cx() - 0.5 * self.m2_width, nmos_pin.cy())
            self.add_layout_pin(pin_names[i], METAL2, offset, height=self.height - offset.y)

            pmos_pin = pmos_pins[i]
            cont = self.add_contact_center(m1m2.layer_stack,
                                           vector(nmos_pin.cx(), pmos_pin.cy()),
                                           size=[1, 2])
            cont_m1 = cont.get_layer_shapes(METAL1)[0]
            self.add_rect(METAL1, vector(pmos_pin.cx(), cont_m1.by()),
                          width=nmos_pin.cx() - pmos_pin.cx(), height=cont_m1.height)

        # extend bl_p, br_p
        pin_names = ["bl_p", "br_p"]
        rects = [self.enable_bl_p, self.enable_br_p]
        for i in range(2):
            rect = rects[i]
            self.add_layout_pin(pin_names[i], METAL2, rect.ul(), width=rect.width,
                                height=self.height - rect.uy())

    def add_m3_power(self):
        for pin_name in ["vdd", "gnd"]:
            for pin in self.get_pins(pin_name):
                AnalogMixin.add_m1_m3_power_via(self, pin)
