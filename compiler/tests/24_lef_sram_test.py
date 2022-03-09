#!/usr/bin/env python3
"""
Check the LEF file for an SRMA
"""

import os

import debug
from globals import OPTS
from testutils import OpenRamTest


class LefTest(OpenRamTest):

    def runTest(self):
        import sram

        debug.info(1, "Testing LEF for sample 2 bit, 16 words SRAM with 1 bank")
        s = sram.sram(word_size=2,
                      num_words=OPTS.num_words,
                      num_banks=OPTS.num_banks,
                      name="sram_2_16_1_{0}".format(OPTS.tech_name))

        OPTS.check_lvsdrc = True

        gdsfile = s.name + ".gds"
        leffile = s.name + ".lef"
        gdsname = os.path.join(OPTS.openram_temp, gdsfile)
        lefname = os.path.join(OPTS.openram_temp, leffile)
        s.gds_write(gdsname)
        s.lef_write(lefname)

        # let's diff the result with a golden model
        golden = os.path.join(os.path.dirname(os.path.realpath(__file__)), "golden", leffile)
        if not os.path.exists(golden):
            debug.warning("{} does not exist so comparison cannot be made".format(golden))
        else:
            self.isdiff(lefname, golden)

        os.system("rm {0}".format(gdsname))
        os.system("rm {0}".format(lefname))


OpenRamTest.run_tests(__name__)
