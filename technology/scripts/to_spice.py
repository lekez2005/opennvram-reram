# http://web.engr.uky.edu/~elias/projects/14.pdf

import os
import shutil
import subprocess
import sys

try:
    from script_loader import load_setup
except ImportError:
    from .script_loader import load_setup

setup, tech_name, _ = load_setup()
output_folder = os.path.join(os.environ["SCRATCH"], "openram", "tmp/spice_export")

cellviews = ["cell_6t", "sense_amp", "write_driver", "ms_flop", "replica_cell_6t", "tri_gate"]

cellviews = ["write_driver_mux_buffer"]
library = setup.import_library_name
library = "openram"

si_template = '''
simLibName = "{0}"
simCellName = "{1}"
hnlNetlistFileName = "{2}"
simViewName = "schematic"
simSimulator = "auCdl"
simNotIncremental = 't
simReNetlistAll = 't
simViewList = '("auCdl" "schematic")
simStopList = '("auCdl")
simNetlistHier = 't
nlCreateAmap = nil
incFILE = ""
setEQUIV = ""
'''

dirname = os.path.abspath(os.path.dirname(__file__))

if not os.path.exists(output_folder):
    os.makedirs(output_folder)

for cellview in cellviews:

    # prepare si.env
    spice_name = cellview + ".sp"
    si_content = si_template.format(library, cellview, spice_name)
    with open(os.path.join(output_folder, "si.env"), "w") as text_file:
        text_file.write(si_content)

    # run si export
    cds_lib = os.path.join(setup.cadence_work_dir, "cds.lib")
    command = ["si", "-batch", "-command", "netlist", "-cdslib", cds_lib]
    retcode = subprocess.call(command, cwd=output_folder)
    if retcode != 0:
        print("Error exporting {}".format(cellview))
        print(" ".join(command))
        sys.exit(-1)

    dest_file = os.path.join(os.environ.get("OPENRAM_TECH"), tech_name, "sp_lib", spice_name)
    source_file = os.path.join(output_folder, spice_name)
    shutil.copy2(source_file, dest_file)
