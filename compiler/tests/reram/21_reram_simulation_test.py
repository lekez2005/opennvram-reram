#!/usr/bin/env python3

from reram_test_base import ReRamTestBase
from simulator_base import SimulatorBase


class ReramSimulationTest(SimulatorBase, ReRamTestBase):
    sim_dir_suffix = "reram"
    RERAM_MODE = "reram"
    valid_modes = [RERAM_MODE]
    def setUp(self):
        super().setUp()
        self.update_global_opts()

    def get_netlist_gen_class(self):
        from modules.reram.reram_spice_characterizer import ReramSpiceCharacterizer
        return ReramSpiceCharacterizer

    def test_simulation(self):
        self.run_simulation()


if __name__ == "__main__":
    ReramSimulationTest.parse_options()
    ReramSimulationTest.run_tests(__name__)
