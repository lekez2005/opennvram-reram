#!/usr/bin/env python3

import os
import pathlib
import sys

from reram_test_base import ReRamTestBase

cell_name = "bank1"
tech = "sky130"


class CalibreLvsTest(ReRamTestBase):
    def test_generate(self):
        from globals import OPTS
        source_added = os.path.join(OPTS.openram_tech, "sp_lib", "source.added")

        source_files = ["temp.sp", f"{cell_name}.spice"]
        flat = OPTS.flat_lvs

        for i in range(2):
            file_name = source_files[i]
            source_file = os.path.join(OPTS.openram_temp, file_name)
            dest_dir = os.path.join(OPTS.openram_temp, "calibre_lvs")
            if not os.path.exists(dest_dir):
                pathlib.Path(dest_dir).mkdir(parents=True, exist_ok=True)
            dest_file = os.path.join(dest_dir, file_name)
            if flat:
                dest_file = dest_file.replace(cell_name, f"{cell_name}_flat")

            with open(source_file, "r") as source, open(dest_file, "w") as dest:
                for line_num, line in enumerate(source.readlines()):
                    if line_num == 1:
                        dest.write(f".include {source_added}\n")
                    line = line.replace("/", "_")
                    line = line.replace(f"{cell_name}_flat", cell_name)
                    dest.write(line)


if "-t" not in sys.argv:
    sys.argv.extend(["-t", "sky130"])
CalibreLvsTest.run_tests(__name__)
