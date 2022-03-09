#!/bin/env python
import os
import sys


def export_gds(gds, options):
    from verify.magic import export_gds_to_magic
    from globals import OPTS
    OPTS.openram_temp = os.environ.get("MGC_TMPDIR")
    cell_name = options.cell_view
    export_gds_to_magic(gds, cell_name, flatten=False)


if __name__ == "__main__":
    sys.path.append(os.environ["OPENRAM_HOME"])
    sys.path.append(os.environ["OPENRAM_TECH"])
    from script_loader import load_setup, latest_scratch

    setup_, tech_name, options_ = load_setup(top_level=True)
    if len(sys.argv) > 0:
        gds_ = sys.argv[0]
    else:
        gds_ = latest_scratch()
    export_gds(gds_, options_)
