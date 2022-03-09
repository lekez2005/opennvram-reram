import os
import random
import subprocess
from importlib import reload

import numpy as np

import debug
from base import utils
from base.utils import write_json
from characterizer.net_probes.sram_probe import SramProbe
from globals import OPTS

SpiceCharacterizer = utils.run_time_mixin()
if not SpiceCharacterizer:
    from characterizer.simulation.spice_characterizer import SpiceCharacterizer


class SimDataMixin(SpiceCharacterizer):

    @staticmethod
    def seed():
        """Seed random generator"""
        seed_val = getattr(OPTS, "simulation_seed", None)
        if seed_val is not None:
            random.seed(seed_val)

    def run_drc_lvs_pex(self):
        """Run DRC, LVS, and PEX"""
        OPTS.check_lvsdrc = True
        import verify
        reload(verify)

        self.sram.sp_write(OPTS.spice_file)
        self.sram.gds_write(OPTS.gds_file)

        if OPTS.run_drc:
            drc_result = verify.run_drc(self.sram.drc_gds_name,
                                        OPTS.gds_file, exception_group="sram")
            if drc_result:
                raise AssertionError("DRC Failed")

        if OPTS.run_lvs:
            lvs_result = verify.run_lvs(self.sram.name, OPTS.gds_file, OPTS.spice_file,
                                        final_verification=True)
            if lvs_result:
                raise AssertionError("LVS Failed")

        force_pex = not os.path.exists(OPTS.pex_spice)
        if OPTS.use_pex and (force_pex or OPTS.run_pex):
            errors = verify.run_pex(self.sram.name, OPTS.gds_file, OPTS.spice_file,
                                    OPTS.pex_spice, run_drc_lvs=False)
            if errors:
                raise AssertionError("PEX failed")

    def replace_spice_models(self, file_name):
        if hasattr(OPTS, "model_replacements"):
            model_replacements = OPTS.model_replacements
            sed_patterns = "; ".join(["s/{}/{}/g".format(mod, rep)
                                      for mod, rep in model_replacements])
            command = ["sed", "--in-place", sed_patterns, file_name]
            debug.info(1, "Replacing bitcells with command: {}".format(" ".join(command)))
            subprocess.run(command, shell=False)

    def initialize_sram(self, probe: SramProbe = None, existing_data=None):
        """Write 'existing_data' address->data map
        and generate random values for unspecified addresses"""
        probe = probe or self.probe
        existing_data = existing_data or getattr(self, "existing_data", {})

        self.seed()

        for address in range(self.sram.num_words):
            if address not in existing_data:
                existing_data[address] = utils.get_random_vector(self.word_size)

        self.existing_data = existing_data

        ic_file = getattr(OPTS, "ic_file", os.path.join(OPTS.openram_temp, "sram.ic"))
        OPTS.ic_file = ic_file

        with open(ic_file, "w") as ic:

            storage_nodes = probe.get_bitcell_storage_nodes()
            for address in range(self.sram.num_words):
                address_data = list(reversed(existing_data[address]))
                for col in range(self.word_size):
                    col_voltage = self.binary_to_voltage(address_data[col])
                    col_node = storage_nodes[address][col]
                    self.write_ic(ic, col_node, col_voltage)

            ic.flush()

    def convert_address(self, address):
        """Convert address integer or vector to binary list MSB first"""
        if type(address) == int:
            return list(map(int, np.binary_repr(address, width=self.addr_size)))
        elif type(address) == list and len(address) == self.addr_size:
            return address
        else:
            debug.error("Invalid address: {}".format(address), -1)

    def convert_data(self, data):
        """Convert data integer to binary list MSB first"""
        if isinstance(data, int):
            return list(map(int, np.binary_repr(data, self.word_size)))
        elif type(data) == list and len(data) == self.word_size:
            return data
        else:
            debug.error("Invalid data: {}".format(data), -1)

    def offset_address_by_bank(self, address, bank):
        assert type(address) == int and bank < self.num_banks
        if self.two_bank_dependent:
            return address
        address += bank * int(2 ** self.sram.bank_addr_size)
        return address

    def complement_data(self, data):
        """Invert all bits"""
        max_val = 2 ** self.word_size - 1
        return data ^ max_val

    @staticmethod
    def invert_vec(data_vec):
        """Invert all bits in list"""
        return [0 if x == 1 else 1 for x in data_vec]

    def write_ic(self, ic, col_node, col_voltage):
        ic.write(".ic V({})={} \n".format(col_node, col_voltage))

    def binary_to_voltage(self, x):
        """Convert binary value to voltage"""
        return x * self.vdd_voltage

    def save_sim_config(self):

        self.sf.write("* Probe cols = [{}]\n".format(",".join(map(str, OPTS.probe_cols))))
        self.sf.write("* Probe bits = [{}]\n".format(",".join(map(str, OPTS.probe_bits))))
        two_bank_dependent = not OPTS.independent_banks and self.sram.num_banks == 2
        self.sf.write("* two_bank_dependent = {}\n".format(int(two_bank_dependent)))

        # save state probes
        write_json(self.probe.state_probes, "state_probes.json")
        write_json(self.probe.voltage_probes, "voltage_probes.json")
        write_json(self.probe.current_probes_json, "current_probes.json")
        self.dump_opts()

    def dump_opts(self):
        def dump_obj(x, f):
            for key in sorted(dir(x)):
                if type(getattr(x, key)).__name__ in ["str", "list", "int", "float"]:
                    f.write("{} = {}\n".format(key, getattr(x, key)))

        with open(os.path.join(OPTS.openram_temp, "config.py"), "w") as config_file:
            dump_obj(OPTS, config_file)
            config_file.write("\n\n")
            dump_obj(SpiceCharacterizer, config_file)
