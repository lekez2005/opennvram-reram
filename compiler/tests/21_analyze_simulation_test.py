#!/usr/bin/env python3

from testutils import OpenRamTest

from sim_analyzer_test import SimAnalyzerTest


class AnalyzeSimulation(SimAnalyzerTest, OpenRamTest):

    def test_analysis(self):
        self.analyze()


if __name__ == "__main__":
    AnalyzeSimulation.parse_options()
    AnalyzeSimulation.run_tests(__name__)
