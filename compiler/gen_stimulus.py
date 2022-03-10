#!/usr/bin/env python3
"""
This script will generate a stimulus file for a given period, load, and slew input
for the given dimension SRAM. It is useful for debugging after an SRAM has been
created without re-running the entire process. Right now, it assumes the nominal
corner, but should probably be extended.
"""

import sys

from globals import parse_args, init_openram, report_status, end_openram

(OPTS, args) = parse_args()

# Override the usage
USAGE = "Usage: {} [options] <config file> <period in ns> <load in fF> <slew in ns>\nUse -h for help.\n".format(__file__)

# Check that we are left with a single configuration file as argument.
if len(args) != 4:
    print(USAGE)
    sys.exit(2)


# We need to get the:
# config file
config_file = args[0]
# period
period = float(args[1])
# load
load = float(args[2])
# slew
slew = float(args[3])

# These depend on arguments, so don't load them until now.

init_openram(config_file=config_file, is_unit_test=False)
OPTS.check_lvsdrc = False
# Put the temp output in the output path since it is what we want to generate!
old_openram_temp = OPTS.openram_temp
OPTS.openram_temp = OPTS.output_path



import sram
class fake_sram(sram.sram):
    """ This is an SRAM that doesn't actually create itself, just computes
    the sizes. """
    def __init__(self, word_size, num_words, num_banks, name):
        self.name = name
        self.word_size = word_size
        self.num_words = num_words
        self.num_banks = num_banks
        c = __import__(OPTS.bitcell)
        self.mod_bitcell = getattr(c, OPTS.bitcell)
        self.bitcell = self.mod_bitcell()
        # to get the row, col, etc.
        self.compute_sizes()

sram = fake_sram(OPTS.word_size, OPTS.num_words, OPTS.num_banks, OPTS.output_name)
sp_file = OPTS.output_path+OPTS.output_name + ".sp"

from characterizer import SpiceCharacterizer
import tech
# Set up the delay and set to the nominal corner
d = SpiceCharacterizer.delay(sram, sp_file, ("TT", tech.spice["nom_supply_voltage"], tech.spice["nom_temperature"]))
# Set the period
d.period = period
# Set the load of outputs and slew of inputs
d.set_load_slew(load,slew)
# Set the probe address/bit
probe_address = "1" * sram.addr_size
probe_data = sram.word_size - 1
d.set_probe(probe_address, probe_data)

d.write_delay_stimulus()

# Output info about this run
report_status()
print("Output files are:\n{0}stim.sp\n{0}sram.sp\n{0}reduced.sp".format(OPTS.output_path))
OPTS.openram_temp = old_openram_temp
# Delete temp files, remove the dir, etc.
end_openram()

