from typing import TYPE_CHECKING

import debug
from base import utils, layout_clearances
from base.contact import m2m3, cross_m2m3, cross_m1m2, contact, cross_m3m4, m3m4
from base.design import METAL2, METAL3, METAL4, METAL1, design
from base.vector import vector
from globals import OPTS
from modules.control_buffers import Rail, ControlBuffers

if TYPE_CHECKING:
    from modules.baseline_bank import BaselineBank
else:
    class BaselineBank:
        pass


class ControlSignalsMixin(BaselineBank):
    """Contain logic for adding control rails from control signals to peripherals"""

    def calculate_rail_offsets(self):
        """Calculate control rails y_offsets, triate_y, control_logic_y, mid_vdd, mid_gnd"""

        self.control_rail_pitch = self.bus_pitch

        self.control_names = self.get_control_names()
        control_outputs = [x for x in self.control_names if x in self.control_buffers.pins]

        self.left_control_rails = control_outputs

        control_outputs = list(sorted(control_outputs,
                                      key=lambda x: self.control_buffers.get_pin(x).lx()))
        # separate into top and bottom pins
        top_pins, bottom_pins = [], []
        for pin_name in control_outputs:
            pin = self.control_buffers.get_pin(pin_name)
            if pin.cy() > 0.5 * self.control_buffers.height:
                top_pins.append(pin_name)
            else:
                bottom_pins.append(pin_name)

        control_vdd = self.control_buffers.get_pins("vdd")[0]
        module_space = (0.5 * control_vdd.height() + self.get_parallel_space(METAL3) +
                        0.5 * m2m3.w_2)
        if OPTS.route_control_signals_left:
            self.calculate_left_rail_offsets(top_pins, bottom_pins, module_space)
        else:
            self.calculate_mid_array_rail_offsets(control_outputs, module_space)

        self.top_control_rails, self.bottom_control_rails = top_pins, bottom_pins
        # mid power rails
        self.wide_power_space = max([self.get_wide_space(METAL2),
                                     self.get_wide_space(METAL3),
                                    self.get_wide_space(METAL4)])
        self.mid_gnd_offset = self.get_mid_gnd_offset()
        self.mid_vdd_offset = self.mid_gnd_offset - self.wide_power_space - self.vdd_rail_width

        fill_height = m2m3.second_layer_height + self.m2_width
        (self.fill_height, self.fill_width) = self.calculate_min_area_fill(fill_height, self.m2_width)

    def calculate_control_buffers_y(self, num_top_rails, num_bottom_rails, module_space):
        if num_bottom_rails > 0:
            self.logic_buffers_bottom = ((num_bottom_rails * self.bus_pitch)
                                         - self.bus_space + module_space)
        else:
            self.logic_buffers_bottom = 0

        control_logic_top = self.get_control_logic_top(module_space)
        self.trigate_y = ((control_logic_top + (num_top_rails * self.bus_pitch)) +
                          self.get_line_end_space(METAL2))
        return control_logic_top

    def calculate_left_rail_offsets(self, top_pins, bottom_pins, module_space):

        control_logic_top = self.calculate_control_buffers_y(len(top_pins),
                                                             len(bottom_pins), module_space)

        self.control_rail_offsets = {}

        for i in range(len(top_pins)):
            self.control_rail_offsets[top_pins[i]] = control_logic_top + i * self.bus_pitch

        y_offset = 0
        for i in reversed(range(len(bottom_pins))):
            self.control_rail_offsets[bottom_pins[i]] = y_offset
            y_offset += self.bus_pitch

    @staticmethod
    def get_default_left_rails():
        return ["wordline_en"]

    def calculate_mid_array_m4_x_offset(self):
        """Calculate ideal position of m4 rail. Should be as far away from adjacent m4's"""
        # get vertical stack
        vertical_stack = self.get_vertical_instance_stack()
        if self.control_buffers_inst in vertical_stack:
            vertical_stack.remove(self.control_buffers_inst)
        vertical_stack = list(sorted(vertical_stack, key=lambda x: x.by()))

        # find largest contiguous x space in vertical stack
        rail_space = self.get_parallel_space(METAL4)
        min_space = utils.floor(self.m4_width + 2 * rail_space)

        m4_spaces = None
        for index, inst in enumerate(vertical_stack):
            new_m4_spaces = layout_clearances.find_clearances(inst.mod.child_mod, METAL4,
                                                              layout_clearances.HORIZONTAL,
                                                              existing=m4_spaces)
            biggest_space = max(new_m4_spaces, key=lambda x: x[1] - x[0])
            if biggest_space[1] - biggest_space[0] <= min_space:
                break
            m4_spaces = new_m4_spaces

        biggest_space = max(m4_spaces, key=lambda x: x[1] - x[0])
        biggest_space_span = biggest_space[1] - biggest_space[0]
        # set rail width based on available space
        func = utils.floor_2x_grid
        self.max_intra_m4_rail_width = func(min(m3m4.height,
                                                biggest_space_span - 2 * rail_space))
        mid_x_offset = 0.5 * (biggest_space[0] + biggest_space[1])
        self.intra_m4_rail_mid_x = utils.round_to_grid(mid_x_offset)
        debug.info(1, "max_intra_m4_rail_width = %.3g", self.max_intra_m4_rail_width)
        debug.info(1, "intra_m4_rail_mid_x = %.3g", self.intra_m4_rail_mid_x)

    def calculate_mid_array_rail_x_offsets(self, control_outputs):
        """Compute x offset of rails that go in between bitcell arrays"""
        left_rails = self.get_default_left_rails()
        if self.use_decoder_clk:
            left_rails.append("decoder_clk")
        elif not self.is_left_bank:
            left_rails.append("clk_buf")
        self.left_control_rails = left_rails
        num_mid_rails = len(control_outputs) - len(left_rails)
        if OPTS.centralize_control_signals:  # closest to middle
            x_offset = 0.5 * self.bitcell_array.width - (1 + 0.5 * num_mid_rails) * self.bitcell.width
        else:
            x_offset = 0  # closest to pin output
        left_x_offset = - 2 * self.vdd_rail_width
        left_rail_index = 0
        # find x offsets
        top_rails, bottom_rails = [], []

        rail_space = max(self.get_line_end_space(METAL3), self.get_parallel_space(METAL4))
        via_allowance = max(0.5 * m2m3.height, 0.5 * self.bus_width)
        for rail_name in control_outputs:
            pin = self.control_buffers.get_pin(rail_name)
            bitcell_index = -1
            if rail_name in left_rails:
                min_x, max_x = left_x_offset, pin.cx() + via_allowance
                rail_x = left_rail_index
                left_rail_index += 1
            else:
                min_x = pin.cx() - via_allowance
                closest_offset = self.find_closest_unoccupied_mid_x(max(x_offset, min_x))
                if closest_offset is None:
                    rail_x = max(pin.cx(), self.bitcell_array.width + via_allowance,
                                 x_offset + via_allowance)
                else:
                    bitcell_index, rail_x = closest_offset
                    self.occupied_m4_bitcell_indices.append(bitcell_index)
                max_x = rail_x
                x_offset = max_x + rail_space
            rail = Rail(rail_name, min_x, max_x)
            rail.x_index = bitcell_index
            rail.rail_x = rail_x
            if pin.cy() > 0.5 * self.control_buffers.height:
                top_rails.append(rail)
            else:
                bottom_rails.append(rail)
        return top_rails, bottom_rails

    def calculate_mid_array_rail_offsets(self, control_outputs, module_space):
        """Calculate both x offset and y offsets of rails that go in between bitcell arrays"""
        top_rails, bottom_rails = self.calculate_mid_array_rail_x_offsets(control_outputs)
        if hasattr(OPTS, "buffer_repeaters_x_offset"):
            # need space to be able to extend the rail to the repeaters
            for i in range(len(top_rails)):
                top_rails[i].index = i
            for i in range(len(bottom_rails)):
                bottom_rails[i].index = i
            num_top_rails = len(top_rails)
            num_bottom_rails = len(bottom_rails)
        else:
            num_top_rails = ControlBuffers.evaluate_no_overlap_rail_indices(top_rails)
            num_top_rails += 1

            num_bottom_rails = ControlBuffers.evaluate_no_overlap_rail_indices(bottom_rails)
            num_bottom_rails += 1

        control_logic_top = self.calculate_control_buffers_y(num_top_rails,
                                                             num_bottom_rails, module_space)
        for rail in top_rails:
            rail.y_offset = control_logic_top + rail.index * self.bus_pitch
        for rail in bottom_rails:
            rail.y_offset = rail.index * self.bus_pitch

        self.control_rail_offsets = {rail.name: rail for rail in top_rails}
        for rail in bottom_rails:
            self.control_rail_offsets[rail.name] = rail
        for rail_name in self.control_rail_offsets:
            if rail_name in self.left_control_rails:
                self.control_rail_offsets[rail_name] = self.control_rail_offsets[rail_name].y_offset

    def get_control_rails_base_x(self):
        return self.mid_vdd_offset - self.wide_m1_space

    def get_control_rails_order(self, destination_pins, get_top_destination_pin_y):
        rail_names = list(sorted(destination_pins.keys(),
                                 key=lambda x: (-self.control_buffers_inst.get_pin(x).uy(),
                                                get_top_destination_pin_y(x)),
                                 reverse=False))
        return rail_names

    def add_control_rails(self):
        """Add rails from control logic buffers to appropriate peripherals"""
        self.calculate_mid_array_m4_x_offset()

        def get_top_destination_pin_y(rail_name_):
            if not destination_pins[rail_name_]:
                return self.bitcell_array_inst.by()  # will be rightmost
            else:
                return max(destination_pins[rail_name_], key=lambda x: x.cy()).cy()

        destination_pins = self.get_control_rails_destinations()
        num_rails = len(self.left_control_rails)
        x_offset = self.get_control_rails_base_x() - (num_rails * self.control_rail_pitch) + self.line_end_space
        rail_names = self.get_control_rails_order(destination_pins, get_top_destination_pin_y)
        self.rail_names = rail_names
        for rail_name in rail_names:
            if rail_name in self.left_control_rails:
                self.add_left_control_rail(rail_name, destination_pins[rail_name],
                                           x_offset, self.control_rail_offsets[rail_name])
                x_offset += self.control_rail_pitch
            else:
                self.add_mid_array_control_rail(rail_name, self.control_buffers_inst,
                                                destination_pins[rail_name])

        self.leftmost_rail = min([getattr(self, x + "_rail") for x in rail_names],
                                 key=lambda x: x.lx())
        self.rightmost_rail = max([getattr(self, x + "_rail") for x in rail_names],
                                  key=lambda x: x.rx())

    @staticmethod
    def get_default_wordline_enables():
        return ["wordline_en"]

    def add_left_control_rail(self, rail_name, dest_pins, x_offset, y_offset):
        """Routes the rail from control logic buffer pin with name 'rail_name' to the destinations 'dest_pins'.
           x_offset is the x_offset of the vertical rail.
           y_offset is the y_offset of the horizontal rail from the control logic buffer pin
         """
        control_pin = self.control_buffers_inst.get_pin(rail_name)
        self.add_rect(METAL2, offset=control_pin.ul(), height=y_offset - control_pin.uy())

        self.add_rect(METAL3, offset=vector(x_offset, y_offset),
                      width=control_pin.rx() - x_offset, height=self.bus_width)

        self.add_cross_contact_center(cross_m2m3, offset=vector(control_pin.cx(),
                                                                y_offset + 0.5 * self.bus_width))

        if not dest_pins:
            rail = self.add_rect(METAL3, offset=vector(x_offset, y_offset), height=self.bus_width,
                                 width=self.bus_width)
        else:
            via_offset = vector(x_offset + 0.5 * self.bus_width, y_offset + 0.5 * self.bus_width)
            self.add_cross_contact_center(cross_m2m3, offset=via_offset)
            top_pin = max(dest_pins, key=lambda x: x.uy())
            rail = self.add_rect(METAL2, offset=vector(x_offset, y_offset),
                                 height=top_pin.cy() - y_offset,
                                 width=self.bus_width)
            self.m2_rails.append(rail)
        setattr(self, rail_name + "_rail", rail)
        if rail_name in self.get_default_wordline_enables():
            return

        for dest_pin in dest_pins:
            rail_height = min(self.bus_width, dest_pin.height())
            rail_y = dest_pin.cy() - 0.5 * rail_height

            if dest_pin.layer in [METAL2, METAL3]:
                via = cross_m2m3
                via_rotate = False
            elif dest_pin.layer == METAL1:
                via = cross_m1m2
                via_rotate = True
            else:
                debug.error("Invalid layer", 1)
                break

            rail_layer = METAL3 if dest_pin.layer == METAL2 else dest_pin.layer
            via_x = x_offset + 0.5 * self.bus_width
            via_y = dest_pin.cy()
            self.add_rect(rail_layer, offset=vector(x_offset, rail_y),
                          width=dest_pin.lx() - x_offset, height=rail_height)
            self.add_cross_contact_center(via, offset=vector(via_x, via_y), rotate=via_rotate)
            if dest_pin.layer == METAL2:
                self.add_contact_center(m2m3.layer_stack,
                                        offset=vector(dest_pin.lx() + 0.5 * m2m3.height, dest_pin.cy()),
                                        rotate=90)
                self.add_rect(METAL3, offset=vector(dest_pin.lx(), rail_y),
                              width=m2m3.height, height=rail_height)

    def add_mid_array_control_rail(self, rail_name, control_buffer_inst, destination_pins):
        rail = self.control_rail_offsets[rail_name]
        control_pin = control_buffer_inst.get_pin(rail_name)

        _, min_rail_width = self.calculate_min_area_fill(self.bus_width, layer=METAL3)
        if rail.x_index >= 0:
            base_x = self.bitcell_array_inst.lx() + self.bitcell_array.bitcell_offsets[rail.x_index]
            rail_mid_x = self.intra_m4_rail_mid_x + base_x
            if rail_mid_x > rail.min_x:
                rail_end = max(rail_mid_x + 0.5 * m3m4.h_1, rail.min_x + min_rail_width)
            else:
                rail_end = min(rail_mid_x - m3m4.h_1, rail.min_x - min_rail_width)
        else:
            rail_mid_x = rail.rail_x
            rail_end = max(rail.max_x, rail.min_x + min_rail_width)

        y_offset = rail.y_offset

        if control_pin.uy() < y_offset:
            start_y = control_pin.uy()
        else:
            start_y = control_pin.by()

        self.add_rect(METAL2, offset=vector(control_pin.lx(), start_y),
                      height=y_offset - start_y, width=control_pin.width())
        self.add_cross_contact_center(cross_m2m3, offset=vector(control_pin.cx(),
                                                                y_offset + 0.5 * self.bus_width))
        self.add_rect(METAL3, offset=vector(rail.min_x, y_offset),
                      width=rail_end - rail.min_x, height=self.bus_width)
        if not destination_pins:
            m3_rail = self.add_rect(METAL3, vector(rail_mid_x - 0.5 * self.m3_width, y_offset))
            setattr(self, rail_name + "_rail", m3_rail)
            return
        rail_top = (max(destination_pins, key=lambda x: x.uy()).cy() +
                    0.5 * cross_m3m4.second_layer_width)

        self.add_cross_contact_center(cross_m3m4, rotate=True,
                                      offset=vector(rail_mid_x, y_offset + 0.5 * self.bus_width))

        rail_width = max(self.bus_width, self.m4_width)
        m4_rail = self.add_rect(METAL4, offset=vector(rail_mid_x - 0.5 * rail_width, y_offset),
                                width=rail_width, height=rail_top - y_offset)
        for dest_pin in destination_pins:
            vias, via_rotates, fill_layers = contact.get_layer_vias(dest_pin.layer, METAL4,
                                                                    cross_via=True)
            via_offset = vector(rail_mid_x, dest_pin.cy())

            for via, via_rotate in zip(vias, via_rotates):
                super(design, self).add_cross_contact_center(via, offset=via_offset,
                                                             rotate=via_rotate)
            for layer in fill_layers:
                if layer == METAL3:
                    fill_height, fill_width = self.calculate_min_area_fill(
                        dest_pin.height(), layer=METAL3)
                else:
                    fill_width, fill_height = self.calculate_min_area_fill(
                        m2m3.height, layer=METAL3)
                self.add_rect_center(layer, offset=via_offset, width=fill_width,
                                     height=fill_height)
            if via_offset.x > dest_pin.rx():
                self.add_rect(dest_pin.layer, dest_pin.lr(), height=dest_pin.height(),
                              width=via_offset.x - dest_pin.rx() + 0.5 * cross_m3m4.first_layer_height)

        setattr(self, rail_name + "_rail", m4_rail)
