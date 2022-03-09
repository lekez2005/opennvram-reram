import os
import subprocess
import sys

try:
    from script_loader import load_setup
except ImportError:
    from .script_loader import load_setup

cell_views = ["cell_6t", "sense_amp", "write_driver", "ms_flop", "replica_cell_6t", "tri_gate",
              "addr_ff", "clock_nor", "dinv", "inv_clk", "inv_nor", "nor_1",
              "out_inv_16", "output_latch", "addr_latch", "cell_10t",
              "dinv_mx", "inv_col", "mux_a", "nor_1_mx", "out_inv_2", "precharge",
              "tgate", "inv", "inv_dec", "mux_abar", "out_inv_4"]
cell_views = ["cell_6t"]

log_file = os.environ["SCRATCH"] + "/logs/strmOut.log"


def export_gds(library, cell_views, output_dir, setup):
    results = []
    for cell_view in cell_views:
        layout_file_path = os.path.join(setup.cadence_work_dir, library, cell_view,
                                        "layout/layout.oa")
        if os.path.isfile(layout_file_path) or True:
            gds_name = cell_view + ".gds"
            command = [
                "strmout",
                "-layerMap", setup.layer_map,
                "-library", library,
                "-view", "layout",
                "-strmFile", gds_name,
                "-topCell", cell_view,
                "-runDir", setup.cadence_work_dir,
                "-logFile", log_file,
                "-outputDir", output_dir
            ]
            if hasattr(setup, 'objectMap'):
                command.extend(["-objectMap", getattr(setup, "objectMap")])
            retcode = subprocess.call(command, cwd=setup.cadence_work_dir)
            if retcode != 0:
                print(f"Error exporting {cell_view} in library {library}")
                print(command)
            else:
                results.append(os.path.join(output_dir, gds_name))
    return results


if __name__ == "__main__":
    setup_, tech_name, options = load_setup(top_level=True)
    library_ = options.library or setup_.import_library_name
    library_ = "openram"
    cell_views = [options.cell_view] if options.cell_view else cell_views
    out_dir = os.path.join(os.environ.get("OPENRAM_TECH"), tech_name, "gds_lib")
    if sys.argv and not sys.argv[0][0] == "-":
        out_dir = os.path.abspath(sys.argv[0])
    export_gds(library_, cell_views, out_dir, setup_)
