#!/usr/bin/env python3
"""
Run a delay test on an sram using ngspice
"""
import os
from unittest import skipIf

from globals import OPTS
from testutils import OpenRamTest

OPTS.spice_name = "ngspice"
OPTS.analytical_delay = False
OpenRamTest.initialize_tests()

import debug


class TimingSramTest(OpenRamTest):

    @skipIf(not OPTS.spice_exe, "ngspice not found")
    def runTest(self):
        from characterizer import SpiceCharacterizer
        import tech
        import sram

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

        if OPTS.tech_name == "freepdk45":
            golden_data = {'leakage_power': 0.0007348262,
                           'delay_lh': [0.05799613],
                           'read0_power': [0.0384102],
                           'read1_power': [0.03279848],
                           'write1_power': [0.03693655],
                           'write0_power': [0.02717752],
                           'slew_hl': [0.03607912],
                           'min_period': 0.742,
                           'delay_hl': [0.3929995],
                           'slew_lh': [0.02160862]}
        elif OPTS.tech_name == "scn3me_subm":
            golden_data = {'leakage_power': 0.00142014,
                           'delay_lh': [0.8018421],
                           'read0_power': [11.44908],
                           'read1_power': [11.416549999999999],
                           'write1_power': [11.718020000000001],
                           'write0_power': [8.250219],
                           'slew_hl': [0.8273725],
                           'min_period': 2.734,
                           'delay_hl': [1.085861],
                           'slew_lh': [0.5730144]}
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
