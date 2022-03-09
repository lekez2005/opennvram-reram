from base import utils
from base.contact import m1m2, poly as poly_contact, cross_m1m2, cross_poly, \
    active as active_contact, m2m3, cross_m2m3, cross_m3m4
from base.design import design, METAL2, METAL1, NWELL, POLY, METAL3, METAL4
from base.vector import vector
from modules.reram.bitcell_aligned_pgate import BitcellAlignedPgate


class ReRamSenseAmp(BitcellAlignedPgate):

    @classmethod
    def get_name(cls, *args, **kwargs):
        return "re_ram_sense_amp"

    def __init__(self):
        # spice file is loaded if name matches file in sp_lib
        design.__init__(self, self.get_name())
        self.create_layout()

    def is_delay_primitive(self):
        return True

    def create_layout(self):
        self.create_modules()
        self.add_output_buffer()
        self.add_differential_amp()
        self.add_vclamp_nmos()
        self.add_sampleb()
        self.add_bitlines()
        self.route_power()
        self.flatten_tx()
        self.add_boundary()

    def add_ptx_inst(self, tx, y_offset, **kwargs):
        x_offset = self.mid_x - 0.5 * tx.width
        inst = self.add_inst(tx.name, tx, vector(x_offset, y_offset), **kwargs)
        self.connect_inst([], check=False)
        return inst

    def add_output_buffer(self):
        self.bottom_space = self.calculate_bottom_space()
        nmos_width = 0.36
        pmos_width = 0.72
        nmos = self.create_ptx_by_width(nmos_width, False, mults=2)
        pmos = self.create_ptx_by_width(pmos_width, True, mults=2)

        # place transistors
        nmos_y = self.bottom_space - nmos.active_rect.by()
        self.buffer_nmos = self.add_ptx_inst(nmos, nmos_y)
        contact_y = (nmos_y + nmos.active_rect.uy() +
                     self.calculate_active_to_poly_cont_mid("nmos")) + 0.05

        pmos_y = (contact_y + self.calculate_active_to_poly_cont_mid("pmos") -
                  pmos.active_rect.by())
        self.buffer_pmos = self.add_ptx_inst(pmos, pmos_y)
        self.buffer_vdd_y = vdd_y = (self.buffer_pmos.by() +
                                     self.buffer_pmos.mod.active_rect.uy() +
                                     self.bottom_space - self.rail_height)

        # poly contact
        self.join_poly(self.buffer_nmos, self.buffer_pmos)
        via_x_offsets = self.calculate_poly_via_offsets(self.buffer_nmos)
        for x_offset in via_x_offsets:
            self.add_cross_contact_center(cross_poly, vector(x_offset, contact_y), )
        x_offset = self.buffer_nmos.rx() + self.m2_width
        self.add_rect(METAL1, vector(x_offset, contact_y - 0.5 * self.m1_width),
                      width=via_x_offsets[0] - x_offset)
        offset = vector(x_offset + 0.5 * self.m2_width, contact_y)
        self.add_cross_contact_center(cross_m1m2, offset, rotate=True)
        # dout not needed so leave it at via
        self.add_layout_pin("dout", METAL2,
                            vector(x_offset, contact_y),
                            height=vdd_y + self.rail_height - contact_y)

        # dout_bar
        nmos_pin = self.buffer_nmos.get_pin("D")
        pmos_pin = self.buffer_pmos.get_pin("D")
        for pin in [nmos_pin, pmos_pin]:
            self.add_contact_center(m1m2.layer_stack, pin.center())

        self.add_layout_pin("dout_bar", METAL2, vector(pin.cx() - 0.5 * self.m2_width, 0),
                            height=pmos_pin.cy())

        self.add_power_tap(0, "gnd", self.buffer_nmos, add_m3=False)
        self.add_power_tap(vdd_y, "vdd", self.buffer_pmos)

    def add_differential_amp(self):
        nmos_width = 0.6
        pmos_width = 0.6
        nmos = self.create_ptx_by_width(nmos_width, False, mults=4,
                                        active_cont_pos=[0, 1, 3, 4])
        pmos = self.create_ptx_by_width(pmos_width, True, mults=4)

        pmos_y = self.buffer_vdd_y + self.bottom_space
        p_contact_y = (pmos_y + pmos.active_rect.uy() +
                       self.calculate_active_to_poly_cont_mid("pmos"))
        n_contact_y = p_contact_y + poly_contact.h_1 + self.poly_vert_space

        n_active_bottom = n_contact_y + self.calculate_active_to_poly_cont_mid("nmos")
        nmos_y = n_active_bottom - nmos.active_rect.by()

        self.diff_pmos = self.add_ptx_inst(pmos, pmos_y)
        self.diff_nmos = self.add_ptx_inst(nmos, nmos_y)

        self.buffer_gnd_y = gnd_y = (self.diff_nmos.by() +
                                     self.diff_nmos.mod.active_rect.uy() +
                                     self.bottom_space - self.rail_height)

        # pmos poly contact
        pmos_poly = self.get_sorted_pins(self.diff_pmos, "G")
        ext = 0.5 * poly_contact.w_1
        via_offsets = [pmos_poly[0].rx() - ext,
                       0.5 * (pmos_poly[1].cx() + pmos_poly[2].cx()) + 0.04,
                       pmos_poly[-1].lx() + ext]
        for x_offset in via_offsets:
            self.add_cross_contact_center(cross_poly, vector(x_offset, p_contact_y))
        for i, layer in enumerate([POLY, METAL1]):
            height = [poly_contact.h_1, poly_contact.w_2][i]
            self.add_rect(layer, vector(pmos_poly[0].cx(), p_contact_y - 0.5 * height),
                          width=pmos_poly[-1].cx() - pmos_poly[0].cx(), height=height)
        for poly_rect in pmos_poly:
            self.add_rect(POLY, poly_rect.ul(), width=poly_rect.width(),
                          height=p_contact_y - poly_rect.uy())
        pmos_pin = self.get_sorted_pins(self.diff_pmos, "D")[0]
        self.add_rect(METAL1, pmos_pin.ul(), width=pmos_pin.width(),
                      height=p_contact_y - pmos_pin.uy())

        # nmos poly
        nmos_poly = self.get_sorted_pins(self.diff_nmos, "G")
        for x_offset in via_offsets:
            self.add_cross_contact_center(cross_poly, vector(x_offset, n_contact_y))

        y_offset = n_contact_y - 0.5 * poly_contact.h_1
        for poly_rect in nmos_poly:
            self.add_rect(POLY, vector(poly_rect.lx(), y_offset), width=poly_rect.width(),
                          height=poly_rect.by() - y_offset)
        self.add_rect(POLY, vector(nmos_poly[1].cx(), y_offset),
                      width=nmos_poly[2].cx() - nmos_poly[1].cx(),
                      height=poly_contact.h_1)
        # vref
        dout_nmos_pin = self.get_sorted_pins(self.diff_nmos, "D")[-1]
        dout_rail_x = dout_nmos_pin.cx() + 0.5 * m1m2.w_2

        vref_pin_y = p_contact_y + m1m2.width + 0.5 * self.m3_space
        via_x = dout_rail_x - self.m2_space - max(0.5 * m1m2.h_2, 0.5 * m2m3.h_1)
        via_y = vref_pin_y + 0.5 * self.bus_width
        self.add_cross_contact_center(cross_m1m2, vector(via_x, via_y),
                                      rotate=True)
        self.add_cross_contact_center(cross_m2m3, vector(via_x, via_y))
        self.add_layout_pin("vref", METAL3, vector(0, vref_pin_y), height=self.bus_width,
                            width=self.width)

        # enable
        en_pin_y = vref_pin_y + self.bus_width + self.bus_space + self.m3_space
        via_y = en_pin_y + 0.5 * self.bus_width
        self.add_cross_contact_center(cross_m2m3, vector(via_offsets[1], via_y))
        self.add_rect(METAL2, vector(via_offsets[1] - 0.5 * self.m2_width, n_contact_y),
                      height=via_y - n_contact_y)
        self.add_cross_contact_center(cross_m1m2, vector(via_offsets[1], n_contact_y),
                                      rotate=True)
        self.add_layout_pin("en", METAL3, vector(0, en_pin_y), height=self.bus_width,
                            width=self.width)

        # nmos gnd pin
        gnd_contact_y = n_active_bottom + nmos.active_rect.height - 0.5 * active_contact.h_1
        self.add_contact_center(active_contact.layer_stack, vector(self.mid_x, gnd_contact_y),
                                rotate=90)

        # common nmos node
        left_pin = self.get_sorted_pins(self.diff_nmos, "D")[0]
        right_pin = self.get_sorted_pins(self.diff_nmos, "S")[1]
        y_offset = gnd_contact_y - 0.5 * active_contact.w_2 - self.m1_space - self.m1_width
        self.add_rect(METAL1, vector(left_pin.lx(), y_offset),
                      width=right_pin.rx() - left_pin.lx())
        for pin in [left_pin, right_pin]:
            self.add_rect(METAL1, vector(pin.lx(), y_offset), height=pin.by() - y_offset)

        # join nmos drain to pmos poly
        nmos_pin = self.get_sorted_pins(self.diff_nmos, "S")[0]
        via_x_offset = nmos_pin.cx() - 0.5 * self.m2_width + 0.5 * m1m2.h_1
        via_y_offset = p_contact_y - 0.5 * m1m2.w_1
        self.add_contact_center(m1m2.layer_stack, vector(via_x_offset, p_contact_y), rotate=90)

        self.add_contact_center(m1m2.layer_stack, nmos_pin.center())
        self.add_rect(METAL2, vector(nmos_pin.cx() - 0.5 * self.m2_width, via_y_offset),
                      height=nmos_pin.cy() - via_y_offset)

        # vdata
        x_offset = nmos_pin.cx() + 0.5 * m1m2.w_2 + self.m2_space + 0.5 * self.m2_width
        via_offset = vector(x_offset + 0.5 * self.m2_width, n_contact_y)
        self.add_cross_contact_center(cross_m1m2, via_offset, rotate=True)
        self.vdata_rect = self.add_rect(METAL2, vector(x_offset, n_contact_y),
                                        height=gnd_y - n_contact_y)

        # dout
        dout_pmos_pin = self.get_sorted_pins(self.diff_pmos, "D")[-1]

        y_bend = dout_pmos_pin.uy() + self.m2_space + 0.5 * self.m2_width
        x_end = dout_rail_x + 0.5 * self.m2_width
        dout_pin = self.get_pin("dout")
        self.add_path(METAL2, [dout_pin.uc(),
                               vector(dout_pin.cx(), y_bend),
                               vector(x_end, y_bend),
                               vector(x_end, dout_nmos_pin.cy() + 0.5 * m1m2.h_2)])
        self.add_contact_center(m1m2.layer_stack, dout_pmos_pin.center())
        self.add_rect(METAL2, vector(dout_pmos_pin.cx(),
                                     dout_pmos_pin.cy() - 0.5 * self.m2_width),
                      width=dout_pin.cx() - dout_pmos_pin.cx())
        self.add_contact_center(m1m2.layer_stack, dout_nmos_pin.center())

        vdd_pin = list(sorted(self.get_pins("vdd"), key=lambda x: x.cy()))[-1]
        self.extend_tx_well(self.diff_pmos, NWELL, vdd_pin)
        self.add_power_tap(gnd_y, "gnd", self.buffer_nmos)

        gnd_pin = list(sorted(self.get_pins("gnd"), key=lambda x: x.cy()))[-1]
        offset = vector(self.mid_x - 0.5 * active_contact.h_2,
                        gnd_contact_y - 0.5 * active_contact.w_2)
        self.add_rect(METAL1, offset, width=active_contact.h_2, height=gnd_pin.cy() - offset.y)

    def add_vclamp_nmos(self):
        nmos = self.create_ptx_by_width(0.36, False, mults=4,
                                        active_cont_pos=[])
        y_offset = self.buffer_gnd_y + self.bottom_space + 0.5 * self.m1_space
        self.clamp_nmos = self.add_ptx_inst(nmos, y_offset)

        active_bottom = y_offset + nmos.active_rect.by()
        active_top = active_bottom + nmos.active_rect.height
        bottom_via_y = active_bottom + 0.5 * active_contact.h_1
        top_via_y = active_top - 0.5 * active_contact.h_1

        source_pins = []
        drain_pins = []
        pins = {"S": source_pins, "D": drain_pins}
        for pin_name, via_y, rotate, in zip(["S", "D"], [bottom_via_y, top_via_y],
                                            [0, 90]):
            sample_pins = self.diff_pmos.get_pins(pin_name)
            for sample_pin in sample_pins:
                pin = self.add_contact_center(active_contact.layer_stack,
                                              vector(sample_pin.cx(), via_y),
                                              rotate=rotate)
                pins[pin_name].append(pin)

        # route bl
        y_offset = top_via_y - 0.5 * active_contact.w_2 - self.m1_space - self.m1_width
        x_offset = source_pins[0].cx() - 0.5 * active_contact.w_2
        self.add_rect(METAL1, vector(x_offset, y_offset),
                      width=source_pins[-1].cx() - x_offset + 0.5 * active_contact.w_2)
        for pin in source_pins:
            self.add_rect(METAL1, vector(pin.cx() - 0.5 * active_contact.w_2, y_offset),
                          height=pin.cy() - y_offset)
        self.bl_y = y_offset + 0.5 * self.m1_width

        # route vdata
        m2_via_height = max(m1m2.h_2, m2m3.h_1)
        vdata_via_y = (y_offset + 0.5 * self.m1_width + 0.5 * m1m2.h_2 +
                       self.m2_space + 0.5 * m2_via_height)
        self.add_rect(METAL2, self.vdata_rect.ul(), height=vdata_via_y - self.vdata_rect.uy())
        for pin in drain_pins:
            self.add_cross_contact_center(cross_m1m2, vector(pin.cx(), vdata_via_y),
                                          rotate=True)
        y_offset = vdata_via_y - 0.5 * self.m2_width
        self.add_rect(METAL2, vector(drain_pins[0].cx(), y_offset),
                      width=drain_pins[-1].cx() - drain_pins[0].cx())

        # vclamp
        via_y = active_top + self.calculate_active_to_poly_cont_mid("nmos")
        # by m1 space
        via_y = max(via_y, vdata_via_y + 0.5 * m1m2.w_1 + self.m1_space +
                    0.5 * self.bus_width)

        self.vclamp_via_y = via_y
        poly_rects = self.get_sorted_pins(self.clamp_nmos, "G")
        ext = 0.5 * poly_contact.w_1
        via_offsets = [poly_rects[0].rx() - ext,
                       0.5 * (poly_rects[1].cx() + poly_rects[2].cx()),
                       poly_rects[-1].lx() + ext]
        for x_offset in via_offsets:
            self.add_cross_contact_center(cross_poly, vector(x_offset, via_y))
        self.add_rect(METAL1, vector(via_offsets[0], via_y - 0.5 * self.m1_width),
                      width=via_offsets[-1] - via_offsets[0])
        for rect in poly_rects:
            self.add_rect(POLY, rect.ul(), width=rect.width(),
                          height=via_y + 0.5 * poly_contact.h_1 - rect.uy())

        self.create_left_pin("vclamp", via_y, via_offsets[0])
        x_offset = -0.5 * m2m3.w_2
        self.add_layout_pin("vclamp", METAL3, vector(x_offset, via_y - 0.5 * self.bus_width),
                            height=self.bus_width, width=self.width - 2 * x_offset)
        self.add_cross_contact_center(cross_m2m3, vector(0, via_y))
        self.add_cross_contact_center(cross_m1m2, vector(0, via_y), rotate=True)
        self.add_rect(METAL1, vector(0, via_y - 0.5 * self.m2_width), width=via_offsets[0])

    def create_left_pin(self, pin_name, mid_y, dest_m1_x):
        x_offset = -0.5 * m2m3.w_2
        self.add_layout_pin(pin_name, METAL3, vector(x_offset, mid_y - 0.5 * self.bus_width),
                            height=self.bus_width, width=self.width - 2 * x_offset)
        self.add_cross_contact_center(cross_m2m3, vector(0, mid_y))
        self.add_cross_contact_center(cross_m1m2, vector(0, mid_y), rotate=True)
        self.add_rect(METAL1, vector(0, mid_y - 0.5 * self.m2_width), width=dest_m1_x)
        self.fill_m2_via(vector(0, mid_y))

    def fill_m2_via(self, offset):
        self.bitcell.fill_m2_via(self, offset)

    def add_sampleb(self):
        pmos = self.create_ptx_by_width(0.9, True, mults=2,
                                        active_cont_pos=[0, 2])
        poly_cont_y = (self.vclamp_via_y + 0.5 * poly_contact.h_1 + self.poly_vert_space +
                       0.5 * poly_contact.h_1)
        active_bottom = poly_cont_y + self.calculate_active_to_poly_cont_mid("pmos")
        y_offset = active_bottom - pmos.active_rect.by()
        self.sample_pmos = self.add_ptx_inst(pmos, y_offset)

        # vdata
        source_pin = self.sample_pmos.get_pin("S")
        self.add_contact_center(m1m2.layer_stack, source_pin.center())
        self.add_rect(METAL2, self.vdata_rect.ul(),
                      height=source_pin.cy() - self.vdata_rect.uy())

        # poly contacts
        poly_rects = self.get_sorted_pins(self.sample_pmos, "G")
        ext = 0.5 * poly_contact.w_1
        via_offsets = [poly_rects[0].rx() - ext, poly_rects[1].lx() + ext]
        y_offset = poly_cont_y - 0.5 * poly_contact.h_1
        for i in range(2):
            self.add_cross_contact_center(cross_poly, vector(via_offsets[i], poly_cont_y))
            self.add_rect(POLY, vector(poly_rects[i].lx(), y_offset),
                          height=poly_rects[i].by() - y_offset,
                          width=poly_rects[i].width())
        # vclampp
        y_offset = self.get_pin("vclamp").uy() + 1.5 * self.bus_space + 0.5 * self.bus_width
        self.create_left_pin("vclampp", y_offset, via_offsets[0])

        # sampleb
        y_offset = self.get_pin("vclampp").uy() + 2 * self.bus_space + 0.5 * self.bus_width
        self.add_layout_pin("sampleb", METAL3, vector(0, y_offset - 0.5 * self.bus_width),
                            height=self.bus_width, width=self.width)
        x_offset = self.sample_pmos.get_pin("D").rx() + 2 * self.m1_space + 0.5 * m1m2.w_1
        offset = vector(x_offset, y_offset)
        self.add_contact_center(m1m2.layer_stack, offset)
        self.add_cross_contact_center(cross_m2m3, offset)
        self.fill_m2_via(offset)
        self.add_path(METAL1, [vector(via_offsets[1], poly_cont_y),
                               vector(x_offset, poly_cont_y),
                               offset])

        vdd_y = active_bottom + pmos.active_rect.height + self.bottom_space - self.rail_height
        vdd_y = utils.ceil(vdd_y)
        self.add_power_tap(vdd_y, "vdd", self.sample_pmos)
        self.height = vdd_y + self.rail_height

    def add_bitlines(self):
        for pin_name in ["bl", "br"]:
            bitcell_pin = self.bitcell.get_pin(pin_name)
            pin_y = self.rail_height
            offset = vector(bitcell_pin.cx() - 0.5 * self.m4_width, pin_y)
            width = max(bitcell_pin.width(), self.m4_width)
            self.add_layout_pin(pin_name, METAL4, offset, width=width,
                                height=self.height - pin_y)
            # add m2 to bottom to prevent adding m1-m3 vias at bitline positions
            self.add_rect(METAL2, vector(offset.x, 0), width=width, height=offset.y)
        bl_pin = self.get_pin("bl")
        m2_via_width = max(m1m2.w_2, m2m3.w_1)
        via_x = min(bl_pin.cx(),
                    self.vdata_rect.cx() - 0.5 * m1m2.w_2 - self.m2_space - 0.5 * m2_via_width)
        offset = vector(via_x, self.bl_y)
        self.add_cross_contact_center(cross_m1m2, offset, rotate=True)
        self.add_cross_contact_center(cross_m2m3, offset, rotate=False)
        self.add_cross_contact_center(cross_m3m4, offset, rotate=True)
        self.fill_m2_via(offset)

    def route_power(self):
        # route m1-m3 for bottom gnd
        bottom_gnd = min(self.get_pins("gnd"), key=lambda x: x.by())
        self.add_layout_pin("gnd", METAL3, bottom_gnd.ll(), width=bottom_gnd.width(),
                            height=bottom_gnd.height())

        dout_bar = self.get_pin("dout_bar")
        min_space = max(m2m3.w_1, m1m2.w_2) + 2 * self.get_space(METAL2)

        for pin_name in ["bl", "br"]:
            pin = self.get_pin(pin_name)
            left_pin, right_pin = sorted([pin, dout_bar], key=lambda x: x.lx())
            space = right_pin.lx() - left_pin.rx()
            if space >= min_space:
                offset = vector(0.5 * (left_pin.rx() + right_pin.lx()),
                                bottom_gnd.by() + 0.5 * max(m1m2.h_2, m2m3.h_1))
                self.add_cross_contact_center(cross_m1m2, offset, rotate=True)
                self.add_cross_contact_center(cross_m2m3, offset)

        # connect transistors to power
        for inst in [self.buffer_nmos, self.buffer_pmos, self.diff_pmos]:
            self.route_tx_to_power(inst, tx_pin_name="S")

        self.route_tx_to_power(self.sample_pmos, tx_pin_name="D")
