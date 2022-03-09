#!/usr/bin/env python3
"""
Run a regression test on various srams
"""
from unittest import skipIf

from globals import OPTS
from testutils import OpenRamTest

OPTS.spice_name = "hspice"
OPTS.analytical_delay = False
OpenRamTest.initialize_tests()


class TimingSetupTest(OpenRamTest):

    @skipIf(not OPTS.spice_exe, "hspice not found")
    def runTest(self):

        from characterizer import setup_hold
        import tech
        slews = [tech.spice["rise_time"] * 2]

        corner = (OPTS.process_corners[0], OPTS.supply_voltages[0], OPTS.temperatures[0])
        sh = setup_hold(corner)
        data = sh.analyze(slews, slews)

        if OPTS.tech_name == "freepdk45":
            golden_data = {'setup_times_LH': [0.014648399999999999],
                           'hold_times_LH': [0.0024414],
                           'hold_times_HL': [-0.0036620999999999997],
                           'setup_times_HL': [0.0085449]}
        elif OPTS.tech_name == "scn3me_subm":
            golden_data = {'setup_times_LH': [0.08178709999999999],
                           'hold_times_LH': [0.0024414],
                           'hold_times_HL': [-0.0646973],
                           'setup_times_HL': [0.0390625]}
        else:
            self.assertTrue(False)  # other techs fail

        # Check if no too many or too few results
        self.assertTrue(len(data.keys()) == len(golden_data.keys()))
        # Check each result
        for k in data.keys():
            if type(data[k]) == list:
                for i in range(len(data[k])):
                    self.isclose(data[k][i], golden_data[k][i], 0.15)
            else:
                self.isclose(data[k], golden_data[k], 0.15)


OpenRamTest.run_tests(__name__)
