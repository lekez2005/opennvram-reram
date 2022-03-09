import datetime
import math
import re
from typing import TYPE_CHECKING

import debug
from base.contact import m1m2, m2m3, cross_m2m3, cross_m1m2, m3m4
from base.contact_full_stack import ContactFullStack
from base.design import METAL1, METAL2, METAL3, METAL4, design, PWELL, ACTIVE, NIMP, PIMP, NWELL
from base.geometry import NO_MIRROR, MIRROR_Y_AXIS
from base.layout_clearances import find_clearances, VERTICAL as CLEAR_VERT
from base.utils import round_to_grid as rg
from base.vector import vector
from base.well_implant_fills import create_wells_and_implants_fills, get_default_fill_layers
from globals import OPTS, print_time
from modules.baseline_bank import BaselineBank
from modules.flop_buffer import FlopBuffer
from modules.hierarchical_predecode2x4 import hierarchical_predecode2x4
from modules.hierarchical_predecode3x8 import hierarchical_predecode3x8
from modules.sram_power_grid import SramPowerGridMixin


class BaselineSram(SramPowerGridMixin, design):
    wide_space = None
    bank_insts = bank = row_decoder = None
    column_decoder = column_decoder_inst = None
    row_decoder_inst = None

    def __init__(self, word_size, num_words, num_banks, name, words_per_row=None,
                 add_power_grid=True):
        """Words will be split across banks in case of two banks"""
        assert num_banks in [1, 2], "Only one or two banks supported"
        if num_banks == 2 and not OPTS.independent_banks:
            assert word_size % 2 == 0, "Word-size must be even when word is spread across two banks"
            word_size = int(word_size / 2)
        if words_per_row is not None:
            assert words_per_row in [1, 2, 4, 8], "Max 8 words per row supported"

        start_time = datetime.datetime.now()

        design.__init__(self, name)
        self.initialize_power_grid(add_power_grid)

        self.bitcell = self.create_mod_from_str(OPTS.bitcell)

        self.compute_sizes(word_size, num_words, num_banks, words_per_row)
        debug.info(2, "create sram of size {0} with {1} num of words".format(self.word_size,
                                                                             self.num_words))
        self.create_layout()

        self.offset_all_coordinates()
        sizes = self.find_highest_coords()
        self.width = sizes[0]
        self.height = sizes[1]
        self.add_boundary()

        self.DRC_LVS(final_verification=True)

        if not OPTS.is_unit_test:
            print_time("SRAM creation", datetime.datetime.now(), start_time)

        # restore word-size
        if num_banks == 2 and not OPTS.independent_banks:
            self.word_size = 2 * self.word_size

    def create_layout(self):
        self.single_bank = self.num_banks == 1
        self.wide_space = self.get_wide_space(METAL1)
        self.m1_pitch = self.m1_width + self.get_parallel_space(METAL1)
        self.m2_pitch = self.m2_width + self.get_parallel_space(METAL2)
        self.m3_pitch = self.m3_width + self.get_parallel_space(METAL3)
        self.create_modules()
        self.add_modules()
        self.add_pins()

        self.min_point = min(self.min_point, self.row_decoder_inst.by(), self.bank_insts[0].by())

        self.route_layout()

    def create_modules(self):
        debug.info(1, "Create sram modules")
        self.create_bank()
        self.row_decoder = self.bank.decoder
        self.min_point = self.bank.mid_vdd.by()
        self.fill_width = self.bank.fill_width
        self.fill_height = self.bank.fill_height
        self.row_decoder_y = self.bank.bitcell_array_inst.uy() - self.row_decoder.height
        self.create_column_decoder()

        bank_flop_connections = [x[0] for x in
                                 self.bank.get_control_flop_connections().values()]
        control_inputs = (self.bank.get_non_flop_control_inputs() +
                          ["clk"] + bank_flop_connections)
        self.control_inputs = control_inputs
        self.bank_flop_inputs = bank_flop_connections

    def add_modules(self):
        debug.info(1, "Add sram modules")
        self.right_bank_inst = self.bank_inst = self.add_bank(0, vector(0, 0))
        self.bank_insts = [self.right_bank_inst]
        self.add_row_decoder()
        self.min_point = min(self.min_point, self.row_decoder_inst.by())
        self.add_col_decoder()
        self.add_power_rails()
        if self.num_banks == 2:
            x_offset = self.get_left_bank_x()
            # align bitcell array
            y_offset = self.right_bank_inst.by() + (self.bank.bitcell_array_inst.by() -
                                                    self.left_bank.bitcell_array_inst.by())
            self.left_bank_inst = self.add_bank(1, vector(x_offset, y_offset))
            self.bank_insts = [self.right_bank_inst, self.left_bank_inst]

    def route_layout(self):
        debug.info(1, "Route sram")
        self.fill_decoder_wordline_space()
        self.route_column_decoder()
        self.route_row_decoder_clk()
        self.route_col_decoder_clock()
        self.route_decoder_outputs()
        self.route_decoder_power()
        self.join_bank_controls()

        self.route_left_bank_power()

        self.copy_layout_pins()
        self.route_power_grid()

    def compute_sizes(self, word_size, num_words, num_banks, words_per_row):
        self.num_banks = num_banks
        self.num_words = num_words
        self.word_size = word_size
        OPTS.num_banks = num_banks

        if self.num_banks == 2 and OPTS.independent_banks:
            self.num_words_per_bank = int(num_words / num_banks)
        else:  # for non-independent banks, put half word per bank, total number of words remains the same
            self.num_words_per_bank = num_words

        if words_per_row is None:
            words_per_row = self.estimate_words_per_row(word_size, self.num_words_per_bank)

        self.words_per_row = words_per_row
        self.num_rows = int(self.num_words_per_bank / self.words_per_row)
        self.num_cols = int(self.word_size * self.words_per_row)

        self.col_addr_size = int(math.log(self.words_per_row, 2))
        self.row_addr_size = int(math.log(self.num_rows, 2))
        self.bank_addr_size = self.col_addr_size + self.row_addr_size
        self.addr_size = int(math.log(num_words, 2))

    def estimate_words_per_row(self, word_size, num_words):
        area = math.inf
        all_words_per_row = [1, 2, 4, 8]
        for i in range(len(all_words_per_row)):
            words_per_row = all_words_per_row[i]
            if not num_words % words_per_row == 0:  # not divisible
                return all_words_per_row[i - 1]
            num_rows = num_words / words_per_row
            # heuristic extra 16 for decoder/wordline, extra 25 for peripherals below array
            tentative_area = (((words_per_row * word_size + 16) * self.bitcell.width) *
                              ((num_rows + 25) * self.bitcell.height))
            if tentative_area > area:  # previous config has lower area, terminate
                return all_words_per_row[i - 1]
            else:
                area = tentative_area
        return all_words_per_row[-1]

    @staticmethod
    def get_bank_class():
        if hasattr(OPTS, "bank_class"):
            return design.import_mod_class_from_str(OPTS.bank_class)
        return BaselineBank

    def create_bank(self):
        bank_class = self.get_bank_class()
        self.bank = bank_class(name="bank", word_size=self.word_size, num_words=self.num_words_per_bank,
                               words_per_row=self.words_per_row, num_banks=self.num_banks)
        self.add_mod(self.bank)
        if self.num_banks == 2:
            debug.info(1, "Creating left bank")
            self.left_bank = bank_class(name="left_bank", word_size=self.word_size,
                                        num_words=self.num_words_per_bank,
                                        words_per_row=self.words_per_row,
                                        num_banks=self.num_banks,
                                        adjacent_bank=self.bank)
            self.add_mod(self.left_bank)

    def add_bank(self, bank_num, position):
        if bank_num == 0:
            bank_mod = self.bank
            mirror = NO_MIRROR
        else:
            bank_mod = self.left_bank
            mirror = MIRROR_Y_AXIS
            position.x += bank_mod.width
        bank_inst = self.add_inst(name="bank{0}".format(bank_num),
                                  mod=bank_mod,
                                  offset=position,
                                  mirror=mirror)

        self.connect_inst(self.get_bank_connections(bank_num, bank_mod))
        return bank_inst

    @staticmethod
    def create_column_decoder_modules(words_per_row):
        if words_per_row == 2:
            column_decoder = FlopBuffer(OPTS.control_flop, OPTS.column_decoder_buffers)
        else:
            col_buffers = OPTS.column_decoder_buffers
            buffer_sizes = [OPTS.predecode_sizes[0]] + col_buffers
            decoder_class = hierarchical_predecode2x4 \
                if words_per_row == 4 else hierarchical_predecode3x8
            column_decoder = decoder_class(use_flops=True, buffer_sizes=buffer_sizes,
                                           negate=False)
        return column_decoder

    def get_col_decoder_connections(self):
        col_decoder_connections = []
        for i in range(self.col_addr_size):
            col_decoder_connections.append("ADDR[{}]".format(i))
        for i in range(self.words_per_row):
            col_decoder_connections.append("sel[{}]".format(i))
        col_decoder_connections.extend(["decoder_clk", "vdd", "gnd"])
        return col_decoder_connections

    def create_column_decoder(self):
        if self.words_per_row < 2:
            return
        self.column_decoder = self.create_column_decoder_modules(self.words_per_row)
        if self.words_per_row == 2:
            # Export internal flop output as layout pin, rearrange pin to match predecoder order
            self.column_decoder.pins = ["din", "dout_bar", "dout", "clk", "vdd", "gnd"]
            col_decoder_buffer = self.column_decoder.buffer_inst.mod
            if len(col_decoder_buffer.module_insts) > 1:
                col_decoder_buffer.copy_layout_pin(col_decoder_buffer.module_insts[-1], "A",
                                                   "out_buf_input")
                self.column_decoder.copy_layout_pin(self.column_decoder.buffer_inst, "out_buf_input",
                                                    "dout_bar")
            else:
                self.column_decoder.copy_layout_pin(self.column_decoder.buffer_inst, "in",
                                                    "dout_bar")

        self.add_mod(self.column_decoder)

    def get_schematic_pin_insts(self):
        return [self.bank_inst, self.row_decoder_inst, self.column_decoder_inst]

    def get_shared_external_pins(self):
        return ["clk", "vdd", "gnd"]

    def add_pins(self):
        """ Adding pins for Bank module"""
        for inst in self.get_schematic_pin_insts():
            if not inst:
                continue
            conn_index = self.insts.index(inst)
            inst_conns = self.conns[conn_index]
            for net in inst_conns:
                if net in self.pins:
                    continue
                count = 0
                for i, conns in enumerate(self.conns):
                    if net in conns:
                        count += 1
                pin_index = inst_conns.index(net)
                if count == 1:
                    debug.info(2, "Add inst %s layout pin %s as %s", inst.name,
                               inst.mod.pins[pin_index], net)
                    self.add_pin(net)
        additional_pins = [x for x in self.get_shared_external_pins() if x not in self.pins]
        self.add_pin_list(additional_pins)

    def copy_layout_pins(self):

        replacements_list = [x[:2] for x in self.get_bank_connection_replacements()]
        replacements = {key: val for key, val in replacements_list}

        right_bank = self.bank_insts[0]
        for pin_name in self.control_inputs:
            new_pin_name = replacements.get(pin_name, pin_name)
            if self.num_banks == 1:
                self.copy_layout_pin(right_bank, pin_name, new_pin_name)
            else:
                rail = getattr(self, pin_name + "_rail")
                self.add_layout_pin(new_pin_name, METAL3, vector(rail.cx(), rail.by()),
                                    width=rail.height, height=rail.height)

        for i in range(self.row_addr_size):
            self.copy_layout_pin(self.row_decoder_inst, "A[{}]".format(i),
                                 "ADDR[{}]".format(i + self.col_addr_size))

        # copy DATA and MASK pins
        for i in range(self.num_banks):
            bank_inst = self.bank_insts[i]
            bank_connections = None
            for index, inst in enumerate(self.insts):
                if inst.name == bank_inst.name:
                    bank_connections = self.conns[index]
                    break
            for pin_index, net in enumerate(bank_connections):
                if net.startswith("DATA") or net.startswith("MASK"):
                    pin_name = bank_inst.mod.pins[pin_index]
                    self.copy_layout_pin(bank_inst, pin_name, net)

    def get_left_bank_x(self):
        x_offset_by_wordline_driver = self.mid_gnd.lx() - self.wide_space - self.bank.width
        # find max control rail offset
        rail_offsets = [getattr(self.bank, rail_name + "_rail").lx() for rail_name in self.bank.rail_names]
        min_rail_x = min(rail_offsets)
        col_to_row_decoder_space = (self.words_per_row + 1) * self.m2_pitch
        if self.column_decoder_inst is not None:
            x_offset_by_col_decoder = (self.column_decoder_inst.lx() - col_to_row_decoder_space -
                                       (self.bank.width - min_rail_x))
            return min(x_offset_by_wordline_driver, x_offset_by_col_decoder)
        return x_offset_by_wordline_driver

    def calculate_min_m2_rail_x(self, y_top):
        bank_m2_rails = self.bank.m2_rails
        valid_rails = [x for x in bank_m2_rails
                       if x.uy() - self.get_line_end_space(METAL2) > y_top]
        leftmost_rail = min(valid_rails + [self.get_decoder_clk_pin()], key=lambda x: x.lx())
        leftmost_rail_x = leftmost_rail.lx()
        return leftmost_rail_x

    def calculate_row_decoder_x(self):
        row_decoder_y = self.row_decoder_y
        # calculate x offset assuming col decoder will be below row decoder
        # we will check if we can still fit col decoder above control flops when adding col decoder
        leftmost_rail_x = self.calculate_min_m2_rail_x(row_decoder_y)

        if self.words_per_row > 1:
            leftmost_rail_x -= self.words_per_row * self.bus_pitch + self.bus_space

        # avoid clash with control flops
        top_flop_inst = self.get_top_flop_inst()
        flop_space = self.bank.get_row_decoder_control_flop_space()
        if rg(top_flop_inst.uy() + flop_space) > rg(row_decoder_y):
            control_pins = [self.bank_inst.get_pin(x) for x in self.bank_flop_inputs]
            leftmost_rail_x = min(leftmost_rail_x, min(map(lambda x: x.lx(), control_pins)))

        self.leftmost_m2_rail_x = leftmost_rail_x

        max_predecoder_x = (leftmost_rail_x - self.get_wide_space(METAL2) -
                            self.row_decoder.width)
        max_row_decoder_x = self.bank.wordline_driver_inst.lx() - self.row_decoder.row_decoder_width
        x_offset = min(max_predecoder_x, max_row_decoder_x)
        if OPTS.separate_vdd_wordline:
            x_offset = self.calculate_separate_vdd_row_dec_x(x_offset)
        if self.has_dummy:
            decoder_right = x_offset + self.row_decoder.row_decoder_width
            wordline_left = self.bank.wordline_driver_inst.lx() + self.bank_inst.lx()
            if rg(wordline_left - decoder_right) < self.poly_pitch:
                x_offset -= rg(self.poly_pitch - (wordline_left - decoder_right))

        return x_offset

    def add_row_decoder(self):
        x_offset = self.calculate_row_decoder_x()
        self.row_decoder_inst = self.add_inst(name="row_decoder", mod=self.row_decoder,
                                              offset=vector(x_offset, self.row_decoder_y))

        self.connect_inst(self.get_row_decoder_connections())

    def get_row_decoder_connections(self):
        temp = []
        for i in range(self.row_addr_size):
            temp.append("ADDR[{0}]".format(i + self.col_addr_size))
        for j in range(self.num_rows):
            temp.append("dec_out[{0}]".format(j))
        temp.extend(["decoder_clk", "vdd", "gnd"])
        return temp

    def calculate_row_decoder_col_decoder_y_space(self):
        col_well = self.column_decoder.get_max_shape(NWELL, "uy", recursive=True)
        row_predecoder = self.row_decoder.all_predecoders[0]
        row_well = row_predecoder.get_max_shape(NWELL, "by", recursive=True)
        well_space = self.get_parallel_space(NWELL)
        space = -row_well.by() + (col_well.uy() - self.column_decoder.height) + well_space
        return max(space, self.bank.row_decoder_col_decoder_space)

    def get_top_flop_inst(self):
        return max(self.bank.control_flop_insts, key=lambda x: x[2].uy())[2]

    def add_col_decoder(self):
        if self.words_per_row == 1:
            return

        top_flop_inst = self.get_top_flop_inst()
        self.col_sel_rails_y = (top_flop_inst.uy() + self.bank.rail_space_above_controls
                                - (self.words_per_row + 1) * self.bus_pitch)

        self.row_decoder_col_decoder_space = self.calculate_row_decoder_col_decoder_y_space()
        column_decoder = self.column_decoder
        col_decoder_y = (self.row_decoder_inst.by() - self.row_decoder_col_decoder_space -
                         column_decoder.height)

        sel_pins = [self.right_bank_inst.get_pin(f"sel[{i}]") for i in range(self.words_per_row)]
        sel_pins = list(sorted(sel_pins, key=lambda x: x.cy()))
        sel_pin_y = sel_pins[0].by()

        col_decoder_is_left = True
        col_decoder_x = None
        self.col_decoder_is_above = False

        # check it can fit y space from control flops to wordline driver

        decoder_vdd = [x for x in self.row_decoder_inst.get_pins("vdd") if x.by() < sel_pin_y]
        top_decoder_vdd = max(decoder_vdd, key=lambda x: x.uy())
        bottom_decoder_vdd = min(decoder_vdd, key=lambda x: x.by())

        top_y = rg(top_decoder_vdd.cy())
        bottom_y = (top_flop_inst.uy() + self.get_space(NWELL, prefix="different") +
                    2 * self.bus_width)
        bottom_y = rg(max(bottom_y, bottom_decoder_vdd.cy()))

        # check if it can fit x space
        left_x = self.row_decoder_inst.rx() + 2 * self.bus_pitch
        right_x = self.leftmost_m2_rail_x - self.bus_pitch
        fits_x_space = right_x - left_x > column_decoder.width

        def align_with_vdd(max_y):
            # align with vdd
            valid_vdd = [x for x in decoder_vdd if rg(x.cy()) <= rg(max_y)]
            max_vdd = max(valid_vdd, key=lambda x: x.cy())
            return max_vdd.cy() - column_decoder.height

        if top_y - bottom_y > column_decoder.height:
            # fits y space
            if fits_x_space:
                self.col_decoder_is_above = True
                col_decoder_is_left = False
                col_decoder_x = 0.5 * (right_x + left_x) - 0.5 * column_decoder.width
                col_decoder_y = align_with_vdd(top_y)
            else:
                # check if there is enough space above control flops
                if col_decoder_y > top_flop_inst.uy() + self.row_decoder_col_decoder_space:
                    # max_top = col_decoder_y +
                    col_decoder_is_left = False
                    col_decoder_x = self.leftmost_m2_rail_x - self.bus_pitch - column_decoder.width

        # check if it fits between row decoder and flops
        flop_inputs_pins = [self.right_bank_inst.get_pin(x)
                            for x in self.bank_flop_inputs]
        left_most_rail_x = min(flop_inputs_pins, key=lambda x: x.lx()).lx() - self.bus_space
        max_col_decoder_x = (left_most_rail_x - (1 + self.words_per_row) * self.bus_pitch -
                             column_decoder.width)
        if max_col_decoder_x > left_x:
            self.col_decoder_is_above = True
            col_decoder_is_left = False
            col_decoder_x = max_col_decoder_x
            col_decoder_y = align_with_vdd(top_y)
        self.col_decoder_is_left = col_decoder_is_left

        if col_decoder_is_left:
            col_decoder_x = max_col_decoder_x
            self.col_sel_rails_y = max(self.col_sel_rails_y, col_decoder_y +
                                       0.5 * column_decoder.height -
                                       0.5 * self.words_per_row * self.bus_pitch)

        self.column_decoder_inst = self.add_inst("col_decoder", mod=self.column_decoder,
                                                 offset=vector(col_decoder_x, col_decoder_y))
        self.connect_inst(self.get_col_decoder_connections())

        self.min_point = min(self.min_point, self.column_decoder_inst.by())

    def add_power_rails(self):
        bank_vdd = self.bank.mid_vdd
        y_offset = min(bank_vdd.by(), self.min_point)
        min_decoder_x = self.row_decoder_inst.lx()
        if self.column_decoder_inst is not None:
            min_decoder_x = min(min_decoder_x, self.column_decoder_inst.lx() - 2 * self.bus_pitch)
        x_offset = min_decoder_x - self.wide_space - bank_vdd.width()
        self.mid_vdd = self.add_rect(METAL2, offset=vector(x_offset, y_offset), width=bank_vdd.width(),
                                     height=bank_vdd.uy() - y_offset)

        x_offset -= (self.bank.wide_power_space + bank_vdd.width())
        self.mid_gnd = self.add_rect(METAL2, offset=vector(x_offset, y_offset), width=bank_vdd.width(),
                                     height=bank_vdd.uy() - y_offset)

    @staticmethod
    def shift_bits(prefix, bit_shift, conns_):
        for index, conn in enumerate(conns_):
            pattern = r"{}\[([0-9]+)\]".format(prefix)
            match = re.match(pattern, conn)
            if match:
                digit = int(match.group(1))
                conns_[index] = "{}[{}]".format(prefix, bit_shift + digit)

    def get_bank_connection_replacements(self):
        address_msb = "ADDR[{}]".format(self.addr_size - 1)
        return [
            ("read", "Web"),
            ("addr_msb", address_msb),
            ("clk_buf", "decoder_clk")
        ]

    def get_bank_connections(self, bank_num, bank_mod):

        connections = bank_mod. \
            connections_from_mod(bank_mod, self.get_bank_connection_replacements())

        if self.num_banks == 2 and bank_num == 1:
            if OPTS.independent_banks:
                connections = bank_mod.connections_from_mod(connections, [("DATA[", "DATA_1["),
                                                                          ("MASK[", "MASK_1[")])
            else:
                self.shift_bits("DATA", self.word_size, connections)
                self.shift_bits("MASK", self.word_size, connections)
        return connections

    def get_decoder_clk_pin(self):
        clk_pin_name = "decoder_clk" if "decoder_clk" in self.bank.pins else "clk_buf"
        return self.right_bank_inst.get_pin(clk_pin_name)

    def get_row_decoder_clk_y(self, clk_pin):
        min_clk_y = clk_pin.by()
        if self.column_decoder_inst:
            # avoid col decoder outputs
            col_decoder_y = max(map(lambda x: x.by(), self.col_decoder_outputs))
            min_clk_y = max(col_decoder_y + self.bus_pitch, min_clk_y)
            # avoid overlap with col decoder
            col_decoder_m1 = self.column_decoder.get_max_shape(METAL1, "uy", recursive=True)
            m1_extension = max(col_decoder_m1.uy() - self.column_decoder.height, 0)
            if (self.column_decoder_inst.by() - m1_extension <= min_clk_y
                    <= self.column_decoder_inst.uy() + m1_extension):
                min_clk_y = max(min_clk_y, self.column_decoder_inst.uy() + m1_extension +
                                self.bus_space)

        else:
            top_flop_inst = self.get_top_flop_inst()
            predecoder_vdd_height = self.row_decoder.all_predecoders[0].get_pins("vdd")[0].height()
            rail_space = 2 * self.get_line_end_space(METAL3) + predecoder_vdd_height
            min_clk_y = max(min_clk_y, top_flop_inst.uy() + rail_space)
        # avoid bank m3 pins
        bank = self.bank_inst.mod
        # use only left edge to min. chances of mid-power rail vias m3 false-positive clash overlaps
        region = [clk_pin.lx(), clk_pin.lx()]
        open_spaces = find_clearances(bank, METAL3, CLEAR_VERT,
                                      existing=[(min_clk_y, bank.bitcell_array_inst.by())],
                                      region=region, recursive=False)
        min_space = self.bus_pitch + self.bus_width
        # prefer between the row and column decoders
        if self.column_decoder_inst:
            mid_y = 0.5 * (self.column_decoder_inst.uy() + self.row_decoder_inst.by())
            for bottom, top in open_spaces:
                if bottom + self.bus_space <= mid_y <= top - self.bus_pitch:
                    return mid_y
        # otherwise, just use the minimum
        open_spaces = [x for x in open_spaces if x[1] - x[0] > min_space]
        free_space = min(open_spaces, key=lambda x: x[0])
        return free_space[0] + self.bus_space

    def route_row_decoder_clk(self):
        clk_pin = self.get_decoder_clk_pin()
        y_offset = self.get_row_decoder_clk_y(clk_pin)

        if clk_pin.layer == METAL3 and not y_offset == clk_pin.by():
            _, min_height = self.calculate_min_area_fill(clk_pin.width(), layer=METAL2)
            self.add_rect(METAL2, clk_pin.ll(), width=clk_pin.width(), height=min_height)
            self.add_cross_contact_center(cross_m2m3, clk_pin.center())

        # find closest clock
        decoder_clk_pins = self.row_decoder_inst.get_pins("clk")
        valid_decoder_pins = list(filter(lambda x: x.by() > clk_pin.by(), decoder_clk_pins))
        closest_clk = [x for x in valid_decoder_pins if x.by() <= y_offset <= x.uy()]
        if closest_clk:
            closest_clk = closest_clk[0]
        else:
            closest_clk = min(valid_decoder_pins, key=lambda x: abs(y_offset - x.cy()))

        self.add_rect(METAL2, offset=clk_pin.ll(), width=clk_pin.width(),
                      height=y_offset - clk_pin.by())
        if clk_pin.layer == METAL3 and not y_offset == clk_pin.by():
            self.add_cross_contact_center(cross_m2m3,
                                          vector(clk_pin.cx(), y_offset + 0.5 * self.bus_width))

        self.clk_m3_rail = self.add_rect(METAL3, offset=vector(closest_clk.cx(), y_offset),
                                         height=self.bus_width,
                                         width=clk_pin.cx() - closest_clk.cx())
        via_offset = vector(closest_clk.lx() + 0.5 * m2m3.w_2, y_offset + 0.5 * self.bus_width)
        self.add_contact_center(m2m3.layer_stack, via_offset)

        if y_offset < closest_clk.by() or y_offset > closest_clk.uy():
            self.add_rect(METAL2, vector(closest_clk.lx(), y_offset), width=closest_clk.width(),
                          height=closest_clk.by() - y_offset)

    def route_column_decoder(self):
        if self.words_per_row < 2:
            return
        if self.words_per_row == 2:
            self.route_flop_column_decoder()
        else:
            self.route_predecoder_column_decoder()

    def route_flop_column_decoder(self):

        # outputs
        out_pin = self.column_decoder_inst.get_pin("dout")
        out_bar_pin = self.column_decoder_inst.get_pin("dout_bar")
        out_bar_y = out_bar_pin.cy()
        out_y = max(out_bar_y, out_pin.cy()) + self.bus_pitch
        y_offsets = [out_bar_y, out_y]
        self.col_decoder_outputs = []

        self.route_col_decoder_to_rail(output_pins=[out_bar_pin, out_pin], rail_offsets=y_offsets)

        self.route_col_decoder_outputs()
        self.route_col_decoder_power()
        self.copy_layout_pin(self.column_decoder_inst, "din", self.get_col_decoder_connections()[0])

    def route_col_decoder_clock(self):
        if not self.column_decoder_inst:
            return
        col_decoder_clk = self.column_decoder_inst.get_pin("clk")

        clk_m3_rail = self.clk_m3_rail

        if col_decoder_clk.layer == METAL1:
            # leave space for address out
            address_space = m2m3.h_2
            via_offset = vector(col_decoder_clk.lx() - self.get_line_end_space(METAL2) -
                                0.5 * self.m2_width - address_space, col_decoder_clk.cy())
            self.add_contact_center(m1m2.layer_stack, via_offset, rotate=90)
            self.add_rect(METAL1, vector(via_offset.x, col_decoder_clk.by()),
                          width=col_decoder_clk.lx() - via_offset.x,
                          height=col_decoder_clk.height())
            col_decoder_clk = self.add_rect_center(METAL2, via_offset)

        if clk_m3_rail.lx() > col_decoder_clk.rx():
            # find rail_y
            row_mod = self.row_decoder.all_predecoders[0]
            row_m1 = row_mod.get_max_shape(METAL1, "by", recursive=True)
            row_extension = max(0, - row_m1.by())
            m1_space = self.get_wide_space(METAL1) + row_extension + self.bus_width
            rail_y = min(clk_m3_rail.by(), self.row_decoder_inst.by() - m1_space)

            rail_x = clk_m3_rail.lx() - 0.5 * self.bus_width
            if rail_y > clk_m3_rail.by() - (m2m3.height + self.get_via_space(m2m3)):
                # direct m3
                rail_top = max(clk_m3_rail.uy(), clk_m3_rail.cy() + 0.5 * m2m3.h_2)
                self.add_rect(METAL3, vector(rail_x, rail_y), width=self.bus_width,
                              height=rail_top - rail_y)
                rail_right = rail_x + self.bus_width
            else:
                bottom_clk = min(self.row_decoder_inst.get_pins("clk"), key=lambda x: x.by())
                self.add_rect(METAL2, vector(bottom_clk.lx(), rail_y), width=bottom_clk.width(),
                              height=bottom_clk.by() - rail_y)
                via_offset = vector(bottom_clk.cx(), rail_y + 0.5 * self.bus_width)
                self.add_cross_contact_center(cross_m2m3, via_offset, fill=False)
                rail_right = bottom_clk.cx() + 0.5 * m2m3.h_2
            clk_m3_rail = self.add_rect(METAL3, vector(rail_x, rail_y),
                                        width=rail_right - rail_x, height=self.bus_width)
            x_offset = col_decoder_clk.cx() - 0.5 * m2m3.h_2
            self.add_rect(METAL3, vector(x_offset, clk_m3_rail.by()),
                          width=clk_m3_rail.lx() - x_offset, height=clk_m3_rail.height)
        self.add_rect(METAL2, vector(col_decoder_clk.lx(), clk_m3_rail.cy()),
                      width=col_decoder_clk.rx() - col_decoder_clk.lx(),
                      height=col_decoder_clk.cy() - clk_m3_rail.cy())
        self.add_cross_contact_center(cross_m2m3, vector(col_decoder_clk.cx(), clk_m3_rail.cy()),
                                      fill=False)

    def route_col_decoder_to_rail(self, output_pins=None, rail_offsets=None):
        if output_pins is None:
            output_pins = [self.column_decoder_inst.get_pin("out[{}]".format(i)) for i in range(self.words_per_row)]
        if rail_offsets is None:
            rail_offsets = [x.cy() for x in output_pins]

        if self.col_decoder_is_left:
            base_x = self.column_decoder_inst.rx() + self.bus_pitch
            # using by() because mirror
            base_y = self.col_sel_rails_y
            rails_y = [base_y + i * self.bus_pitch for i in range(self.words_per_row)]

            x_offset = self.leftmost_m2_rail_x
            rails_x = [x_offset + i * self.bus_pitch for i in range(self.words_per_row)]
        else:
            base_x = self.leftmost_m2_rail_x
            rails_y = []
            rails_x = []
        x_offsets = [base_x + i * self.bus_pitch for i in range(self.words_per_row)]

        self.col_decoder_outputs = []
        for i in range(self.words_per_row):
            output_pin = output_pins[i]
            x_offset = x_offsets[i]
            y_offset = rail_offsets[i]

            if i == 0 and self.words_per_row == 2:

                if len(self.column_decoder.buffer_inst.mod.module_insts) > 1:
                    self.add_contact_center(m1m2.layer_stack, output_pin.center(), rotate=90)
                    fill_height = m1m2.h_2
                    _, fill_width = self.calculate_min_area_fill(fill_height, layer=METAL2)
                    self.add_rect_center(METAL2, output_pin.center(), width=fill_width,
                                         height=fill_height)
                m3_x = output_pin.cx() - 0.5 * m2m3.h_2
                self.add_rect(METAL3, offset=vector(m3_x, y_offset - 0.5 * self.bus_width),
                              width=x_offset - m3_x,
                              height=self.bus_width)
                self.add_cross_contact_center(cross_m2m3, offset=vector(output_pin.cx(), y_offset),
                                              fill=False)
                rail_via_offset = vector(x_offset + 0.5 * self.bus_width, y_offset)
                self.add_cross_contact_center(cross_m2m3, offset=rail_via_offset, fill=True)
            else:
                rail_via_offset = vector(x_offset + 0.5 * self.bus_width,
                                         y_offset + 0.5 * self.bus_width)
                self.add_rect(METAL1, offset=vector(output_pin.cx(), y_offset),
                              width=x_offset - output_pin.cx(),
                              height=self.bus_width)
                self.add_cross_contact_center(cross_m1m2, offset=rail_via_offset, rotate=True)
            if not self.col_decoder_is_left:
                self.col_decoder_outputs.append(self.add_rect(METAL2,
                                                              offset=vector(x_offset, y_offset),
                                                              width=self.bus_width,
                                                              height=self.bus_width))
            else:
                _, fill_height = self.calculate_min_area_fill(self.bus_width, layer=METAL2)
                rail_y = rails_y[i]
                m2_height = rail_y - y_offset
                self.add_rect(METAL2, offset=vector(x_offset, y_offset),
                              height=m2_height, width=self.bus_width)

                if abs(m2_height) < fill_height:
                    self.add_rect(METAL2, offset=vector(x_offset, y_offset), height=fill_height, width=self.bus_width)

                self.add_cross_contact_center(cross_m2m3, offset=vector(x_offset + 0.5 * self.bus_width,
                                                                        rail_y + 0.5 * self.bus_width))
                self.add_rect(METAL3, offset=vector(x_offset, rail_y), width=rails_x[i] - x_offset,
                              height=self.bus_width)
                self.add_cross_contact_center(cross_m2m3, offset=vector(rails_x[i] + 0.5 * self.bus_width,
                                                                        rail_y + 0.5 * self.bus_width))
                self.col_decoder_outputs.append(self.add_rect(METAL2, offset=vector(rails_x[i], rail_y),
                                                              width=self.bus_width, height=self.bus_width))

    def route_col_decoder_outputs(self):
        if self.num_banks == 2:
            top_predecoder_inst = max(self.row_decoder.pre2x4_inst + self.row_decoder.pre3x8_inst,
                                      key=lambda x: x.uy())
            # place rails just above the input flops
            num_flops = top_predecoder_inst.mod.number_of_inputs
            y_space = top_predecoder_inst.get_pins("vdd")[0].height() + self.get_wide_space(METAL3) + self.bus_space
            self.left_col_mux_select_y = (self.row_decoder_inst.by() + top_predecoder_inst.by()
                                          + num_flops * top_predecoder_inst.mod.flop.height + y_space)

        for i in range(self.words_per_row):
            sel_pin = self.right_bank_inst.get_pin("sel[{}]".format(i))
            rail = self.col_decoder_outputs[i]
            self.add_rect(METAL2, offset=rail.ul(), width=self.bus_width,
                          height=sel_pin.cy() - rail.uy())
            self.add_rect(METAL1, offset=vector(rail.lx(), sel_pin.cy() - 0.5 * self.bus_width),
                          width=sel_pin.lx() - rail.lx(), height=self.bus_width)
            self.add_cross_contact_center(cross_m1m2, offset=vector(rail.cx(), sel_pin.cy()),
                                          rotate=True)

            if self.num_banks == 2:
                # route to the left
                x_start = self.left_bank_inst.rx() - self.left_bank.leftmost_rail.offset.x
                x_offset = x_start + (1 + i) * self.bus_pitch

                y_offset = self.left_col_mux_select_y + i * self.bus_pitch
                self.add_rect(METAL2, offset=vector(rail.lx(), sel_pin.cy()), width=self.bus_width,
                              height=y_offset - sel_pin.cy())
                self.add_cross_contact_center(cross_m2m3,
                                              offset=vector(rail.cx(),
                                                            y_offset + 0.5 * self.bus_width))
                self.add_rect(METAL3, offset=vector(x_offset, y_offset), height=self.bus_width,
                              width=rail.lx() - x_offset)
                self.add_cross_contact_center(cross_m2m3,
                                              offset=vector(x_offset + 0.5 * self.bus_width,
                                                            y_offset + 0.5 * self.bus_width))
                sel_pin = self.left_bank_inst.get_pin("sel[{}]".format(i))
                self.add_rect(METAL2, offset=vector(x_offset, sel_pin.cy()), width=self.bus_width,
                              height=y_offset - sel_pin.cy())
                self.add_cross_contact_center(cross_m1m2,
                                              offset=vector(x_offset + 0.5 * self.bus_width,
                                                            sel_pin.cy()), rotate=True)
                self.add_rect(METAL1, offset=sel_pin.lr(), height=sel_pin.height(),
                              width=x_offset - sel_pin.rx())

    def route_right_bank_sel_in(self, sel_offsets):
        """
        route sel pins from col decoder to the bank on the right
        :param sel_offsets: arranged from sel_0 to sel_x
        """
        y_bend = (self.bank.wordline_driver_inst.by() - self.bank.col_decoder_rail_space +
                  self.m3_pitch)
        x_bend = (self.row_decoder_inst.lx() + self.row_decoder.width +
                  self.words_per_row * self.m2_pitch + 2 * self.wide_space)
        for i in range(len(sel_offsets)):
            in_pin = self.bank_insts[0].get_pin("sel[{}]".format(i))
            x_offset = sel_offsets[i]
            self.add_rect(METAL2, offset=vector(x_offset, in_pin.by()), height=y_bend - in_pin.by())
            self.add_contact(m2m3.layer_stack, offset=vector(x_offset,
                                                             y_bend + self.m3_width - m2m3.height))

            self.add_rect(METAL3, offset=vector(x_offset, y_bend), width=x_bend - x_offset)

            self.add_contact(m2m3.layer_stack, offset=vector(x_bend + m2m3.height, y_bend),
                             rotate=90)
            in_pin = self.bank_insts[0].get_pin("sel[{}]".format(i))
            self.add_rect(METAL2, offset=vector(x_bend, in_pin.by()), height=y_bend - in_pin.by())
            self.add_contact(m1m2.layer_stack, offset=vector(x_bend, in_pin.by()))
            self.add_rect(METAL1, offset=vector(x_bend, in_pin.by()), width=in_pin.lx() - x_bend)

            y_bend += self.m3_pitch
            x_bend -= self.m2_pitch

    def route_predecoder_column_decoder(self):

        # address pins
        all_addr_pins = [x for x in self.get_col_decoder_connections() if x.startswith("ADDR")]
        all_addr_pins = list(reversed(all_addr_pins))
        for i in range(self.col_addr_size):
            self.copy_layout_pin(self.column_decoder_inst, "flop_in[{}]".format(i), all_addr_pins[i])

        #
        self.route_col_decoder_to_rail()
        self.route_col_decoder_outputs()
        self.route_col_decoder_power()

    def route_decoder_power(self):
        rails = [self.mid_vdd, self.mid_gnd]

        sample_power_pin = max(self.row_decoder_inst.get_pins("vdd"), key=lambda x: x.uy())
        m3m4_via = ContactFullStack(start_layer=METAL3, stop_layer=METAL4,
                                    centralize=True, max_width=self.mid_vdd.width,
                                    max_height=sample_power_pin.height())

        pin_names = ["vdd", "gnd"]
        for i in range(2):
            rail = rails[i]
            center_rail_x = 0.5 * (rail.lx() + rail.rx())
            power_pins = self.row_decoder_inst.get_pins(pin_names[i])
            for power_pin in power_pins:
                if power_pin.uy() < self.bank.wordline_driver_inst.by() + \
                        self.bank_inst.by():
                    pin_right = power_pin.rx()
                    x_offset = rail.lx()
                else:
                    if OPTS.separate_vdd_wordline:
                        pin_right = max(power_pin.rx(),
                                        power_pin.lx() + self.row_decoder.row_decoder_width)
                    else:
                        pin_right = self.bank.wordline_driver_inst.lx()
                    x_offset = rail.lx() if self.single_bank else self.left_bank_inst.rx()
                self.add_rect(power_pin.layer, offset=vector(x_offset, power_pin.by()),
                              width=pin_right - x_offset, height=power_pin.height())
                if power_pin.layer == METAL1:
                    vias = [m1m2]
                    sizes = [[1, 2]]
                else:
                    vias = [m2m3, m3m4]
                    sizes = [[1, 2], m3m4_via.dimensions]
                for via, size in zip(vias, sizes):
                    self.add_contact_center(via.layer_stack,
                                            offset=vector(center_rail_x, power_pin.cy()),
                                            size=size, rotate=90)

        via_offsets, fill_height = self.evaluate_left_power_rail_vias()
        self.add_left_power_rail_vias(via_offsets, self.mid_vdd.uy(), fill_height)

    def evaluate_left_power_rail_vias(self):
        # find locations for
        fill_width = self.mid_vdd.width
        _, fill_height = self.calculate_min_area_fill(fill_width, min_height=self.m3_width,
                                                      layer=METAL3)

        wide_space = self.get_wide_space(METAL3)
        via_spacing = wide_space + self.parallel_via_space
        via_pitch = via_spacing + max(m2m3.height, fill_height)

        m2_m3_blockages = []

        for pin_name in ["vdd", "gnd"]:
            power_pins = self.row_decoder_inst.get_pins(pin_name)
            power_pins = [x for x in power_pins if x.layer == METAL3]
            for power_pin in power_pins:
                m2_m3_blockages.append((power_pin.by(), power_pin.uy()))

        if self.num_banks == 2 and self.column_decoder_inst is not None:
            # prevent select pins clash
            sel_rails_height = (1 + self.words_per_row) * self.bus_pitch
            m2_m3_blockages.append((self.left_col_mux_select_y,
                                    self.left_col_mux_select_y + sel_rails_height))

        if self.num_banks == 2:
            # prevent clashes with wl output to left bank
            decoder_out_offsets = self.get_decoder_output_offsets(self.bank_insts[-1])
            for y_offset in decoder_out_offsets:
                m2_m3_blockages.append((y_offset, y_offset + self.m3_width))

        m2_m3_blockages = list(sorted(m2_m3_blockages, key=lambda x: x[0]))
        via_top = self.mid_vdd.uy() - via_pitch
        via_offsets = []

        lowest_flop_inst = min(self.bank.control_flop_insts, key=lambda x: x[2].by())[2]
        y_offset = lowest_flop_inst.by()

        while y_offset < via_top:
            if len(m2_m3_blockages) > 0 and m2_m3_blockages[0][0] <= y_offset + via_pitch:
                y_offset = m2_m3_blockages[0][1] + wide_space
                m2_m3_blockages.pop(0)
            else:
                via_offsets.append(y_offset)
                y_offset += via_pitch
        return via_offsets, fill_height

    def add_left_power_rail_vias(self, via_offsets, rail_top, fill_height):
        m4_power_pins = self.right_bank_inst.get_pins("vdd") + self.right_bank_inst.get_pins("gnd")
        if self.num_banks == 2:
            m4_power_pins.extend(self.left_bank_inst.get_pins("vdd") + self.left_bank_inst.get_pins("gnd"))
        m4_power_pins = [x for x in m4_power_pins if x.layer == METAL4]

        self.m4_vdd_rects = []
        self.m4_gnd_rects = []
        rails = [self.mid_vdd, self.mid_gnd]
        fill_width = self.mid_vdd.width

        for i in range(2):
            rail = rails[i]
            for y_offset in via_offsets:
                via_offset = vector(rail.cx(), y_offset + 0.5 * fill_height)
                self.add_contact_center(m2m3.layer_stack, offset=via_offset,
                                        size=[1, 2], rotate=90)
                self.add_contact_center(m3m4.layer_stack, offset=via_offset,
                                        size=[1, 2], rotate=90)
                self.add_rect_center(METAL3, offset=via_offset, width=fill_width,
                                     height=fill_height)

            rect = self.add_rect(METAL4, offset=rail.ll(),
                                 width=rail.width, height=rail_top - rail.by())
            if i % 2 == 0:
                self.m4_vdd_rects.append(rect)
            else:
                self.m4_gnd_rects.append(rect)

        self.m4_power_pins = m4_power_pins

    def route_col_decoder_power(self):
        rails = [self.mid_vdd, self.mid_gnd]

        sample_power = [x for x in self.row_decoder_inst.get_pins("vdd")
                        if x.cy() < self.bank_inst.get_pin("sel[0]").uy()][0]
        row_decoder_y = rg(self.row_decoder_inst.by())
        x_offset = sample_power.rx()
        for i, pin_name in enumerate(["vdd", "gnd"]):
            for pin in self.column_decoder_inst.get_pins(pin_name):
                if rg(pin.cy()) >= row_decoder_y:
                    if pin.layer == METAL1:
                        self.add_rect(pin.layer, vector(x_offset, pin.by()),
                                      width=pin.lx() - x_offset, height=pin.height())
                else:
                    rail = rails[i]
                    via = m2m3 if pin.layer == METAL3 else m1m2
                    self.add_rect(pin.layer, offset=vector(rail.lx(), pin.by()),
                                  height=pin.height(), width=pin.lx() - rail.lx())
                    self.add_contact_center(via.layer_stack,
                                            offset=vector(rail.cx(), pin.cy()),
                                            size=[1, 2], rotate=90)

    def route_predecoder_col_mux_power_pin(self, pin, rail):
        via = m1m2 if pin.layer == METAL1 else m2m3
        self.add_rect(pin.layer, offset=vector(rail.lx(), pin.by()),
                      width=pin.lx() - rail.lx(), height=pin.height())
        self.add_contact_center(via.layer_stack, offset=vector(rail.cx(), pin.cy()),
                                size=[1, 2], rotate=90)

    def route_left_bank_power(self):
        if self.num_banks == 1:
            return
        debug.info(1, "Route left bank sram power")
        rails = [self.mid_gnd, self.mid_vdd]
        pin_names = ["gnd", "vdd"]
        for i in range(2):
            rail = rails[i]
            for pin in self.left_bank.wordline_driver_inst.get_pins(pin_names[i]):
                pin_x = self.left_bank_inst.rx() - pin.lx()
                y_offset = self.left_bank_inst.by() + pin.by()
                self.add_rect(pin.layer, offset=vector(pin_x, y_offset), height=pin.height(),
                              width=rail.rx() - pin_x)
                if pin.layer == METAL3:
                    y_offset = pin.cy() + self.left_bank_inst.by()
                    self.add_contact_center(m2m3.layer_stack, offset=vector(rail.cx(), y_offset),
                                            size=[1, 2], rotate=90)

    def get_decoder_output_offsets(self, bank_inst):
        offsets = []

        buffer_mod = self.bank.wordline_driver.logic_buffer
        gnd_pin = buffer_mod.get_pin("gnd")

        odd_rail_y = gnd_pin.uy() + self.get_parallel_space(METAL3)
        even_rail_y = buffer_mod.height - odd_rail_y - self.m3_width

        for row in range(self.bank.num_rows):
            if row % 2 == 0:
                rail_y = even_rail_y
            else:
                rail_y = odd_rail_y
            y_shift = self.bank.wordline_driver_inst.mod.bitcell_offsets[row]
            offsets.append(y_shift + rail_y + bank_inst.mod.wordline_driver_inst.by())

        return offsets

    def route_decoder_outputs(self):
        # place m3 rail to the bank wordline drivers just below the power rail

        fill_height = m2m3.height
        _, fill_width = self.calculate_min_area_fill(fill_height, layer=METAL2)

        y_offsets = self.get_decoder_output_offsets(self.bank_insts[0])

        for row in range(self.num_rows):
            decoder_out = self.row_decoder_inst.get_pin("decode[{}]".format(row))
            wl_ins = [self.right_bank_inst.get_pin("dec_out[{}]".format(row))]
            if not self.single_bank:
                wl_ins.append(self.left_bank_inst.get_pin("dec_out[{}]".format(row)))

            if row % 2 == 0:
                via_y = decoder_out.uy() - 0.5 * m2m3.second_layer_height
            else:
                via_y = decoder_out.by() - 0.5 * m2m3.second_layer_height

            via_offset = vector(decoder_out.cx() - 0.5 * self.m3_width, via_y)
            self.add_contact(m2m3.layer_stack, offset=via_offset)

            y_offset = y_offsets[row]
            self.add_rect(METAL3, offset=via_offset, height=y_offset - via_offset.y)
            if self.num_banks == 1:
                x_offset = via_offset.x
            else:
                x_offset = wl_ins[1].cx() - 0.5 * self.m3_width
            self.add_rect(METAL3, offset=vector(x_offset, y_offset),
                          width=wl_ins[0].cx() + 0.5 * self.m3_width - x_offset)

            for i in range(len(wl_ins)):
                wl_in = wl_ins[i]
                x_offset = wl_in.cx() - 0.5 * self.m3_width
                self.add_rect(METAL3, offset=vector(x_offset, wl_in.cy()),
                              height=y_offset - wl_in.cy())
                self.add_contact_center(m2m3.layer_stack, wl_in.center())
                self.add_contact_center(m1m2.layer_stack, wl_in.center())
                if fill_width > 0:
                    self.add_rect_center(METAL2, offset=wl_in.center(), width=fill_width,
                                         height=fill_height)

    def join_control(self, pin_name, y_offset):
        via_extension = 0.5 * (cross_m2m3.height - cross_m2m3.contact_width)
        left_pin = self.bank_insts[1].get_pin(pin_name)
        right_pin = self.bank_insts[0].get_pin(pin_name)
        for pin in [left_pin, right_pin]:
            self.add_cross_contact_center(cross_m2m3,
                                          offset=vector(pin.cx(),
                                                        y_offset + 0.5 * self.bus_width))
            rail_bottom = y_offset + 0.5 * self.bus_width - 0.5 * cross_m2m3.height
            if rail_bottom < pin.by():
                self.add_rect(pin.layer, offset=vector(pin.lx(), rail_bottom),
                              width=pin.width(), height=pin.by() - rail_bottom)
        join_rail = self.add_rect(METAL3,
                                  offset=vector(left_pin.lx() - via_extension,
                                                y_offset),
                                  height=self.bus_width,
                                  width=right_pin.rx() - left_pin.lx() +
                                        2 * via_extension)
        setattr(self, pin_name + "_rail", join_rail)

    def join_bank_controls(self):
        control_inputs = self.control_inputs
        if self.single_bank:
            return

        # find y offset of connecting rails
        cross_clk_rail_y = self.bank.cross_clk_rail.offset.y
        if self.num_banks == 2:
            cross_clk_rail_y = min(cross_clk_rail_y,
                                   self.left_bank_inst.by() + self.left_bank.cross_clk_rail.offset.y)

        if self.column_decoder_inst is not None:
            vdd_pin = min(self.column_decoder_inst.get_pins("vdd"), key=lambda x: x.by())
            cross_clk_rail_y = min(cross_clk_rail_y,
                                   vdd_pin.by() - self.get_parallel_space(METAL3))

        y_offset = (cross_clk_rail_y - (len(control_inputs) * self.bus_pitch))

        for i in range(len(control_inputs)):
            self.join_control(control_inputs[i], y_offset)
            y_offset += self.bus_pitch

    def fill_decoder_wordline_space(self):
        if OPTS.separate_vdd_wordline:
            return
        wordline_logic = self.bank.wordline_driver.logic_buffer.logic_mod
        decoder_inverter = self.row_decoder.inv_inst[-1].mod
        fill_layers, fill_purposes = [], []
        for layer, purpose in zip(*get_default_fill_layers()):
            if layer not in [ACTIVE]:
                # No NIMP, PWELL to prevent min spacing to PIMP, NWELL respectively
                fill_layers.append(layer)
                fill_purposes.append(purpose)
        rects = create_wells_and_implants_fills(decoder_inverter,
                                                wordline_logic, layers=fill_layers,
                                                purposes=fill_purposes)
        x_offset = self.row_decoder_inst.lx() + self.row_decoder.inv_inst[-1].rx()
        width = (self.right_bank_inst.lx() + self.bank.wordline_driver_inst.lx() +
                 self.bank.wordline_driver.buffer_insts[0].lx()) - x_offset
        bitcell_height = self.bitcell.height
        mod_height = wordline_logic.height

        bitcell_rows_per_driver = round(wordline_logic.height / bitcell_height)

        for row in range(0, self.num_rows, bitcell_rows_per_driver):
            y_base = (self.bank.bitcell_array_inst.by() + self.bank_inst.by() +
                      self.row_decoder.bitcell_offsets[row])
            for layer, rect_bottom, rect_top, left_rect, right_rect in rects:
                if ((left_rect.height >= mod_height or right_rect.height >= mod_height) and
                        layer in [PIMP, NIMP]):
                    # prevent overlap between NIMP and PIMP spanning entire logic
                    continue
                if right_rect.uy() > mod_height or left_rect.uy() > mod_height:
                    rect_top = max(right_rect.uy(), left_rect.uy())
                if right_rect.by() < 0 or left_rect.by() < 0:
                    rect_bottom = min(right_rect.by(), left_rect.by())
                if layer in [NIMP, PWELL]:
                    # prevent space from pimplant to nimplant or PWELL to NWELL
                    rect_top = max(left_rect.uy(), right_rect.uy())
                # cover align with bitcell nwell
                if row % (2 * bitcell_rows_per_driver) == 0:
                    y_offset = y_base + (mod_height - rect_top)
                else:
                    y_offset = y_base + rect_bottom
                self.add_rect(layer, offset=vector(x_offset, y_offset), width=width,
                              height=rect_top - rect_bottom)
        # join wells from row decoder to left bank
        if self.num_banks == 1:
            return

        for row in range(0, self.num_rows + 1, bitcell_rows_per_driver):
            if row % (2 * bitcell_rows_per_driver) == 0:
                well = "nwell"
            else:
                well = "pwell"
            well_height = getattr(self.row_decoder, f"contact_{well}_height", None)
            if well_height:
                driver_inst = self.bank_insts[-1].mod.wordline_driver_inst
                right_x = self.row_decoder.contact_mid_x + self.row_decoder_inst.lx()
                buffer_x = driver_inst.mod.buffer_insts[0].lx() + well_height  # extra well_height
                start_x = (self.bank_insts[1].rx() -
                           self.bank_insts[-1].mod.wordline_driver_inst.lx() - buffer_x)
                if row == self.num_rows:
                    y_base = self.row_decoder.bitcell_offsets[row - 1] + bitcell_height
                else:
                    y_base = self.row_decoder.bitcell_offsets[row]

                y_offset = self.bank.bitcell_array_inst.by() + y_base - 0.5 * well_height
                self.add_rect(well, vector(start_x, y_offset),
                              width=right_x - start_x,
                              height=well_height)

    def add_lvs_correspondence_points(self):
        pass

    def add_cross_contact_center(self, cont, offset, rotate=False,
                                 rail_width=None, fill=True):
        cont_inst = super().add_cross_contact_center(cont, offset, rotate)
        if fill:
            self.add_cross_contact_center_fill(cont, offset, rotate, rail_width)
        return cont_inst


if TYPE_CHECKING:
    baseline_ = BaselineSram
else:
    class baseline_:
        pass
