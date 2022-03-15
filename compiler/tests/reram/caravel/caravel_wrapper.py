"""user_analog_project_wrapper = reram_wrapper + user_analog_project_wrapper_empty"""
import os

import numpy as np

import debug
import tech
from base.design import design
from base.spice_parser import SpiceParser
from base.vector import vector
from globals import OPTS
from pin_assignments_mixin import PinAssignmentsMixin
from caravel_esd_mixin import CaravelEsdMixin
from caravel_config import gds_dir, spice_dir, sram_configs, xschem_dir
from reram_wrapper import LoadFromGDS, ReRamWrapper

from router_mixin import RouterMixin

caravel_root_gds = os.path.abspath(os.path.join(gds_dir, "..", "caravel", "gds"))

wrapper_name = "user_analog_project_wrapper"
empty_wrapper_name = "user_analog_project_wrapper_empty"


class EmptyCaravel(LoadFromGDS):
    def __init__(self, name, gds_file, spice_file=None):
        super().__init__(name, gds_file, spice_file)

        sample_netlist = os.path.join(xschem_dir, f"{wrapper_name}.spice")
        spice_parser = SpiceParser(sample_netlist)
        self.pins = spice_parser.get_pins(wrapper_name)
        self.conns = []

    def sp_write_file(self, sp, usedMODS):
        pins_str = " ".join(self.pins)
        sp.write(f"\n.SUBCKT {self.name} {pins_str}\n")
        sp.write(f".ENDS {self.name}\n")


class CaravelWrapper(PinAssignmentsMixin, RouterMixin, CaravelEsdMixin, design):
    def __init__(self):
        design.__init__(self, wrapper_name)
        self.sram_to_wrapper_conns = {}
        self.wrapper_to_wrapper_conns = {}
        self.analyze_sizes()
        self.create_layout()

    @staticmethod
    def analyze_sizes():
        min_word_size = min(map(lambda x: x.word_size, sram_configs))
        max_num_words = max(map(lambda x: x.num_words, sram_configs))
        num_address_pins = int(np.log2(max_num_words))
        PinAssignmentsMixin.num_address_pins = num_address_pins
        debug.info(1, "Number of address pins is %d", num_address_pins)
        PinAssignmentsMixin.word_size = min_word_size
        debug.info(1, "Min Word size = %d", min_word_size)

    def create_layout(self):
        self.create_empty_wrapper()
        self.sram = ReRamWrapper()
        self.create_diode()
        self.assign_pins()
        self.add_modules()
        self.route_layout()
        self.create_netlist()
        tech.add_tech_layers(self)
        self.flatten_diodes()
        self.write_to_gds()
        self.write_to_spice()

    def create_empty_wrapper(self):
        gds_file = os.path.join(OPTS.openram_tech, "gds_lib", f"{empty_wrapper_name}.gds")
        self.empty_wrapper = EmptyCaravel(empty_wrapper_name, gds_file)
        self.add_mod(self.empty_wrapper)
        debug.info(1, "Loaded caravel wrapper gds Width=%4.4g Height=%4.4g",
                   self.empty_wrapper.width, self.empty_wrapper.height)

    def add_modules(self):
        self.width = self.empty_wrapper.width
        self.height = self.empty_wrapper.height
        self.add_boundary()

        self.wrapper_inst = self.add_inst(self.empty_wrapper.name, self.empty_wrapper,
                                          vector(0, 0))
        self.connect_inst(self.empty_wrapper.pins, check=False)

        x_offset = 0.5 * self.width - 0.5 * self.sram.width
        y_offset = 0.5 * self.height - 0.5 * self.sram.height

        self.sram_inst = self.add_inst(self.sram.name, self.sram,
                                       vector(x_offset, y_offset))

        clk_pin = self.sram_inst.get_pin("clk")
        self.mid_y = clk_pin.cy()
        self.mid_x = clk_pin.cx()

        self.connect_inst([], check=False)

    def write_to_gds(self):
        gds_file = os.path.join(gds_dir, f"{wrapper_name}.gds")
        self.gds_file_name = gds_file
        debug.info(1, "Exported to gds %s", gds_file)
        self.gds_write(gds_file)

        self.lvs_gds_file = os.path.join(gds_dir, f"{wrapper_name}.lvs.gds")
        for pin_name in self.wrapper_to_wrapper_conns:
            if pin_name in self.pin_map:
                del self.pin_map[pin_name]
        self.visited = False
        self.gds_file = ""
        self.gds_read()
        self.gds_write(self.lvs_gds_file)

    def write_to_spice(self):
        self.lvs_spice_file = os.path.join(spice_dir, f"{wrapper_name}.lvs.spice")
        with open(self.lvs_spice_file, "w") as f:
            f.write(self.lvs_spice_content)

        spice_file = os.path.join(spice_dir, f"{wrapper_name}.spice")
        debug.info(1, "Exported to spice %s", spice_file)
        self.sp_write(spice_file)
