from typing import List

from base.design import design
from characterizer.dependency_graph import create_graph, GraphPath
from characterizer.net_probes.sram_probe import SramProbe

READ = "read"
WRITE = "write"


class CriticalPath:

    def __init__(self, delay_obj: 'SimStepsGenerator'):

        self.sram = delay_obj.sram
        self.delay_obj = delay_obj
        self.probe = delay_obj.probe

        self.paths = {
        }

    def derive_critical_paths(self, address):
        if address not in self.paths:
            self.paths[address] = {}
        paths = self.paths[address]
        debug()
        # paths["precharge_bl"] = self.derive_precharge(address, "bl")
        # paths["precharge_br"] = self.derive_precharge(address, "br")
        # paths["decoder"] = self.derive_row_decoder_paths(address)
        # self.derive_write_path(address)
        self.derive_wordline_paths(address)
        print(paths)

    @staticmethod
    def filter_paths_by_modules(paths: List[GraphPath], modules: List[design]) -> List[GraphPath]:
        """Return paths containing ALL modules, with order preserved"""
        debug()
        modules = [mod for mod in modules]
        for path in paths:
            mods = [x for x in modules]
            for node in path.nodes:
                if not mods:
                    break
                node_modules = [x[0] for x in node.all_parent_modules] + [node.module]
                for node_module in node_modules:
                    if not mods:
                        break
                    if isinstance(node_module, mods[0].__class__):
                        mods.pop(0)
            if not mods:
                yield path

    @staticmethod
    def filter_paths_by_nets(paths: List[GraphPath], nets: List[str]) -> List[GraphPath]:
        nets_in = [net for net in nets]
        for path in paths:
            nets = [x for x in nets_in]
            for node in path.nodes:
                if not nets:
                    break
                node_net = node.get_full_net()
                if node_net in nets:
                    nets.remove(node_net)
            if not nets:
                yield path

    @staticmethod
    def probe_path(path: GraphPath, parent_mod, pex_file, probe_cache,
                   destination_inst=None):
        probes = []
        nodes = path.nodes
        for i in range(len(nodes)):
            start_node = nodes[i]
            start_net = start_node.get_full_net()
            if i < len(nodes) - 1:
                end_node = nodes[i + 1]
                end_net = end_node.get_full_net(in_net=True)
            else:
                end_node = nodes[i]
                end_net = end_node.get_full_net(in_net=False)
            node_probes = []
            for net in [start_net, end_net]:
                extraction_func = SramProbe.generic_get_extracted_net
                full_net = extraction_func(net, parent_mod, "_", destination_inst)
                full_net = "_".join([x for x in full_net if x])
                if full_net not in probe_cache:
                    res, _ = SramProbe.extract_pex_pattern(full_net, pex_file)
                    probe_cache[full_net] = res
                node_probes.append(probe_cache[full_net])
            probes.append(node_probes)
        return probes

    def derive_row_decoder_paths(self, address):
        _, _, row, _ = self.probe.decode_address(address)
        decoder_out = "dec_out[{}]".format(row)
        paths = create_graph(decoder_out, self.sram)

        nets = ["clk", "Xrow_decoder.Xpre_0.in[0]"]  # so only one address flop is probed
        paths = list(self.filter_paths_by_nets(paths, nets))
        return paths

    def get_default_bank_col(self, address, bank_inst, col):
        bank_index, bank_inst_, row, col_index = self.probe.decode_address(address)

        if bank_inst is None:
            bank_inst = bank_inst_

        bank = bank_inst.mod
        if col is None:
            num_cols = bank.num_cols
            col = num_cols - bank.words_per_row + col_index
        return bank_inst, col

    def derive_precharge(self, address, pin_name="bl", bank_inst=None, col=None, driver_names=None):
        bank_inst, col = self.get_default_bank_col(address, bank_inst, col)
        if driver_names is None:
            driver_names = [bank_inst.mod.precharge_array.name]

        paths = create_graph("X{}.{}[{}]".format(bank_inst.name, pin_name, col),
                             self.sram, driver_inclusions=driver_names)
        paths = list(self.filter_paths_by_nets(paths, ["clk"]))
        print(paths)
        return paths

    def derive_write_path(self, address, bank_inst=None, col=None, driver_names=None):

        bank_inst, col = self.get_default_bank_col(address, bank_inst, col)
        bank = bank_inst.mod

        # write bit lines
        net = "X{}.bl[{}]".format(bank_inst.name, col)
        if bank.words_per_row > 1 and driver_names is None:
            driver_names = [bank_inst.mod.column_mux_array.name]
        elif driver_names is None:
            driver_names = [bank_inst.mod.write_driver_array.name]

        paths = create_graph(net, self.sram, driver_inclusions=driver_names,
                             driver_exclusions=["sense_amp_array", "tri_gate_array"])
        paths = list(self.filter_paths_by_nets(paths, ["clk"]))

        self.paths[address]["write_driver"] = paths

    def derive_wordline_paths(self, address, wl_net="wl", enable_net="wordline_en"):
        self.paths[address]["wl"] = self.derive_wordline_path(address, wl_net, enable_net)

    def derive_wordline_path(self, address, wl_net, enable_net):
        _, bank_inst, row, _ = self.probe.decode_address(address)

        wl_net = "{}.{}[{}]".format(bank_inst.name, wl_net, row)
        enable_net = "X{}.{}".format(bank_inst.name, enable_net)

        paths = create_graph(wl_net, self.sram)

        nets = ["clk", enable_net]  # so only second half of cycle
        paths = list(self.filter_paths_by_nets(paths, nets))
        return paths

    def derive_read_path(self):
        pass

    def evaluate_path_delay(self):
        pass

    def evaluate_delay(self):
        pass

    def evaluate_first_half(self):
        pass
