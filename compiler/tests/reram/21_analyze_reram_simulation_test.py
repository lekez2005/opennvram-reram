#!/usr/bin/env python3

from reram_test_base import ReRamTestBase
from sim_analyzer_test import SimAnalyzerTest
from simulator_base import SimulatorBase


class AnalyzeReramSimulationTest(SimAnalyzerTest, SimulatorBase, ReRamTestBase):
    sim_dir_suffix = "reram"
    RERAM_MODE = "reram"
    valid_modes = [RERAM_MODE]

    def setUp(self):
        super().setUp()
        self.update_global_opts()
        from globals import OPTS
        mean_thickness = 0.5 * (OPTS.min_filament_thickness + OPTS.max_filament_thickness)
        self.analyzer.address_data_threshold = mean_thickness

    def get_read_negation(self):
        return True

    def test_analysis(self):
        self.analyze()


if __name__ == "__main__":
    AnalyzeReramSimulationTest.parse_options()
    AnalyzeReramSimulationTest.run_tests(__name__)
