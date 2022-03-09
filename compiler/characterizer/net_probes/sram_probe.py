import itertools
import re
import shutil
from subprocess import check_output, CalledProcessError

import numpy as np

import debug
from characterizer.dependency_graph import get_instance_module, get_net_driver, get_all_net_drivers
from characterizer.net_probes.probe_utils import get_current_drivers, get_all_tx_fingers, format_bank_probes, \
    get_voltage_connections, get_extracted_prefix
from globals import OPTS
from tech import spice as tech_spice


class SramProbe(object):
    """
    Define methods to probe internal SRAM nets given address info
    Mostly geared towards extracted simulations since node names aren't preserved during extraction
    """

    def __init__(self, sram, pex_file=None):
        debug.info(1, "Initialize sram probe")
        self.sram = sram
        if pex_file is None:
            self.pex_file = OPTS.pex_spice
        else:
            self.pex_file = pex_file

        bitcell = self.sram.create_mod_from_str(OPTS.bitcell)
        bitcell_pins = [x.lower() for x in bitcell.pin_map.keys()]
        if "q" in bitcell_pins:
            self.q_pin = bitcell.get_pin("q")
        if "qbar" in bitcell_pins:
            self.qbar_pin = bitcell.get_pin("qbar")

        self.two_bank_dependent = not OPTS.independent_banks and self.sram.num_banks == 2
        self.word_size = (int(self.sram.word_size / 2)
                          if self.two_bank_dependent else self.sram.word_size)
        self.half_sram_word = int(0.5 * self.word_size)

        self.net_separator = "_" if OPTS.use_pex else "."

        self.current_probes_json = {}
        self.current_probes = set()

        self.voltage_probes = {}
        self.state_probes = {}

        self.bitcell_probes = {}
        self.word_driver_clk_probes = {}
        self.clk_probes = self.voltage_probes["clk"] = {}
        self.wordline_probes = self.voltage_probes["wl"] = {}
        self.decoder_probes = self.voltage_probes["decoder"] = {}
        self.decoder_inputs_probes = {}

        self.dout_probes = self.voltage_probes["dout"] = {}
        self.data_in_probes = self.voltage_probes["data_in"] = {}
        self.mask_probes = self.voltage_probes["mask"] = {}

        self.external_probes = ["dout", "mask", "data_in"]

        for i in range(sram.word_size):
            self.dout_probes[i] = "D[{}]".format(i)
            self.data_in_probes[i] = "data[{}]".format(i)
            self.mask_probes[i] = "mask[{}]".format(i)

        self.current_probes = set()

        self.probe_labels = {"clk"}
        self.saved_nodes = set()

    def probe_bit_cells(self, address, pin_name="q"):
        """Probe Q, QBAR of bitcell"""
        address = self.address_to_vector(address)
        address_int = self.address_to_int(address)

        if pin_name not in self.bitcell_probes:
            self.bitcell_probes[pin_name] = {}

        if address_int in self.bitcell_probes[pin_name]:
            return

        bank_index, bank_inst, row, col_index = self.decode_address(address)

        pin_labels = [""] * self.sram.word_size
        for i in range(self.sram.word_size):
            col = i * self.sram.words_per_row + self.address_to_int(col_index)
            pin_labels[i] = self.get_bitcell_label(bank_index, row, col, pin_name)

        pin_labels.reverse()
        self.probe_labels.update(pin_labels)

        if pin_name not in self.bitcell_probes:
            self.bitcell_probes[pin_name] = {}
        self.bitcell_probes[pin_name][address_int] = pin_labels

    def get_bitcell_label(self, bank_index, row, col, pin_name):
        label = "Xbank{}.Xbitcell_array.Xbit_r{}_c{}".format(bank_index, row, col)
        if OPTS.use_pex:
            label = label.replace(".", "_")
        return "Xsram.{}.{}".format(label, pin_name)

    def probe_bitlines(self, bank, row=None):
        for pin_name in ["bl", "br"]:
            if pin_name not in self.voltage_probes:
                self.voltage_probes[pin_name] = {}
            if bank not in self.voltage_probes[pin_name]:
                self.voltage_probes[pin_name][bank] = {}

        if row is None:
            row = self.sram.num_rows - 1
        for col in range(self.sram.num_cols):
            for pin_name in ["bl", "br"]:
                pin_label = self.get_bitline_label(bank, col, pin_name, row)
                self.probe_labels.add(pin_label)
                self.voltage_probes[pin_name][bank][col] = pin_label

    def get_bitline_label(self, bank, col, label, row):
        if OPTS.use_pex:  # select top right bitcell
            pin_label = "Xsram.Xbank{bank}_{pin_name}[{col}]_Xbank{bank}_Xbitcell_array" \
                        "_Xbit_r{row}_c{col}".format(bank=bank, col=col, pin_name=label, row=row)
        else:
            pin_label = "Xsram.Xbank{}.{}[{}]".format(bank, label, col)
        return pin_label

    def get_bitcell_probes(self, address, pin_name="q", pex_file=None):
        """Retrieve simulation probe name based on extracted file"""
        address = self.address_to_vector(address)
        address_int = self.address_to_int(address)

        if pin_name not in self.bitcell_probes or address_int not in self.bitcell_probes[pin_name]:
            debug.error("invalid pin name/address")
        pin_labels = self.bitcell_probes[pin_name][address_int]

        if not OPTS.use_pex:
            return pin_labels[:]
        else:
            pin_labels_pex = []
            for label in pin_labels:
                pin_labels_pex.append(self.extract_from_pex(label, pex_file))
            return pin_labels_pex

    def get_bitcell_storage_nodes(self):
        nodes_map = {}
        pattern = self.get_storage_node_pattern()
        for address in range(self.sram.num_words):
            bank_index, bank_inst, row, col_index = self.decode_address(address)
            address_nodes = [""] * self.sram.word_size
            nodes_map[address] = address_nodes
            for i in range(self.sram.word_size):
                col = i * self.sram.words_per_row + self.address_to_int(col_index)
                if self.two_bank_dependent and i > self.half_sram_word:
                    col -= self.sram.num_cols
                    bank_index_ = 1
                else:
                    bank_index_ = bank_index
                address_nodes[i] = pattern.format(bank=bank_index_, row=row, col=col,
                                                  name="Xbit")
        return nodes_map

    def get_storage_node_pattern(self):
        general_pattern = list(self.state_probes.values())[0][0]  # type: str

        def sub_specific(pattern, prefix, key):
            pattern = re.sub(prefix + r"\[[0-9]+\]", prefix + "[{" + key + "}]", pattern)
            delims = ["_", r"\."]
            replacements = ["_", "."]
            for i in range(2):
                delim = delims[i]
                replacement = replacements[i]
                pattern = re.sub(delim + prefix + "[0-9]+",
                                 replacement + prefix + "{" + key + "}",
                                 pattern)
            return pattern

        general_pattern = sub_specific(general_pattern, "Xbank", "bank")
        general_pattern = sub_specific(general_pattern, "r", "row")
        general_pattern = sub_specific(general_pattern, "c", "col")
        return general_pattern

    def get_decoder_probes(self, address):
        if OPTS.use_pex:
            return self.extract_from_pex(self.decoder_probes[address])
        else:
            return self.decoder_probes[address]

    def get_wordline_label(self, bank_index, row, col, wl_net="wl"):
        wl_label = f"Xbank{bank_index}.{wl_net}[{row}]"
        template = self.probe_net_at_inst(wl_label, self.sram.bank.bitcell_array_inst)
        label = re.sub(r"_r([0-9]+)_c([0-9]+)", "_r{row}_c{col}", template)
        return label.format(row=row, col=col)

    def get_word_driver_clk_probes(self, bank_index, pex_file=None):
        label_key = "dec_b{}_clk".format(bank_index)
        probe_name = self.word_driver_clk_probes[label_key]
        if OPTS.use_pex:
            return [self.extract_from_pex(probe_name, pex_file)]
        else:
            return [probe_name]

    @staticmethod
    def get_buffer_stages_probes(buf):
        results = set()
        buffer_mod = getattr(buf, "buffer_mod", buf)
        num_stages = len(buffer_mod.buffer_invs)
        if hasattr(buf, "buffer_mod"):
            prefix = ".Xbuffer"
        else:
            prefix = ""

        for i in range(num_stages):
            num_fingers = buffer_mod.buffer_invs[i].tx_mults
            for finger in range(num_fingers):
                if not OPTS.use_pex or finger == 0:
                    suffix = ""
                else:
                    suffix = "@{}".format(finger + 1)
                tx_prefix = tech_spice["tx_instance_prefix"]
                results.add(f"{prefix}.Xinv{i}.{tx_prefix}pmos1{suffix}")
        return list(results)

    def driver_current_probes(self, net_template, nets, bits, modules, replacements=None):
        if replacements is None:
            replacements = [("Xmod_0", "Xmod_{bit}")]
        results = []
        for net in nets:
            sample_net = net_template.format(bank=0, net=net, bit=0)
            net_drivers = get_current_drivers(sample_net, self.sram,
                                              candidate_drivers=modules)
            for driver in net_drivers:
                drivers = get_all_tx_fingers(driver, replacements)
                for bit in bits:
                    for tx_driver in drivers:
                        results.append((bit, tx_driver.format(bit=bit)))
        return results

    def bitline_current_probes(self, bank, bits, modules, nets=None, suffix=""):
        if nets is None:
            nets = ["bl", "br"]
        suffix = suffix if self.sram.words_per_row > 1 else ""
        bitline_template = "Xbank{bank}.{net}" + suffix + "[{bit}]"
        probes = self.driver_current_probes(bitline_template, nets, bits,
                                            modules=modules)
        probes = format_bank_probes(probes, bank)
        sorted_probes = list(sorted(probes, key=lambda x: x[0]))
        grouped_probes = itertools.groupby(sorted_probes, key=lambda x: x[0])
        probes_dict = {key: [x[1] for x in val] for key, val in grouped_probes}
        probe_list = [x[1] for x in probes]
        self.current_probes.update(probe_list)
        return probes_dict

    def update_current_probes(self, probes, inst_name, bank):
        if inst_name not in self.current_probes_json:
            self.current_probes_json[inst_name] = {}
        self.current_probes_json[inst_name][bank] = probes

    def write_driver_current_probes(self, bank, bits):
        probes = self.bitline_current_probes(bank, bits, modules=["write_driver_array"],
                                             suffix="_out")
        self.update_current_probes(probes, "write_driver_array", bank)

    def mask_flop_current_probes(self, bank, bits):
        if not self.sram.bank.has_mask_in:
            return
        flop_name = self.sram.bank.msf_data_in.name
        probes = self.bitline_current_probes(bank, bits, modules=[flop_name],
                                             nets=["mask_in", "mask_in_bar"],
                                             suffix="")
        self.update_current_probes(probes, "mask_flops_array", bank)

    def data_flop_current_probes(self, bank, bits):
        flop_name = self.sram.bank.msf_data_in.name
        probes = self.bitline_current_probes(bank, bits, modules=[flop_name],
                                             nets=["data_in", "data_in_bar"],
                                             suffix="")
        self.update_current_probes(probes, "data_flops_array", bank)

    def sense_amp_current_probes(self, bank, bits):
        probes = self.bitline_current_probes(bank, bits, modules=["sense_amp_array"],
                                             nets=["sense_out", "sense_out_bar"],
                                             suffix="")
        self.update_current_probes(probes, "sense_amp_array", bank)

    def tri_state_current_probes(self, bank, bits):
        mod_name = self.sram.bank.tri_gate_array.name
        probes = self.bitline_current_probes(bank, bits, modules=[mod_name],
                                             nets=["data"],
                                             suffix="")
        self.update_current_probes(probes, "tri_gate_array", bank)

    def precharge_current_probes(self, bank, cols):
        probes = self.bitline_current_probes(bank, cols, modules=["precharge_array"],
                                             suffix="")
        self.update_current_probes(probes, "precharge_array", bank)

    def get_bitcell_current_nets(self):
        return ["q", "qbar"]

    def get_bank_bitcell_current_probes(self, bank, bits, row, col_index):
        cols = [col_index + bit * self.sram.words_per_row for bit in bits]
        template = "Xbank{bank}.Xbitcell_array.Xbit_r" + str(row) + "_c{bit}.{net}"
        nets = self.get_bitcell_current_nets()
        replacements = [("r([0-9]+)_c([0-9]+)", "r\g<1>_c{bit}")]
        probes = self.driver_current_probes(template, nets, cols,
                                            modules=["bitcell_array"],
                                            replacements=replacements)
        probes = format_bank_probes(probes, bank)
        probes = [(int(col / self.sram.words_per_row), probe) for col, probe in probes]
        return probes

    def probe_bitcell_currents(self, address):

        if "bitcell_array" not in self.current_probes_json:
            self.current_probes_json["bitcell_array"] = {}

        self.current_probes_json["bitcell_array"][address] = {}

        bank, _, row, col_index = self.decode_address(address)

        if self.two_bank_dependent:
            banks = [0, 1]
            all_bits = [self.offset_bits_by_bank(OPTS.probe_bits, 0, self.word_size),
                        self.offset_bits_by_bank(OPTS.probe_bits, 1, self.word_size)]
            bit_shifts = [0, self.sram.bank.word_size]
        else:
            banks = [bank]
            all_bits = [OPTS.probe_bits]
            bit_shifts = [0]
        for bank, bits, bit_shift in zip(banks, all_bits, bit_shifts):
            probes = self.get_bank_bitcell_current_probes(bank, bits, row, col_index)
            self.current_probes.update([x[1] for x in probes])
            for bit, probe in probes:
                bit_ = bit + bit_shift
                self.current_probes_json["bitcell_array"][address][bit_] = probe

    def get_control_buffers_probe_pins(self, bank):
        bank_name = 'bank{}'.format(bank)
        bank_inst = get_instance_module(bank_name, self.sram)
        return bank_inst.mod.get_control_rails_destinations().keys()

    def get_control_buffers_net_driver(self, bank, net):
        """Get the driver driving 'net' within bank"""
        bank_name = 'bank{}'.format(bank)
        bank_inst = get_instance_module(bank_name, self.sram)
        bank_mod = bank_inst.mod
        control_buffers = bank_mod.control_buffers
        driver = get_net_driver(net, control_buffers)

        _, child_mod, conns = driver
        control_conn_index = control_buffers.conns.index(conns)

        buffer_inst = control_buffers.insts[control_conn_index]

        return bank_inst, buffer_inst, control_conn_index

    def control_buffers_current_probes(self, bank):
        visited_insts = []
        if "control_buffers" not in self.current_probes:
            self.current_probes_json["control_buffers"] = {}
        control_probes = self.current_probes_json["control_buffers"]
        if bank not in control_probes:
            control_probes[bank] = {}
        for net in self.get_control_buffers_probe_pins(bank):
            driver = self.get_control_buffers_net_driver(bank, net)
            bank_inst, buffer_inst, control_conn_index = driver
            if control_conn_index in visited_insts:
                continue

            visited_insts.append(control_conn_index)
            control_name = bank_inst.mod.control_buffers_inst.name

            all_tx = self.get_buffer_stages_probes(buffer_inst.mod)
            all_tx = [(0, "X{}.X{}".format(control_name, buffer_inst.name) + x) for x in all_tx]
            all_tx = [x[1] for x in format_bank_probes(all_tx, bank)]
            self.current_probes.update(all_tx)
            control_probes[bank][net] = all_tx

    def offset_bits_by_bank(self, elements, bank, max_val):
        """Get portions of bits located in a bank"""
        if self.two_bank_dependent:
            if bank == 0:
                return [x for x in elements if x < max_val]
            else:
                return [x - max_val for x in elements if x >= max_val]
        else:
            return elements

    def get_control_buffers_probe_bits(self, destination_inst, bank, net=None):
        name = destination_inst.name
        if name in ["wordline_driver"]:
            return [self.sram.bank.num_rows - 1]
        elif name in ["precharge_array"]:
            return self.offset_bits_by_bank(OPTS.probe_cols, bank, self.sram.bank.num_cols)
        else:
            return self.offset_bits_by_bank(OPTS.probe_bits, bank, self.word_size)

    def get_wordline_nets(self):
        return ["wl"]

    def wordline_driver_currents(self, address):
        bank, _, row, col_index = self.decode_address(address)
        if self.two_bank_dependent:
            banks = [0, 1]
        else:
            banks = [bank]
        for bank in banks:
            bank_name = 'bank{}'.format(bank)
            bank_inst = get_instance_module(bank_name, self.sram)
            bank_mod = bank_inst.mod

            for net in self.get_wordline_nets():
                # get wordline driver array
                full_net = net + "[{}]".format(row)
                out_drivers, in_out_drivers = get_all_net_drivers(full_net, bank_mod)
                driver = list(filter(lambda x: not x[1].name == "bitcell_array",
                                     out_drivers + in_out_drivers))[0]
                _, wordline_driver_array, conns = driver
                conn_index = bank_mod.conns.index(conns)
                driver_inst = bank_mod.insts[conn_index]

                # get pin driver within wordline driver array
                pin_index = conns.index(full_net)
                pin_name = wordline_driver_array.pins[pin_index]
                driver = get_net_driver(pin_name, wordline_driver_array)
                _, buffer, conns = driver
                conn_index = wordline_driver_array.conns.index(conns)
                inst = wordline_driver_array.insts[conn_index]
                all_tx = self.get_buffer_stages_probes(buffer)

                all_tx = [(0, "X{}.X{}".format(driver_inst.name, inst.name) + x) for x in all_tx]
                all_tx = [x[1] for x in format_bank_probes(all_tx, bank)]

                if net not in self.current_probes_json:
                    self.current_probes_json[net] = {}
                self.current_probes_json[net][address] = all_tx

                self.current_probes.update(all_tx)

    def probe_address_currents(self, address):
        # self.probe_bitcell_currents(address)
        self.wordline_driver_currents(address)

    @staticmethod
    def get_decoder_out_format():
        return "Xsram.dec_out[{}]"

    def probe_address(self, address, pin_name="q"):

        address = self.address_to_vector(address)
        address_int = self.address_to_int(address)

        bank_index, bank_inst, row, col_index = self.decode_address(address)

        self.add_decoder_inputs(address_int, row, bank_index)

        col = self.sram.num_cols - 1
        wl_label = self.get_wordline_label(bank_index, row, col)
        if self.two_bank_dependent:
            self.probe_labels.add(wl_label)
            wl_label = self.get_wordline_label(1, row, col)

        self.voltage_probes["wl"][address_int] = wl_label
        self.probe_labels.add(wl_label)

        pin_labels = [""] * self.sram.word_size
        for bit in range(self.word_size):
            col = bit * self.sram.words_per_row + col_index
            pin_labels[bit] = self.get_bitcell_label(bank_index, row, col, pin_name)
            if self.two_bank_dependent:
                pin_labels[bit + self.word_size] = self.get_bitcell_label(1, row,
                                                                          col, pin_name)

        self.update_bitcell_labels(pin_labels)
        self.state_probes[address_int] = pin_labels

    def update_bitcell_labels(self, pin_labels):
        self.probe_labels.update(pin_labels)

    def probe_bank_currents(self, bank):
        if not OPTS.verbose_save:
            return

        cols = OPTS.probe_cols
        bits = [int(x / self.sram.words_per_row) for x in cols]

        self.write_driver_current_probes(bank, bits)
        self.mask_flop_current_probes(bank, bits)
        self.data_flop_current_probes(bank, bits)
        self.sense_amp_current_probes(bank, bits)
        self.tri_state_current_probes(bank, bits)
        self.precharge_current_probes(bank, cols)
        self.control_buffers_current_probes(bank)

    def set_clk_probe(self, bank):
        probes = self.voltage_probes["control_buffers"][bank]
        if "decoder_clk" in probes:
            net = "decoder_clk"
        else:
            net = "clk_buf"
        self.clk_probes[bank] = probes[net][-1]

    def probe_bank(self, bank):
        self.probe_bank_currents(bank)

        self.probe_bitlines(bank)
        self.probe_write_drivers(bank)
        self.probe_precharge_nets(bank)
        self.probe_sense_amps(bank)
        self.control_buffers_voltage_probes(bank)
        self.set_clk_probe(bank)
        self.probe_decoder_col_mux(bank)
        self.probe_control_flops(bank)

    def probe_control_flops(self, bank):
        self.probe_labels.add("Xsram.Xbank{}.read_buf".format(bank))
        self.probe_labels.add("Xsram.Xbank{}.bank_sel_buf".format(bank))

    def probe_decoder_col_mux(self, bank):
        # predecoder flop output
        if OPTS.use_pex:
            decoder = self.sram.bank.decoder
            for i in range(len(decoder.pre2x4_inst) + len(decoder.pre3x8_inst)):
                pass
                self.probe_labels.add("Xsram.Xrow_decoder_Xpre_{}_in[0]".format(i))
                self.probe_labels.add("Xsram.Xrow_decoder_Xpre_{}_in[1]".format(i))
            self.probe_labels.add("Xsram.decoder_clk_Xrow_decoder")

        # sel outputs
        if self.sram.words_per_row > 1 and OPTS.verbose_save:
            for i in range(self.sram.words_per_row):
                if OPTS.use_pex:
                    col = (self.word_size - 1) * self.sram.words_per_row + i
                    self.probe_labels.add("Xsram.sel[{0}]_Xbank{1}_Xcolumn_mux_array_xmod_{2}".
                                          format(i, bank, col))
                else:
                    self.probe_labels.add("Xsram.sel[{}]".format(bank, i))

    def add_decoder_inputs(self, address_int, row, bank_index):
        decoder_label = self.get_decoder_out_format().format(row)
        self.decoder_probes[address_int] = decoder_label
        self.probe_labels.add(decoder_label)

    def probe_net_at_inst(self, net, destination_inst, parent_mod=None):
        if not OPTS.use_pex:
            return "Xsram.{}".format(net)
        res = self.get_extracted_net(net, destination_inst=destination_inst,
                                     parent_mod=parent_mod)
        prefix, parent_net, suffix = res
        if prefix:
            prefix = f"N{self.net_separator}{prefix}_{parent_net}"
        else:
            prefix = f"N{self.net_separator}{parent_net}"
        return f"{prefix}{self.net_separator}{suffix}"

    @staticmethod
    def get_full_bank_net(net, prefix, suffix, bank_inst, sram):
        separator = "_" if OPTS.use_pex else "."
        if net not in bank_inst.mod.pins:
            prefix = "{}{}".format(separator, prefix) if prefix else ""
            prefix = "X{}{}{}{}".format(bank_inst.name, prefix, separator, net)
        else:
            pin_index = bank_inst.mod.pins.index(net)
            inst_index = sram.insts.index(bank_inst)
            conn = sram.conns[inst_index]
            parent_net = conn[pin_index]
            prefix = "{}".format(parent_net)
        if OPTS.use_pex:
            suffix = "X{}{}{}".format(bank_inst.name, separator, suffix)
            prefix = "N_{}".format(prefix)
            return "{}{}{}".format(prefix, separator, suffix)
        else:
            return "Xsram.{}".format(prefix)

    def probe_internal_nets(self, bank_, sample_net, array_inst, internal_nets):

        """Probe write driver internal bl_bar, br_bar"""

        if array_inst.name not in self.voltage_probes:
            self.voltage_probes[array_inst.name] = {}
        if bank_ not in self.voltage_probes[array_inst.name]:
            self.voltage_probes[array_inst.name][bank_] = {}

        bank_name = 'bank{}'.format(bank_)
        bank_inst = get_instance_module(bank_name, self.sram)

        candidate_drivers = [array_inst.name]

        # find the netlist hierarchy leading to that driver
        driver = next(get_voltage_connections(sample_net, bank_inst.mod,
                                              candidate_drivers=candidate_drivers))
        hierarchy, _, _ = driver
        hierarchy = ".".join(hierarchy)

        for net in internal_nets:
            self.voltage_probes[array_inst.name][bank_][net] = net_probes = {}
            full_net = hierarchy + "." + net
            res = self.get_extracted_net(full_net,
                                         destination_inst=array_inst,
                                         parent_mod=bank_inst.mod)
            prefix, parent_net, suffix = res

            if OPTS.use_pex:
                full_net = self.get_full_bank_net(parent_net, prefix, suffix, bank_inst, self.sram)
            else:
                full_net = self.get_full_bank_net(parent_net, prefix, "", bank_inst, self.sram)

            template = full_net.replace("Xmod_0", "Xmod_{bit}")
            template = template.replace("[0]", "[{bit}]")
            for bit in self.get_control_buffers_probe_bits(array_inst, bank_, net):
                full_net = template.format(bit=bit)
                net_probes[bit] = full_net
                self.probe_labels.add(full_net)

    def control_buffers_voltage_probes(self, bank):
        key = "control_buffers"
        if key not in self.voltage_probes:
            self.voltage_probes[key] = {}
        if bank not in self.voltage_probes[key]:
            self.voltage_probes[key][bank] = {}

        bank_name = 'bank{}'.format(bank)
        bank_inst = get_instance_module(bank_name, self.sram)
        bank_mod = bank_inst.mod
        control_buffer_inst = bank_mod.control_buffers_inst

        for net in self.get_control_buffers_probe_pins(bank):
            self.voltage_probes[key][bank][net] = probes = {}

            bank_net = "Xbank{}.{}".format(bank, net)
            if not OPTS.use_pex:
                probes[-1] = "Xsram.{}".format(bank_net)
                for inst, _ in bank_mod.get_net_loads(net):
                    for bit in self.get_control_buffers_probe_bits(inst, bank, net):
                        probes[bit] = probes[-1]
                self.probe_labels.update(probes.values())
                continue

            # control buffer
            _ = self.get_extracted_net(net, destination_inst=control_buffer_inst,
                                       parent_mod=bank_mod)
            prefix, parent_net, suffix = _
            probes[-1] = self.get_full_bank_net(parent_net, prefix,
                                                suffix, bank_inst, self.sram)

            # loads
            for inst, pin_name in bank_mod.get_net_loads(net):
                prefix, parent_net, suffix = self.get_extracted_net(net, destination_inst=inst,
                                                                    parent_mod=bank_mod)
                full_net = self.get_full_bank_net(parent_net, prefix, suffix, bank_inst, self.sram)
                full_net = re.sub(r"mod_[0-9]+([_\.])?", r"mod_{bit}\g<1>", full_net)
                bits = self.get_control_buffers_probe_bits(inst, bank)
                for bit in bits:
                    probes[bit] = full_net.format(bit=bit)

            self.probe_labels.update(probes.values())

    def get_extracted_net(self, net, destination_inst=None, parent_mod=None):
        if parent_mod is None:
            parent_mod = self.sram

        return self.generic_get_extracted_net(net, parent_mod, self.net_separator,
                                              destination_inst)

    @staticmethod
    def generic_get_extracted_net(net, parent_mod, net_separator, destination_inst=None):
        candidate_drivers = [destination_inst.name] if destination_inst else None

        name_hier, inst_hierarchy, child_net = next(get_voltage_connections(
            net, parent_mod, candidate_drivers=candidate_drivers))
        suffix = net_separator.join(name_hier)

        prefix, internal_net = get_extracted_prefix(child_net, inst_hierarchy)
        if inst_hierarchy and internal_net in inst_hierarchy[0].mod.pins:
            inst = inst_hierarchy[0]
            conn_index = parent_mod.insts.index(inst)
            parent_net = parent_mod.conns[conn_index][inst.mod.pins.index(internal_net)]
        else:
            parent_net = internal_net

        debug.info(2, "net %s in module %s: prefix = %s, parent_net = %s, suffix=%s",
                   net, parent_mod, prefix, parent_net, suffix)

        return prefix, parent_net, suffix

    @staticmethod
    def filter_internal_nets(child_mod, candidate_nets):
        netlist = child_mod.get_spice_parser().get_module(child_mod.name).contents
        netlist = "\n".join(netlist)

        results = []
        for net in candidate_nets:
            if " {} ".format(net) in netlist:
                results.append(net)
        return results

    def get_write_driver_internal_nets(self):
        child_mod = self.sram.bank.write_driver_array.child_mod
        pin_names = ["vdd"]
        candidate_nets = ["bl_bar", "br_bar", "data", "mask", "mask_bar", "bl_p", "br_p"]
        return pin_names + self.filter_internal_nets(child_mod, candidate_nets)

    def probe_write_drivers(self, bank_):
        """Probe write driver internal bl_bar, br_bar"""
        # first locate an instance of sense amp driver
        suffix = "_out" if self.sram.words_per_row > 1 else ""
        bl_net = "bl{}[0]".format(suffix)

        bank_name = 'bank{}'.format(bank_)
        bank_inst = get_instance_module(bank_name, self.sram)
        write_driver_array_inst = bank_inst.mod.write_driver_array_inst

        self.probe_internal_nets(bank_, sample_net=bl_net,
                                 array_inst=write_driver_array_inst,
                                 internal_nets=self.get_write_driver_internal_nets())

    def get_sense_amp_internal_nets(self):
        return ["dout", "out_int", "outb_int", "bl", "br"]

    def probe_sense_amps(self, bank_):
        """Probe bitlines at sense amps"""
        # first locate an instance of sense amp driver
        suffix = "_out" if self.sram.words_per_row > 1 else ""
        bl_net = "bl{}[0]".format(suffix)

        bank_name = 'bank{}'.format(bank_)
        bank_inst = get_instance_module(bank_name, self.sram)
        sense_amp_inst = bank_inst.mod.sense_amp_array_inst

        self.probe_internal_nets(bank_, sample_net=bl_net, array_inst=sense_amp_inst,
                                 internal_nets=self.get_sense_amp_internal_nets())

    def probe_precharge_nets(self, bank_):
        bank_name = 'bank{}'.format(bank_)
        bank_inst = get_instance_module(bank_name, self.sram)
        precharge_inst = bank_inst.mod.precharge_array_inst
        if "vdd" not in precharge_inst.mod.pins:
            return
        bl_net = "bl[0]"
        self.probe_internal_nets(bank_, sample_net=bl_net, array_inst=precharge_inst,
                                 internal_nets=["vdd"])

    def extract_nested_probe(self, key, container, existing_mappings):
        # tries to maintain original container to references don't get lost
        def extract_key(key_):
            val = existing_mappings.get(key_, self.extract_from_pex(key_))
            existing_mappings[key_] = val
            return val

        value = container[key]
        if isinstance(value, str):
            container[key] = extract_key(value)
        elif isinstance(value, list):
            results = [extract_key(x) for x in value]
            value.clear()
            value.extend(results)
        elif isinstance(value, dict):
            for sub_key in value:
                self.extract_nested_probe(sub_key, value, existing_mappings)
        else:
            raise ValueError("Invalid value type: {}".format(value))

    def extract_probes(self):
        if not OPTS.use_pex:
            # self.probe_labels.add("Xsram.Xbank0.*")
            self.saved_nodes.update(self.probe_labels)
            return
        debug.info(1, "Extracting probes")
        net_mapping = {key: self.extract_from_pex(key) for key in self.probe_labels}
        self.saved_nodes.update(set(net_mapping.values()))

        for key in self.voltage_probes:
            if key in self.external_probes:
                continue
            self.extract_nested_probe(key, self.voltage_probes, net_mapping)

        self.extract_state_probes(net_mapping)

    def extract_state_probes(self, existing_mappings):
        for key in self.state_probes:
            self.extract_nested_probe(key, self.state_probes, existing_mappings)

    def extract_from_pex(self, label, pex_file=None):
        if not OPTS.use_pex:
            return label
        if pex_file is None:
            pex_file = self.pex_file

        label_sub = label.replace("Xsram.", "")
        match, pattern = self.extract_pex_pattern(label_sub, pex_file)
        if not match:
            debug.error("Match not found in pex file for label {} {}".format(label,
                                                                             pattern))
            return label
        return 'Xsram.' + match

    @staticmethod
    def extract_pex_pattern(label, pex_file):
        label_sub = label.replace(".", "_").replace("[", r"\[").replace("]", r"\]")
        prefix = "" if label.startswith("N_") else "N_"
        pattern = r"\s{}{}_[MX]\S+_[gsd]".format(prefix, label_sub)
        match = (SramProbe.grep_file(pattern, pex_file, regex=True) or
                 SramProbe.grep_file(label, pex_file, regex=False))
        return match, pattern

    @staticmethod
    def grep_file(pattern, pex_file, regex=True):
        rg = shutil.which("rg")
        if rg:
            executable = "rg"
            flags = "-ie" if regex else "-iF"
        else:
            executable = "grep"
            flags = "-iE" if regex else "-iF"
        try:
            match = check_output([executable, "-m1", "-o", flags, pattern, pex_file])
            return match.decode().strip()
        except CalledProcessError as ex:
            if ex.returncode == 1:  # mismatch
                return None
            else:
                raise ex

    def decode_address(self, address):
        if isinstance(address, int):
            address = self.address_to_vector(address)
        if self.sram.num_banks == 4:
            bank_index = 2 ** address[0] + address[1]
            address = address[2:]
        elif self.two_bank_dependent:
            bank_index = 0
        elif self.sram.num_banks == 2:
            bank_index = address[0]
            address = address[1:]
        else:
            bank_index = 0

        bank_inst = self.sram.bank_insts[bank_index]
        address_int = self.address_to_int(address)

        words_per_row = self.sram.words_per_row
        num_col_bits = int(np.log2(words_per_row))
        if num_col_bits > 0:
            row_address = address[:-num_col_bits]
        else:
            row_address = address
        row = self.address_to_int(row_address)
        col_index = address_int % self.sram.words_per_row

        return bank_index, bank_inst, row, col_index

    def address_to_vector(self, address):
        """Convert address integer to binary list MSB first"""
        if type(address) == int:
            return list(map(int, np.binary_repr(address, width=self.sram.addr_size)))
        elif type(address) == list and len(address) == self.sram.addr_size:
            return address
        else:
            debug.error("Invalid address: {}".format(address))

    def address_to_int(self, address):
        """Convert address to integer. Address can be vector of integers MSB first or integer"""
        if type(address) == int:
            return address
        elif type(address) == list:
            return int("".join(str(a) for a in address), base=2)
        else:
            debug.error("Invalid data: {}".format(address))

    def clear_labels(self):
        self.sram.objs = list(filter(lambda x: not x.name == "label", self.sram.objs))
