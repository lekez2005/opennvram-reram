from importlib import reload

import characterizer
import debug
import verify
from characterizer import SpiceCharacterizer
from characterizer.net_probes import sram_probe
from globals import OPTS


class FunctionalTest:

    def __init__(self, _sram=None, spice_name="spectre", use_pex=True):

        OPTS.spice_name = self.spice_name = spice_name
        OPTS.use_pex = self.use_pex = use_pex
        self.spice_file = OPTS.spice_file
        self.gds_file = OPTS.gds_file
        self.pex_file = OPTS.pex_spice

        self.banks = {}
        self.addresses = None
        self.saved_nodes = set()

        self.probe = None
        self.delay = None

        OPTS.analytical_delay = False
        OPTS.trim_netlist = False

        reload(characterizer)

        import sram
        OPTS.check_lvsdrc = False
        if _sram is None:
            self.sram = sram.sram(word_size=OPTS.word_size,
                                  num_words=OPTS.num_words,
                                  num_banks=OPTS.num_banks,
                                  name="sram1")
        else:
            self.sram = _sram

    def add_probes(self, addresses=None):
        if addresses is None:
            addresses = [0]
        self.addresses = addresses
        if self.probe is None:
            self.probe = probe = sram_probe.SramProbe(self.sram, self.pex_file)
        else:
            probe = self.probe
        for address in addresses:
            probe.probe_bit_cells(address, "QBAR")
            probe.probe_bit_cells(address, "q")

            probe.probe_bit_lines(address, "bl")
            probe.probe_bit_lines(address, "br")

            probe.probe_wordlines(address)
            probe.probe_decoder_outputs(address)
        self.banks = banks = {}
        for address in addresses:
            address_vec = self.probe.address_to_vector(address)
            bank_index, bank_inst, _, _ = probe.decode_address(address_vec)
            if bank_index not in banks:
                banks[bank_index] = bank_inst
        bank_inst = None
        for bank_index in banks:
            bank_inst = banks[bank_index]
            if self.sram.words_per_row > 1:
                probe.probe_sense_amps(bank_index, bank_inst, "bl")
                probe.probe_sense_amps(bank_index, bank_inst, "br")
            probe.probe_sense_amps(bank_index, bank_inst, "data")
            probe.probe_word_driver_clk(bank_index, bank_inst)
            if OPTS.use_pex:
                probe.add_misc_bank_probes(bank_inst, bank_index)
        if OPTS.use_pex and bank_inst is not None:
            probe.add_misc_probes(bank_inst)

    def extract_probes(self):
        probe = self.probe
        if OPTS.use_pex:
            self.saved_nodes = set()
            for label in probe.probe_labels:
                try:
                    self.saved_nodes.add(probe.extract_from_pex(label))
                except:
                    debug.warning("Probe {} not found in extracted netlist".format(label))
        else:
            self.saved_nodes = set(probe.probe_labels)

    def run_drc_lvs_pex(self):
        old_drc_lvs = OPTS.check_lvsdrc
        OPTS.check_lvsdrc = True
        reload(verify)

        self.sram.sp_write(self.spice_file)
        self.sram.gds_write(self.gds_file)

        drc_result = verify.run_drc(self.sram.name, self.gds_file, exception_group="sram")
        if drc_result:
            raise AssertionError("DRC Failed")

        lvs_result = verify.run_lvs(self.sram.name, self.gds_file, self.spice_file, final_verification=True)
        if lvs_result:
            raise AssertionError("LVS Failed")

        if self.use_pex:
            errors = verify.run_pex(self.sram.name, self.gds_file, self.spice_file, self.pex_file)
            if errors:
                raise AssertionError("PEX failed")

        OPTS.check_lvsdrc = old_drc_lvs

    def create_delay(self, corner, delay=None):
        if delay is None:
            self.delay = SpiceCharacterizer(self.sram, self.spice_file, corner)
        else:
            self.delay = delay
        if len(self.addresses) > 0:
            address_vec = self.probe.address_to_vector(self.addresses[0])
            self.delay.probe_address = "".join(map(str, address_vec))
        else:
            self.delay.probe_address = "1" * self.sram.addr_size
        self.delay.probe_data = self.sram.word_size - 1
        self.delay.prepare_netlist()

        self.extract_probes()

        addr_map_list = []
        for address in self.addresses:
            addr_map_list.append({
                "address": address,
                "net_names": self.probe.get_bitcell_probes(address, "q"),
                "decoder_label": self.probe.get_decoder_probes(address)
                #"net_names": []
            })

        self.delay.set_stimulus_params(addr_map_list, list(self.saved_nodes))
