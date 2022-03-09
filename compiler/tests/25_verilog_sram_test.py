#!/usr/bin/env python3
"""
Check the  .v file for an SRAM
"""
import os

import debug
from globals import OPTS
from testutils import OpenRamTest


class VerilogTest(OpenRamTest):

    def runTest(self):
        import sram

        debug.info(1, "Testing Verilog for sample 2 bit, 16 words SRAM with 1 bank")
        s = sram.sram(word_size=2,
                      num_words=OPTS.num_words,
                      num_banks=OPTS.num_banks,
                      name="sram_2_16_1_{0}".format(OPTS.tech_name))

        vfile = s.name + ".v"
        vname = os.path.join(OPTS.openram_temp, vfile)
        s.verilog_write(vname)

        # let's diff the result with a golden model
        golden = os.path.join(os.path.dirname(os.path.realpath(__file__)), "golden", vfile)

        if not os.path.exists(golden):
            debug.warning("{} does not exist so comparison cannot be made".format(golden))
        else:
            self.isdiff(vname, golden)

        os.system("rm {0}".format(vname))


OpenRamTest.run_tests(__name__)
