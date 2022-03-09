#!/usr/bin/env python3
"""
This tests the top-level executable. It checks that it generates the
appropriate files: .lef, .lib, .sp, .gds, .v. It DOES NOT, however,
check that these files are right.
"""

import os
import re
import sys
import shutil

import debug
from globals import OPTS
from testutils import OpenRamTest


class OpenRAMTest(OpenRamTest):

    def runTest(self):
        debug.info(1, "Testing top-level openram.py with 2-bit, 16 word SRAM.")
        out_file = "testsram"
        # make a temp directory for output
        out_path = os.path.join(OPTS.openram_temp, "testsram_{0}".format(OPTS.tech_name))

        # make sure we start without the files existing
        if os.path.exists(out_path):
            shutil.rmtree(out_path, ignore_errors=True)
        self.assertEqual(os.path.exists(out_path), False)

        try:
            os.makedirs(out_path, 0o0750)
        except OSError as e:
            if e.errno == 17:  # errno.EEXIST
                os.chmod(out_path, 0o0750)

        # specify the same verbosity for the system call
        verbosity = ""
        for i in range(OPTS.debug_level):
            verbosity += " -v"

        OPENRAM_HOME = os.path.abspath(os.environ.get("OPENRAM_HOME"))

        cmd = "{6} {0} -n -o {1} -p {2} {3} config_20_{4}.py 2>&1 > {5}".format(
            os.path.join(OPENRAM_HOME, "openram.py"),
            out_file,
            out_path,
            verbosity,
            OPTS.tech_name,
            os.path.join(out_path, "output.log"), sys.executable)

        debug.info(1, cmd)
        os.system(cmd)

        # assert an error until we actually check a resul
        for extension in ["gds", "v", "lef", "sp"]:
            filename = os.path.join(out_path, "{}.{}".format(out_file, extension))
            debug.info(1, "Checking for file: " + filename)
            if not os.path.exists(filename):
                debug.print_str(filename)
            self.assertEqual(os.path.exists(filename), True)

        # Make sure there is any .lib file
        import glob
        files = glob.glob(os.path.join(out_path, "*.lib"))
        self.assertTrue(len(files) > 0)

        # grep any errors from the output
        with open(os.path.join(out_path, "output.log"), "r") as out_log_file:
            output = out_log_file.read()
        self.assertEqual(len(re.findall('ERROR', output)), 0)
        self.assertEqual(len(re.findall('WARNING', output)), 0)

        # now clean up the directory
        if OPTS.purge_temp:
            if os.path.exists(out_path):
                shutil.rmtree(out_path, ignore_errors=True)
            self.assertEqual(os.path.exists(out_path), False)


OpenRamTest.run_tests(__name__)
