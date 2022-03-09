#!/usr/bin/env python3
"""
Run a regression test on various srams
"""
import os
from unittest import skipIf

import debug
from globals import OPTS
from testutils import OpenRamTest

OPTS.spice_name = "spectre"
OPTS.analytical_delay = False
OpenRamTest.initialize_tests()

import tech
from characterizer import SpiceCharacterizer


@skipIf(not OPTS.spice_exe, "{} not available".format(OPTS.spice_name))
class SramFuncTest(OpenRamTest):

    def runTest(self):
        import sram

        debug.info(1, "Testing timing for sample 1bit, 16words SRAM with 1 bank")
        s = sram.sram(word_size=1,
                      num_words=16,
                      num_banks=1,
                      name="sram_func_test")

        tempspice = os.path.join(OPTS.openram_temp, "temp.sp")
        s.sp_write(tempspice)

        probe_address = "1" * s.addr_size
        probe_data = s.word_size - 1
        debug.info(1, "Probe address {0} probe data {1}".format(probe_address, probe_data))

        corner = (OPTS.process_corners[0], OPTS.supply_voltages[0], OPTS.temperatures[0])
        d = SpiceCharacterizer(s, tempspice, corner)
        d.set_probe(probe_address, probe_data)

        # This will exit if it doesn't find a feasible period
        d.load = tech.spice["msflop_in_cap"] * 4
        d.slew = tech.spice["rise_time"] * 2
        d.find_feasible_period()


OpenRamTest.run_tests(__name__)
