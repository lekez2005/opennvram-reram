"""Combine multiple SRAM banks into one"""
import itertools
import math
import os

import debug
import tech
from base import utils
from base.contact import cross_m2m3, cross_m3m4, m2m3, m3m4
from base.design import design, METAL5, METAL2, METAL3, METAL4
from base.geometry import MIRROR_Y_AXIS, NO_MIRROR, MIRROR_X_AXIS, MIRROR_XY
from base.hierarchy_layout import layout as hierarchy_layout
from base.hierarchy_spice import spice as hierarchy_spice, INPUT, OUTPUT, INOUT
from base.pin_layout import pin_layout
from base.utils import pin_rect, round_to_grid as round_
from base.vector import vector
from pin_assignments_mixin import PinAssignmentsMixin
from router_mixin import METAL6

default_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "../../../.."))
base_dir = os.environ.get("CARAVEL_WORKSPACE", default_base_dir)
gds_dir = os.path.join(base_dir, "gds")
xschem_dir = os.path.join(base_dir, "xschem")
verilog_dir = os.path.join(base_dir, "verilog", "rtl")
spice_dir = os.path.join(base_dir, "netgen")

mid_control_pins = ["clk", "sense_trig", "web", "csb"]

module_x_space = 5
module_y_space = 5

rail_width = m3m4.w_1
rail_space = 0.35
rail_pitch = rail_width + rail_space


class SramConfig:
    sram = None

    def __init__(self, word_size, num_rows, words_per_row, num_banks=1):
        self.word_size = word_size
        self.num_rows = num_rows
        self.num_banks = num_banks
        self.words_per_row = words_per_row

        self.num_words = num_banks * words_per_row * num_rows
        self.address_width = int(math.log2(self.num_words))

        banks_str = f"_bank_{num_banks}" * (num_banks > 1)
        words_per_row_str = f"_wpr_{words_per_row}" * (words_per_row > 1)
        self.module_name = f"r_{self.num_rows}_w_{word_size}{words_per_row_str}{banks_str}"

    @property
    def gds_file(self):
        return os.path.join(gds_dir, f"{self.module_name}.gds")

    @property
    def spice_file(self):
        return os.path.join(base_dir, "netgen", f"{self.module_name}.spice")


class LoadFromGDS(design):

    def __init__(self, name, gds_file, spice_file=None):
        self.name = name
        self.gds_file = gds_file
        self.sp_file = spice_file

        debug.info(2, "Load %s from %s", self.name, self.gds_file)

        if spice_file is not None:
            hierarchy_spice.__init__(self, self.name)
        hierarchy_layout.__init__(self, self.name)
        self.root_structure = [x for x in self.gds.xyTree if x[0].startswith(self.name)][0]

        (self.width, self.height) = utils.get_libcell_size(gds_file, tech.GDS["unit"],
                                                           tech.layer["boundary"])
        debug.info(2, "Mod %s width = %5.5g height=%5.5g", self.name, self.width, self.height)
        self.pin_map = {}

    def get_pins(self, pin_name):
        pin_name = pin_name.lower()
        if pin_name not in self.pin_map:
            # get pin non-recursively to save time
            pins = []
            gds = self.gds
            label_list = gds.getLabelDBInfo(pin_name, tech.layer_pin_map)
            for label in label_list:
                (label_coordinate, label_layer) = label
                boundaries = gds.getPinInStructure(label_coordinate, label_layer,
                                                   self.root_structure)
                boundary = max(boundaries, key=lambda x: (x[2] - x[0]) * (x[3] - x[1]))
                boundary = [x * self.gds.units[0] for x in boundary]
                rect = pin_rect(boundary)
                pins.append(pin_layout(pin_name, rect, label_layer))

            self.pin_map[pin_name] = pins
        return self.pin_map[pin_name]

    def get_pin(self, text):
        return self.get_pins(text)[0]


sram_configs = [
    SramConfig(word_size=64, num_rows=64, words_per_row=1),
    SramConfig(word_size=32, num_rows=32, words_per_row=1),
    SramConfig(word_size=64, num_rows=64, words_per_row=2),
    SramConfig(word_size=16, num_rows=16, words_per_row=1)
]

# sram_configs = [
#     SramConfig(word_size=8, num_rows=32, words_per_row=1),
#     SramConfig(word_size=8, num_rows=32, words_per_row=1),
#     SramConfig(word_size=8, num_rows=32, words_per_row=1),
#     SramConfig(word_size=8, num_rows=32, words_per_row=1)
# ]

top_left = sram_configs[0]
top_right = sram_configs[1]
bottom_left = sram_configs[2]
bottom_right = sram_configs[3]


class Sram(LoadFromGDS):
    pass


class ReRamWrapper(design):
    def __init__(self):
        design.__init__(self, "sram1")
        debug.info(1, "Creating Sram Wrapper %s", self.name)
        self.create_layout()
        self.generate_spice()
        self.generate_verilog()

    def create_layout(self):
        self.pins_to_mid_rails = []
        self.connection_replacements = [{}, {}, {}, {}]
        self.create_srams()
        self.evaluate_pins()
        self.add_srams()
        self.join_bank_pins()
        self.connect_indirect_rail_pins()
        self.add_power_grid()
        self.create_netlist()
        self.verify_connections()

    def create_netlist(self):
        pins = set()
        for i, bank in enumerate(self.bank_insts):
            connections = bank.mod.pins
            conn_index = self.insts.index(bank)
            replacements = self.connection_replacements[i]
            connections = [replacements.get(x, x) for x in connections]

            pins.update([x for x in connections if not x.startswith("data_out_internal")])

            self.conns[conn_index] = connections
            replacements_sort = sorted([(key, value) for key, value in replacements.items()],
                                       key=lambda x: x[0])
            replacement_str = [f"{key} <==> {value}" for key, value in replacements_sort]
            debug.info(2, "Bank %d, connection replacements: %s", i,
                       ", ".join(replacement_str))
        self.pins = list(sorted(pins))

    def verify_connections(self):
        """Ensure all pins have been connected totop level"""
        unconnected_pins = []
        for i, bank in enumerate(self.bank_insts):
            connections = self.conns[self.insts.index(bank)]
            for net in connections:
                if not net.startswith("data_out_internal[") and net not in self.pin_map:
                    unconnected_pins.append((i, net))
        if unconnected_pins:
            debug.error(f"Unconnected bank pins: %s", -1, str(unconnected_pins))

    def create_srams(self):
        debug.info(1, "Loading SRAM sub-bank modules")
        self.sram_mods = {}
        create_count = 0
        for config in sram_configs:
            if config.module_name in self.sram_mods:
                sram = self.sram_mods[config.module_name]
            else:
                sram = LoadFromGDS(config.module_name, config.gds_file, config.spice_file)
                self.sram_mods[config.module_name] = sram
                create_count += 1
                if create_count > 1:
                    sram.gds.add_suffix_to_structures(f"_n{create_count}")

            sram.word_size = config.word_size
            config.sram = sram
            self.add_mod(sram)
            debug.info(1, "Loaded SRAM sub-bank %s", sram.name)

    def evaluate_pins(self):
        num_rails = PinAssignmentsMixin.num_address_pins + len(mid_control_pins)

        def noop(*args):
            pass

        self.num_data_out = 1 + PinAssignmentsMixin.assign_gpio_pins(noop)

        # 2 from data_others, mask_others, 3x since data_in, mask_in, data_out
        num_rails += 3 * self.num_data_out + 2
        # G S G S G for clk, sense_trig
        num_rails += 3

        self.num_rails = num_rails
        self.y_mid_space = 2 * module_y_space + self.num_rails * rail_pitch - rail_space

        self.m3_fill_width = m2m3.h_2
        _, self.m3_fill_height = self.calculate_min_area_fill(self.m3_fill_width,
                                                              layer=METAL3)

    def add_srams(self):
        debug.info(1, "Adding SRAM sub-banks")
        self.sram_insts = {}

        def get_vdd(mod, layer):
            return [x for x in mod.get_pins("vdd") if x.layer == layer]

        def align_vdd_y(left_mod, right_mod):
            left_vdd = min(get_vdd(left_mod, METAL5), key=lambda x: x.cy())
            right_vdd = min(get_vdd(right_mod, METAL5), key=lambda x: x.cy())
            return left_vdd.cy() - right_vdd.cy()

        def align_vdd_x(top_mod, bottom_mod):
            top_vdd = min(get_vdd(top_mod, METAL6), key=lambda x: x.cx())
            bot_vdd = min(get_vdd(bottom_mod, METAL6), key=lambda x: x.cx())
            return top_vdd.cx() - bot_vdd.cx()

        # evaluate y offsets
        top_left_y = 0
        top_right_y = align_vdd_y(top_left.sram, top_right.sram)

        bottom_y = min(top_left_y, top_right_y) - self.y_mid_space

        bottom_y_shift = align_vdd_y(bottom_left.sram, bottom_right.sram)
        bottom_left_y = bottom_y
        bottom_right_y = bottom_y - bottom_y_shift

        # evaluate x offsets
        top_left_x = top_left.sram.width
        x_shift = align_vdd_x(top_left.sram, bottom_left.sram)
        bottom_left_x = top_left_x - x_shift

        x_offset = max(bottom_left_x, top_left_x) + module_x_space
        x_shift = align_vdd_x(top_right.sram, bottom_right.sram)

        top_right_x = x_offset
        bottom_right_x = x_offset + x_shift

        def add_inst(name, config, x_offset, y_offset, mirror):
            inst = self.add_inst(name, config.sram, vector(x_offset, y_offset),
                                 mirror=mirror)
            self.connect_inst([], check=False)
            return inst

        self.top_left_inst = add_inst("top_left", top_left, top_left_x,
                                      top_left_y, MIRROR_Y_AXIS)
        self.top_right_inst = add_inst("top_right", top_right, top_right_x,
                                       top_right_y, NO_MIRROR)
        self.bottom_left_inst = add_inst("bottom_left", bottom_left, bottom_left_x,
                                         bottom_left_y, MIRROR_XY)
        self.bottom_right_inst = add_inst("bottom_right", bottom_right, bottom_right_x,
                                          bottom_right_y, MIRROR_X_AXIS)
        self.bank_insts = [self.top_left_inst, self.top_right_inst,
                           self.bottom_left_inst, self.bottom_right_inst]
        self.offset_all_coordinates()
        self.width = max(self.bottom_right_inst.rx(), self.top_right_inst.rx())
        self.height = max(self.top_left_inst.uy(), self.top_right_inst.uy())

        bottom_inst_top = max(self.bottom_left_inst.uy(), self.bottom_right_inst.uy())
        self.mid_rail_y = bottom_inst_top + 0.5 * self.y_mid_space
        self.bottom_mid_via_y = bottom_inst_top + 0.5 * module_y_space

        top_inst_bottom = min(self.top_left_inst.by(), self.top_right_inst.by())
        self.top_mid_via_y = top_inst_bottom - 0.5 * module_y_space

    def get_rail_y(self, y_index):
        return self.mid_rail_y + y_index * rail_pitch

    def connect_indirect_rail_pins(self):

        via_y_ext = 0.5 * max(m2m3.h_1, m3m4.h_2)

        m2_pin_names = ["csb", "clk", "web", "sense_trig"]
        m2_rails = []

        # make unique
        all_mid_x = []
        rails = []
        for rail in self.pins_to_mid_rails:
            mid_x = utils.round_to_grid(rail[0].cx())
            if rail[0].name in m2_pin_names:
                m2_rails.append(rail)
            if mid_x in all_mid_x:
                continue
            rails.append(rail)
            all_mid_x.append(mid_x)

        pins_to_mid_rails = list(sorted(rails, key=lambda x: x[0].cx()))

        # group by left, right and move m2 pins to the left or right to prevent m4 space
        m2_rails = list(sorted(m2_rails, key=lambda x: x[0].lx()))
        min_space = 1
        m2_groups = [[m2_rails[0]]]
        for m2_rail in m2_rails[1:]:
            if m2_rail[0].lx() - m2_groups[-1][-1][0].lx() < min_space:
                m2_groups[-1].append(m2_rail)
            else:
                m2_groups.append([m2_rail])

        space = m3m4.h_2 + self.m4_space
        for i, group in enumerate(m2_groups):
            base_x = group[0][0].cx()
            if base_x < min(self.top_right_inst.lx(), self.bottom_right_inst.lx()):
                scale = 1
            else:
                scale = -1
                group = list(reversed(group))
            for j, rail in enumerate(group):
                pin = rail[0]
                mid_y = pin.by() - space * (len(group) - 1 - j)
                mid_x = base_x + scale * (j * space)
                self.add_path(METAL2, [vector(pin.cx(), pin.by() + self.m2_width),
                                       vector(pin.cx(), pin.by()),
                                       vector(pin.cx(), mid_y),
                                       vector(mid_x, mid_y)], width=pin.width())
                rect = self.add_rect_center(METAL2, vector(mid_x, mid_y),
                                            width=pin.width(), height=pin.width())
                rect.layer = pin.layer
                rail[0] = rect

        for index, (pin, y_offset) in enumerate(pins_to_mid_rails):
            if pin.by() > self.mid_rail_y:
                layer = METAL4
                # from pin to intermediate via
                mid_via_y = self.top_mid_via_y - (index % 2) * rail_pitch
                start_y = pin.by()
                height = mid_via_y - start_y - 0.5 * m3m4.h_2
                # intermediate via to middle destination
                dest_rail_width = self.m4_width
                dest_rail_y = mid_via_y + 0.5 * m3m4.h_2
                dest_rail_height = y_offset - 0.5 * m3m4.h_2 - dest_rail_y
            else:
                layer = METAL2
                mid_via_y = self.bottom_mid_via_y + (index % 2) * rail_pitch
                start_y = pin.uy()
                height = mid_via_y - start_y + 0.5 * m2m3.h_1

                dest_rail_width = self.bus_width
                dest_rail_y = mid_via_y - 0.5 * m2m3.h_1
                dest_rail_height = y_offset + 0.5 * m2m3.h_1 - dest_rail_y

            self.add_rect(pin.layer, vector(pin.lx(), start_y), width=pin.rx() - pin.lx(),
                          height=height)
            via_offset = vector(pin.cx(), mid_via_y)
            self.add_cross_contact_center(cross_m2m3, via_offset)
            self.add_cross_contact_center(cross_m3m4, via_offset, rotate=True)
            self.add_rect(layer, vector(pin.cx() - 0.5 * dest_rail_width, dest_rail_y),
                          width=dest_rail_width, height=dest_rail_height)
            via, rotate = (cross_m2m3, False) if layer == METAL2 else (cross_m3m4, True)
            self.add_cross_contact_center(via, vector(pin.cx(), y_offset), rotate=rotate)

    def join_pins(self, y_index=None, pin_name=None, pins=None):
        if y_index is None:
            y_index = self.rail_y_index
        y_offset = self.get_rail_y(y_index)
        if pins is None:
            pins = [x.get_pin(pin_name) for x in self.bank_insts]

        def get_layer_via(layer_):
            if layer_ == METAL2:
                return cross_m2m3, False
            else:
                return cross_m3m4, True

        for pin in pins:
            y_end = self.get_pin_y_edge(pin)

            if y_end < self.mid_rail_y:
                layer = METAL2
                rail_y = y_offset + 0.5 * m2m3.h_1
            else:
                layer = METAL4
                rail_y = y_offset - m3m4.h_2
            if not layer == pin.layer:
                self.pins_to_mid_rails.append([pin, y_offset])
            else:
                layer = pin.layer
                self.add_rect(pin.layer, vector(pin.lx(), rail_y),
                              width=pin.width(),
                              height=y_end - rail_y)
                via, rotate = get_layer_via(layer)
                self.add_cross_contact_center(via, vector(pin.cx(), y_offset), rotate=rotate)
        via_x_ext = 0.5 * max(m2m3.h_2, m3m4.h_1)
        min_x = min(map(lambda x: x.cx(), pins)) - via_x_ext
        max_x = max(map(lambda x: x.cx(), pins)) + via_x_ext
        if pin_name is not None:
            self.add_layout_pin(pin_name, METAL3,
                                vector(min_x, y_offset - 0.5 * rail_width),
                                width=max_x - min_x, height=rail_width)

    def get_pin_y_edge(self, pin):
        if pin.by() > self.mid_rail_y:
            return utils.round_to_grid(pin.by())
        return utils.round_to_grid(pin.uy())

    def join_m4_gnd_pins(self):
        gnd_rail_indices = [-2, 0, 2]
        for bank in self.bank_insts:
            # only select pins that are at least as low as DATA[0]
            data_pin = bank.get_pin("DATA[0]")
            reference_y = self.get_pin_y_edge(data_pin)
            gnd_pins = [pin for pin in bank.get_pins("gnd") if pin.layer == METAL4]
            m4_pins = []
            for pin in gnd_pins:
                y_edge = self.get_pin_y_edge(pin)
                if self.mid_rail_y < y_edge <= reference_y:
                    m4_pins.append(pin)
                elif self.mid_rail_y > y_edge >= reference_y:
                    m4_pins.append(pin)
            for y_index in gnd_rail_indices:
                self.join_pins(y_index, pins=m4_pins)

        for y_index in gnd_rail_indices:
            y_offset = self.get_rail_y(y_index) - 0.5 * rail_width
            self.add_layout_pin("gnd", METAL3, vector(0, y_offset), width=self.width,
                                height=rail_width)

    @staticmethod
    def alternate_bits(bits):
        num_bits = len(bits)
        half_bits = math.floor(num_bits / 2)
        alt_bits = []
        for i in range(half_bits):
            alt_bits.append(bits[i + half_bits])
            alt_bits.append(bits[half_bits - i - 1])
        if num_bits % 2 == 1:
            alt_bits.append(bits[-1])
        return alt_bits

    def join_address_pins(self):
        bits = list(range(PinAssignmentsMixin.num_address_pins))
        alt_bits = self.alternate_bits(bits)
        for bit in alt_bits:
            all_pins = []
            pin_name = f"ADDR[{bit}]"
            for bank in self.bank_insts:
                # debug.pycharm_debug()
                if pin_name.lower() in bank.mod.pins:
                    pin = bank.get_pin(pin_name)
                    all_pins.append(pin)
            self.join_pins(pins=all_pins, pin_name=pin_name)

            self.increment_y_index()

    def join_data_pins(self):
        pin_names = []
        num_data = self.num_data_out - 1

        assigned_bits = []
        un_assigned_bits = []

        for bank in self.bank_insts:
            word_size = bank.mod.word_size
            bit_spacing = max(1, word_size / num_data)
            debug.info(2, "Bit spacing for %s is %.3g", bank.mod.name, bit_spacing)
            tentative_bits = [math.floor((i + 1) * bit_spacing) for i in range(num_data - 1)]
            tentative_bits.append(word_size - 1)
            tentative_bits.append(0)

            tentative_bits = list(sorted(set(tentative_bits)))

            assigned_bits.append(tentative_bits)
            un_assigned_bits.append([x for x in range(word_size)
                                     if x not in tentative_bits])

        for i in range(num_data + 1):
            pin_names.append(("mask", i))
            pin_names.append(("data_out", i))
            pin_names.append(("data", i))

        other_pins = ["data_others", "mask_others", "data_out_others"]
        pin_names.extend([(x, None) for x in other_pins])

        alt_pin_names = self.alternate_bits(pin_names)
        for pin_name, wrapper_bit in alt_pin_names:
            pins = []
            if pin_name in other_pins:
                pins = []
                bank_pin_name = pin_name.replace("_others", "")
                for bank_index, bank in enumerate(self.bank_insts):
                    for bank_bit in un_assigned_bits[bank_index]:
                        bank_pin = bank.get_pin(f"{bank_pin_name}[{bank_bit}]")
                        if pin_name == "data_out_others":
                            replacement = f"data_out_internal[{bank_bit}]"
                        else:
                            replacement = pin_name
                        self.connection_replacements[bank_index][bank_pin.name] = replacement
                        pins.append(bank_pin)
            else:
                wrapper_name = f"{pin_name}[{wrapper_bit}]"
                for bank_index, bank in enumerate(self.bank_insts):
                    if wrapper_bit < len(assigned_bits[bank_index]):
                        bank_bit = assigned_bits[bank_index][wrapper_bit]
                        bank_pin = bank.get_pin(f"{pin_name}[{bank_bit}]")
                        self.connection_replacements[bank_index][bank_pin.name] = wrapper_name
                        pins.append(bank_pin)
                pin_name = wrapper_name
            self.join_pins(pin_name=pin_name, pins=pins)
            self.increment_y_index()

    def increment_y_index(self):
        y_index = self.rail_y_index
        if y_index >= 0:
            self.rail_y_index = - y_index
        else:
            self.rail_y_index = -y_index + 1

    def join_bank_pins(self):
        debug.info(1, "Joining sub-bank pins")
        # control rails
        y_indices = [-3, -1, 1, 3]
        pin_names = ["csb", "clk", "sense_trig", "web"]
        for pin_name, y_index in zip(pin_names, y_indices):
            self.join_pins(y_index, pin_name=pin_name)

        self.join_m4_gnd_pins()
        self.rail_y_index = 4
        self.join_address_pins()
        self.join_data_pins()
        for bank in self.bank_insts:
            for pin_name in ["vref", "vclamp", "vclampp"]:
                self.copy_layout_pin(bank, pin_name)

    def add_power_grid(self):
        debug.info(1, "Joining sub-banks power grid")
        # Note this only works when there is only one "vdd_wordline"
        for pin_name in ["vdd_write", "vdd_wordline"]:
            for bank in self.bank_insts:
                self.copy_layout_pin(bank, pin_name)
        for pin_name in ["vdd", "gnd"]:
            m6_pin_x = set()
            m5_pin_y = set()

            m5_sample = None
            m6_sample = None

            for bank in self.bank_insts:
                pins = bank.get_pins(pin_name)

                m5_pins = [pin for pin in pins if pin.layer == METAL5]
                m6_pins = [pin for pin in pins if pin.layer == METAL6]
                if m5_pins:
                    m5_sample = m5_pins[0]
                if m6_pins:
                    m6_sample = m6_pins[0]

                m5_pin_y.update([round_(pin.cy()) for pin in m5_pins])
                m6_pin_x.update([round_(pin.cx()) for pin in m6_pins])

            for y_offset in m5_pin_y:
                self.add_layout_pin(pin_name, METAL5,
                                    vector(0, y_offset - 0.5 * m5_sample.height()),
                                    width=self.width, height=m5_sample.height())

            for x_offset in m6_pin_x:
                self.add_layout_pin(pin_name, METAL6,
                                    vector(x_offset - 0.5 * m6_sample.width(), 0),
                                    width=m6_sample.width(), height=self.height)

    def generate_spice(self):
        file_name = os.path.join(spice_dir, f"{self.name}.spice")
        self.spice_file_name = file_name
        debug.info(1, "Reram spice file is %s", file_name)
        self.sp_write(file_name)

    def get_pin_type(self, pin_name):
        inputs = ["sense_trig", "vref", "vclamp", "vclampp", "csb", "web", "clk",
                  "data_others", "mask_others"]

        prefixes = {
            "data[": (INPUT, self.num_data_out),
            "mask[": (INPUT, self.num_data_out),
            "data_out[": (OUTPUT, self.num_data_out),
            "data_out_internal[": (OUTPUT, self.num_data_out),
            "addr[": (INPUT, PinAssignmentsMixin.num_address_pins)
        }

        pin_type = None

        pin_name = pin_name.lower()
        if pin_name in inputs:
            pin_type = INPUT
        elif pin_name in ["vdd", "gnd", "vdd_write", "vdd_wordline"]:
            pin_type = INOUT
        else:
            for prefix in prefixes:
                if pin_name.startswith(prefix):
                    pin_type = prefixes[prefix][0]
                    width = prefixes[prefix][1]
                    pin_name = f"[{width - 1}:0] {prefix[:-1]}"

        if not pin_type:
            assert False, f"Pin type for {pin_name} not specified"
        return pin_type, pin_name

    def generate_verilog(self):
        file_name = os.path.join(verilog_dir, f"{self.name}.v")
        debug.info(1, "Reram Verilog file is %s", file_name)
        with open(file_name, "w") as f:
            f.write(f"// Generated from OpenRAM\n\n")
            f.write(f"module reram_{self.name} (\n")

            processed_keys = set()
            for pin in self.pins:
                pin_type, pin_name = self.get_pin_type(pin)
                if pin_name in processed_keys:
                    continue
                processed_keys.add(pin_name)
                f.write(f"    {pin_type} {pin_name},\n")

            f.write(f");\n")
