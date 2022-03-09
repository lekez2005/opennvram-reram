"""Dimensions are hard-coded
Should really be done in magic but...
"""
import itertools

import tech
from base.contact import m1m2, cross_m1m2, poly as poly_contact
from base.design import design, POLY, METAL1, METAL2, ACTIVE, NIMP, PIMP
from base.vector import vector
from modules.reram.bitcell_aligned_pgate import BitcellAlignedPgate
from pgates.ptx import ptx


class MsFlopHorzPitch(BitcellAlignedPgate):

    @classmethod
    def get_name(cls):
        return "ms_flop_horz_pitch"

    def __init__(self):
        # spice file is loaded if name matches file in sp_lib
        design.__init__(self, self.get_name())
        self.create_layout()

    def create_layout(self):

        self.set_tx_sizes()
        self.add_clk_buffer()
        self.add_leader_tgate()
        self.add_leader_buffer()
        self.add_follower_tgate()
        self.add_follower_buffer()
        self.add_power()
        self.add_boundary()
        self.join_implants()
        self.flatten_tx()
        tech.add_tech_layers(self)

    def create_ptx(self, width, is_pmos=False, **kwargs):
        return self.create_ptx_by_width(width, is_pmos, **kwargs)

    def add_ptx_inst(self, tx, offset, **kwargs):
        inst = self.add_inst(tx.name, tx, offset, **kwargs)
        self.connect_inst([], check=False)
        return inst

    def set_tx_sizes(self):
        self.height = 3.2
        self.nmos_clk_size = 0.36
        self.pmos_clk_size = 0.9

        self.nmos_tgate_size = 0.36
        self.pmos_tgate_size = 0.6

        self.nmos_latch_size = 0.61
        self.pmos_latch_size = self.nmos_latch_size * 2

    def get_clk_buf_offsets(self, nmos, pmos):
        mid_y = 1.4
        space = 0.24

        contact_y = 1.24
        tx_x_offset = 0.2
        nmos_y = mid_y - space - nmos.active_rect.uy() - 0.15
        pmos_y = mid_y + space + (pmos.height - pmos.active_rect.uy())

        return nmos_y, pmos_y, tx_x_offset, contact_y

    def add_clk_pin(self, contact_y):
        nmos_poly = self.get_sorted_pins(self.clk_buf_nmos_inst, "G")
        x_offset = nmos_poly[0].rx() - poly_contact.first_layer_width
        self.add_contact(poly_contact.layer_stack, vector(x_offset, contact_y))
        pin_y = contact_y + 0.5 * poly_contact.second_layer_height - 0.5 * self.m1_width
        self.add_layout_pin("clk", METAL1, vector(0, pin_y), width=nmos_poly[0].lx())

    def route_clk_buf(self, contact_y):
        # clk_bar
        pmos_source = self.clk_buf_pmos_inst.get_pins("S")[0]
        y_top = pmos_source.by() + m1m2.second_layer_height - m1m2.first_layer_height
        x_offset = pmos_source.cx() - 0.5 * m1m2.second_layer_width
        self.add_contact(m1m2.layer_stack, vector(x_offset, y_top))
        nmos_source = self.clk_buf_nmos_inst.get_pins("S")[0]
        self.add_contact_center(m1m2.layer_stack, nmos_source.center())
        y_offset = nmos_source.cy()
        x_offset = x_offset + 0.5 * m1m2.second_layer_width - 0.5 * self.m2_width
        self.add_rect(METAL2, vector(x_offset, y_offset), width=self.m2_width,
                      height=y_top - y_offset + 0.5 * m1m2.second_layer_height)

        # clk_bar to clk_buf_in
        nmos_poly = self.get_sorted_pins(self.clk_buf_nmos_inst, "G")
        via_x = (nmos_poly[0].rx() + self.poly_vert_space +
                 0.5 * poly_contact.first_layer_width)
        offset = vector(via_x, contact_y + 0.5 * poly_contact.height)
        self.add_contact_center(poly_contact.layer_stack, offset)
        self.add_contact_center(m1m2.layer_stack, offset)
        self.clk_bar_0 = self.add_rect(METAL2,
                                       vector(x_offset, offset.y - 0.5 * self.m2_width),
                                       width=via_x - x_offset)
        # clk_buf
        x_offset = via_x + 0.5 * poly_contact.second_layer_width + self.m1_space
        pmos_source = self.clk_buf_pmos_inst.get_pins("S")[1]
        nmos_source = self.clk_buf_nmos_inst.get_pins("S")[1]
        self.clk_buf_m1 = self.add_rect(METAL1, vector(x_offset, nmos_source.by()),
                                        height=pmos_source.uy() - nmos_source.by())

    def add_clk_buffer(self):
        # add transistors
        nmos = self.create_ptx(self.nmos_clk_size, False, mults=2)
        pmos = self.create_ptx(self.pmos_clk_size, True, mults=2)

        nmos_y, pmos_y, tx_x_offset, contact_y = self.get_clk_buf_offsets(nmos, pmos)
        self.clk_buf_nmos_inst = self.add_ptx_inst(nmos, vector(tx_x_offset, nmos_y))

        self.clk_buf_pmos_inst = self.add_ptx_inst(pmos, vector(tx_x_offset, pmos_y))

        self.join_poly(self.clk_buf_nmos_inst, self.clk_buf_pmos_inst)

        # clk pin
        self.add_clk_pin(contact_y)
        self.route_clk_buf(contact_y)

    def add_poly_contact(self, tx_inst, *, y_offset: float, poly_index: int,
                         rotate=90, x_offset=None):
        """middle contact offset"""
        poly_gates = self.get_sorted_pins(tx_inst, "G")
        if not x_offset:
            if poly_index == 0:
                x_offset = (poly_gates[1].lx() - self.poly_vert_space -
                            0.5 * poly_contact.first_layer_width)
            else:
                x_offset = (poly_gates[0].rx() + self.poly_vert_space +
                            0.5 * poly_contact.first_layer_width)
        self.add_contact_center(poly_contact.layer_stack, vector(x_offset, y_offset),
                                rotate=rotate)
        poly_rect = poly_gates[poly_index]
        self.add_rect(POLY, poly_rect.lc(), width=poly_rect.width(),
                      height=y_offset - poly_rect.cy())
        return x_offset

    def add_leader_tgate(self):
        tgate_nmos = self.create_ptx(self.nmos_tgate_size, False, mults=2)
        tgate_pmos = self.create_ptx(self.pmos_tgate_size, True, mults=2)
        x_offset = (self.clk_buf_pmos_inst.lx() +
                    self.clk_buf_pmos_inst.mod.active_rect.rx() + self.get_space(ACTIVE))
        x_offset -= tgate_nmos.active_rect.lx()
        x_offset = max(x_offset, self.clk_buf_m1.rx() + 0.3)

        nmos_y = 0.25
        pmos_y = 2.1

        # y_offset = self.clk_bar.uy() + self.m2_space + 0.05 - tgate_nmos.active_rect.by()

        self.l_tgate_nmos = self.add_ptx_inst(tgate_nmos, vector(x_offset, nmos_y))
        # y_offset = self.clk_buf.by() - self.m2_space - 0.05 - tgate_pmos.active_rect.uy()
        self.l_tgate_pmos = self.add_ptx_inst(tgate_pmos, vector(x_offset, pmos_y))

        self.join_poly(self.l_tgate_nmos, self.l_tgate_pmos, [(0, 1)])
        # clk_buf contacts
        active_to_cont = self.calculate_active_to_poly_cont_mid(tgate_nmos.tx_type)
        clk_buf_n_y = self.l_tgate_nmos.by() + tgate_nmos.active_rect.uy() + active_to_cont
        nmos_poly = self.get_sorted_pins(self.l_tgate_nmos, "G")
        x_offset = nmos_poly[1].lx() + 0.03 + 0.5 * poly_contact.width
        clk_buf_n_x = self.add_poly_contact(self.l_tgate_nmos, y_offset=clk_buf_n_y,
                                            poly_index=1, x_offset=x_offset)
        self.l_clk_buf_poly_x = clk_buf_n_x

        active_to_cont = self.calculate_active_to_poly_cont_mid(tgate_pmos.tx_type)
        clk_buf_p_y = self.l_tgate_pmos.by() + tgate_pmos.active_rect.by() - active_to_cont
        clk_buf_p_x = self.add_poly_contact(self.l_tgate_pmos, rotate=0,
                                            y_offset=clk_buf_p_y, poly_index=0)

        # din
        x_offset = (clk_buf_p_x - 0.5 * poly_contact.second_layer_width - self.m1_space -
                    self.m1_width)
        pmos_source = self.l_tgate_pmos.get_pins("S")[0]
        nmos_source = self.l_tgate_nmos.get_pins("S")[0]
        self.add_rect(METAL1, vector(x_offset, nmos_source.by()),
                      height=pmos_source.uy() - nmos_source.by())
        via_offset = vector(x_offset + 0.5 * m1m2.first_layer_width,
                            pmos_source.uy() - 0.5 * m1m2.first_layer_height)
        self.add_contact_center(m1m2.layer_stack, via_offset)
        pin_y = via_offset.y - 0.5 * self.m2_width
        self.add_layout_pin("din", METAL2, vector(0, pin_y), width=via_offset.x)

        # clk_bar to tgate poly
        x_offset = clk_buf_p_x
        y_offset = self.clk_bar_0.cy()
        self.add_contact_center(poly_contact.layer_stack, vector(x_offset, y_offset))
        self.add_contact_center(m1m2.layer_stack, vector(x_offset, y_offset))
        self.clk_bar_1 = self.add_rect(METAL2,
                                       vector(x_offset, y_offset - 0.5 * self.m2_width),
                                       width=self.clk_bar_0.rx() - x_offset)
        # clk_buf to tgate poly
        self.add_contact_center(m1m2.layer_stack,
                                vector(self.clk_buf_m1.cx(), clk_buf_p_y))
        self.add_contact_center(m1m2.layer_stack,
                                vector(clk_buf_p_x, clk_buf_p_y))
        self.clk_buf_1 = self.add_rect(METAL2, vector(clk_buf_p_x,
                                                      clk_buf_p_y - 0.5 * self.m2_width),
                                       width=self.clk_buf_m1.cx() - clk_buf_p_x)
        path_y = clk_buf_p_y - 0.5 * m1m2.first_layer_height + 0.5 * self.m1_width
        self.add_path(METAL1, [vector(clk_buf_p_x, path_y),
                               vector(clk_buf_n_x, path_y),
                               vector(clk_buf_n_x, clk_buf_n_y)])
        # nmos int via
        nmos_pin = self.l_tgate_nmos.get_pin("D")
        x_offset = self.get_sorted_pins(self.l_tgate_nmos, "S")[0].rx() + self.m1_space
        offset = vector(x_offset, nmos_pin.uy() - self.m1_width)
        self.add_rect(METAL1, offset, width=nmos_pin.lx() - offset.x)
        self.add_rect(METAL1, offset, height=self.m1_width + self.m1_space)
        y_offset = nmos_pin.by() + self.m2_width + self.get_space(METAL2) + 0.05
        int_via_n_offset = vector(x_offset + 0.5 * m1m2.first_layer_width,
                                  y_offset + 0.5 * m1m2.height)
        self.add_cross_contact_center(cross_m1m2, int_via_n_offset)
        # pmos int via
        pmos_pin = self.l_tgate_pmos.get_pin("D")
        y_offset = clk_buf_p_y + 0.5 * m1m2.second_layer_height + self.m2_space
        x_offset = clk_buf_p_x + (0.5 * self.m2_width + self.m2_space +
                                  0.5 * m1m2.second_layer_width -
                                  0.5 * m1m2.first_layer_width)
        offset = vector(x_offset, y_offset)
        self.add_rect(METAL1, offset, height=pmos_pin.by() + self.m1_width - offset.y)
        int_via_p_offset = vector(offset.x + 0.5 * m1m2.first_layer_width,
                                  offset.y + 0.5 * m1m2.first_layer_height)
        self.add_contact_center(m1m2.layer_stack, int_via_p_offset)

        # join int vias
        x_offset = int_via_p_offset.x - 0.5 * self.m2_width
        y_offset = int_via_n_offset.y + 0.5 * m1m2.second_layer_height - self.m2_width
        self.add_rect(METAL2, vector(int_via_n_offset.x, y_offset),
                      width=x_offset - int_via_n_offset.x)
        self.l_int_rect = self.add_rect(METAL2, vector(x_offset, y_offset),
                                        height=int_via_p_offset.y - y_offset)

        # clk_bar bottom rail
        x_offset = self.clk_bar_1.lx() - 0.5 * self.m2_width
        offset = vector(x_offset, nmos_pin.by() - 0.05)
        self.add_rect(METAL2, offset, height=self.clk_bar_1.by() - offset.y)
        self.clk_bar_rail = self.add_rect(METAL2, offset)

        # clk_buf top rail
        y_offset = pmos_pin.uy()
        x_offset = clk_buf_p_x - 0.5 * self.m2_width
        self.add_rect(METAL2, vector(x_offset, clk_buf_p_y),
                      height=y_offset - clk_buf_p_y)
        self.clk_buf_rail = self.add_rect(METAL2, vector(x_offset, y_offset))

    def connect_tgate_and_buffer_diffusions(self, x_offset, tgate_nmos, tgate_pmos,
                                            buffer_nmos, buffer_pmos):

        tgate_pmos_source = tgate_pmos.get_pins("S")[1]
        tgate_nmos_source = tgate_nmos.get_pins("S")[1]
        buffer_pmos_source = buffer_pmos.get_pins("S")[0]
        buffer_nmos_source = buffer_nmos.get_pins("S")[0]
        y_top = buffer_pmos_source.by()
        y_bottom = buffer_nmos_source.uy() - self.m1_width
        self.add_rect(METAL1, vector(x_offset, y_bottom), height=y_top - y_bottom)
        for y_offset in [y_top, y_bottom]:
            self.add_rect(METAL1, vector(x_offset, y_offset),
                          width=buffer_nmos_source.rx() - x_offset)
        for left_pin, right_pin in [(tgate_nmos_source, buffer_nmos_source),
                                    (tgate_pmos_source, buffer_pmos_source)]:
            self.add_rect(METAL1, left_pin.lr(), height=left_pin.height(),
                          width=right_pin.lx() - left_pin.rx())

    def route_dout_bar_to_poly(self, buffer_nmos):
        nmos_poly = self.get_sorted_pins(buffer_nmos, "G")[0]

        active_to_cont = self.calculate_active_to_poly_cont_mid("pmos")

        poly_via_y = (self.l_buffer_pmos.by() + self.l_buffer_pmos.mod.active_rect.by() -
                      active_to_cont)
        poly_via_x = nmos_poly.rx() - 0.5 * poly_contact.first_layer_width
        buffer_nmos_source = buffer_nmos.get_pins("S")[1]
        y_offset = self.clk_bar_rail.uy() + self.m2_space + 0.5 * m1m2.h_2

        via_offset = vector(buffer_nmos_source.cx(), y_offset)
        self.add_contact_center(m1m2.layer_stack, via_offset)
        self.add_path(METAL2, [via_offset,
                               vector(poly_via_x, via_offset.y),
                               vector(poly_via_x, poly_via_y)])
        via_offset = vector(poly_via_x, poly_via_y)
        self.add_contact_center(poly_contact.layer_stack, via_offset)
        self.add_contact_center(m1m2.layer_stack, via_offset)

        return poly_via_y, y_offset

    def route_int_to_buffer_input(self, rail_x, poly_via_y, buffer_pmos):
        y_offset = poly_via_y + 0.05 + 0.5 * m1m2.h_2 + self.m2_space
        via_x = self.add_poly_contact(buffer_pmos, y_offset=poly_via_y, poly_index=1,
                                      rotate=0)
        self.add_rect(METAL2, vector(rail_x, y_offset), width=via_x - rail_x)
        self.add_rect(METAL2, vector(via_x - 0.5 * self.m2_width, poly_via_y),
                      height=y_offset + self.m2_width - poly_via_y)
        self.add_contact_center(m1m2.layer_stack, vector(via_x, poly_via_y))
        return via_x

    def add_leader_buffer(self):
        buffer_nmos = self.create_ptx(self.nmos_latch_size, False, mults=2)
        buffer_pmos = self.create_ptx(self.pmos_latch_size, True, mults=2)

        # TODO active overlap not working?
        x_offset = (self.l_tgate_nmos.lx() + self.l_tgate_nmos.mod.active_rect.rx() +
                    self.get_space(ACTIVE) - buffer_nmos.active_rect.lx())
        y_offset = self.l_tgate_nmos.by()
        self.l_buffer_nmos = self.add_ptx_inst(buffer_nmos, vector(x_offset, y_offset))
        y_offset = self.l_tgate_pmos.uy() - buffer_pmos.height
        self.l_buffer_pmos = self.add_ptx_inst(buffer_pmos, vector(x_offset, y_offset))

        self.join_poly(self.l_buffer_nmos, self.l_buffer_pmos)

        # tgate dout to buffer dout
        x_offset = (self.l_clk_buf_poly_x + 0.5 * poly_contact.second_layer_height +
                    self.m1_space)
        self.connect_tgate_and_buffer_diffusions(x_offset, self.l_tgate_nmos, self.l_tgate_pmos,
                                                 self.l_buffer_nmos, self.l_buffer_pmos)

        # tgate dout_bar to buffer out_bar
        poly_via_y, _ = self.route_dout_bar_to_poly(self.l_buffer_nmos)

        # tgate int to buffer input
        rail_x = self.l_int_rect.rx()
        via_x = self.route_int_to_buffer_input(rail_x, poly_via_y, self.l_buffer_pmos)
        self.l_buffer_cont_x = via_x

    def add_follower_tgate(self):
        tgate_nmos = self.create_ptx(self.l_tgate_nmos.mod.tx_width, False, mults=2)
        tgate_pmos = self.create_ptx(self.l_tgate_pmos.mod.tx_width, True, mults=2)
        x_offset = (self.l_buffer_nmos.lx() + self.l_buffer_nmos.mod.active_rect.rx() +
                    self.get_space(ACTIVE) - tgate_nmos.active_rect.lx())

        self.f_tgate_nmos = self.add_ptx_inst(tgate_nmos,
                                              vector(x_offset, self.l_tgate_nmos.by()))
        self.f_tgate_pmos = self.add_ptx_inst(tgate_pmos,
                                              vector(x_offset, self.l_tgate_pmos.by()))
        # leader buffer dout_bar to tgate left source
        tgate_pmos_source = self.f_tgate_pmos.get_pins("S")[0]
        tgate_nmos_source = self.f_tgate_nmos.get_pins("S")[0]
        buffer_pmos_source = self.l_buffer_pmos.get_pins("S")[1]
        buffer_nmos_source = self.l_buffer_nmos.get_pins("S")[1]
        x_offset = self.l_buffer_cont_x + 0.5 * m1m2.w_1 + self.m1_space
        y_offset = buffer_nmos_source.uy() - self.m1_width
        self.add_rect(METAL1, vector(x_offset, y_offset),
                      height=buffer_pmos_source.by() + self.m1_width - y_offset)
        for left_pin, right_pin in [(buffer_nmos_source, tgate_nmos_source),
                                    (buffer_pmos_source, tgate_pmos_source)]:
            self.add_rect(METAL1, vector(left_pin.rx(), right_pin.by()),
                          height=right_pin.height(),
                          width=right_pin.lx() - left_pin.rx())

        # clk_bar to tgate input
        self.join_poly(self.f_tgate_nmos, self.f_tgate_pmos, [(0, 1)])

        active_to_cont = self.calculate_active_to_poly_cont_mid(tgate_pmos.tx_type)
        clk_buf_p_y = self.f_tgate_pmos.by() + tgate_pmos.active_rect.by() - active_to_cont

        nmos_poly = self.get_sorted_pins(self.f_tgate_nmos, "G")[0]
        pmos_poly = self.get_sorted_pins(self.f_tgate_pmos, "G")[0]
        clk_buf_p_x = nmos_poly.lx() - 0.5 * poly_contact.w_1
        self.add_poly_contact(self.l_tgate_pmos, y_offset=clk_buf_p_y,
                              poly_index=1, x_offset=clk_buf_p_x, rotate=0)
        self.add_rect(POLY, pmos_poly.ll(), width=pmos_poly.width(),
                      height=clk_buf_p_y - 0.5 * poly_contact.h_1 - pmos_poly.by())
        x_offset = clk_buf_p_x - 0.05
        self.add_rect(METAL2, self.clk_bar_rail.lr(),
                      width=x_offset - self.clk_bar_rail.rx())
        self.add_rect(METAL2, vector(x_offset - 0.5 * self.m2_width, self.clk_bar_rail.by()),
                      height=clk_buf_p_y - self.clk_bar_rail.by())
        self.add_contact_center(m1m2.layer_stack, vector(x_offset, clk_buf_p_y))

        clk_bar_m2_x = x_offset

        # clk_buf to tgate input
        active_to_cont = self.calculate_active_to_poly_cont_mid(tgate_nmos.tx_type)
        y_shift = 0.1
        clk_buf_n_y = (self.f_tgate_nmos.by() + tgate_nmos.active_rect.uy()
                       + active_to_cont + y_shift)

        clk_buf_m2_x = clk_bar_m2_x + 0.5 * m1m2.w_2 + self.m2_space + 0.5 * self.m2_width
        self.add_rect(METAL2, self.clk_buf_rail.lr(),
                      width=clk_buf_m2_x - self.clk_buf_rail.rx())
        self.add_rect(METAL2, vector(clk_buf_m2_x - 0.5 * self.m2_width, clk_buf_n_y),
                      height=self.clk_buf_rail.uy() - clk_buf_n_y)

        clk_buf_n_x = nmos_poly.rx() - 0.5 * poly_contact.w_1
        self.add_contact_center(poly_contact.layer_stack, vector(clk_buf_n_x, clk_buf_n_y))
        self.add_contact_center(m1m2.layer_stack, vector(clk_buf_m2_x, clk_buf_n_y))

        via_x = self.get_sorted_pins(self.f_tgate_nmos, "G")[1].lx() + 0.1
        via_y = clk_buf_n_y - y_shift
        self.add_poly_contact(self.f_tgate_nmos, y_offset=via_y,
                              poly_index=1, rotate=90, x_offset=via_x)
        self.f_clk_buf_via_x = via_x

        offset = vector(clk_buf_p_x, clk_buf_p_y)
        mid_y = offset.y - 0.5 * m1m2.h_1 - self.m1_width
        self.add_path(METAL1, [offset, vector(offset.x, mid_y),
                               vector(via_x, mid_y),
                               vector(via_x, via_y)])

        # follower int
        pmos_pin = self.f_tgate_pmos.get_pin("D")
        nmos_pin = self.f_tgate_nmos.get_pin("D")

        via_y = pmos_pin.by() - self.m1_space - 0.5 * m1m2.h_1
        y_offset = via_y - 0.5 * m1m2.h_1
        self.add_rect(METAL1, vector(pmos_pin.lx(), y_offset),
                      height=pmos_pin.by() - y_offset)

        via_x = (clk_buf_m2_x + 0.5 * m1m2.second_layer_width + self.m2_space +
                 0.5 * m1m2.w_2)
        self.add_contact_center(m1m2.layer_stack, vector(via_x, via_y))
        self.add_rect(METAL1, vector(pmos_pin.lx(), y_offset),
                      width=via_x - pmos_pin.lx(), height=m1m2.h_1)

        self.f_int_rect_x = via_x
        self.add_contact_center(m1m2.layer_stack, nmos_pin.center())
        path_y = nmos_pin.uy() - 0.5 * self.m2_width
        self.add_path(METAL2, [vector(nmos_pin.cx(), path_y),
                               vector(via_x + 0.5 * self.m2_width, path_y),
                               vector(via_x + 0.5 * self.m2_width, via_y)])

    def add_follower_buffer(self):
        buffer_nmos = self.create_ptx(self.l_buffer_nmos.mod.tx_width, False, mults=2)
        x_offset = (self.f_tgate_nmos.lx() + self.f_tgate_nmos.mod.active_rect.rx() +
                    self.get_space(ACTIVE) - buffer_nmos.active_rect.lx())
        buffer_pmos = self.create_ptx(self.l_buffer_pmos.mod.tx_width, True, mults=2)

        y_offset = self.l_buffer_nmos.by()
        self.f_buffer_nmos = self.add_ptx_inst(buffer_nmos, vector(x_offset, y_offset))
        y_offset = self.l_buffer_pmos.by()
        self.f_buffer_pmos = self.add_ptx_inst(buffer_pmos, vector(x_offset, y_offset))

        # dout_bar
        x_offset = self.f_clk_buf_via_x + 0.5 * self.m1_width + self.m1_space + 0.08
        self.connect_tgate_and_buffer_diffusions(x_offset, self.f_tgate_nmos,
                                                 self.f_tgate_pmos,
                                                 self.f_buffer_nmos, self.f_buffer_pmos)

        self.join_poly(self.f_buffer_nmos, self.f_buffer_pmos)
        poly_via_y, dout_y = self.route_dout_bar_to_poly(self.f_buffer_nmos)

        right_edge = self.f_buffer_pmos.rx() + self.m1_width + 0.2
        pmos_pin = self.get_sorted_pins(self.f_buffer_pmos, "S")[0]
        y_mid = pmos_pin.uy() - 0.5 * m1m2.h_1
        self.add_contact_center(m1m2.layer_stack, vector(pmos_pin.cx(), y_mid))
        self.add_layout_pin("dout_bar", METAL2,
                            vector(pmos_pin.cx(), y_mid - 0.5 * self.m2_width),
                            width=right_edge - pmos_pin.cx())
        # dout
        rail_x = self.f_int_rect_x
        via_x = self.route_int_to_buffer_input(rail_x, poly_via_y, self.f_buffer_pmos)

        x_offset = via_x + 0.5 * m1m2.w_1 + self.m1_space
        pmos_pin = self.get_sorted_pins(self.f_buffer_pmos, "S")[1]
        nmos_pin = self.get_sorted_pins(self.f_buffer_nmos, "S")[1]
        y_offset = nmos_pin.uy() - self.m1_width
        self.add_rect(METAL1, vector(x_offset, y_offset),
                      height=pmos_pin.by() + self.m1_width - y_offset)
        self.add_layout_pin("dout", METAL2,
                            vector(nmos_pin.cx(), dout_y - 0.5 * self.m2_width),
                            width=right_edge - nmos_pin.cx())

        self.width = self.get_pin("dout").rx()

    def add_power(self):
        # leader nmos gnd
        self.add_power_tap(-0.5 * self.rail_height, "gnd", self.l_tgate_nmos, add_m3=False)
        # leader pmos vdd
        self.add_power_tap(self.height - 0.5 * self.rail_height, "vdd",
                           self.l_buffer_pmos, add_m3=False)

        for inst in [self.clk_buf_nmos_inst, self.clk_buf_pmos_inst,
                     self.l_buffer_nmos, self.l_buffer_pmos,
                     self.f_buffer_nmos, self.f_buffer_pmos]:
            self.route_tx_to_power(inst)

    def join_implants(self):
        def tx_type_func(inst):
            return inst.mod.tx_type

        def get_implant(inst):
            return max(inst.get_layer_shapes(NIMP) + inst.get_layer_shapes(PIMP),
                       key=lambda x: x.width * x.height)

        ptx_insts = [x for x in self.insts if isinstance(x.mod, ptx)]
        implant_width = self.implant_width
        # sort by tx type
        ptx_insts = sorted(ptx_insts, key=tx_type_func)
        for tx_type, insts in itertools.groupby(ptx_insts, key=tx_type_func):
            insts = list(sorted(insts, key=lambda x: x.lx()))
            for i, (left_inst, right_inst) in enumerate(zip(insts[:-1], insts[1:])):
                left_rect = get_implant(left_inst)
                right_rect = get_implant(right_inst)
                if tx_type == "nmos":
                    layer = NIMP
                    bottom = min(left_rect.by(), right_rect.by())
                    height = min(left_rect.uy(), right_rect.uy()) - bottom
                else:
                    layer = PIMP
                    bottom = max(left_rect.by(), right_rect.by())
                    height = max(left_rect.uy(), right_rect.uy()) - bottom
                self.add_rect(layer, vector(left_rect.lx(), bottom), height=height,
                              width=right_rect.lx() - left_rect.lx() + implant_width)
                if i == len(insts) - 2:
                    self.add_rect(layer, right_rect.lr(), height=right_rect.height,
                                  width=self.width - right_rect.rx())
