#!/usr/bin/env python3

import os
import sys
from types import SimpleNamespace

reram_dir = os.path.abspath(os.path.join(os.environ.get("OPENRAM_HOME"), "tests", "reram"))
sys.path.insert(0, reram_dir)

from reram_test_base import ReRamTestBase
from simulator_base import SimulatorBase


def bind_self(self, method_name, new_method):
    func_type = type(getattr(self, method_name))
    setattr(self, method_name, func_type(new_method, self))


def noop(*args, **kwargs):
    pass


class CaravelSimulationTest(SimulatorBase, ReRamTestBase):
    sim_dir_suffix = "caravel"
    RERAM_MODE = "reram"
    valid_modes = [RERAM_MODE]

    def test_simulation(self):
        self.run_simulation()

    def get_netlist_gen_class(self):
        from globals import OPTS
        from modules.reram.reram_spice_characterizer import ReramSpiceCharacterizer
        from modules.reram.reram_spice_characterizer import ReramProbe
        from modules.reram.reram_spice_dut import ReramSpiceDut
        from base.spice_parser import SpiceParser

        test_self = self

        class DummyProbe(ReramProbe):

            def probe_bank(self, bank):
                self.probe_bank_currents(bank)
                self.probe_bitlines(bank)
                self.set_clk_probe(bank)

            def probe_address(self, address, pin_name="q"):
                pass

            def probe_address_currents(self, address):
                pass

            def set_clk_probe(self, bank):
                self.clk_probes[bank] = "clk"

        class CaravelDut(ReramSpiceDut):
            def instantiate_sram(self, sram):
                self.caravel_wrapper = caravel_wrapper = test_self.caravel_wrapper
                parser = SpiceParser(caravel_wrapper.get_lvs_spice_file())
                self.caravel_pins = parser.get_pins(caravel_wrapper.name)
                nets = " ".join(self.caravel_pins)

                self.sf.write(f"Xsram1 {nets} {caravel_wrapper.name}\n")
                self.map_caravel_nets()
                self.generate_constant_voltages()

            def generate_constant_voltages(self):
                import caravel_config
                from pin_assignments_mixin import VDD_ESD
                super().generate_constant_voltages()
                # bank_sels
                selected_index = caravel_config.simulation_sel_index
                for bank_index in range(4):
                    if bank_index == selected_index:
                        value = 0
                    else:
                        value = self.voltage
                    net = f"bank_sel_b[{bank_index}]"
                    self.gen_constant(net, value)

                self.gen_constant("mask_others", caravel_config.simulation_other_mask *
                                  self.voltage)
                self.gen_constant("data_others", caravel_config.simulation_other_data *
                                  self.voltage)

                self.gen_constant(VDD_ESD, caravel_config.simulation_esd_voltage)

            def map_caravel_nets(self):
                caravel_wrapper = self.caravel_wrapper
                pin_map = caravel_wrapper.sram_to_wrapper_conns
                for reram_wrapper_pin in caravel_wrapper.sram.pins:
                    if reram_wrapper_pin not in pin_map:
                        continue
                    caravel_wrapper_pin = pin_map[reram_wrapper_pin]
                    if reram_wrapper_pin.startswith("addr["):
                        reram_wrapper_pin = reram_wrapper_pin.replace("addr[", "A[")
                    self.sf.write(f'V{caravel_wrapper_pin}_short {caravel_wrapper_pin} '
                                  f'{reram_wrapper_pin} 0\n')

        class CaravelCharacterizer(ReramSpiceCharacterizer):
            def create_probe(self):
                self.probe = DummyProbe(self.sram, OPTS.pex_spice)

            def create_dut(self):
                stim = CaravelDut(self.sf, self.corner)
                return stim

            def run_pex_and_extract(self):
                pass

            def setup_write_measurements(self, *args, **kwargs):
                pass

            def setup_read_measurements(self, *args, **kwargs):
                pass

            def get_saved_nodes(self):
                self.sf.write(".probe tran v(*)\n")
                self.sf.write(".probe tran i(*)\n")
                self.trim_sp_file = test_self.caravel_wrapper.get_lvs_spice_file()
                OPTS.ic_file = ""
                return []

            def initialize_sram(self, *args, **kwargs):
                pass

        return CaravelCharacterizer

    def create_sram(self):
        from pin_assignments_mixin import PinAssignmentsMixin

        caravel_wrapper, lvs_spice_file = self.create_caravel_shim()
        reram_wrapper = caravel_wrapper.sram
        sram = reram_wrapper.bank_insts[0].mod

        sram.addr_size = sram.bank_addr_size = PinAssignmentsMixin.num_address_pins
        sram.num_words = sram.num_rows = int(2 ** sram.addr_size)
        sram.word_size = sram.num_cols = PinAssignmentsMixin.word_size
        sram.words_per_row = sram.num_banks = 1
        sram.bank_insts = [None]

        bank = SimpleNamespace(has_mask_in=True, num_rows=sram.num_rows,
                               num_cols=sram.num_cols, words_per_row=sram.words_per_row)
        sram.bank = bank

        self.caravel_wrapper = caravel_wrapper

        return sram

    def create_caravel_shim(self):
        from base.design import METAL3, METAL4, METAL5
        from base.design import design
        from caravel.caravel_wrapper import CaravelWrapper
        from caravel.reram_wrapper import ReRamWrapper
        import caravel_config
        from globals import OPTS
        import debug

        """
        Loading SRAM pins from GDS loads very slowly so create a dummy sram gds that
        emulates the original gds. The dummy contains only vdd pins that are returned
        and renamed when a pin is loaded
        """

        class DummySram(design):
            def __init__(self, name):
                design.__init__(self, name)
                self.width = self.height = 2
                self.add_boundary()
                self.gds_file = self.get_dummy_gds_file(name)

                self.add_layout_pin("vdd", METAL3, (0, 0))
                self.add_layout_pin("vdd", METAL4, (0, 0))
                self.add_layout_pin("vdd", METAL5, (0, 0))
                self.add_layout_pin("vdd", "metal6", (0, 0))

            @staticmethod
            def get_dummy_gds_file(name):
                return os.path.join(OPTS.openram_temp, f"dummy_{name}.gds")

        class DummyReRamWrapper(ReRamWrapper):

            def __init__(self):
                design.__init__(self, "sram1")
                debug.info(1, "Creating Sram Wrapper %s", self.name)
                self.create_layout()
                self.add_boundary()

            def connect_indirect_rail_pins(self):
                pass

            def add_srams(self):
                super().add_srams()
                from base.geometry import instance

                def get_pins(self_, pin_name):
                    pins = instance.get_pins(self_, "vdd")
                    for pin in pins:
                        pin.name = pin_name
                    return pins

                def get_pin(self_, pin_name):
                    return self_.get_pins(pin_name)[0]

                for bank_inst in self.bank_insts:
                    bind_self(bank_inst, "get_pins", get_pins)
                    bind_self(bank_inst, "get_pin", get_pin)

        class DummyCaravelWrapper(CaravelWrapper):
            def create_reram_wrapper(self):
                self.sram = dummy_reram_wrapper

            def create_netlist(self):
                copy_layout_pin = self.copy_layout_pin
                self.copy_layout_pin = noop
                super().create_netlist()
                self.copy_layout_pin = copy_layout_pin

            def route_diodes_to_power(self):
                pass

            def flatten_diodes(self):
                pass

            def route_enables_to_grid(self):
                pass

            def add_tech_layers(self):
                pass

            def write_to_gds(self):
                pass

            def write_to_spice(self):
                pass

        for config in caravel_config.sram_configs:
            dummy_sram = DummySram(config.module_name)
            dummy_sram.gds_write(dummy_sram.gds_file)

            def new_get_gds_file(self_):
                return DummySram.get_dummy_gds_file(self_.module_name)

            bind_self(config, "get_gds_file", new_get_gds_file)

        OPTS.add_internal_grid = False
        dummy_reram_wrapper = DummyReRamWrapper()
        caravel_wrapper = DummyCaravelWrapper()
        lvs_spice_file = caravel_wrapper.get_lvs_spice_file()
        return caravel_wrapper, lvs_spice_file

    def setUp(self):
        super().setUp()
        self.update_global_opts()


if __name__ == "__main__":
    CaravelSimulationTest.parse_options()
    CaravelSimulationTest.run_tests(__name__)
