#!/usr/bin/env python3
"""
Run a regression test on various srams
"""
from unittest import skipIf

from testutils import OpenRamTest
from globals import OPTS

OPTS.spice_name = "ngspice"
OPTS.analytical_delay = False
OpenRamTest.initialize_tests()


class TimingSetupTest(OpenRamTest):

    @skipIf(not OPTS.spice_exe, "ngspice not found")
    def runTest(self):
        from characterizer import setup_hold
        import tech
        slews = [tech.spice["rise_time"] * 2]

        corner = (OPTS.process_corners[0], OPTS.supply_voltages[0], OPTS.temperatures[0])
        sh = setup_hold(corner)
        data = sh.analyze(slews, slews)
        golden_data = None
        if OPTS.tech_name == "freepdk45":
            golden_data = {'setup_times_LH': [0.01464844],
                           'hold_times_LH': [0.0024414059999999997],
                           'hold_times_HL': [-0.003662109],
                           'setup_times_HL': [0.008544922]}
        elif OPTS.tech_name == "scn3me_subm":
            golden_data = {'setup_times_LH': [0.07568359],
                           'hold_times_LH': [0.008544922],
                           'hold_times_HL': [-0.05859374999999999],
                           'setup_times_HL': [0.03295898]}
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
