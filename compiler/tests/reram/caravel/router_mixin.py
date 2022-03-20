import math
from typing import TYPE_CHECKING, List

import numpy as np

import debug
from base.contact import m3m4, cross_m3m4, contact
from base.design import design, METAL3, METAL4, METAL5
from base.geometry import instance, rectangle
from base.pin_layout import pin_layout
from base.vector import vector
from globals import OPTS
from mim_capacitor import MimCapacitor
from pin_assignments_mixin import VDD_WORDLINE, VDD, GND, VSS_D2, VSS_A2, VSS_A1, VCC_D2, VDD_ESD, VDD_A2
from tech import spice as tech_spice

if TYPE_CHECKING:
    from caravel_wrapper import CaravelWrapper
else:
    class CaravelWrapper:
        pass

METAL6 = "metal6"

m4m5 = contact(layer_stack=(METAL4, "via4", METAL5), dimensions=[1, 2])
m5m6 = contact(layer_stack=(METAL5, "via5", METAL6))
m3m4_three = contact(layer_stack=m3m4.layer_stack, dimensions=[1, 3])
m5_width = design.get_min_layer_width(METAL5)

INCREASING = "increasing"
DECREASING = "decreasing"

grid_padding = 50
sram_padding = 10
edge_power_grid_padding = 15

internal_power_grid_obstruction_padding = 50
internal_power_grid_padding = 80

power_grid_space = 1.7
power_grid_width = 3.1
power_grid_pitch = power_grid_width + power_grid_space

internal_grid_space = 20
internal_grid_pitch = internal_grid_space + power_grid_width

decoupling_cap_width = decoupling_cap_height = 15

grid_space = 3
m3_width = 0.28
m4_width = 0.56
via_space_threshold = 2

sense_pins = ["vclamp", "vclampp", "vref"]


class GridNode:
    perp_start_index: int
    perp_end_index: int

    def __init__(self, grid_index, net, perp_start_index=None, perp_end_index=None):
        self.grid_index = grid_index
        self.net = net
        if perp_start_index is not None and perp_end_index is not None:
            self.set_start_end(perp_start_index, perp_end_index)

    def set_start_end(self, perp_start_index, perp_end_index):
        self.perp_start_index, self.perp_end_index = sorted([perp_start_index,
                                                             perp_end_index])

    def overlaps(self, start_index, end_index, net):
        if net == self.net:
            return False

        lower = (self.perp_start_index, self.perp_end_index)
        upper = [*sorted([start_index, end_index])]

        if lower[0] > upper[0]:
            lower, upper = upper, lower
        return upper[0] <= lower[1]

    def __str__(self):
        if self.net == "sram":
            net = ""
        else:
            net = f" - {self.net}"
        return f"({self.grid_index}{net}): ({self.perp_start_index}, {self.perp_end_index})"


class RoutingGrid:
    def __init__(self, sram_inst: instance, caravel_inst: instance):
        self.sram_inst = sram_inst
        self.caravel_inst = caravel_inst
        self.create_x_y_grid()

    def create_grid(self, span, sram_start, sram_end):
        start = grid_padding
        end = span - grid_padding

        self.grid_pitch = grid_pitch = m4_width + grid_space

        sram_start -= sram_padding
        sram_end += sram_padding

        total_span = end - start + grid_space
        num_points = math.floor(total_span / grid_pitch)
        sram_start_index = math.floor((sram_start - start) / grid_pitch)
        sram_end_index = math.ceil((sram_end - start) / grid_pitch)

        sram_nodes = []
        for index in range(sram_start_index, sram_end_index + 1):
            sram_nodes.append(GridNode(grid_index=index, net="sram"))

        grid_indices = list(range(num_points))
        grid_offsets = [start + x * grid_pitch for x in grid_indices]

        return grid_indices, grid_offsets, sram_nodes, start, end

    @staticmethod
    def set_sram_start_end(nodes, perp_nodes):
        start_index = min(map(lambda x: x.grid_index, perp_nodes))
        end_index = max(map(lambda x: x.grid_index, perp_nodes))
        for node in nodes:
            node.set_start_end(start_index, end_index)

    def create_x_y_grid(self):
        res = self.create_grid(span=self.caravel_inst.width,
                               sram_start=self.sram_inst.lx(),
                               sram_end=self.sram_inst.rx())
        (self.grid_x_indices, self.grid_x_offsets, self.grid_y_nodes,
         self.start_x, self.end_x) = res

        res = self.create_grid(span=self.caravel_inst.height,
                               sram_start=self.sram_inst.by(),
                               sram_end=self.sram_inst.uy())
        (self.grid_y_indices, self.grid_y_offsets, self.grid_x_nodes,
         self.start_y, self.end_y) = res

        self.set_sram_start_end(self.grid_x_nodes, self.grid_y_nodes)
        self.set_sram_start_end(self.grid_y_nodes, self.grid_x_nodes)

    @staticmethod
    def find_closest_index(offset, all_offsets):
        return np.argmin([abs(x - offset) for x in all_offsets])

    def find_open_index(self, offset, start, end, net, all_offsets, perp_offsets,
                        grid_nodes: List[GridNode],
                        direction, closest):
        grid_index = self.find_closest_index(offset, all_offsets)

        start_index = self.find_closest_index(start, perp_offsets)
        end_index = self.find_closest_index(end, perp_offsets)

        grid_nodes = sorted(grid_nodes, key=lambda x: x.grid_index)
        if direction == INCREASING:
            candidate_nodes = [x for x in grid_nodes if x.grid_index >= grid_index]
            valid_indices = [x for x in range(len(all_offsets)) if x >= grid_index]
        else:
            valid_indices = [x for x in range(len(all_offsets)) if x <= grid_index]
            candidate_nodes = [x for x in reversed(grid_nodes) if x.grid_index <= grid_index]
            valid_indices = list(reversed(valid_indices))

        if not closest:
            valid_indices = list(reversed(valid_indices))
            candidate_nodes = list(reversed(candidate_nodes))

        index = None
        for index in valid_indices:
            collision = False
            for node in candidate_nodes:
                if node.grid_index == index and node.overlaps(start_index, end_index, net):
                    collision = True
                    break
            if not collision:
                break

        return all_offsets[index]

    def find_open_x(self, x_offset, y_start, y_end, net, direction, closest=True):
        return self.find_open_index(x_offset, y_start, y_end, net,
                                    self.grid_x_offsets, self.grid_y_offsets,
                                    self.grid_y_nodes, direction, closest)

    def find_open_y(self, y_offset, x_start, x_end, net, direction, closest):
        return self.find_open_index(y_offset, x_start, x_end, net,
                                    self.grid_y_offsets, self.grid_x_offsets,
                                    self.grid_x_nodes, direction, closest)


class RouterMixin(CaravelWrapper):
    def route_layout(self):
        self.route_sram_connections()
        self.add_power_grid()
        self.route_enables_to_grid()
        self.add_esd_diodes()

    def add_short_resistance(self, pin_name):
        import caravel_config
        pin_shift = caravel_config.res_short_pin_shift
        resistor_name = f"{pin_name}_short".replace("[", "_").replace("]", "")

        caravel_pin = self.wrapper_inst.get_pin(pin_name)
        if self.is_top_pin(caravel_pin):
            res_layer = METAL4
            width = res_width = m4_width
            height = res_length = self.m4_width
            x_offset = caravel_pin.cx() - 0.5 * width
            y_offset = caravel_pin.by() - pin_shift - height
        else:
            res_layer = METAL3
            height = res_width = m3_width
            width = res_length = self.m3_width
            if caravel_pin.lx() < 0.5 * self.width:
                x_offset = caravel_pin.rx() + pin_shift
            else:
                x_offset = caravel_pin.lx() - pin_shift - width
            y_offset = caravel_pin.cy() - 0.5 * height
        self.add_rect(f"res_{res_layer}", vector(x_offset, y_offset),
                      width=width, height=height)

        res_name = tech_spice[f"{res_layer}_res_name"]
        spice_device = f"R{{0}} {{1}} {res_name} w={res_width:.3g} " \
                       f"l={res_length:.3g}"
        return spice_device, resistor_name

    def add_x_rail(self, x_start, x_end, y_mid, net, is_start, is_end):

        x_start_grid, x_end_grid = sorted([x_start, x_end])
        start_index = self.grid.find_closest_index(x_start_grid, self.grid_x_offsets)
        end_index = self.grid.find_closest_index(x_end_grid, self.grid_x_offsets)

        if is_start:
            rail_height = m3_width
        else:
            rail_height = m4_width

        if is_end:
            if x_end > x_start:
                x_end += m3m4_three.height
                x_start -= 0.5 * m3m4.height
            else:
                x_end -= m3m4_three.height
                x_start += 0.5 * m3m4.height
        else:
            if x_end > x_start:
                x_end += 0.5 * m3m4.height
                x_start -= 0.5 * m3m4.height
            else:
                x_end -= 0.5 * m3m4.height
                x_start += 0.5 * m3m4.height

        self.add_rect(METAL3, vector(x_start, y_mid - 0.5 * rail_height),
                      height=rail_height, width=x_end - x_start)

        grid_index = self.grid.find_closest_index(y_mid, self.grid_y_offsets)
        node = GridNode(grid_index, net, start_index, end_index)

        self.grid.grid_x_nodes.append(node)

    def add_y_rail(self, y_start, y_end, x_mid, net):
        y_start, y_end = sorted([y_start, y_end])
        grid_index = self.grid.find_closest_index(x_mid, self.grid_x_offsets)
        start_index = self.grid.find_closest_index(y_start, self.grid_x_offsets)
        end_index = self.grid.find_closest_index(y_end, self.grid_x_offsets)

        via_ext = 0.5 * m3m4.h_2
        height = y_end - y_start + 2 * via_ext
        self.add_rect(METAL4, vector(x_mid - 0.5 * m4_width, y_start - via_ext),
                      height=height, width=m4_width)

        node = GridNode(grid_index, net, start_index, end_index)

        self.grid.grid_y_nodes.append(node)

    def add_m3m4_path(self, path, net, from_caravel):

        def is_direct_path(start_, end_):
            return start_.x == end_.x and abs(start_.y - end_.y) < via_space_threshold

        for i, (start, end) in enumerate(zip(path[:-1], path[1:])):
            if from_caravel:
                is_start = end == path[-1]
                is_end = start == path[0]
            else:
                is_start = start == path[0]
                is_end = end == path[-1]
            if is_direct_path(start, end):
                # add direct M3
                width = m3m4.h_1
                self.add_rect(METAL3, vector(start.x - 0.5 * width, start.y),
                              width=width, height=end.y - start.y)
                continue
            if end == path[-1]:
                if not from_caravel:
                    if end.x > start.x:
                        via_x = end.x + 0.5 * m3m4_three.height
                    else:
                        via_x = end.x - 0.5 * m3m4_three.height
                    self.add_contact_center(m3m4.layer_stack, vector(via_x, end.y),
                                            size=m3m4_three.dimensions, rotate=90)
            else:
                # look ahead
                next_end = path[i + 2]
                if not is_direct_path(end, next_end):
                    self.add_cross_contact_center(cross_m3m4, vector(end.x, end.y),
                                                  rotate=True)

            if start.x == end.x:
                # vertical rail
                self.add_y_rail(start.y, end.y, end.x, net)
            else:
                # horizontal rail
                self.add_x_rail(start.x, end.x, end.y, net, is_start, is_end)

    def is_top_pin(self, caravel_pin):
        return caravel_pin.by() > self.wrapper_inst.uy() - grid_padding

    def route_sram_to_caravel(self, sram_pin, caravel_pin):
        caravel_net = caravel_pin.name

        if sram_pin.name in sense_pins:
            # There are multiple sense pins
            if sram_pin.rx() < self.sram_inst.get_pin("clk").cx():
                x_dir = DECREASING
            else:
                x_dir = INCREASING
        elif caravel_pin.lx() <= sram_pin.cx():
            x_dir = DECREASING
        else:
            x_dir = INCREASING

        if x_dir == DECREASING:
            x_start = sram_pin.lx()
        else:
            x_start = sram_pin.rx()

        if caravel_pin.cx() > self.mid_x:
            x_end = caravel_pin.lx()
        else:
            x_end = caravel_pin.rx()

        is_top_pin = self.is_top_pin(caravel_pin)
        if is_top_pin:
            # find open x_offset
            y_index = len(self.grid_y_offsets) - 1
            x_offset = self.mid_x
            y_end = sram_pin.cy()

            y_offset = self.grid_y_offsets[y_index]
            while y_index >= 0:
                y_offset = self.grid_y_offsets[y_index]
                x_offset = self.grid.find_open_x(x_start, y_offset, y_end, caravel_net,
                                                 direction=x_dir, closest=True)
                # confirm it's actually open
                next_open_y = self.grid.find_open_y(y_offset, x_offset, x_end,
                                                    caravel_net,
                                                    direction=DECREASING, closest=True)
                if next_open_y <= y_offset:
                    y_offset = next_open_y
                    break

                y_index -= 1

            path = [vector(caravel_pin.cx(), caravel_pin.by()),
                    vector(caravel_pin.cx(), y_offset),
                    vector(x_offset, y_offset),
                    vector(x_offset, sram_pin.cy()),
                    vector(x_start, sram_pin.cy())]
            from_caravel = True
        else:
            y_end = caravel_pin.cy()
            y_start = sram_pin.cy()
            if caravel_pin.cy() <= sram_pin.cy():
                y_dir = INCREASING
            else:
                y_dir = DECREASING

            x_offset = self.grid.find_open_x(x_start, y_start, y_end, caravel_net,
                                             direction=x_dir, closest=True)
            y_offset = self.grid.find_open_y(y_end, x_offset, caravel_pin.cx(), caravel_net,
                                             direction=y_dir, closest=True)

            y_end = caravel_pin.cy()

            if caravel_pin.cx() > self.mid_x:
                x_edge = caravel_pin.lx() - 2 * self.m4_space
                edge_dir = DECREASING
            else:
                x_edge = caravel_pin.rx() + 2 * self.m4_space
                edge_dir = INCREASING

            x_bend = self.grid.find_open_x(x_edge, y_offset, y_end, caravel_net,
                                           direction=edge_dir, closest=True)

            path = [vector(x_start, sram_pin.cy()),
                    vector(x_offset, sram_pin.cy()),
                    vector(x_offset, y_offset),
                    vector(x_bend, y_offset),
                    vector(x_bend, y_end),
                    vector(x_end, y_end)]
            from_caravel = False

        x_index = self.grid.find_closest_index(x_offset, self.grid_x_offsets)
        y_index = self.grid.find_closest_index(y_offset, self.grid_y_offsets)

        debug.info(2, "(x, y) for net %s:%s is (%5.5g, %5.5g), (%d, %d)",
                   sram_pin.name, caravel_pin.name, x_offset, y_offset, x_index, y_index)

        self.add_m3m4_path(path, caravel_net, from_caravel=from_caravel)

    def route_sram_connections(self):
        self.grid = RoutingGrid(self.sram_inst, self.wrapper_inst)
        self.grid_x_offsets = self.grid.grid_x_offsets
        self.grid_y_offsets = self.grid.grid_y_offsets

        def get_caravel_pin(sram_name):
            caravel_net = self.sram_to_wrapper_conns[sram_name]
            return self.wrapper_inst.get_pins(caravel_net)[0]

        def process_order(pin_name_):
            caravel_pin = get_caravel_pin(pin_name_)
            is_top_pin = self.is_top_pin(caravel_pin)
            # process top pins first
            if is_top_pin:
                # process edges first
                return 0, -abs(caravel_pin.cx() - self.mid_x)
            return 1, -abs(caravel_pin.cy() - self.mid_y)

        pin_names = self.sram_to_wrapper_conns.keys()
        pin_names = list(sorted(pin_names, key=process_order))
        for pin_name in pin_names:
            if "gnd" in pin_name or "vdd" in pin_name:
                continue
            caravel_pin_ = get_caravel_pin(pin_name)
            for pin in self.sram_inst.get_pins(pin_name):
                self.route_sram_to_caravel(pin, caravel_pin_)

    def add_power_grid(self):
        self.vert_power_grid = {key: [] for key in self.grid_names_set}
        self.horz_power_grid = {key: [] for key in self.grid_names_set}
        self.vert_power_internal_grid = {key: [] for key in self.grid_names_set}
        self.horz_power_internal_grid = {key: [] for key in self.grid_names_set}

        self.add_edge_power_grid()
        self.connect_sram_power()
        self.add_internal_power_grid()
        self.add_decoupling_cap()
        self.route_caravel_power()

    def add_power_via(self, x_offset, y_offset, shift_center=False):
        if shift_center:
            x_offset += 0.5 * self.power_grid_via.width
            y_offset += 0.5 * self.power_grid_via.height
        self.add_contact_center(self.power_grid_via.layer_stack,
                                vector(x_offset, y_offset), size=[2, 2])

    @staticmethod
    def is_overlap(rect1, rect2):
        def to_rect(rect):
            if isinstance(rect, pin_layout):
                return rectangle(layerNumber=0, offset=rect.ll(),
                                 width=rect.width(), height=rect.height())
            return rect

        return to_rect(rect1).overlaps(to_rect(rect2))

    def add_connections(self, rect, grid_pin_name, power_grid):
        for dest_pin in power_grid[grid_pin_name]:
            if not self.is_overlap(dest_pin, rect):
                continue
            self.add_power_via(rect.cx(), dest_pin.cy())

    def add_vertical_connections(self, rect, grid_pin_name, is_internal_grid=False):
        self.vert_power_grid[grid_pin_name].append(rect)
        if is_internal_grid:
            self.vert_power_internal_grid[grid_pin_name].append(rect)
        for dest_pin in self.horz_power_grid[grid_pin_name]:
            if not self.is_overlap(dest_pin, rect):
                continue

            self.add_power_via(rect.cx(), dest_pin.cy())

    def connect_to_top(self, pin, grid_pin_name):
        rect = self.add_rect(pin.layer, pin.ul(), width=pin.rx() - pin.lx(),
                             height=self.height - edge_power_grid_padding - pin.uy())
        self.add_vertical_connections(rect, grid_pin_name)

    def connect_to_bottom(self, pin, grid_pin_name):
        rect = self.add_rect(pin.layer, vector(pin.lx(), 0), width=pin.rx() - pin.lx(),
                             height=pin.by())
        self.add_vertical_connections(rect, grid_pin_name)

    def add_horizontal_connections(self, rect, grid_pin_name, is_internal_grid=False):
        self.horz_power_grid[grid_pin_name].append(rect)
        if is_internal_grid:
            self.horz_power_internal_grid[grid_pin_name].append(rect)
        for dest_pin in self.vert_power_grid[grid_pin_name]:
            if not self.is_overlap(dest_pin, rect):
                continue
            self.add_power_via(dest_pin.cx(), rect.cy())

    def connect_to_left(self, pin, grid_pin_name):
        rect = self.add_rect(pin.layer, vector(0, pin.by()), width=pin.lx(),
                             height=pin.height())
        self.add_horizontal_connections(rect, grid_pin_name)

    def connect_to_right(self, pin, grid_pin_name):
        rect = self.add_rect(pin.layer, pin.lr(),
                             width=self.width - edge_power_grid_padding - pin.rx(),
                             height=pin.height())
        self.add_horizontal_connections(rect, grid_pin_name)

    def add_edge_power_grid(self):
        self.power_grid_via = contact(layer_stack=(METAL5, "via5", METAL6),
                                      dimensions=[2, 2])

        def add_power_pin(x_offset, y_offset, horizontal):
            if horizontal:
                width = self.wrapper_inst.width - 2 * offset
                height = power_grid_width
                grid = self.horz_power_grid
            else:
                width = power_grid_width
                height = self.wrapper_inst.height - 2 * offset
                grid = self.vert_power_grid

            if horizontal:
                layer = METAL5
            else:
                layer = METAL6
            pin = self.add_layout_pin(pin_name, layer, vector(x_offset, y_offset),
                                      width=width, height=height)
            grid[pin_name].append(pin)
            self.add_power_via(x_offset, y_offset, shift_center=True)

        for i, pin_name in enumerate(self.edge_grid_names):
            offset = edge_power_grid_padding + i * power_grid_pitch

            bottom_y = offset
            top_y = self.wrapper_inst.uy() - offset - power_grid_width
            left_x = offset
            right_x = self.wrapper_inst.rx() - offset - power_grid_width

            add_power_pin(left_x, bottom_y, horizontal=True)
            add_power_pin(left_x, bottom_y, horizontal=False)
            add_power_pin(left_x, top_y, horizontal=True)
            add_power_pin(right_x, bottom_y, horizontal=False)

            self.add_power_via(right_x, top_y, shift_center=True)

    def connect_sram_power(self):
        # vdd wordline
        for pin_name in ["vdd_wordline"]:
            for pin in self.sram_inst.get_pins(pin_name):
                if pin.uy() > self.mid_y:
                    self.connect_to_top(pin, VDD_WORDLINE)
                else:
                    self.connect_to_bottom(pin, VDD_WORDLINE)
        # vdd write
        for i, sram_name in enumerate(self.vdd_write_sram_pins):
            caravel_name = self.vdd_write_pins[i]
            for pin in self.sram_inst.get_pins(sram_name):
                if pin.cx() > self.mid_x:
                    self.connect_to_right(pin, caravel_name)
                else:
                    self.connect_to_left(pin, caravel_name)

        for pin_name in ["vdd", "gnd"]:
            grid_name = VDD if pin_name == "vdd" else GND
            for pin in self.sram_inst.get_pins(pin_name):
                if pin.width() > pin.height():
                    rect = self.add_rect(pin.layer, vector(edge_power_grid_padding, pin.by()),
                                         width=self.width - 2 * edge_power_grid_padding,
                                         height=pin.height())
                    if pin.layer == METAL5:
                        self.add_horizontal_connections(rect, grid_name)
                else:
                    rect = self.add_rect(pin.layer, vector(pin.lx(), 0),
                                         width=pin.width(),
                                         height=self.height - edge_power_grid_padding)
                    if pin.layer == METAL6:
                        self.add_vertical_connections(rect, grid_name)

    def get_closest_horizontal_power(self, source_pin, dest_pin_name):
        """Get closest horizontal power pin that overlaps with the
        vertical pin source_pin is to be connected to"""

        dest_pins = self.get_pins(dest_pin_name)
        dest_pins_ = [x for x in dest_pins if x.layer == METAL6]
        if source_pin.cx() < self.mid_x:
            # left
            vertical_rail = min(dest_pins_, key=lambda x: x.lx())
        else:
            vertical_rail = max(dest_pins_, key=lambda x: x.rx())

        adjacent_destinations = self.horz_power_grid[dest_pin_name]

        adjacent_destinations = [x for x in adjacent_destinations
                                 if x.lx() < vertical_rail.cx() < x.rx()]
        horizontal_rail = min(adjacent_destinations,
                              key=lambda x: abs(source_pin.cy() - x.cy()))
        return horizontal_rail, vertical_rail

    def route_enables_to_grid(self):
        for source_pin_name, dest_pin_name in self.wrapper_to_wrapper_conns.items():
            if dest_pin_name in ["io_oeb[26]", "io_oeb[25]"]:
                debug.error("enable pins are below power grid. Handle special case")
            source_pins = self.wrapper_inst.get_pins(source_pin_name)
            source_pins = [x for x in source_pins if x.layer == METAL4]

            for source_pin in source_pins:
                if source_pin.by() > self.wrapper_inst.uy() - grid_padding:
                    if source_pin.name in self.power_pin_map:
                        continue
                    # top pin
                    dest_pins = self.get_pins(dest_pin_name)
                    dest_pins_ = [x for x in dest_pins if x.layer == METAL5]
                    dest_pin = max(dest_pins_, key=lambda x: x.uy())
                    offset = vector(source_pin.cx() - 0.5 * m4_width, dest_pin.by())
                    self.add_rect(METAL4, offset, width=m4_width,
                                  height=source_pin.by() - offset.y)
                    self.add_contact_center(m4m5.layer_stack,
                                            vector(source_pin.cx(), dest_pin.cy()),
                                            size=[1, 3])
                else:
                    _ = self.get_closest_horizontal_power(source_pin, dest_pin_name)
                    horizontal_rail, vertical_rail = _
                    if source_pin.cx() < self.mid_x:
                        # left
                        via_x = source_pin.rx() - 0.5 * m3m4.height
                    else:
                        via_x = source_pin.lx() + 0.5 * m3m4.height

                    self.add_contact_center(m3m4.layer_stack,
                                            vector(via_x, source_pin.cy()), rotate=90)

                    self.add_rect(METAL3, vector(via_x, source_pin.cy() - 0.5 * m3_width),
                                  height=m3_width,
                                  width=vertical_rail.cx() - via_x)
                    self.add_cross_contact_center(cross_m3m4,
                                                  vector(vertical_rail.cx(),
                                                         source_pin.cy()),
                                                  rotate=True)

                    end_y = horizontal_rail.cy()
                    if end_y > source_pin.cy():
                        y_offset = source_pin.cy() - 0.5 * m3m4.height
                    else:
                        y_offset = source_pin.cy() + 0.5 * m3m4.height
                    self.add_rect(METAL4, vector(vertical_rail.cx() -
                                                 0.5 * m4_width, y_offset),
                                  width=m4_width, height=end_y - y_offset)

                    offset = vector(vertical_rail.cx(), end_y)
                    self.add_contact_center(m4m5.layer_stack, offset, size=[1, 3])

    def add_internal_power_grid(self):
        if not OPTS.add_internal_grid:
            return
        pin_order = [VDD_ESD, GND, VDD, GND, VDD_WORDLINE, GND, VDD, GND] + self.alternated_vdd_write_pins
        num_grid = len(pin_order)

        def assign_grid(span, lower_obstruction, higher_obstruction):
            offsets = []
            offset = internal_power_grid_padding
            while offset < lower_obstruction - internal_power_grid_obstruction_padding:
                offsets.append(offset)
                offset += internal_grid_pitch

            offset = higher_obstruction + internal_power_grid_obstruction_padding
            while offset < span - internal_power_grid_padding:
                offsets.append(offset)
                offset += internal_grid_pitch
            return offsets

        horizontal_grid = assign_grid(self.height, self.sram_inst.by(),
                                      self.sram_inst.uy())
        for i in range(len(horizontal_grid)):
            rect = self.add_rect(METAL5, vector(edge_power_grid_padding, horizontal_grid[i]),
                                 height=power_grid_width,
                                 width=self.width - 2 * edge_power_grid_padding)
            self.add_horizontal_connections(rect, pin_order[i % num_grid], is_internal_grid=True)

        vertical_grid = assign_grid(self.width, self.sram_inst.lx(),
                                    self.sram_inst.rx())
        for i in range(len(vertical_grid)):
            rect = self.add_rect(METAL6, vector(vertical_grid[i], 0),
                                 height=self.height - edge_power_grid_padding,
                                 width=power_grid_width)
            self.add_vertical_connections(rect, pin_order[i % num_grid], is_internal_grid=True)

    def add_decoupling_cap(self):
        debug.info(1, "Adding decoupling caps")
        self.decoupling_cap = MimCapacitor(width=decoupling_cap_width, height=decoupling_cap_height)
        via_shift = vector(0.5 * self.decoupling_cap.width, 0.5 * self.decoupling_cap.height)
        self.add_mod(self.decoupling_cap)
        power_pins = self.vdd_write_pins + [VDD, VDD_WORDLINE, VDD_ESD]
        self.decoupling_caps = {}
        for power_pin in power_pins:
            self.decoupling_caps[power_pin] = []
            index = 0
            for power_rect in self.vert_power_internal_grid[power_pin]:
                for gnd_rect in self.horz_power_internal_grid[GND]:
                    offset = vector(power_rect.cx(), gnd_rect.cy()) - via_shift
                    inst = self.add_inst(f"{power_pin}_decouple_{index}", self.decoupling_cap,
                                         offset=offset)
                    self.connect_inst([power_pin, GND])
                    self.decoupling_caps[power_pin].append(inst)
                    index += 1
        debug.info(1, "Added decoupling caps")

    def route_caravel_power(self):
        pin_map = {VSS_D2: GND, VSS_A2: GND, VSS_A1: GND, VCC_D2: VDD, VDD_A2: VDD_ESD}
        for key, value in pin_map.items():
            self.assign_wrapper_power(key, value)

        self.power_pin_map = pin_map
        debug.info(1, "Routing caravel power pins to power grid")

        power_pins = list(pin_map.keys()) + [GND, VDD, VDD_WORDLINE, VDD_ESD] + self.vdd_write_pins
        for pin_name in power_pins:
            dest_name = pin_map.get(pin_name, pin_name)
            for source_pin in self.wrapper_inst.get_pins(pin_name):
                is_top_pin = self.is_top_pin(source_pin)
                if is_top_pin:
                    candidates = self.horz_power_grid[dest_name]
                    closest = min(candidates, key=lambda x: abs(x.cy() - source_pin.cy()))
                    self.add_rect(METAL4, vector(source_pin.lx(), closest.by()),
                                  width=source_pin.width(),
                                  height=source_pin.by() - closest.by())
                    self.add_contact_center(m4m5.layer_stack,
                                            vector(source_pin.cx(), closest.cy()),
                                            size=[2, 20], rotate=90)
                    continue

                _ = self.get_closest_horizontal_power(source_pin, dest_name)
                horizontal_rail, vertical_rail = _
                if source_pin.cx() < self.mid_x:
                    end_x = vertical_rail.rx()
                else:
                    end_x = vertical_rail.lx()
                if horizontal_rail.cy() > source_pin.cy():
                    end_y = horizontal_rail.uy()
                else:
                    end_y = horizontal_rail.by()

                self.add_rect(METAL4, vector(source_pin.cx(), source_pin.by()),
                              width=end_x - source_pin.cx(),
                              height=source_pin.height())
                self.add_rect(METAL4, vector(vertical_rail.lx(), source_pin.by()),
                              width=vertical_rail.width(),
                              height=end_y - source_pin.by())
                self.add_contact_center(m4m5.layer_stack,
                                        vector(vertical_rail.cx(),
                                               horizontal_rail.cy()),
                                        size=[1, 5])
