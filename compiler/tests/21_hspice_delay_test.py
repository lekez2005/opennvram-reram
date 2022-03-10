#!/usr/bin/env python3
"""
Run a regression test on various srams
"""
import os
from unittest import skipIf

from globals import OPTS
from testutils import OpenRamTest

OPTS.spice_name = "hspice"
OPTS.analytical_delay = False
OpenRamTest.initialize_tests()

import debug


class TimingSramTest(OpenRamTest):

    @skipIf(not OPTS.spice_exe, "hspice not found")
    def runTest(self):
        OPTS.spice_name = "hspice"
        OPTS.analytical_delay = False

        # This is a hack to reload the characterizer __init__ with the spice version
        from characterizer import SpiceCharacterizer

        import sram
        import tech
        debug.info(1, "Testing timing for sample 1bit, 16words SRAM with 1 bank")
        s = sram.sram(word_size=OPTS.word_size,
                      num_words=OPTS.num_words,
                      num_banks=OPTS.num_banks,
                      name="sram1")

        tempspice = os.path.join(OPTS.openram_temp, "temp.sp")
        s.sp_write(tempspice)

        probe_address = "1" * s.addr_size
        probe_data = s.word_size - 1
        debug.info(1, "Probe address {0} probe data {1}".format(probe_address, probe_data))

        corner = (OPTS.process_corners[0], OPTS.supply_voltages[0], OPTS.temperatures[0])
        d = SpiceCharacterizer(s, tempspice, corner)
        loads = [tech.spice["msflop_in_cap"] * 4]
        slews = [tech.spice["rise_time"] * 2]
        data = d.analyze(probe_address, probe_data, slews, loads)

        golden_data = None
        if OPTS.tech_name == "freepdk45":
            golden_data = {'leakage_power': 0.0006964536000000001,
                           'delay_lh': [0.0573055],
                           'read0_power': [0.0337812],
                           'read1_power': [0.032946500000000004],
                           'write1_power': [0.0361529],
                           'write0_power': [0.026179099999999997],
                           'slew_hl': [0.0285185],
                           'min_period': 0.205,
                           'delay_hl': [0.070554],
                           'slew_lh': [0.0190073]}
        elif OPTS.tech_name == "scn3me_subm":
            golden_data = {'leakage_power': 0.0004004581,
                           'delay_lh': [0.6538954],
                           'read0_power': [9.7622],
                           'read1_power': [9.589],
                           'write1_power': [10.2578],
                           'write0_power': [6.928400000000001],
                           'slew_hl': [0.8321625],
                           'min_period': 2.344,
                           'delay_hl': [0.9019090999999999],
                           'slew_lh': [0.5896232]}
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
