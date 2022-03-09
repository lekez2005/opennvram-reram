#!/bin/env python

import os
import subprocess
import sys

sys.path.append(os.path.dirname(__file__))
try:
    from script_loader import load_setup, latest_scratch
except (ImportError, ModuleNotFoundError):
    from .script_loader import load_setup, latest_scratch


def export_gds(gds, setup=None):
    if setup is None:
        setup, _, _ = load_setup(top_level=False)

    command = [
        "strmin",
        "-layerMap", setup.layer_map,
        "-library", setup.export_library_name,
        "-strmFile", gds,
        "-attachTechFileOfLib", setup.pdk_library_name,
        "-logFile", os.environ["SCRATCH"] + "/logs/strmIn.log",
        "-view", "layout"
    ]

    subprocess.call(command, cwd=setup.cadence_work_dir)


if __name__ == "__main__":
    setup_, tech_name, _ = load_setup(top_level=True)
    if len(sys.argv) > 0:
        gds_ = sys.argv[0]
    else:
        gds_ = latest_scratch()
    export_gds(gds_, setup=setup_)
