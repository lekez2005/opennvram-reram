"""Dimensions are hard-coded
Should really be done in magic but...
"""
from base import utils
from base.analog_cell_mixin import AnalogMixin
from base.contact import poly as poly_contact, m1m2, m2m3, cross_m1m2
from base.design import design, METAL1, METAL3, METAL2, POLY, NWELL, PWELL
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from ms_flop_horz_pitch import MsFlopHorzPitch


class MsFlopClkBuf(MsFlopHorzPitch):

    @classmethod
    def get_name(cls, *args, **kwargs):
        return "ms_flop_clk_buf"

    def join_implants(self):
        pass

    def __init__(self, *args, **kwargs):
        # spice file is loaded if name matches file in sp_lib
        design.__init__(self, self.get_name())
        self.create_modules()

        self.create_layout()

    def get_clk_buf_offsets(self, nmos, pmos):
        self.height = 15
        self.bottom_space = self.calculate_bottom_space()

        tx_x_offset = 0.5 * self.width - 0.5 * nmos.width
        nmos_y = self.bottom_space - nmos.active_rect.by()

        contact_y = (nmos_y + nmos.active_rect.uy() +
                     self.calculate_active_to_poly_cont_mid("nmos")) + 0.05

        pmos_y = (contact_y + self.calculate_active_to_poly_cont_mid("pmos") -
                  pmos.active_rect.by())
        return nmos_y, pmos_y, tx_x_offset, contact_y - 0.5 * poly_contact.h_1

    def add_clk_pin(self, contact_y):
        nmos_poly = self.get_sorted_pins(self.clk_buf_nmos_inst, "G")[0]

        # clk input
        fill_height = m1m2.second_layer_height
        _, fill_width = self.calculate_min_area_fill(fill_height, layer=METAL2)

        x_offset = nmos_poly.rx() - 0.5 * poly_contact.first_layer_width
        y_offset = contact_y + 0.5 * poly_contact.h_1
        self.clk_buf_cont_y = y_offset
        offset = vector(x_offset, y_offset)
        self.clk_bar_via_offset = offset

        for via in [poly_contact, m1m2, m2m3]:
            self.add_contact_center(via.layer_stack, offset)

        if fill_width:
            self.add_rect_center(METAL2, offset, width=fill_width,
                                 height=fill_height)

        pin_y = y_offset - 0.5 * self.bus_width
        self.add_layout_pin("clk", METAL3, vector(0, pin_y), width=self.width,
                            height=self.bus_width)

        # clk_buf_input
        nmos_poly = self.get_sorted_pins(self.clk_buf_nmos_inst, "G")[1]
        via_x = nmos_poly.lx() + 0.5 * poly_contact.w_1
        offset = vector(via_x, y_offset)
        self.add_contact_center(poly_contact.layer_stack,
                                vector(via_x, y_offset))
        self.clk_buf_via_offset = offset

    def join_sources(self, nmos_sources, pmos_sources, left_via_x, right_via_x,
                     rotate_via=False, rect_width=None):
        x_offsets = []
        rect_width = rect_width or utils.round_to_grid(1.5 * self.m1_width)
        for i in range(2):
            nmos_source = nmos_sources[i]
            pmos_source = pmos_sources[i]
            bottom_source, top_source = sorted([nmos_source, pmos_source],
                                               key=lambda x: x.by())
            m1_extent = 0.5 * (poly_contact.h_2 if rotate_via else poly_contact.w_2)
            if i == 0:
                x_offset = left_via_x - m1_extent - self.m1_space - rect_width
            else:
                x_offset = right_via_x + m1_extent + self.m1_space
            for rect in [bottom_source, top_source]:
                self.add_rect(METAL1, vector(x_offset, rect.by()),
                              height=rect.height(), width=rect.cx() - x_offset)
            self.add_rect(METAL1, vector(x_offset, bottom_source.by()),
                          width=rect_width,
                          height=top_source.uy() - bottom_source.by())
            x_offsets.append(x_offset)
        return x_offsets

    def route_clk_buf(self, contact_y):

        nmos_sources = self.get_sorted_pins(self.clk_buf_nmos_inst, "S")
        pmos_sources = self.get_sorted_pins(self.clk_buf_pmos_inst, "S")

        pmos_conts = []
        rails = []

        self.join_sources(nmos_sources, pmos_sources, self.clk_bar_via_offset.x,
                          self.clk_buf_via_offset.x)

        for i in range(2):
            pmos_source = pmos_sources[i]
            # vertical rails
            num_contacts = calculate_num_contacts(self, pmos_source.height(),
                                                  layer_stack=m1m2.layer_stack)
            cont = self.add_contact_center(m1m2.layer_stack, pmos_source.center(),
                                           size=[1, num_contacts])
            pmos_conts.append(cont)
            offset = vector(cont.cx() - 0.5 * self.m2_width,
                            cont.cy() - 0.5 * cont.mod.h_2)
            rail = self.add_rect(METAL2, offset,
                                 height=self.clk_buf_pmos_inst.uy() - offset.y)
            rails.append(rail)
        self.clk_bar_rail, self.clk_buf_rail = rails

        # clk_bar to clk_buf in
        x_offset = (self.clk_bar_via_offset.x + 0.5 * m2m3.w_1 +
                    self.m2_space + 0.5 * self.m2_width)
        terminal_y = self.clk_buf_via_offset.y + 0.5 * m2m3.h_1 - 0.5 * self.m2_width
        pmos_source = pmos_sources[0]
        y_bend = pmos_source.cy() - 0.5 * m1m2.h_2 - self.m2_space - 0.5 * self.m2_width
        self.add_path(METAL2, [pmos_source.center(),
                               vector(x_offset, pmos_source.cy()),
                               vector(x_offset, y_bend),
                               vector(self.clk_buf_via_offset.x, y_bend),
                               vector(self.clk_buf_via_offset.x, terminal_y)])
        self.add_contact_center(m1m2.layer_stack, self.clk_buf_via_offset)

        self.clk_buf_vdd_y = (self.clk_buf_pmos_inst.by() +
                              self.clk_buf_pmos_inst.mod.active_rect.uy() +
                              self.bottom_space - self.rail_height)

    def add_clk_buffer_power(self):
        self.add_power_tap(0, "gnd", self.clk_buf_nmos_inst)
        self.add_power_tap(self.clk_buf_vdd_y, "vdd", self.clk_buf_pmos_inst)

    def route_tgate_poly_contacts(self, nmos_inst, pmos_inst,
                                  n_contact_y, p_contact_y):
        mid_y = p_contact_y + 0.5 * poly_contact.w_1 + self.poly_vert_space

        pmos_poly = self.get_sorted_pins(pmos_inst, "G")[0]
        nmos_poly = self.get_sorted_pins(nmos_inst, "G")[1]

        if nmos_inst == self.l_tgate_nmos:
            single_cont_rail, dual_cont_rail = self.clk_bar_rail, self.clk_buf_rail
        else:
            single_cont_rail, dual_cont_rail = self.clk_buf_rail, self.clk_bar_rail

        poly_fill_x = [x.lx() for x in [pmos_poly, nmos_poly]]

        self.join_poly(nmos_inst, pmos_inst, [(0, 1)], mid_y=mid_y)

        def m2_rail_to_poly(m2_rail, via_offset):
            m1m2_offset = vector(m2_rail.cx(), via_offset.y)
            self.add_cross_contact_center(cross_m1m2, m1m2_offset, rotate=True)
            self.add_rect(METAL1, vector(via_offset.x, offset.y - 0.5 * self.m1_width),
                          width=m2_rail.cx() - via_offset.x)

        # connect clk buf
        left_rail, right_rail = sorted([single_cont_rail, dual_cont_rail],
                                       key=lambda x: x.lx())
        left_via_x = left_rail.rx()
        right_via_x = right_rail.lx()

        via_y_offsets = [p_contact_y, n_contact_y]
        poly_rects = [pmos_poly, nmos_poly]
        poly_fill_y = [p_contact_y + 0.5 * poly_contact.w_1,
                       n_contact_y - 0.5 * poly_contact.w_1]

        for i, (x_offset, y_offset) in enumerate(zip([left_via_x, right_via_x],
                                                     via_y_offsets)):
            offset = vector(x_offset, y_offset)
            self.add_contact_center(poly_contact.layer_stack, offset,
                                    rotate=90)
            self.add_rect(POLY, vector(poly_fill_x[i], poly_fill_y[i]),
                          height=poly_rects[i].cy() - poly_fill_y[i])
            m2_rail_to_poly(dual_cont_rail, offset)

        # connect clk_buf
        if nmos_inst == self.l_tgate_nmos:
            offset = vector(left_via_x, n_contact_y)
        else:
            offset = vector(right_via_x, p_contact_y)
        self.add_contact_center(poly_contact.layer_stack, offset,
                                rotate=90)
        m2_rail_to_poly(single_cont_rail, offset)
        return left_via_x, right_via_x

    def route_tgate_int(self, nmos_inst, pmos_inst, gnd_y):
        # int
        nmos_drain = nmos_inst.get_pin("D")
        pmos_drain = pmos_inst.get_pin("D")
        for pin in [pmos_drain, nmos_drain]:
            self.add_contact_center(m1m2.layer_stack, pin.center())
        offset = vector(pmos_drain.cx() - 0.5 * self.m2_width, pmos_drain.cy())
        return self.add_rect(METAL2, offset,
                             height=gnd_y + self.rail_height - offset.y)

    def add_leader_tgate(self):
        tgate_nmos = self.create_ptx(self.nmos_tgate_size, False, mults=2)
        tgate_pmos = self.create_ptx(self.pmos_tgate_size, True, mults=2)

        x_offset = 0.5 * self.width - 0.5 * tgate_nmos.width

        nmos_poly = tgate_nmos.get_pins("G")[0]

        pmos_y = (self.clk_buf_vdd_y + self.bottom_space +
                  tgate_pmos.active_rect.by())
        pmos_active_top = pmos_y + tgate_pmos.active_rect.uy()
        p_contact_y = (pmos_active_top + self.calculate_active_to_poly_cont_mid("pmos"))
        n_contact_y = (p_contact_y + poly_contact.w_1 + 2 * self.poly_vert_space +
                       nmos_poly.width())
        nmos_active_bottom = n_contact_y + self.calculate_active_to_poly_cont_mid("nmos")

        nmos_y = nmos_active_bottom - tgate_nmos.active_rect.by()

        self.l_tgate_nmos = self.add_ptx_inst(tgate_nmos, vector(x_offset, nmos_y))
        self.l_tgate_pmos = self.add_ptx_inst(tgate_pmos, vector(x_offset, pmos_y))

        self.tgate_p_contact_y = p_contact_y - self.l_tgate_pmos.by()
        self.tgate_n_contact_y = n_contact_y - self.l_tgate_pmos.by()

        self.route_tgate_poly_contacts(self.l_tgate_nmos, self.l_tgate_pmos, n_contact_y,
                                       p_contact_y)

        # join diffusions
        nmos_sources = self.get_sorted_pins(self.l_tgate_nmos, "S")
        pmos_sources = self.get_sorted_pins(self.l_tgate_pmos, "S")

        self.tgate_source_x = self.join_sources(nmos_sources, pmos_sources,
                                                self.clk_bar_rail.cx(),
                                                self.clk_buf_rail.cx(), rotate_via=True)

        # din pin
        x_offset = (self.clk_bar_rail.cx() - 0.5 * m1m2.w_2 - self.m2_space -
                    self.m2_width - 0.05)
        pmos_pin = pmos_sources[0]
        y_offset = pmos_pin.by() + 0.5 * m1m2.h_2
        self.add_layout_pin("din", METAL2, vector(x_offset, 0),
                            height=y_offset)
        self.add_contact_center(m1m2.layer_stack, vector(x_offset + 0.5 * self.m2_width,
                                                         y_offset))

        gnd_y = (self.l_tgate_nmos.by() + self.l_tgate_nmos.mod.active_rect.uy() +
                 self.bottom_space - self.rail_height)
        self.leader_gnd_y = gnd_y

        # int
        self.l_int_rect = self.route_tgate_int(self.l_tgate_nmos, self.l_tgate_pmos, gnd_y)

        # power
        self.add_clk_buffer_power()
        for rail in [self.clk_bar_rail, self.clk_buf_rail]:
            self.add_rect(METAL2, rail.ul(), width=rail.width,
                          height=gnd_y + self.rail_height - rail.uy())

        self.add_power_tap(gnd_y, "gnd", self.l_tgate_nmos)

        sample_vdd = self.get_pins("vdd")[0]
        self.extend_tx_well(self.l_tgate_pmos, NWELL, sample_vdd)

    def join_drains_by_m2(self, top_tx_inst, bottom_tx_inst, power_rail_y):

        top_pin = self.get_sorted_pins(top_tx_inst, "S")[1]
        bottom_pin = self.get_sorted_pins(bottom_tx_inst, "S")[1]
        x_offset = (top_pin.cx() + 0.5 * self.m2_width + self.m2_space +
                    0.5 * m1m2.w_2)
        top_via_y = (power_rail_y + self.rail_height +
                     + self.m1_space + 0.5 * m1m2.h_1)

        self.add_contact_center(m1m2.layer_stack, vector(x_offset, bottom_pin.cy()))
        self.add_contact_center(m1m2.layer_stack, vector(x_offset, top_via_y))
        self.add_rect(METAL2, vector(x_offset - 0.5 * self.m2_width, bottom_pin.cy()),
                      height=top_via_y - bottom_pin.cy())
        self.add_rect(METAL1, vector(x_offset - 0.5 * self.m1_width, top_via_y),
                      height=top_pin.by() + self.m1_width - top_via_y)
        return top_via_y

    def place_latch_buffers(self, power_rail_y):
        buffer_nmos = self.create_ptx(self.nmos_latch_size, False, mults=2)
        buffer_pmos = self.create_ptx(self.pmos_latch_size, True, mults=2)

        x_offset = self.clk_buf_nmos_inst.lx()
        y_offset = power_rail_y + self.bottom_space
        nmos_inst = self.add_ptx_inst(buffer_nmos, vector(x_offset, y_offset))
        mid_space = self.clk_buf_pmos_inst.by() - self.clk_buf_nmos_inst.uy()
        y_offset = y_offset + buffer_nmos.height + mid_space
        pmos_inst = self.add_ptx_inst(buffer_pmos, vector(x_offset, y_offset))

        # join sources
        via_offsets = self.calculate_poly_via_offsets(nmos_inst)
        nmos_sources = self.get_sorted_pins(nmos_inst, "S")
        pmos_sources = self.get_sorted_pins(pmos_inst, "S")
        self.join_sources(nmos_sources, pmos_sources, *via_offsets,
                          rotate_via=False, rect_width=self.m1_width)
        # join poly
        self.join_poly(nmos_inst, pmos_inst)
        cont_y = nmos_inst.uy() + (self.clk_buf_cont_y -
                                   self.clk_buf_nmos_inst.uy())
        for x_offset in via_offsets:
            self.add_contact_center(poly_contact.layer_stack, vector(x_offset, cont_y))

        return nmos_inst, pmos_inst, via_offsets, cont_y

    def route_buffer_dout_bar(self, pmos_inst, x_offset, y_offset):
        pin = self.get_sorted_pins(pmos_inst, "S")[0]
        offset = vector(pin.cx(), pin.by() + 0.5 * m1m2.h_1)
        self.add_contact_center(m1m2.layer_stack, offset)
        self.add_path(METAL2, [offset,
                               vector(x_offset, offset.y),
                               vector(x_offset, y_offset)])

    def add_leader_buffer(self):

        res = self.place_latch_buffers(self.leader_gnd_y)
        self.l_buffer_nmos, self.l_buffer_pmos, via_offsets, cont_y = res
        # tgate output to buffer drain
        nmos_drain_via_y = self.join_drains_by_m2(self.l_buffer_nmos, self.l_tgate_nmos,
                                                  power_rail_y=self.leader_gnd_y)
        y_bend = (nmos_drain_via_y + 0.5 * m1m2.h_2 +
                  self.m2_space + 0.5 * self.m2_width)

        # poly contacts
        # m2 to poly contact
        l_int_y = y_bend + 0.5 * self.m2_width + self.m2_space + 0.5 * self.m2_width
        m2_via_y = l_int_y + 0.5 * self.m2_width + self.m2_space + 0.5 * m1m2.h_2

        for x_offset in via_offsets:
            self.add_contact_center(m1m2.layer_stack, vector(x_offset, m2_via_y))

        # l_int
        rect = self.l_int_rect
        self.add_path(METAL2, [vector(rect.cx(), rect.uy()),
                               vector(rect.cx(), l_int_y),
                               vector(via_offsets[0], l_int_y),
                               vector(via_offsets[0], m2_via_y)])
        # l dout_bar
        self.route_buffer_dout_bar(self.l_buffer_pmos, via_offsets[1], m2_via_y)

        # move clk_rails to the side
        vdd_top = (self.l_buffer_pmos.by() + self.l_buffer_pmos.mod.active_rect.uy() +
                   self.bottom_space)
        x_offsets = self.tgate_source_x

        rails = []
        for i, rail in enumerate([self.clk_bar_rail, self.clk_buf_rail]):
            extension = 0.5 * self.m2_width
            if i == 0:
                x_bend = x_offsets[i] - extension + self.m2_width
            else:
                x_bend = x_offsets[i] + extension + self.m2_width
            self.add_path(METAL2, [vector(rail.cx(), rail.uy()),
                                   vector(rail.cx(), y_bend),
                                   vector(x_bend, y_bend),
                                   vector(x_bend, vdd_top)])
            rails.append(self.add_rect(METAL2,
                                       vector(x_bend - 0.5 * self.m2_width, vdd_top)))

        self.clk_bar_rail_1, self.clk_buf_rail_1 = rails

        # power
        gnd_pin = list(sorted(self.get_pins("gnd"), key=lambda x: x.cy()))[-1]
        self.extend_tx_well(self.l_buffer_nmos, PWELL, gnd_pin)
        self.l_buffer_vdd_y = vdd_top - self.rail_height
        self.add_power_tap(vdd_top - self.rail_height, "vdd", self.l_buffer_pmos,
                           add_m3=False)

    def add_follower_tgate(self):
        tgate_nmos = self.create_ptx(self.nmos_tgate_size, False, mults=2)
        tgate_pmos = self.create_ptx(self.pmos_tgate_size, True, mults=2)
        x_offset = self.l_tgate_nmos.lx()

        pmos_y = self.l_buffer_vdd_y + self.bottom_space
        mid_space = self.l_tgate_nmos.by() - self.l_tgate_pmos.uy()
        nmos_y = pmos_y + tgate_pmos.height + mid_space
        self.f_tgate_nmos = self.add_ptx_inst(tgate_nmos, vector(x_offset, nmos_y))
        self.f_tgate_pmos = self.add_ptx_inst(tgate_pmos, vector(x_offset, pmos_y))

        n_contact_y = self.tgate_n_contact_y + pmos_y
        p_contact_y = self.tgate_p_contact_y + pmos_y

        self.route_tgate_poly_contacts(self.f_tgate_nmos, self.f_tgate_pmos,
                                       n_contact_y, p_contact_y)

        # extend clk rails
        top_y = [n_contact_y, p_contact_y]
        for i in range(2):
            source_rail = [self.clk_bar_rail_1, self.clk_buf_rail_1][i]
            dest_rail = [self.clk_bar_rail, self.clk_buf_rail][i]
            self.add_path(METAL2, [vector(source_rail.cx(), source_rail.uy()),
                                   vector(source_rail.cx(), p_contact_y),
                                   vector(dest_rail.cx(), p_contact_y),
                                   vector(dest_rail.cx(), top_y[i])])

        # join diffusions
        nmos_sources = self.get_sorted_pins(self.f_tgate_nmos, "S")
        pmos_sources = self.get_sorted_pins(self.f_tgate_pmos, "S")

        self.tgate_source_x = self.join_sources(nmos_sources, pmos_sources,
                                                self.clk_bar_rail.cx(),
                                                self.clk_buf_rail.cx(), rotate_via=True)

        # buffer drain to tgate input
        top_pin = self.get_sorted_pins(self.f_tgate_pmos, "S")[0]
        self.add_contact_center(m1m2.layer_stack, top_pin.center())
        bottom_pin = self.get_sorted_pins(self.l_buffer_pmos, "S")[0]

        self.add_contact_center(m1m2.layer_stack,
                                vector(bottom_pin.cx(), bottom_pin.uy() - 0.5 * m1m2.h_1))

        self.add_rect(METAL2, vector(bottom_pin.cx() - 0.5 * m1m2.w_2, bottom_pin.by()),
                      width=m1m2.w_2, height=top_pin.cy() - bottom_pin.by())

        gnd_y = (self.f_tgate_nmos.by() + self.f_tgate_nmos.mod.active_rect.uy() +
                 self.bottom_space - self.rail_height)
        self.follower_gnd_y = gnd_y

        # int
        self.f_int_rect = self.route_tgate_int(self.f_tgate_nmos, self.f_tgate_pmos, gnd_y)

        vdd_pin = list(sorted(self.get_pins("vdd"), key=lambda x: x.cy()))[-1]
        self.extend_tx_well(self.f_tgate_pmos, NWELL, vdd_pin)

    def add_follower_buffer(self):
        insts = self.place_latch_buffers(self.follower_gnd_y)

        self.f_buffer_nmos, self.f_buffer_pmos, via_offsets, cont_y = insts
        for x_offset in via_offsets:
            self.add_contact_center(m1m2.layer_stack, vector(x_offset, cont_y))

        # int
        rect = self.f_int_rect
        y_bend = self.f_buffer_nmos.get_pins("S")[0].uy() + 0.5 * self.m2_width
        self.add_path(METAL2, [vector(rect.cx(), rect.uy()),
                               vector(rect.cx(), y_bend),
                               vector(via_offsets[0], y_bend),
                               vector(via_offsets[0], cont_y)])

        # f dout_bar
        self.route_buffer_dout_bar(self.f_buffer_pmos, via_offsets[1], cont_y)

        # tgate output to buffer drain
        self.join_drains_by_m2(self.f_buffer_nmos, self.f_tgate_nmos,
                               power_rail_y=self.follower_gnd_y)

        vdd_y = (self.f_buffer_pmos.by() +
                 self.f_buffer_pmos.mod.active_rect.uy() +
                 self.bottom_space - self.rail_height)
        self.height = vdd_y + self.rail_height

        # output pins
        pin_names = ["dout", "dout_bar"]
        tx_pins = self.get_sorted_pins(self.f_buffer_pmos, "S")
        for i in range(2):
            tx_pin = tx_pins[i]
            y_offset = tx_pin.uy() - 0.5 * m1m2.h_1
            self.add_contact_center(m1m2.layer_stack, vector(tx_pin.cx(), y_offset))
            if i == 0:
                y_offset = tx_pin.by() + 0.5 * m1m2.h_2
            self.add_layout_pin(pin_names[i], METAL2,
                                vector(tx_pin.cx() - 0.5 * self.m2_width, y_offset),
                                height=self.height - y_offset)

        self.add_power_tap(self.follower_gnd_y, "gnd", self.f_tgate_nmos)
        self.add_power_tap(vdd_y, "vdd", self.f_buffer_pmos)

    def add_power(self):

        leader_vdd = min(self.get_pins("vdd"), key=lambda x: abs(x.cy() - self.l_buffer_pmos.uy()))
        AnalogMixin.add_m1_m3_power_via(self, leader_vdd)

        for inst in [self.clk_buf_nmos_inst, self.clk_buf_pmos_inst,
                     self.l_buffer_nmos, self.l_buffer_pmos,
                     self.f_buffer_nmos, self.f_buffer_pmos]:
            self.route_tx_to_power(inst)
