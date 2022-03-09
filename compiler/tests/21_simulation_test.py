#!/usr/bin/env python3
"""
Run a delay test on sram using spectre/hspice
"""

from simulator_base import SimulatorBase
from testutils import OpenRamTest


class SimulationTest(OpenRamTest, SimulatorBase):

    def setUp(self):
        super().setUp()
        self.update_global_opts()

    def get_netlist_gen_class(self):
        from characterizer import SpiceCharacterizer
        return SpiceCharacterizer

    def test_simulation(self):
        self.run_simulation()


SimulationTest.parse_options()
SimulationTest.run_tests(__name__)
