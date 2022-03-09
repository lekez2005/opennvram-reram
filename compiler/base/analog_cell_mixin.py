from typing import TYPE_CHECKING

import tech
from base import utils
from base.utils import round_to_grid as rg
from base.contact import well as well_contact, m1m2, m2m3
from base.design import ACTIVE, NIMP, PIMP, METAL2, METAL3, METAL1
from base.layout_clearances import find_clearances, HORIZONTAL
from base.pin_layout import pin_layout
from base.vector import vector
from base.well_active_contacts import add_power_tap, calculate_num_contacts
from pgates.ptx import ptx
from pgates.ptx_spice import ptx_spice

if TYPE_CHECKING:
    from base.design import design as design_
else:
    class design_:
        pass


class AnalogMixin(design_):
    """Contains commonly used routines in analog cells"""

    @staticmethod
    def get_sorted_pins(tx_inst, pin_name):
        return list(sorted(tx_inst.get_pins(pin_name), key=lambda x: x.lx()))

    @staticmethod
    def calculate_num_fingers(available_width: float, sample_ptx: ptx):
        poly_pitch = sample_ptx.poly_pitch
        end_to_poly = ptx.calculate_end_to_poly()
        return 1 + round((available_width - 2 * end_to_poly - sample_ptx.poly_width) /
                         poly_pitch)

    def connect_ptx_spice(self, name, tx_inst, connections, num_fingers=None):
        tx = tx_inst.mod
        num_fingers = num_fingers or tx.mults
        tx_spice = ptx_spice(width=tx.tx_width, mults=num_fingers,
                             tx_type=tx.tx_type, tx_length=tx.tx_length)
        self.add_mod(tx_spice)
        self.add_inst(name, tx_spice, vector(0, 0))
        self.connect_inst(connections)

    def calculate_rail_to_active(self, tx, x_axis_mirror=False):
        # power rails to tx actives
        well_contact_mid_y = 0.5 * self.rail_height
        well_contact_active_top = well_contact_mid_y + 0.5 * well_contact.first_layer_width

        active_space = tech.drc.get("active_to_body_active", self.get_space(ACTIVE))

        rail_to_active = well_contact_active_top + active_space

        # based on implants
        implant_top = max(well_contact_active_top + self.implant_enclose_active,
                          well_contact_mid_y + 0.5 * self.implant_width)

        tx_implant = max(tx.get_layer_shapes(NIMP) + tx.get_layer_shapes(PIMP),
                         key=lambda x: x.width * x.height)

        if x_axis_mirror:
            active_to_implant = tx_implant.uy() - tx.active_rect.uy()
        else:
            active_to_implant = tx.active_rect.by() - tx_implant.by()
        implant_based_space = active_to_implant + implant_top
        # based on poly
        poly_based_space = well_contact_active_top + tx.poly_extend_active + self.poly_to_active

        return max(rail_to_active, implant_based_space, poly_based_space)

    def add_power_tap(self, pin_name, y_offset):
        return add_power_tap(self, y_offset, pin_name, self.width)

    def augment_power_pins(self):
        if not getattr(tech, "has_local_interconnect"):
            return
        for pin_name in ["vdd", "gnd"]:
            if pin_name not in self.pin_map:
                continue
            for pin in self.get_pins(pin_name):
                self.add_m1_m3_power_via(self, pin)

    @staticmethod
    def add_m1_m3_power_via(self: design_, pin: pin_layout, recursive=True,
                            recursive_insts=None, existing=None, add_m3_pin=True):
        if add_m3_pin:
            self.add_layout_pin(pin.name, METAL3, pin.ll(), width=pin.width(),
                                height=pin.height())

        m2_height = max(m1m2.second_layer_height, m2m3.first_layer_height)
        y_top = pin.cy() + 0.5 * m2_height + self.get_line_end_space(METAL2)
        y_bottom = pin.cy() - 0.5 * m2_height - self.get_line_end_space(METAL2)

        if recursive_insts:
            recursive = False

        if existing:
            left_edge = utils.round_to_grid(existing[0][0])
            right_edge = utils.round_to_grid(existing[-1][1])
        else:
            left_edge = 0.0
            right_edge = utils.round_to_grid(self.width)

        open_spaces = find_clearances(self, layer=METAL2, direction=HORIZONTAL,
                                      region=(y_bottom, y_top), recursive=recursive,
                                      recursive_insts=recursive_insts, existing=existing)

        fill_height = pin.height()
        _, fill_width = self.calculate_min_area_fill(fill_height, layer=METAL2)
        _, min_m2_width = self.calculate_min_area_fill(max(m1m2.w_2, m2m3.w_1))

        min_space = (max(m1m2.h_2, m2m3.h_1, fill_width) +
                     2 * self.get_parallel_space(METAL2))
        half_space = utils.round_to_grid(0.5 * min_space)

        def add_via_extension(mid_x, direction=1):
            self.add_rect(METAL1, vector(mid_x, pin.by()), height=pin.height(),
                          width=direction * 0.5 * m1m2.h_1)
            self.add_rect(METAL3, vector(mid_x, pin.by()), height=pin.height(),
                          width=direction * 0.5 * m2m3.h_2)

        for space in open_spaces:
            space = [utils.round_to_grid(x) for x in space]
            extent = utils.round_to_grid(space[1] - space[0])

            via_extent = extent - 2 * self.get_line_end_space(METAL2)

            for i, via in enumerate([m1m2, m2m3]):
                sample_contact = calculate_num_contacts(self, via_extent,
                                                        layer_stack=via.layer_stack,
                                                        return_sample=True)
                if space[0] == left_edge:
                    mid_contact = None
                    if space[1] == right_edge:
                        m2_extent = sample_contact.h_2 if i == 0 else sample_contact.h_1
                        m2_space = self.get_line_end_space(METAL2)
                        if rg((right_edge - left_edge) - (m2_extent + m2_space)) >= 0:
                            mid_contact = rg(0.5 * (space[0] + space[1]))
                    if mid_contact is None:
                        # align with adjacent cell
                        mid_contact = (left_edge - 0.5 * via.height +
                                       0.5 * sample_contact.height)
                        if extent <= half_space:
                            continue
                        add_via_extension(left_edge, -1)
                elif space[1] == right_edge:
                    mid_contact = (right_edge + 0.5 * via.height -
                                   0.5 * sample_contact.height)
                    if extent <= half_space:
                        continue
                    add_via_extension(right_edge, 1)
                else:
                    if extent <= min_space:
                        continue
                    mid_contact = utils.round_to_grid(0.5 * (space[0] + space[1]))

                offset = vector(mid_contact, pin.cy())

                self.add_contact_center(via.layer_stack, offset, rotate=90,
                                        size=sample_contact.dimensions)
                if i == 1 and sample_contact.h_2 < min_m2_width:
                    width = max(fill_width, sample_contact.h_2)
                    self.add_rect_center(METAL2, offset, width=width, height=fill_height)
