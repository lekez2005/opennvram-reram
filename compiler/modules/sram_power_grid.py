from typing import TYPE_CHECKING

import debug
import tech
from base import utils
from base.contact_full_stack import ContactFullStack
from base.design import METAL4, METAL5, NWELL
from base.utils import round_to_grid as round_
from base.vector import vector

if TYPE_CHECKING:
    from modules.baseline_sram import BaselineSram
else:
    class BaselineSram:
        pass


class SramPowerGridMixin(BaselineSram):

    def initialize_power_grid(self, add_power_grid):
        self.add_power_grid = add_power_grid
        if not self.add_power_grid:
            return
        self.power_grid_x_forbidden = []
        self.power_grid_y_forbidden = []
        self.calculate_power_grid_pitch()

    def get_power_grid_forbidden_regions(self):
        return self.power_grid_x_forbidden, self.power_grid_y_forbidden

    def calculate_power_grid_pitch(self):
        """Calculate x and y power grid width + space + grid"""
        second_top_layer, top_layer = tech.power_grid_layers
        self.power_grid_x_layer = top_layer
        self.power_grid_y_layer = second_top_layer

        power_grid_width = getattr(tech, "power_grid_width", self.m4_width)
        power_grid_x_space = getattr(tech, "power_grid_x_space",
                                     self.get_wide_space(second_top_layer))
        power_grid_y_space = getattr(tech, "power_grid_y_space",
                                     self.get_wide_space(top_layer))

        # second_top to top layer via
        m_top_via = ContactFullStack(start_layer=second_top_layer, stop_layer=top_layer,
                                     centralize=True, max_width=power_grid_width,
                                     max_height=power_grid_width)
        power_grid_width = max(power_grid_width, m_top_via.width)

        power_grid_height = max(m_top_via.height, power_grid_width)

        self.power_grid_x_space = power_grid_x_space
        self.power_grid_y_space = power_grid_y_space
        self.power_grid_width = power_grid_width
        self.power_grid_height = power_grid_height

        self.power_grid_x_pitch = self.power_grid_x_space + self.power_grid_width
        self.power_grid_y_pitch = self.power_grid_y_space + self.power_grid_height

        self.power_grid_top_via = m_top_via

    def calculate_grid_m4_vias(self, m_top_via):
        """ m4 to second_top layer vias """
        all_m4_power_pins = self.m4_power_pins + self.m4_gnd_rects + self.m4_vdd_rects
        all_m4_power_widths = list(set([utils.round_to_grid(x.rx() - x.lx())
                                        for x in all_m4_power_pins]))

        if not self.power_grid_y_layer == METAL5:
            m5_via = ContactFullStack(start_layer=METAL5, stop_layer=self.power_grid_y_layer,
                                      centralize=True, max_width=m_top_via.width)
            via_m5_height = m5_via.via_insts[0].mod.first_layer_width
        else:
            m5_via = None
            via_m5_height = None

        self.power_grid_m4_vias = all_m4_vias = {}

        for width in all_m4_power_widths:
            via_height = max(self.power_grid_height, via_m5_height or 0.0)
            all_m4_vias[width] = ContactFullStack(start_layer=METAL4, stop_layer=METAL5,
                                                  centralize=True, max_width=width,
                                                  max_height=via_height)
        rail_height = max(map(lambda x: x.height, [m_top_via] + list(all_m4_vias.values())))
        self.power_grid_height = max(rail_height, self.power_grid_height)
        self.power_grid_y_pitch = self.power_grid_y_space + self.power_grid_height

        return m5_via, all_m4_power_pins, all_m4_vias

    def calculate_grid_positions(self, min_value, max_value, forbidden_values, pitch):
        forbidden_regions = []
        for offset in forbidden_values:
            forbidden_regions.append((round_(offset - pitch), round_(offset + pitch)))
        grid_pos = []
        offset = min_value
        while offset <= max_value:
            collision = False
            for lower_bound, upper_bound in forbidden_regions:
                if lower_bound <= offset <= upper_bound:
                    collision = True
                    break
            if not collision:
                grid_pos.append(offset)
            offset += pitch
        return grid_pos

    def connect_y_rail_to_m4(self, rail_rect, m4_rects, all_m4_vias, m5_via):
        prev_m4_rect = None
        m4_space = self.get_wide_space(METAL4)
        rail_space = self.power_grid_y_space

        for m4_rect in m4_rects:
            if m4_rect.by() > rail_rect.by() or m4_rect.uy() < rail_rect.uy():
                continue
            m4_rect_width = utils.round_to_grid(m4_rect.rx() - m4_rect.lx())
            m4_via = all_m4_vias[m4_rect_width]

            if prev_m4_rect:
                if (m4_rect.cx() - 0.5 * m4_via.width <
                        prev_m4_rect.cx() + 0.5 * m4_via.width + m4_space):
                    continue
            # add m4 via
            self.add_inst(m4_via.name, mod=m4_via,
                          offset=vector(m4_rect.cx(), rail_rect.cy() - 0.5 * m4_via.height))
            self.connect_inst([])
            # add m5 via
            if m5_via:
                m4_m5_via = m4_via.via_insts[0].mod
                if prev_m4_rect and (m4_rect.cx() - 0.5 * m5_via.width <
                                     prev_m4_rect.cx() + 0.5 * m5_via.width + rail_space):
                    # just connect using M5
                    rect_height = m4_m5_via.second_layer_width
                    self.add_rect(METAL5, offset=vector(prev_m4_rect.cx(),
                                                        rail_rect.cy() - 0.5 * rect_height),
                                  width=m4_rect.cx() + 0.5 * m4_via.width - prev_m4_rect.cx(),
                                  height=rect_height)
                else:
                    self.add_inst(m5_via.name, mod=m5_via,
                                  offset=vector(m4_rect.cx(),
                                                rail_rect.cy() - 0.5 * m5_via.height))
                    self.connect_inst([])

                prev_m4_rect = m4_rect

    def route_power_grid(self):
        if not self.add_power_grid:
            for i in range(self.num_banks):
                self.copy_layout_pin(self.bank_insts[i], "vdd")
                self.copy_layout_pin(self.bank_insts[i], "gnd")
            return

        debug.info(1, "Route sram power grid")

        second_top_layer, top_layer = tech.power_grid_layers
        debug.check(int(second_top_layer[5:]) > 4 and int(top_layer[5:]) > 5,
                    "Power grid only supported for > M4")
        m_top_via = self.power_grid_top_via
        m5_via, all_m4_power_pins, all_m4_vias = self.calculate_grid_m4_vias(m_top_via)

        x_forbidden, y_forbidden = self.get_power_grid_forbidden_regions()

        # dimensions of vertical top layer grid
        left = min(map(lambda x: x.cx(), all_m4_power_pins)) - 0.5 * m_top_via.width
        right = max(map(lambda x: x.cx(), all_m4_power_pins)) - 0.5 * m_top_via.width
        bottom = min(map(lambda x: x.by(), all_m4_power_pins))
        top = max(map(lambda x: x.uy(), all_m4_power_pins))

        # add top layer
        top_layer_pins = []

        x_grid_pos = self.calculate_grid_positions(left, right, x_forbidden, self.power_grid_x_pitch)
        for i, x_offset in enumerate(x_grid_pos):
            pin_name = "gnd" if i % 2 == 0 else "vdd"
            top_layer_pins.append(self.add_layout_pin(pin_name, top_layer, offset=vector(x_offset, bottom),
                                                      width=self.power_grid_width,
                                                      height=top - bottom))
        top_gnd = top_layer_pins[0::2]
        top_vdd = top_layer_pins[1::2]

        # add second_top layer
        m4_vdd_rects = self.m4_vdd_rects + [x for x in self.m4_power_pins if x.name == "vdd"]
        self.m4_vdd_rects = m4_vdd_rects = list(sorted(m4_vdd_rects, key=lambda x: x.lx()))
        m4_gnd_rects = self.m4_gnd_rects + [x for x in self.m4_power_pins if x.name == "gnd"]
        m4_gnd_rects = list(sorted(m4_gnd_rects, key=lambda x: x.lx()))

        y_grid_pos = self.calculate_grid_positions(bottom, top - self.power_grid_height,
                                                   y_forbidden, self.power_grid_y_pitch)

        for i, y_offset in enumerate(y_grid_pos):
            pin_name = "gnd" if i % 2 == 0 else "vdd"
            pin = self.add_layout_pin(pin_name, second_top_layer, offset=vector(left, y_offset),
                                      height=self.power_grid_height,
                                      width=right + m_top_via.width - left)
            rail_rect = pin
            # connect to top grid
            top_pins = top_gnd if i % 2 == 0 else top_vdd
            for top_pin in top_pins:
                self.add_inst(m_top_via.name, m_top_via,
                              offset=vector(top_pin.cx(), rail_rect.cy() - 0.5 * m_top_via.height))
                self.connect_inst([])

            # connect to m4 below
            m4_rects = m4_gnd_rects if i % 2 == 0 else m4_vdd_rects
            self.connect_y_rail_to_m4(rail_rect, m4_rects, all_m4_vias, m5_via)


class WordlineVddMixin(BaselineSram):

    def calculate_separate_vdd_row_dec_x(self, max_x_offset):
        # wordline nwell x
        wordline_driver = self.bank.wordline_driver_inst.mod
        if hasattr(wordline_driver, "add_body_taps"):
            wordline_driver.add_body_taps()

        reference_y = utils.round_to_grid(wordline_driver.buffer_insts[0].by())

        insts = [x for x in wordline_driver.insts
                 if utils.round_to_grid(x.by()) == reference_y]
        wordline_well = min(wordline_driver.get_layer_shapes(NWELL, insts=insts),
                            key=lambda x: x.lx())
        wordline_x = (wordline_well.lx() + self.bank.wordline_driver_inst.lx() +
                      self.bank_inst.lx())
        # decoder nwell x
        reference_y = utils.round_to_grid(self.row_decoder.nand_inst[0].by())
        insts = [x for x in self.row_decoder.insts
                 if utils.round_to_grid(x.by()) == reference_y]
        decoder_wells = self.row_decoder.get_layer_shapes(NWELL, insts=insts)
        decoder_wells = [x for x in decoder_wells if x.uy() > reference_y]
        decoder_well = max(decoder_wells, key=lambda x: x.rx())
        decoder_right = decoder_well.rx()

        well_space = self.get_space(NWELL, prefix="different")
        max_x_offset = min(max_x_offset, wordline_x - well_space - decoder_right)
        return max_x_offset

    def create_vdd_wordline(self: 'BaselineSram'):
        _, top_layer = tech.power_grid_layers
        for bank_inst in self.bank_insts:
            pins = bank_inst.get_pins("vdd_wordline")
            pins = [x for x in pins if x.layer == METAL4]
            for pin in pins:
                x_offset = pin.cx() - 0.5 * self.power_grid_width
                self.add_layout_pin("vdd_wordline", top_layer, vector(x_offset, pin.by()),
                                    width=self.power_grid_width, height=pin.height())
                self.power_grid_x_forbidden.append(x_offset)

    def join_decoder_wells(self):
        pass

    def fill_decoder_wordline_space(self):
        pass
