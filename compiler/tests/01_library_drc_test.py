#!/usr/bin/env python3
"Run a regression test the library cells for DRC"

import os
import re

from testutils import OpenRamTest
import debug
import globals
from globals import OPTS


class library_drc_test(OpenRamTest):

    def runTest(self):
        import verify

        (gds_dir, gds_files) = setup_files()
        drc_errors = 0
        debug.info(1, "\nPerforming DRC on: " + ", ".join(gds_files))
        for f in gds_files:
            name = re.sub('\.gds$', '', f)
            gds_name = "{0}/{1}".format(gds_dir, f)
            if not os.path.isfile(gds_name):
                drc_errors += 1
                debug.error("Missing GDS file: {}".format(gds_name))
            drc_errors += verify.run_drc(name, gds_name)

        # fails if there are any DRC errors on any cells
        self.assertEqual(drc_errors, 0)
        globals.end_openram()

def setup_files():
    gds_dir = os.path.join(OPTS.openram_tech, "gds_lib")
    files = os.listdir(gds_dir)
    nametest = re.compile("\.gds$", re.IGNORECASE)
    gds_files = list(filter(nametest.search, files))
    return (gds_dir, gds_files)


OpenRamTest.run_tests(__name__)
