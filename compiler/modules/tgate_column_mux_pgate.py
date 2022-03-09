import debug
import tech
from base import utils
from base.analog_cell_mixin import AnalogMixin
from base.contact import well as well_contact, m1m2, poly as poly_contact, cross_poly, cross_m1m2
from base.design import design, ACTIVE, NIMP, PIMP, POLY, METAL1, METAL2, TAP_ACTIVE, NWELL, PWELL, PO_DUMMY
from base.unique_meta import Unique
from base.vector import vector
from base.well_active_contacts import extend_tx_well, calculate_num_contacts
from globals import OPTS
from pgates.ptx import ptx


class tgate_column_mux_pgate(AnalogMixin, design, metaclass=Unique):

    @classmethod
    def get_sizes(cls):
        inverter_size = getattr(OPTS, "tgate_inverter_size", 1)
        tgate_size = getattr(OPTS, "column_mux_size")
        tgate_pmos_size = getattr(OPTS, "column_mux_pmos_size",
                                  tgate_size * tech.parameter["beta"])
        return inverter_size, tgate_size, tgate_pmos_size

    @classmethod
    def get_name(cls):
        inverter_size, tgate_size, tgate_pmos_size = cls.get_sizes()
        name = f"tgate_col_mux_{inverter_size:.3g}_{tgate_size:.3g}_{tgate_pmos_size:.3g}"
        return name.replace(".", "__")

    def __init__(self):
        design.__init__(self, self.get_name())
        self.create_layout()

    def create_layout(self):
        self.inverter_size, self.tgate_size, self.tgate_pmos_size = self.get_sizes()
        self.setup_layout_constants()
        self.add_sel_inverter()
        self.route_inverter_inputs()
        self.route_inverter_outputs()
        self.add_inverter_tap()

        self.add_tgates()
        self.route_tgate_inputs()
        self.route_tgate_outputs()
        self.add_tgates_taps()

        self.add_netlist()
        self.add_boundary()

        tech.add_tech_layers(self)
        self.augment_power_pins()

    def add_netlist(self):
        self.add_pin_list(["bl", "br", "bl_out", "br_out", "sel", "vdd", "gnd"])

        connect_spice = self.connect_ptx_spice
        # inverters
        connect_spice("inv_nmos", self.inverter_nmos, ["sel_bar", "sel", "gnd", "gnd"], 1)
        connect_spice("inv_pmos", self.inverter_pmos, ["sel_bar", "sel", "vdd", "vdd"], 1)
        connect_spice("buf_nmos", self.inverter_nmos, ["sel_buf", "sel_bar", "gnd", "gnd"], 1)
        connect_spice("buf_pmos", self.inverter_pmos,
                      ["sel_buf", "sel_bar", "vdd", "vdd"], 1)

        # tgates
        nmos_insts = self.tgate_nmos_insts
        connect_spice("bl_nmos", nmos_insts[0], ["bl", "sel_buf", "bl_out", "gnd"])
        connect_spice("br_nmos", nmos_insts[1], ["br", "sel_buf", "br_out", "gnd"])

        pmos_insts = self.tgate_pmos_insts
        connect_spice("bl_pmos", pmos_insts[0], ["bl", "sel_bar", "bl_out", "vdd"])
        connect_spice("br_pmos", pmos_insts[1], ["br", "sel_bar", "br_out", "vdd"])

    def setup_layout_constants(self):
        self.bitcell = self.create_mod_from_str(OPTS.bitcell)
        self.width = self.bitcell.width
        self.mid_x = utils.round_to_grid(0.5 * self.width)
        self.bl_width = self.poly_pitch - self.get_parallel_space(METAL2)

        # nmos_y
        y_offset = (self.bl_width +  # bitline pin top
                    self.get_parallel_space(METAL2) + self.m2_width +  # sel_bend top
                    self.get_line_end_space(METAL2) + 0.5 * m1m2.h_2)  # cont mid
        self.inv_cont_y = y_offset

        self.bot_gnd_y = (self.inv_cont_y - 0.5 * max(m1m2.h_1, poly_contact.h_2) -
                          self.get_line_end_space(METAL1) - self.rail_height)

        self.end_to_poly = ptx.calculate_end_to_poly()
        sample_ptx = ptx(mults=3, dummy_pos=[1, 2])
        poly_gates = list(sorted(sample_ptx.get_pins("G"), key=lambda x: x.lx()))

        poly_to_poly = poly_gates[2].cx() - poly_gates[0].cx() - sample_ptx.poly_width
        # takes dummy poly into account
        self.ptx_active_space = max(poly_to_poly - 2 * self.end_to_poly,
                                    self.get_space(ACTIVE))
        debug.info(2, "ptx active space is %.3g", self.ptx_active_space)

        # inverter number of fingers
        # inverter_fingers = calculate_num_fingers(self.width - self.ptx_active_space)
        # inverter_fingers = math.floor(inverter_fingers / 2)
        self.inverter_fingers = 1  # to permit space for body taps

        debug.info(2, "number of inverter fingers is %d", self.inverter_fingers)

        # fingers for tgate
        # calculate mid space
        left_source = self.get_sorted_pins(sample_ptx, "S")[0]
        self.tgate_mid_space = 2 * (0.5 * self.m2_width + self.get_line_end_space(METAL2) +
                                    0.5 * m1m2.w_2 - left_source.cx())

        available_width = self.mid_x - 0.5 * (self.ptx_active_space + self.tgate_mid_space)
        self.num_tgate_fingers = self.calculate_num_fingers(available_width, sample_ptx)

    def create_ptx(self, tx_width, tx_mults, is_pmos=False, *args, **kwargs):
        kwargs.setdefault("dummy_pos", [1, 2])
        tx_type = "pmos" if is_pmos else "nmos"
        tx = ptx(width=tx_width, mults=tx_mults, tx_type=tx_type,
                 contact_poly=False, *args, **kwargs)
        self.add_mod(tx)
        return tx

    def add_sel_inverter(self):
        """Add sel inverter and buffer nmos/pmos"""
        dummy_pos = list(range(4))
        # add nmos
        nmos_width = self.inverter_size * self.min_tx_width
        finger_width = nmos_width / self.inverter_fingers
        if finger_width < self.min_tx_width:
            self.inverter_fingers = 1
            finger_width = nmos_width
        nmos = self.create_ptx(finger_width, self.inverter_fingers * 2, dummy_pos=dummy_pos)

        nmos_to_mid = ptx.calculate_active_to_poly_cont_mid(nmos.tx_type, nmos.tx_width,
                                                            use_m1m2=True)
        y_offset = self.inv_cont_y + nmos_to_mid - nmos.active_rect.by()

        x_offset = self.mid_x - 0.5 * nmos.width
        self.inverter_nmos = self.add_inst("inv_nmos", nmos, vector(x_offset, y_offset))
        self.connect_inst([], check=False)

        # gnd
        top_m1 = max(self.inverter_nmos.get_layer_shapes(METAL1), key=lambda x: x.uy())
        gnd_y = top_m1.uy() + self.get_line_end_space(METAL1)
        gnd_pin = self.add_layout_pin("gnd", METAL1, vector(0, gnd_y), width=self.width,
                                      height=self.rail_height)

        # add pmos
        pmos_width = tech.parameter["beta"] * nmos_width
        finger_width = pmos_width / self.inverter_fingers
        pmos = self.create_ptx(finger_width, self.inverter_fingers * 2, is_pmos=True,
                               dummy_pos=dummy_pos)

        # based on active space
        active_to_active = 2 * tech.drc.get("implant_to_channel")
        nmos_active_top = self.inverter_nmos.by() + nmos.active_rect.uy()
        y_offset = nmos_active_top + active_to_active - pmos.active_rect.by()

        # based on active to nwell
        pmos_nwell = min(pmos.get_layer_shapes(NWELL), key=lambda x: x.by())
        nwell_active_space = tech.drc.get("nwell_to_active_space")
        y_offset = max(y_offset, nmos_active_top + nwell_active_space - pmos_nwell.by())

        # based on m1 space
        m1m2_cont = calculate_num_contacts(None, pmos.tx_width, return_sample=True,
                                           layer_stack=m1m2)
        m1_y = min(pmos.get_layer_shapes(METAL1), key=lambda x: x.by()).by()
        m1_y = min(m1_y, pmos.active_rect.cy() - 0.5 * m1m2_cont.h_1)
        y_offset = max(y_offset, gnd_pin.uy() + self.get_line_end_space(METAL1) - m1_y)

        self.inverter_pmos = self.add_inst("inv_pmos", pmos, vector(x_offset, y_offset))
        self.connect_inst([], check=False)

        # add vdd
        rail_to_active = self.calculate_rail_to_active(pmos, x_axis_mirror=True)
        vdd_y = (self.inverter_pmos.by() + pmos.active_rect.uy() +
                 rail_to_active - self.rail_height)

        pin, _, _ = self.add_power_tap("vdd", vdd_y)
        extend_tx_well(self, self.inverter_pmos, pin)

        ptx.flatten_tx_inst(self, self.inverter_nmos)
        ptx.flatten_tx_inst(self, self.inverter_pmos)

    def add_inverter_tap(self):
        """Add nmos tap beside nmos"""
        if self.has_dummy:
            # will clash with dummies, adjacent module might have tap
            self.add_power_tap("gnd", self.bot_gnd_y)
            return
        # add nmos tap
        nwell = min(self.get_layer_shapes(NWELL), key=lambda x: x.by())
        tap_to_nwell = tech.drc.get("nwell_to_tap_active_space",
                                    tech.drc.get("nwell_to_active_space", 0))

        ptap_top = nwell.by() - max(tap_to_nwell, self.implant_enclose_active)
        gnd_pin = max(self.get_pins("gnd"), key=lambda x: x.uy())

        tap_width = well_contact.w_1
        _, tap_height = self.calculate_min_area_fill(tap_width, layer=TAP_ACTIVE)

        x_offset = - 0.5 * well_contact.contact_width
        tap_rect = self.add_rect(TAP_ACTIVE, vector(x_offset, ptap_top), width=tap_width,
                                 height=-tap_height)
        mid_offset = vector(tap_rect.cx(), tap_rect.cy())
        m1_x = - 0.5 * well_contact.w_1
        self.add_rect(METAL1, vector(m1_x, gnd_pin.by()), width=gnd_pin.lx() - m1_x,
                      height=gnd_pin.height())
        self.add_ptap(tap_height, mid_offset)

        extend_tx_well(self, self.inverter_nmos, gnd_pin)

    def add_ptap(self, tap_height, mid_offset, rotate=0):
        num_contacts = calculate_num_contacts(self, tap_height,
                                              layer_stack=well_contact.layer_stack)
        return self.add_contact_center(well_contact.layer_stack, mid_offset,
                                       implant_type="p", well_type=PWELL,
                                       size=[1, num_contacts], rotate=rotate)

    def route_inverter_inputs(self):
        """Sel pin + sel_bar to sel_buf input"""
        nmos_poly_pins = self.get_sorted_pins(self.inverter_nmos, "G")
        pmos_poly_pins = self.get_sorted_pins(self.inverter_pmos, "G")

        # join poly
        if self.has_dummy:
            all_nmos = [(POLY, nmos_poly_pins),
                        (PO_DUMMY, self.inverter_nmos.get_layer_shapes(PO_DUMMY))]
            all_pmos = [(POLY, pmos_poly_pins),
                        (PO_DUMMY, self.inverter_pmos.get_layer_shapes(PO_DUMMY))]
        else:
            all_nmos, all_pmos = [(POLY, nmos_poly_pins)], [(POLY, pmos_poly_pins)]
        for (layer, nmos_rects), (_, pmos_rects) in zip(all_nmos, all_pmos):
            for nmos_rect, pmos_rect in zip(nmos_rects, pmos_rects):
                self.add_rect(layer, nmos_rect.ul(), width=nmos_rect.rx() - nmos_rect.lx(),
                              height=pmos_rect.by() - nmos_rect.uy())

        # sel in
        cont_y = self.inv_cont_y
        fill_height = max(poly_contact.h_2, m1m2.h_1)
        _, fill_width = self.calculate_min_area_fill(fill_height, layer=METAL1)

        sel_x = self.mid_x - 0.5 * self.m2_width - self.get_line_end_space(METAL2) - m1m2.w_2

        for i in range(2):
            nmos_poly = nmos_poly_pins[i]
            poly_y = cont_y - 0.5 * poly_contact.h_1
            if i == 0:
                via_x = nmos_poly.rx() - 0.5 * poly_contact.w_1
                fill_x = via_x + 0.5 * poly_contact.w_2 - 0.5 * fill_width
                if sel_x < via_x - 0.5 * fill_width:
                    self.add_rect(METAL1, vector(sel_x, cont_y - 0.5 * fill_height),
                                  width=via_x - sel_x, height=fill_height)
            else:
                via_x = nmos_poly.lx() + 0.5 * poly_contact.w_1
                fill_x = via_x - 0.5 * poly_contact.w_2 + 0.5 * fill_width

            self.add_contact_center(poly_contact.layer_stack, vector(via_x, cont_y))
            self.add_rect(POLY, vector(nmos_poly.lx(), poly_y), width=nmos_poly.width(),
                          height=nmos_poly.by() - poly_y)

            self.add_rect_center(METAL1, vector(fill_x, cont_y), width=fill_width,
                                 height=fill_height)
            if i == 0:
                self.add_sel_pin(sel_x, cont_y)

        # sel_bar to sel_buf_in
        source_pin = self.get_sorted_pins(self.inverter_nmos, "S")[0]
        start_y = source_pin.cy() - 0.5 * m1m2.h_2 + 0.5 * self.m2_width
        end_y = cont_y + 0.5 * m1m2.h_2 - 0.5 * self.m2_width
        via_x = nmos_poly_pins[1].cx()
        self.add_path(METAL2, [vector(source_pin.cx(), start_y),
                               vector(self.mid_x, start_y),
                               vector(self.mid_x, end_y),
                               vector(via_x, end_y)])
        self.add_contact_center(m1m2.layer_stack, vector(via_x, cont_y))

    def add_sel_pin(self, sel_x, cont_y):
        self.add_contact_center(m1m2.layer_stack,
                                vector(sel_x + 0.5 * self.m2_width, cont_y))
        y_bend = cont_y - 0.5 * m1m2.h_2 - self.m2_width - self.get_line_end_space(METAL2)

        offset = vector(sel_x, y_bend)
        self.add_rect(METAL2, offset, width=self.mid_x - offset.x)
        self.add_rect(METAL2, offset, height=cont_y - offset.y)
        self.add_layout_pin("sel", METAL2, vector(self.mid_x - 0.5 * self.m2_width, 0),
                            height=offset.y + self.m2_width)

    def route_inverter_outputs(self):
        rails = []
        cont = None
        for tx_inst in [self.inverter_nmos, self.inverter_pmos]:
            source_pins = self.get_sorted_pins(tx_inst, "S")
            for i, pin in enumerate(source_pins):
                # add m1m2 contacts
                num_contacts = calculate_num_contacts(self, tx_inst.mod.tx_width,
                                                      layer_stack=m1m2)
                cont = self.add_contact_center(m1m2.layer_stack, pin.center(),
                                               size=[1, num_contacts])
                fill_height = cont.mod.h_1
                _, fill_width = self.calculate_min_area_fill(fill_height, layer=METAL1)
                if fill_width > cont.mod.w_1:
                    if i == 0:
                        fill_x = pin.rx() - fill_width
                    else:
                        fill_x = pin.lx()
                    self.add_rect(METAL1, vector(fill_x, pin.cy() - 0.5 * fill_height),
                                  width=fill_width, height=fill_height)
                # join nmos, pmos
                rail_top = pin.cy() + 0.5 * cont.mod.h_2
                rail_y = self.inverter_nmos.cy()
                rail_x = pin.cx() - 0.5 * self.m2_width
                if tx_inst == self.inverter_pmos:
                    rails.append(self.add_rect(METAL2, vector(rail_x, rail_y),
                                               height=rail_top - rail_y))

            # power
            drain_pin = tx_inst.get_pin("D")
            width = 1.5 * drain_pin.width()
            if tx_inst == self.inverter_nmos:
                target_pin = max(self.get_pins("gnd"), key=lambda x: x.uy())
            else:
                target_pin = self.get_pin("vdd")
            y_offset = min(drain_pin.cy(), drain_pin.cy() - 0.5 * cont.mod.h_1)
            self.add_rect(METAL1, vector(drain_pin.cx() - 0.5 * width, y_offset),
                          width=width, height=target_pin.cy() - y_offset)
        self.sel_bar_rail, self.sel_buf_rail = rails

    def add_tgates(self):
        num_fingers = self.num_tgate_fingers
        pmos_width = self.tgate_pmos_size * self.min_tx_width
        finger_width = pmos_width / self.num_tgate_fingers
        pmos = self.create_ptx(finger_width, tx_mults=num_fingers, is_pmos=True)

        nmos_width = self.tgate_size * self.min_tx_width
        finger_width = nmos_width / self.num_tgate_fingers
        nmos = self.create_ptx(finger_width, tx_mults=num_fingers, is_pmos=False)

        # add pmos
        vdd_pin = self.get_pin("vdd")
        self.tgate_p_cont_y = (vdd_pin.uy() + self.get_parallel_space(METAL1) +
                               0.5 * poly_contact.h_2)
        cont_to_active = ptx.calculate_active_to_poly_cont_mid(pmos.tx_type, pmos.tx_width,
                                                               use_m1m2=True)
        pmos_y = self.tgate_p_cont_y + cont_to_active - pmos.active_rect.by()
        # calculate pmos_y based on implant space
        if self.implant_enclose_poly:
            top_implant = max(self.get_layer_shapes(NIMP, recursive=True),
                              key=lambda x: x.uy())
            pimplant_y = (pmos.active_rect.by() - cont_to_active - 0.5 * poly_contact.h_1)
            pmos_y_2 = top_implant.uy() - pimplant_y
            if pmos_y_2 > pmos_y:
                self.tgate_p_cont_y = pmos_y_2 + pmos.active_rect.by() - cont_to_active
            pmos_y = max(pmos_y, pmos_y_2)

        pmos_poly_top = pmos_y + pmos.get_pins("G")[0].uy()
        self.tgate_n_cont_y = pmos_poly_top + self.poly_vert_space + 0.5 * poly_contact.h_1
        cont_to_active = ptx.calculate_active_to_poly_cont_mid(nmos.tx_type, nmos.tx_width,
                                                               use_m1m2=True)
        nmos_y = self.tgate_n_cont_y + cont_to_active - nmos.active_rect.by()

        self.tgate_pmos_insts = pmos_insts = []
        self.tgate_nmos_insts = nmos_insts = []
        min_mid_space = 0.5 * self.tgate_mid_space - pmos.active_rect.lx()
        if self.has_dummy:
            # align dummies
            poly_pitch = pmos.poly_pitch
            poly_space = pmos.poly_space
            mid_space = utils.round_to_grid(0.5 * poly_space + poly_pitch - pmos.end_to_poly)
            mid_space = max(min_mid_space, mid_space)
        else:
            # distribute space
            available_space = self.mid_x - pmos.active_rect.width
            active_space = 0.5 * self.ptx_active_space
            # first see if there is enough space to assign to both sides
            if available_space >= 2 * max(min_mid_space, active_space):
                mid_space = available_space / 2
            else:
                extra_space = available_space - (min_mid_space + active_space)
                mid_space = min_mid_space + max(0, utils.floor(extra_space / 2))

        self.tgate_mid_space = 2 * mid_space

        pmos_names = ["bl_tgate_p", "br_tgate_p"]
        nmos_names = ["bl_tgate_n", "br_tgate_n"]
        for i in range(2):
            if i == 0:
                x_offset = self.mid_x - mid_space - pmos.active_rect.width
            else:
                x_offset = self.mid_x + mid_space
            pmos_inst = self.add_inst(pmos_names[i], pmos, vector(x_offset, pmos_y))
            pmos_insts.append(pmos_inst)
            self.connect_inst([], check=False)

            nmos_inst = self.add_inst(nmos_names[i], nmos, vector(x_offset, nmos_y))
            nmos_insts.append(nmos_inst)
            self.connect_inst([], check=False)

        for inst in pmos_insts:
            extend_tx_well(self, inst, vdd_pin)

        for inst in nmos_insts + pmos_insts:
            ptx.flatten_tx_inst(self, inst)

        # calculate gnd y offset
        nmos_inst = self.tgate_nmos_insts[0]
        # put tap above
        active_top = max(nmos_inst.get_layer_shapes(ACTIVE), key=lambda x: x.uy()).uy()
        rail_top = active_top + self.calculate_rail_to_active(nmos_inst.mod)
        self.height = rail_top
        self.top_gnd_y = rail_top - self.rail_height

    def route_tgate_inputs(self):
        # sel bar
        pmos_poly_pins = (self.get_sorted_pins(self.tgate_pmos_insts[0], "G") +
                          self.get_sorted_pins(self.tgate_pmos_insts[1], "G"))
        horz_poly = pmos_poly_pins[0].width() < poly_contact.w_1

        def connect_poly(poly_pins, cont_y, rail):
            bottom_y = cont_y - 0.5 * poly_contact.h_1
            # contact bottom to poly bottom
            for pin in poly_pins:
                self.add_rect(POLY, vector(pin.lx(), bottom_y), width=pin.width(),
                              height=pin.by() - bottom_y)
            # add m1 across all
            start_x = poly_pins[0].cx()
            end_x = poly_pins[-1].cx()

            self.add_rect(METAL1, vector(start_x, cont_y - 0.5 * poly_contact.w_2),
                          width=end_x - start_x, height=poly_contact.w_2)

            if horz_poly:
                index_step = 2
                self.add_rect(POLY, vector(start_x, bottom_y),
                              width=end_x - start_x, height=poly_contact.h_1)
            else:
                index_step = 1
            for pin in poly_pins[::index_step]:
                self.add_cross_contact_center(cross_poly, vector(pin.cx(), cont_y))

            # add m2 and via
            self.add_rect(METAL2, rail.ul(), width=rail.rx() - rail.lx(),
                          height=cont_y - rail.uy())
            if poly_pins == pmos_poly_pins:
                via_x = rail.cx() - 0.5 * self.m2_width + 0.5 * m1m2.w_2
            else:
                via_x = rail.cx()
            self.add_cross_contact_center(cross_m1m2, vector(via_x, cont_y),
                                          rotate=True)

        connect_poly(pmos_poly_pins, self.tgate_p_cont_y, self.sel_bar_rail)

        orig_rail = self.sel_buf_rail
        x_offset = self.mid_x - 0.5 * self.m2_width
        y_offset = orig_rail.uy() - self.m2_width
        offset = vector(x_offset, y_offset)
        self.add_rect(METAL2, offset, width=orig_rail.cx() - offset.x)
        new_rail = self.add_rect(METAL2, offset, width=self.m2_width)

        nmos_poly_pins = (self.get_sorted_pins(self.tgate_nmos_insts[0], "G") +
                          self.get_sorted_pins(self.tgate_nmos_insts[1], "G"))
        connect_poly(nmos_poly_pins, self.tgate_n_cont_y, new_rail)

    def route_tgate_outputs(self):

        sample_nmos_inst = self.tgate_nmos_insts[0]
        sample_pmos_inst = self.tgate_pmos_insts[0]

        sample_n_cont = calculate_num_contacts(self, sample_nmos_inst.mod.tx_width,
                                               layer_stack=m1m2, return_sample=True)
        sample_p_cont = calculate_num_contacts(self, sample_pmos_inst.mod.tx_width,
                                               layer_stack=m1m2, return_sample=True)

        pin_names = ["bl", "br"]
        sample_nmos_pin = self.tgate_nmos_insts[0].get_pins("S")[0]
        nmos_y = sample_nmos_pin.cy()

        nmos_pin_top = nmos_y + 0.5 * sample_n_cont.h_2

        for i, inst in enumerate(self.tgate_pmos_insts):
            source_drains = list(sorted(inst.get_pins("S") + inst.get_pins("D"),
                                        key=lambda x: x.lx()))
            pmos_pin_bot = source_drains[0].cy() - 0.5 * sample_p_cont.h_2

            bitcell_pin = self.bitcell.get_pin(pin_names[i])

            for pin in source_drains:
                self.add_contact_center(m1m2.layer_stack, pin.center(),
                                        size=sample_p_cont.dimensions)
                self.add_contact_center(m1m2.layer_stack, vector(pin.cx(), nmos_y),
                                        size=sample_n_cont.dimensions)
                self.add_rect(METAL2, vector(pin.cx() - 0.5 * self.bl_width, pmos_pin_bot),
                              height=nmos_pin_top - pmos_pin_bot, width=self.bl_width)
            # bitline outputs
            if i == 0:
                target_pin = source_drains[-2]
                out_pins = source_drains[-2::-2]
            else:
                target_pin = source_drains[1]
                out_pins = source_drains[1::2]

            y_offset = (target_pin.cy() - 0.5 * sample_p_cont.h_2 -
                        self.get_line_end_space(METAL2) - self.m2_width)
            for pin in out_pins:
                self.add_rect(METAL2, vector(pin.cx() - 0.5 * self.bl_width, y_offset),
                              height=pmos_pin_bot - y_offset, width=self.bl_width)
            if len(out_pins) > 0:
                self.add_rect(METAL2, vector(out_pins[0].cx(), y_offset),
                              width=out_pins[-1].cx() - out_pins[0].cx())

            self.add_bitline_out(target_pin, y_offset, pin_names[i])

            # bitline inputs
            nmos_inst = self.tgate_nmos_insts[i]
            source_drains = list(sorted(nmos_inst.get_pins("S") + nmos_inst.get_pins("D"),
                                        key=lambda x: x.lx()))
            if i == 0:
                target_pin = source_drains[-1]
                out_pins = source_drains[-1::-2]
            else:
                target_pin = source_drains[0]
                out_pins = source_drains[0::2]

            y_offset = (target_pin.cy() + 0.5 * sample_n_cont.h_2 +
                        self.get_line_end_space(METAL2))
            for pin in out_pins:
                self.add_rect(METAL2, vector(pin.cx() - 0.5 * self.bl_width, nmos_pin_top),
                              height=y_offset - nmos_pin_top + self.bl_width,
                              width=self.bl_width)
            if len(out_pins) > 0:
                self.add_rect(METAL2, vector(out_pins[0].cx(), y_offset),
                              width=out_pins[-1].cx() - out_pins[0].cx())

            self.add_rect(METAL2, vector(target_pin.cx(), y_offset),
                          width=bitcell_pin.cx() - target_pin.cx(), height=self.bl_width)
            self.add_layout_pin(pin_names[i], METAL2, vector(bitcell_pin.lx(), y_offset),
                                width=bitcell_pin.width(),
                                height=self.height - y_offset)

    def add_bitline_out(self, pmos_pin, y_offset, pin_name):
        sel_pin = self.get_pin("sel")
        bitcell_pin = self.bitcell.get_pin(pin_name)
        x_offset = pmos_pin.cx() - 0.5 * self.bl_width

        y_bend = (sel_pin.uy() - self.m2_width - self.get_parallel_space(METAL2) -
                  self.bl_width)
        offset = vector(x_offset, y_bend)
        self.add_rect(METAL2, offset, height=y_offset - offset.y, width=self.bl_width)
        self.add_rect(METAL2, offset, width=bitcell_pin.cx() - offset.x)
        if bitcell_pin.rx() > 0.5 * self.bitcell.width:
            x_offset = bitcell_pin.rx() - self.bl_width
        else:
            x_offset = bitcell_pin.lx()

        self.add_layout_pin(f"{pin_name}_out", METAL2, vector(x_offset, 0),
                            width=self.bl_width,
                            height=offset.y + self.bl_width)

    def add_tgates_taps(self):
        self.add_power_tap("gnd", self.top_gnd_y)

        gnd_pin = max(self.get_pins("gnd"), key=lambda x: x.uy())
        for inst in self.tgate_nmos_insts:
            extend_tx_well(self, inst, gnd_pin)

        vdd_pin = self.get_pin("vdd")
        for inst in self.tgate_pmos_insts:
            extend_tx_well(self, inst, vdd_pin)

        def get_largest_rect_at_inst(inst, layer):
            all_rects = self.get_layer_shapes(layer, recursive=True)
            mid_y = inst.cy()
            mid_x = inst.cx()
            valid_rects = [x for x in all_rects if x.lx() <= mid_x <= x.rx() and
                           x.by() <= mid_y <= x.uy()]
            if not valid_rects:
                return None
            return max(valid_rects, key=lambda x: x.width * x.height)

        # join wells
        if self.has_pwell:
            tgate_nwell = get_largest_rect_at_inst(self.tgate_pmos_insts[0], NWELL)
            tgate_pwell = get_largest_rect_at_inst(self.tgate_nmos_insts[0], PWELL)
            self.add_rect(NWELL, tgate_nwell.ul(), width=tgate_nwell.width,
                          height=tgate_pwell.by() - tgate_nwell.uy())

        # extend inverter implants to width
        for layer in [NIMP, PIMP]:
            for inst in [self.inverter_nmos, self.inverter_pmos]:
                rect = get_largest_rect_at_inst(inst, layer)
                if rect and self.implant_enclose_active:
                    self.add_rect(layer, vector(0, rect.by()), width=self.width,
                                  height=rect.height)

        # join tgate implants
        for layer, insts in zip([NIMP, PIMP], [self.tgate_nmos_insts, self.tgate_pmos_insts]):
            left_inst, right_inst = sorted(insts, key=lambda x: x.lx())
            left_rect = get_largest_rect_at_inst(left_inst, layer)
            right_rect = get_largest_rect_at_inst(right_inst, layer)
            if right_rect.lx() - left_rect.rx() < self.implant_space:
                self.add_rect(layer, left_rect.ll(), height=left_rect.height,
                              width=right_rect.rx() - left_rect.lx())

        well_tap_implant = get_largest_rect_at_inst(self.get_pin("vdd"), NIMP)
        pmos_implant = get_largest_rect_at_inst(self.tgate_pmos_insts[0], PIMP)
        nmos_implant = get_largest_rect_at_inst(self.tgate_nmos_insts[0], NIMP)
        for layer, top, bottom in [[NIMP, pmos_implant, well_tap_implant],
                                   [PIMP, nmos_implant, pmos_implant]]:
            if top.by() - bottom.uy() < self.implant_space:
                x_offset = min(top.lx(), bottom.lx())
                width = max(top.rx(), bottom.rx()) - x_offset
                self.add_rect(layer, vector(x_offset, bottom.uy()),
                              width=width, height=top.by() - bottom.uy())
