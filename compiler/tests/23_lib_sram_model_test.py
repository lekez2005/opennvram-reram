#!/usr/bin/env python3
"""
Check the .lib file for an SRAM
"""
import os
import re

import debug
from globals import OPTS
from testutils import OpenRamTest


class LibTest(OpenRamTest):

    def runTest(self):
        import sram
        from characterizer import lib

        debug.info(1, "Testing timing for sample 2 bit, 16 words SRAM with 1 bank")
        s = sram.sram(word_size=2,
                      num_words=16,
                      num_banks=1,
                      name="sram_2_16_1_{0}".format(OPTS.tech_name))

        tempspice = os.path.join(OPTS.openram_temp, "temp.sp")
        s.sp_write(tempspice)

        lib(out_dir=OPTS.openram_temp, sram=s, sp_file=tempspice, use_model=True)

        # get all of the .lib files generated
        files = os.listdir(OPTS.openram_temp)
        nametest = re.compile("\.lib$", re.IGNORECASE)
        lib_files = list(filter(nametest.search, files))

        # and compare them with the golden model
        for filename in lib_files:
            newname = filename.replace(".lib", "_analytical.lib")
            libname = os.path.join(OPTS.openram_temp, filename)
            dirname = os.path.dirname(os.path.realpath(__file__))
            golden = os.path.join(dirname, "golden", newname)
            if not os.path.exists(golden):
                debug.warning("{} does not exist so comparison cannot be made".format(golden))
            else:
                self.isapproxdiff(libname, golden, 0.15)
            

OpenRamTest.run_tests(__name__)
