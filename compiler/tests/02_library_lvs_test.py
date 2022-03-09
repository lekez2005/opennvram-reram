#!/usr/bin/env python3
"Run a regression test the library cells for LVS"

import os
import re

from testutils import OpenRamTest
import debug
import globals
from globals import OPTS


class library_lvs_test(OpenRamTest):

    def runTest(self):
        import verify
        (gds_dir, sp_dir, allnames) = setup_files()
        lvs_errors = 0
        debug.info(1, "Performing LVS on: " + ", ".join(allnames))

        for f in allnames:
            gds_name = os.path.join(gds_dir, "{0}.gds".format(f))
            sp_name = os.path.join(sp_dir, "{0}.sp".format(f))
            if not os.path.isfile(gds_name):
                lvs_errors += 1
                debug.error("Missing GDS file {}".format(gds_name))
            if not os.path.isfile(sp_name):
                lvs_errors += 1
                debug.error("Missing SPICE file {}".format(gds_name))
            lvs_errors += verify.run_lvs(f, gds_name, sp_name)
            self.assertEqual(lvs_errors, 0)
        # fail if the error count is not zero
        self.assertEqual(lvs_errors, 0)
        globals.end_openram()

def setup_files():
    gds_dir = os.path.join(OPTS.openram_tech, "gds_lib")
    sp_dir = os.path.join(OPTS.openram_tech, "sp_lib")
    nametest = re.compile(r"(?P<mod>\S+)\.(?:gds|sp)", re.IGNORECASE)
    files = os.listdir(sp_dir)
    sp_names = nametest.findall("\n".join(files))
    # only use sp files since some gds files may be filler cells without netlists
    return (gds_dir, sp_dir, sp_names)


OpenRamTest.run_tests(__name__)
