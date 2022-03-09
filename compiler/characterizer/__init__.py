from globals import find_exe, get_tool
from characterizer.simulation.spice_characterizer import SpiceCharacterizer
from .lib import *
from .setup_hold import *

debug.info(2, "Initializing characterizer...")

OPTS.spice_exe = ""

if not OPTS.analytical_delay:
    if OPTS.spice_name != "":
        OPTS.spice_exe = find_exe(OPTS.spice_name)
        if OPTS.spice_exe == "":
            debug.error("{0} not found. Unable to perform characterization.".format(OPTS.spice_name), 1)
    else:
        (OPTS.spice_name, OPTS.spice_exe) = get_tool("spice", ["xa", "hspice", "ngspice", "ngspice.exe"])

    # set the input dir for spice files if using ngspice 
    if OPTS.spice_name == "ngspice":
        os.environ["NGSPICE_INPUT_DIR"] = "{0}".format(OPTS.openram_temp)
    
    if OPTS.spice_exe == "":
        debug.error("No recognizable spice version found. Unable to perform characterization.", 1)

    if OPTS.spice_name in ["hspice", "spectre"]:
        try:
            from characterizer.simulation.psf_reader import PsfReader as SpiceReader
        except:
            debug.warning(f"Invalid spice reader for spice name {OPTS.spice_name}")
    else:
        raise ValueError(f"Invalid spice reader for spice name {OPTS.spice_name}")
