import debug
import tech
from base.contact import m1m2, m2m3, cross_m3m4, m3m4, contact
from base.design import METAL1, METAL3, METAL4, METAL5
from base.layout_clearances import find_clearances, VERTICAL
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from globals import OPTS
from modules.baseline_sram import BaselineSram
from modules.sram_mixins import StackedDecoderMixin, DecoderAddressPins
from modules.sram_power_grid import WordlineVddMixin


class ReRam(WordlineVddMixin, DecoderAddressPins, StackedDecoderMixin, BaselineSram):

    def route_decoder_power(self):
        rails = [self.mid_vdd, self.mid_gnd]
        pin_names = ["vdd", "gnd"]
        for rail, pin_name in zip(rails, pin_names):
            for pin in self.row_decoder_inst.get_pins(pin_name):
                self.add_rect(pin.layer, vector(rail.lx(), pin.by()), height=pin.height(),
                              width=pin.lx() - rail.lx())
                via = m1m2 if pin.layer == METAL1 else m2m3
                self.add_contact_center(via.layer_stack, vector(rail.cx(), pin.cy()),
                                        size=[1, 2], rotate=90)

        self.add_m2_m4_power()
        self.route_write_driver_power()
        self.create_vdd_wordline()

    def copy_layout_pins(self):
        self.add_address_pins()
        exceptions = ["vdd", "gnd", "vdd_wordline"] + self.bank.vdd_write_pins
        for pin in self.pins:
            if pin.lower() in self.pin_map or pin in exceptions:
                continue

            for inst in [self.bank_inst, self.row_decoder_inst]:
                conn_index = self.insts.index(inst)
                inst_conns = self.conns[conn_index]
                if pin in inst_conns:
                    pin_index = inst_conns.index(pin)
                    debug.info(2, "Copy inst %s layout pin %s to %s", inst.name,
                               inst.mod.pins[pin_index], pin)
                    self.copy_layout_pin(inst, inst.mod.pins[pin_index], pin)
                    break
        tech.add_tech_layers(self)

    def route_write_driver_power(self):

        def get_top_pin(pin_name):
            return max(self.bank_inst.get_pins(pin_name), key=lambda x: x.cy())

        pins = sorted([get_top_pin(x) for x in self.bank.vdd_write_pins],
                      key=lambda x: x.cy())

        if OPTS.separate_vdd_write:
            # TODO: sky_tapeout: remove duplicated logic
            # add y shift to prevent clash with vdd
            y_shift = 1
            mid_y = 0.5 * (pins[0].cy() + pins[0].cy()) + y_shift
            y_offsets = [mid_y - 0.5 * self.power_grid_y_space - self.power_grid_width,
                         mid_y + 0.5 * self.power_grid_y_space]
        else:
            pin = pins[0]
            y_offsets = [pin.cy() - 0.5 * self.power_grid_width]
        for i, pin in enumerate(pins):
            self.add_layout_pin(pin.name, METAL5, vector(pin.lx(), y_offsets[i]),
                                width=pin.width(), height=self.power_grid_width)
            self.power_grid_y_forbidden.append(y_offsets[i])

    def add_m2_m4_power(self):
        self.m4_gnd_rects = []
        self.m4_vdd_rects = []
        self.m4_power_pins = m4_power_pins = (self.bank_inst.get_pins("vdd") +
                                              self.bank_inst.get_pins("gnd"))
        rails = [self.mid_vdd, self.mid_gnd]
        pin_names = ["vdd", "gnd"]
        for pin_name, rail in zip(pin_names, rails):
            m4_pin = self.add_layout_pin(pin_name, METAL4, rail.ll(), width=rail.width,
                                         height=rail.height)
            m4_power_pins.append(m4_pin)
            open_spaces = find_clearances(self, METAL3, direction=VERTICAL,
                                          region=(m4_pin.lx(), m4_pin.rx()),
                                          existing=[(m4_pin.by(), m4_pin.uy())])
            # TODO: sky_tapeout: remove duplicated logic
            min_space = 1
            for open_space in open_spaces:
                available_space = open_space[1] - open_space[0] - min_space
                if available_space <= 0:
                    continue
                mid_via_y = 0.5 * (open_space[0] + open_space[1])
                for via in [m2m3, m3m4]:
                    sample_contact = calculate_num_contacts(self, available_space,
                                                            layer_stack=via.layer_stack,
                                                            return_sample=True)
                    if available_space > sample_contact.h_1:
                        self.add_contact_center(via.layer_stack,
                                                vector(rail.cx(), mid_via_y),
                                                size=[1, sample_contact.dimensions[1]])

    def route_power_grid(self):
        super().route_power_grid()

        m4m5 = ("metal4", "via4", "metal5")
        m5m6 = ("metal5", "via5", "metal6")

        fill_width = m3m4.w_2
        _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL4)

        right_vdd = max(self.bank_inst.get_pins("vdd"), key=lambda x: x.rx())

        vdd_rects = self.m4_vdd_rects

        for write_pin_name in self.bank.vdd_write_pins:
            sram_pin = self.get_pin(write_pin_name)
            bank_pins = self.bank.get_pins(write_pin_name)
            for rect in vdd_rects:
                if (sram_pin.lx() <= rect.cx() <= sram_pin.rx() and
                        rect.cx() <= right_vdd.lx()):

                    offset = vector(rect.cx(), sram_pin.cy())
                    self.add_contact_center(m4m5, offset)

                    for bank_pin in bank_pins:

                        offset = vector(rect.cx(), bank_pin.cy())
                        self.add_cross_contact_center(cross_m3m4, offset, fill=False,
                                                      rotate=True)

                        if offset.y < sram_pin.cy():
                            m4_end = max(sram_pin.cy(), offset.y + fill_height)
                        else:
                            m4_end = min(sram_pin.cy(), offset.y - fill_height)
                        height = m4_end - offset.y
                        offset.y = 0.5 * (offset.y + m4_end)
                        self.add_rect_center(METAL4, offset, width=fill_width, height=height)

        wordline_pin = self.get_pin("vdd_wordline")

        open_spaces = find_clearances(self, METAL5, direction=VERTICAL,
                                      region=(wordline_pin.lx(), wordline_pin.rx()),
                                      existing=[(wordline_pin.by(), wordline_pin.uy())])

        # adjust tech.power_grid_y_space until there is space for wordline via
        # TODO: sky_tapeout: remove duplicated logic
        sample_m5m6 = contact(m5m6)
        min_space = sample_m5m6.height + 2 * self.get_wide_space(METAL5)
        for open_space in open_spaces:
            if open_space[1] - open_space[0] < min_space:
                continue
            mid_via_y = 0.5 * (open_space[0] + open_space[1])
            offset = vector(wordline_pin.cx(), mid_via_y)
            self.add_contact_center(m4m5, offset)
            self.add_contact_center(m5m6, offset)
