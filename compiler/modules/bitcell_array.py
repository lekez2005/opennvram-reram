import math
from typing import List, Dict

import debug
from base import design
from base.design import METAL1, METAL3, METAL2, PO_DUMMY
from base.geometry import NO_MIRROR, MIRROR_Y_AXIS, MIRROR_X_AXIS, MIRROR_XY, instance
from base.vector import vector
from base.well_implant_fills import create_wells_and_implants_fills
from globals import OPTS
from tech import drc, spice, add_tech_layers


class bitcell_array(design.design):
    """
    Creates a rows x cols array of memory cells. Assumes bit-lines
    and word line is connected by abutment.
    Connects the word lines and bit lines.
    """

    def __init__(self, cols, rows, name="bitcell_array"):
        design.design.__init__(self, name)
        debug.info(1, "Creating {0} {1} x {2}".format(self.name, rows, cols))

        self.column_size = cols
        self.row_size = rows
        self.body_tap_insts = []
        self.bitcell_x_offsets = None

        mods = self.create_modules()
        self.cell, self.body_tap, self.dummy_cell = mods
        self.child_mod = self.cell
        for mod in mods:
            if mod is not None:
                self.add_mod(mod)

        self.add_pins()
        self.create_layout()
        self.add_dummy_polys()
        self.add_layout_pins()
        self.DRC_LVS()

    def add_pins(self):
        for col in range(self.column_size):
            self.add_pin("bl[{0}]".format(col))
            self.add_pin("br[{0}]".format(col))
        for row in range(self.row_size):
            self.add_pin("wl[{0}]".format(row))
        self.add_pin("vdd")
        self.add_pin("gnd")

    def create_layout(self):

        self.create_inst_containers()
        self.add_bitcell_cells()
        self.add_bitcell_dummy_cells()
        self.add_body_taps()

        self.fill_repeaters_space_implant()
        self.connect_dummy_cell_layouts()
        add_tech_layers(self)

    @staticmethod
    def create_modules():
        bitcell = bitcell_array.create_mod_from_str_(OPTS.bitcell)
        if OPTS.use_x_body_taps or OPTS.use_y_body_taps:
            body_tap = bitcell_array.create_mod_from_str_(OPTS.body_tap)
        else:
            body_tap = None
        if OPTS.dummy_cell is not None:
            dummy_cell = bitcell_array.create_mod_from_str_(OPTS.dummy_cell)
        else:
            dummy_cell = bitcell
        return bitcell, body_tap, dummy_cell

    def get_cell_offset(self, col_index, row_index):
        if self.bitcell_x_offsets is None:
            x_offsets = self.calculate_x_offsets(num_cols=self.column_size)
            self.bitcell_x_offsets = x_offsets
            self.combined_x_offsets = list(sorted(x_offsets[0] + x_offsets[2]))

            y_offsets = self.calculate_y_offsets(num_rows=self.row_size)
            self.bitcell_y_offsets = y_offsets
            self.combined_y_offsets = list(sorted(y_offsets[0] + y_offsets[2]))

            self.bitcell_offsets = self.bitcell_x_offsets[0]
            self.tap_offsets = self.bitcell_x_offsets[1]

        x_offset = self.combined_x_offsets[col_index]
        y_offset = self.combined_y_offsets[row_index]
        mirror = NO_MIRROR

        # assuming bitcell's default is nwell on top, psub below, to make bottom-most bitcell's
        # nwell align with precharge cell's nwell, the lowest cell should be mirrored around x axis
        if row_index % 2 == 1:
            if col_index % 2 == 0 and OPTS.mirror_bitcell_y_axis and not OPTS.symmetric_bitcell:
                mirror = MIRROR_Y_AXIS
                x_offset += self.cell.width
        else:
            y_offset += self.cell.height
            if col_index % 2 == 0 and OPTS.mirror_bitcell_y_axis and not OPTS.symmetric_bitcell:
                mirror = MIRROR_XY
                x_offset += self.cell.width
            else:
                mirror = MIRROR_X_AXIS
        return x_offset, y_offset, mirror

    def create_inst_containers(self):
        self.cell_inst = [[None] * self.column_size for x in range(self.row_size)]  # type: List[List[instance]]
        self.dummy_inst = {
            "vertical": [[None] * (self.row_size + 2 * OPTS.num_bitcell_dummies) for _ in range(2 * OPTS.num_bitcell_dummies)],
            "horizontal": [[None] * (self.column_size + 2 * OPTS.num_bitcell_dummies) for _ in range(2 * OPTS.num_bitcell_dummies)]
        }  # type: Dict[str, List[List[instance]]]
        self.horizontal_dummy = self.dummy_inst["horizontal"]
        self.vertical_dummy = self.dummy_inst["vertical"]

        cols = list(range(OPTS.num_bitcell_dummies))
        cols += [x + OPTS.num_bitcell_dummies + self.column_size for x in cols]

        rows = list(range(OPTS.num_bitcell_dummies))
        rows += [x + OPTS.num_bitcell_dummies + self.row_size for x in rows]

        self.dummy_rows = rows
        self.dummy_cols = cols

    def get_cell_inst_row(self, row):
        if row in self.dummy_rows:
            return self.horizontal_dummy[self.dummy_rows.index(row)]
        dummy_cells = [self.vertical_dummy[i][row] for i in range(len(self.dummy_cols))]
        return dummy_cells[:OPTS.num_bitcell_dummies] + self.cell_inst[row - OPTS.num_bitcell_dummies] + dummy_cells[OPTS.num_bitcell_dummies:]

    def get_bitcell_connections(self, row, col):
        if hasattr(self.cell, "get_bitcell_connections"):
            return self.cell.get_bitcell_connections(self, row, col)
        if row in self.dummy_rows:
            wl_conn = "gnd"
        else:
            wl_conn = "wl[{}]".format(row - OPTS.num_bitcell_dummies)
        if col in self.dummy_cols:
            bl_nets = "vdd vdd"
        else:
            bl_nets = "bl[{0}] br[{0}] ".format(col - OPTS.num_bitcell_dummies)
        return "{0} {1} vdd gnd".format(bl_nets, wl_conn).split()

    def add_bitcell_cells(self):
        for col in range(self.column_size):
            for row in range(self.row_size):
                name = "bit_r{0}_c{1}".format(row, col)
                x_offset, y_offset, mirror = self.get_cell_offset(col + OPTS.num_bitcell_dummies,
                                                                  row + OPTS.num_bitcell_dummies)

                cell_inst = self.add_inst(name=name, mod=self.cell,
                                          offset=vector(x_offset, y_offset),
                                          mirror=mirror)
                self.cell_inst[row][col] = cell_inst
                self.connect_inst(self.get_bitcell_connections(row + OPTS.num_bitcell_dummies,
                                                               col + OPTS.num_bitcell_dummies))

    def add_bitcell_dummy_cells(self):
        """Add dummy on all four edges. Total rows = rows + 2, total_cols = cols + 2"""
        if not OPTS.num_bitcell_dummies:
            self.width = self.cell_inst[-1][-1].rx()
            self.height = self.cell_inst[-1][-1].uy()
            self.dummy_rows = self.dummy_cols = []
            return

        num_dummies = OPTS.num_bitcell_dummies
        cols = self.dummy_cols
        rows = self.dummy_rows

        # vertical
        for i in range(len(cols)):
            col = cols[i]
            for row in range(self.row_size + 2 * num_dummies):
                name = "dummy_r{0}_c{1}".format(row, col)
                x_offset, y_offset, mirror = self.get_cell_offset(col, row)
                dummy_inst = self.add_inst(name=name, mod=self.dummy_cell,
                                           offset=vector(x_offset, y_offset),
                                           mirror=mirror)
                self.connect_inst(self.get_bitcell_connections(row, col))
                self.dummy_inst["vertical"][i][row] = dummy_inst

        # horizontal
        # back populate from vertical to horizontal
        for row_index, row in enumerate(rows):
            for col_index, col in enumerate(cols):
                self.horizontal_dummy[row_index][col] = self.vertical_dummy[col_index][row]
        # fill rows
        for i in range(len(rows)):
            for col in range(self.column_size):
                x_offset, y_offset, mirror = self.get_cell_offset(col + num_dummies, rows[i])
                name = "dummy_r{0}_c{1}".format(rows[i], col + num_dummies)
                dummy_inst = self.add_inst(name=name, mod=self.dummy_cell,
                                           offset=vector(x_offset, y_offset),
                                           mirror=mirror)
                self.connect_inst(self.get_bitcell_connections(rows[i], col + num_dummies))
                self.horizontal_dummy[i][col + num_dummies] = dummy_inst

        self.width = self.horizontal_dummy[-1][-1].rx()
        self.height = self.vertical_dummy[-1][-1].uy()

    def add_body_taps(self):
        if not OPTS.use_x_body_taps and not OPTS.use_y_body_taps:
            return
        if OPTS.use_x_body_taps:
            _, tap_offsets, _ = self.bitcell_x_offsets
            tap_offsets = [x for x in tap_offsets]  # copy to prevent modification of original
            if hasattr(OPTS, "repeaters_array_space_offsets"):
                tap_offsets += OPTS.repeaters_array_space_offsets
            cell_offsets, _, dummy_offsets = self.bitcell_y_offsets
            sweep_var = range(self.row_size + 2 * OPTS.num_bitcell_dummies)
            mirrors = [MIRROR_X_AXIS, NO_MIRROR]
            tap_size = self.body_tap.height
        else:
            _, tap_offsets, _ = self.bitcell_y_offsets
            cell_offsets, _, dummy_offsets = self.bitcell_x_offsets
            sweep_var = range(self.column_size + 2 * OPTS.num_bitcell_dummies)
            mirrors = [MIRROR_Y_AXIS, NO_MIRROR]
            tap_size = self.body_tap.width

        cell_offsets = list(sorted(cell_offsets + dummy_offsets))

        for tap_offset in tap_offsets:
            for var in sweep_var:
                mirror = mirrors[var % 2]
                if OPTS.use_x_body_taps:
                    x_offset = tap_offset
                    y_offset = cell_offsets[var] + (var % 2 == 0) * tap_size
                else:
                    x_offset = cell_offsets[var] + (var % 2 == 0) * tap_size
                    y_offset = tap_offset

                tap_inst = self.add_inst(name=self.body_tap.name, mod=self.body_tap,
                                         offset=vector(x_offset, y_offset), mirror=mirror)
                self.connect_inst([])
                self.body_tap_insts.append(tap_inst)

    def connect_dummy_cell_layouts(self):
        """Connect dummy wordlines to gnd and dummy bitlines to vdd"""
        if OPTS.num_bitcell_dummies > 0 and False:
            self.dummy_cell.route_dummy_cells(self)

    def fill_repeaters_space_implant(self):
        if not OPTS.use_x_body_taps or not getattr(OPTS, "repeaters_array_space_offsets", None):
            return
        fill_rects = create_wells_and_implants_fills(self.body_tap, self.body_tap)
        for row in range(self.row_size):
            for x_offset in OPTS.repeaters_array_space_offsets[1:]:
                for fill_rect in fill_rects:
                    if row % 2 == 0:
                        fill_rect = (fill_rect[0], self.body_tap.height - fill_rect[2],
                                     self.body_tap.height - fill_rect[1], fill_rect[3])
                    rect_instance = fill_rect[3]
                    rect_left = x_offset + (rect_instance.rx() - self.body_tap.width)
                    rect_right = x_offset + rect_instance.lx()
                    rect_y = row * self.cell.height + fill_rect[1]
                    self.add_rect(fill_rect[0], offset=vector(rect_left, rect_y),
                                  width=rect_right - rect_left,
                                  height=fill_rect[2] - fill_rect[1])

    def add_dummy_polys(self):
        if not self.has_dummy:
            return

        for row in range(self.row_size + len(self.dummy_rows)):
            row_instances = self.get_cell_inst_row(row)
            y_base = row_instances[0].by()
            rects = self.add_dummy_poly(self.cell, row_instances, True)
            for rect in rects:
                if self.cell.height - rect.height < self.poly_vert_space:
                    self.add_rect(PO_DUMMY, vector(rect.lx(), y_base),
                                  width=rect.width, height=self.cell.height)

    def get_full_width(self):
        if "vdd" not in self.cell.pins:
            return self.width
        vdd_pin = min(self.cell.get_pins("vdd"), key=lambda x: x.lx())
        lower_x = vdd_pin.lx()
        # lower_x is negative, so subtract off double this amount for each pair of
        # overlapping cells
        full_width = self.width - 2 * lower_x
        return full_width

    def get_full_height(self):
        # shift it up by the overlap amount (gnd_pin) too
        # must find the lower gnd pin to determine this overlap
        gnd_pins = list(filter(lambda x: x.layer == METAL2, self.cell.get_pins("gnd")))
        if gnd_pins:
            lower_y = min(gnd_pins, key=lambda x: x.by()).by()
        else:
            lower_y = 0

        # lower_y is negative, so subtract off double this amount for each pair of
        # overlapping cells
        full_height = self.height - 2 * lower_y
        return full_height, lower_y

    def copy_vertical_pin(self, pin_name, col, new_pin_name):
        pin = self.cell_inst[0][col].get_pin(pin_name)
        new_pin_name = new_pin_name.format(col)
        self.add_layout_pin(new_pin_name, pin.layer,
                            offset=vector(pin.lx(), 0), width=pin.width(),
                            height=self.height)

    def add_bitline_layout_pins(self):
        for col in range(self.column_size):
            _, _, mirror = self.get_cell_offset(col, 0)
            pin_names = ["bl", "br"]
            if mirror in [MIRROR_Y_AXIS, MIRROR_XY] and OPTS.symmetric_bitcell:
                new_pin_names = ["br[{}]", "bl[{}]"]
            else:
                new_pin_names = ["bl[{}]", "br[{}]"]
            for i, pin_name in enumerate(pin_names):
                self.copy_vertical_pin(pin_name, col, new_pin_names[i])

    def add_layout_pins(self):

        full_height, lower_y = self.get_full_height()
        full_width = self.get_full_width()

        self.add_bitline_layout_pins()

        offset = vector(0.0, 0.0)
        for col in range(self.column_size):
            m2_gnd_pins = list(filter(lambda x: x.layer == METAL2 and x.height() >= self.cell.height,
                                      self.cell_inst[0][col].get_pins("gnd")))
            for gnd_pin in m2_gnd_pins:
                # avoid duplicates by only doing even rows
                # also skip if it isn't the pin that spans the entire cell down to the bottom

                self.add_layout_pin(text="gnd",
                                    layer=METAL2,
                                    offset=gnd_pin.ll(),
                                    width=gnd_pin.width(),
                                    height=full_height)

            # increments to the next column width
            offset.x += self.cell.width

        offset.x = 0.0
        for row in range(self.row_size):
            wl_pin = self.cell_inst[row][0].get_pin("WL")

            if "vdd" not in self.cell.pins:
                vdd_pins = []
            else:
                vdd_pins = self.cell_inst[row][0].get_pins("vdd")

            if "gnd" not in self.cell.pins:
                gnd_pins = []
            else:
                gnd_pins = self.cell_inst[row][0].get_pins("gnd")

            for gnd_pin in gnd_pins:
                # only add to even rows
                if gnd_pin.layer in [METAL1, METAL3]:
                    self.add_layout_pin(text="gnd",
                                        layer=gnd_pin.layer,
                                        offset=vector(0, gnd_pin.by()),
                                        width=full_width,
                                        height=gnd_pin.height())

            # add vdd label and offset
            # only add to odd rows to avoid duplicates
            for vdd_pin in vdd_pins:
                if (row % 2 == 1 or row == 0) and vdd_pin.layer in [METAL1, METAL3]:
                    self.add_layout_pin(text="vdd",
                                        layer=vdd_pin.layer,
                                        offset=vector(0, vdd_pin.by()),
                                        width=full_width,
                                        height=vdd_pin.height())

            # add wl label and offset
            self.add_layout_pin(text="wl[{0}]".format(row),
                                layer=wl_pin.layer,
                                offset=vector(0, wl_pin.by()),
                                width=full_width,
                                height=wl_pin.height())

            # increments to the next row height
            offset.y += self.cell.height

    @staticmethod
    def calculate_offsets(num_elements, cell_size, tap_size=None, dummy_size=None,
                          num_dummies=0, cell_grouping=2):
        """Get (bitcell_offsets, tap_offsets, dummy_offsets)"""
        num_elements += 2 * num_dummies
        if dummy_size is None:
            dummy_size = cell_size
        # determine positions of body taps
        if tap_size is None:
            tap_indices = []
        else:
            tap_spacing = int(math.floor(0.95 * drc["latchup_spacing"] / cell_size))
            tap_indices = list(range(tap_spacing, num_elements, tap_spacing))
            if len(tap_indices) == 0:
                tap_indices = [int(num_elements / 2)]
            elif tap_indices[-1] == num_elements - 1:
                # avoid putting at top of array to make it predictable
                tap_indices[-1] = num_elements - 2 * cell_grouping

        tap_indices = list(sorted(set(tap_indices)))
        # group assuming no dummies
        # offset by num_dummies so real cells stay grouped
        tap_indices = [x - num_dummies for x in tap_indices]
        # normalize by cells_per_group
        tap_indices = [x - (x % cell_grouping) for x in tap_indices]
        # add back the dummies to get back to regular indexing
        tap_indices = [x + num_dummies for x in tap_indices]

        bitcell_offsets = []
        tap_offsets = []
        offset = dummy_size * num_dummies
        for i in range(num_elements - 2 * num_dummies):
            if i in tap_indices:
                tap_offsets.append(offset)
                offset += tap_size
            bitcell_offsets.append(offset)
            offset += cell_size

        dummy_offsets = [i * dummy_size for i in range(num_dummies)]
        dummy_offsets += [offset + x for x in dummy_offsets]

        return bitcell_offsets, tap_offsets, dummy_offsets

    @staticmethod
    def insert_space_in_offsets(space, relative_offset, all_offsets, cell_grouping=2):
        """Insert between all_offsets"""
        bitcell_offsets, tap_offsets, dummy_offsets = all_offsets
        max_offset = max(bitcell_offsets + tap_offsets + dummy_offsets)
        offset = relative_offset * max_offset
        closest_index = min(range(len(bitcell_offsets)),
                            key=lambda i: abs(bitcell_offsets[i] - offset))
        closest_index = closest_index - closest_index % cell_grouping
        closest_offset = bitcell_offsets[closest_index]
        outputs = []
        for offset_list in all_offsets:
            outputs.append([x if x < closest_offset else x + space for x in offset_list])
        return closest_offset, outputs

    @staticmethod
    def calculate_x_offsets(num_cols):
        bitcell, body_tap, dummy_cell = bitcell_array.create_modules()
        dummy_width = dummy_cell.width if dummy_cell is not None else None
        if OPTS.use_x_body_taps:
            tap_width = body_tap.width
        else:
            tap_width = None

        x_offsets = bitcell_array.calculate_offsets(num_cols, bitcell.width, tap_size=tap_width,
                                                    dummy_size=dummy_width,
                                                    num_dummies=OPTS.num_bitcell_dummies,
                                                    cell_grouping=OPTS.cells_per_group)
        add_repeaters = (OPTS.add_buffer_repeaters and
                         num_cols > OPTS.buffer_repeaters_col_threshold and
                         len(OPTS.buffer_repeater_sizes) > 0)
        add_repeater_space = add_repeaters and OPTS.dedicated_repeater_space

        if add_repeater_space:
            # calculate number of tap spaces needed and insert space
            output_nets = [x[1] for x in OPTS.buffer_repeater_sizes]
            flattened_nets = [x for y in output_nets for x in y]
            num_rails = len(flattened_nets)
            m4_space = bitcell_array.get_parallel_space("metal4")
            m4_pitch = max(bitcell_array.get_min_layer_width("metal4"),
                           bitcell_array.get_bus_width()) + m4_space
            rails_space = num_rails * m4_pitch + m4_space
            if OPTS.use_x_body_taps:
                rails_num_taps = math.ceil(rails_space / body_tap.width)
                OPTS.repeaters_space_num_taps = rails_num_taps
                rails_space = rails_num_taps * body_tap.width
            else:
                rails_num_taps = 0
            res = bitcell_array.insert_space_in_offsets(rails_space,
                                                        relative_offset=OPTS.repeater_x_offset,
                                                        all_offsets=x_offsets,
                                                        cell_grouping=OPTS.cells_per_group)
            closest_offset, x_offsets = res
            OPTS.buffer_repeaters_x_offset = closest_offset
            if OPTS.use_x_body_taps:
                OPTS.repeaters_array_space_offsets = [OPTS.buffer_repeaters_x_offset + i * tap_width
                                                      for i in range(rails_num_taps)]
        elif add_repeaters:
            max_x_offset = max([x[-1] for x in x_offsets if x])
            OPTS.buffer_repeaters_x_offset = OPTS.repeater_x_offset * max_x_offset
        return x_offsets

    @staticmethod
    def calculate_y_offsets(num_rows):
        bitcell, body_tap, dummy_cell = bitcell_array.create_modules()
        if dummy_cell is not None:
            dummy_height = dummy_cell.height
        else:
            dummy_height = None

        if OPTS.use_y_body_taps:
            tap_height = body_tap.height
        else:
            tap_height = None

        y_offsets = bitcell_array.calculate_offsets(num_rows, bitcell.height, tap_size=tap_height,
                                                    dummy_size=dummy_height,
                                                    num_dummies=OPTS.num_bitcell_dummies,
                                                    cell_grouping=OPTS.cells_per_group)
        return y_offsets

    def analytical_delay(self, slew, load=0):
        wl_wire = self.gen_wl_wire()
        wl_wire.return_delay_over_wire(slew)

        wl_to_cell_delay = wl_wire.return_delay_over_wire(slew)
        # hypothetical delay from cell to bl end without sense amp
        bl_wire = self.gen_bl_wire()
        cell_load = 2 * bl_wire.return_input_cap()  # we ingore the wire r
        # hence just use the whole c
        bl_swing = 0.1
        cell_delay = self.cell.analytical_delay(wl_to_cell_delay.slew, cell_load, swing=bl_swing)

        # we do not consider the delay over the wire for now
        return self.return_delay(cell_delay.delay + wl_to_cell_delay.delay,
                                 wl_to_cell_delay.slew)

    def analytical_power(self, proc, vdd, temp, load):
        """Power of Bitcell array and bitline in nW."""

        # Dynamic Power from Bitline
        bl_wire = self.gen_bl_wire()
        cell_load = 2 * bl_wire.return_input_cap()
        bl_swing = 0.1  # This should probably be defined in the tech file or input
        freq = spice["default_event_rate"]
        bitline_dynamic = bl_swing * cell_load * vdd * vdd * freq  # not sure if calculation is correct

        # Calculate the bitcell power which currently only includes leakage
        cell_power = self.cell.analytical_power(proc, vdd, temp, load)

        # Leakage power grows with entire array and bitlines.
        total_power = self.return_power(cell_power.dynamic + bitline_dynamic * self.column_size,
                                        cell_power.leakage * self.column_size * self.row_size)
        return total_power

    def gen_wl_wire(self):
        wl_wire = self.generate_rc_net(int(self.column_size), self.width, drc["minwidth_metal1"])
        wl_wire.wire_c = 2 * spice["min_tx_gate_c"] + wl_wire.wire_c  # 2 access tx gate per cell
        return wl_wire

    def gen_bl_wire(self):
        bl_pos = 0
        bl_wire = self.generate_rc_net(int(self.row_size - bl_pos), self.height, drc["minwidth_metal1"])
        bl_wire.wire_c = spice["min_tx_drain_c"] + bl_wire.wire_c  # 1 access tx d/s per cell
        return bl_wire

    def output_load(self, bl_pos=0):
        bl_wire = self.gen_bl_wire()
        return bl_wire.wire_c  # sense amp only need to charge small portion of the bl
        # set as one segment for now

    def input_load(self):
        wl_wire = self.gen_wl_wire()
        return wl_wire.return_input_cap()
