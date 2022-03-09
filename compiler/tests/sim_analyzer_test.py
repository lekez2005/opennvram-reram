import os
import re
import time

import numpy as np

from simulator_base import SimulatorBase

# quick way to exclude signals from plot
plot_exclusions = ["sense_en", "outb_int"]


def print_max_delay(desc, val):
    if val > 0:
        print("{} delay = {:.4g}p".format(desc, val * 1e12), flush=True)


def energy_format(l):
    return ", ".join(["{:.3g}".format(x) for x in l])


class SimAnalyzerTest(SimulatorBase):

    def setUp(self):
        super().setUp()
        self.initialize()

    def initialize(self):
        self.update_global_opts()
        from characterizer.simulation.sim_analyzer import SimAnalyzer
        self.debug.info(1, "Simulation Dir: %s", self.temp_folder)
        self.analyzer = SimAnalyzer(self.temp_folder)
        self.debug.info(1, "Simulation end: %s",
                        time.ctime(os.path.getmtime(self.analyzer.stim_file)))
        self.sim_data = self.analyzer.sim_data
        self.read_settling_time = 150e-12
        self.write_settling_time = 200e-12

        with open(os.path.join(self.temp_folder, "sim_saves.txt"), "w") as f:
            f.write("\n".join(self.analyzer.all_saved_list))

        self.RISING_EDGE = self.analyzer.RISING_EDGE
        self.FALLING_EDGE = self.analyzer.FALLING_EDGE
        self.voltage_probes = self.analyzer.voltage_probes
        self.current_probes = self.analyzer.current_probes
        self.state_probes = self.analyzer.state_probes

    def analyze(self):
        from globals import OPTS
        if OPTS.energy:
            self.analyze_energy()
            return
        self.load_events()

        self.analyze_precharge_decoder(self.all_read_events +
                                       self.all_write_events)

        if not self.cmd_line_opts.skip_read_check:
            max_read_event, max_read_bit_delays = self.analyze_read_events()
            self.max_read_event, self.max_read_bit_delays = max_read_event, max_read_bit_delays
        if not self.cmd_line_opts.skip_write_check:
            max_write_event, max_write_bit_delays = self.analyze_write_events()
            self.max_write_event, self.max_write_bit_delays = max_write_event, max_write_bit_delays
        print("----------------Critical Paths---------------")
        if not self.cmd_line_opts.skip_read_check:
            self.evaluate_read_critical_path(max_read_event, max_read_bit_delays)
        if not self.cmd_line_opts.skip_write_check:
            self.evaluate_write_critical_path(max_write_event, max_write_bit_delays)

        self.run_plots()

    def set_energy_vdd(self):
        self.sim_data.vdd = self.sim_data.get_signal("v(vdd)")[0]
        from characterizer.simulation import sim_analyzer
        sim_analyzer.VDD_CURRENT = 'i1(vvdd)'

    def analyze_energy(self):
        self.set_energy_vdd()
        op_energies, self.read_period = self.analyze_energy_events("READ")
        op_energies, self.write_period = self.analyze_energy_events("WRITE")

    def analyze_energy_events(self, event_name):
        op_pattern = r"-- {}.*t = ([0-9\.]+) period = ([0-9\.]+)".format(event_name)
        decoder_clk = re.search(r"-- decoder_clk = (\S+)", self.analyzer.stim_str).group(1)
        events = re.findall(op_pattern, self.analyzer.stim_str)
        op_period = None

        op_energies = []
        for op_time, op_period in events:
            op_time = float(op_time) * 1e-9
            op_period = float(op_period) * 1e-9
            max_op_start = op_time + 0.5 * op_period
            clk_ref_time = self.sim_data.get_transition_time_thresh(decoder_clk, op_time,
                                                                    stop_time=max_op_start,
                                                                    edgetype=self.RISING_EDGE)
            op_energy = self.analyzer.measure_energy([clk_ref_time, clk_ref_time + op_period])
            op_energies.append(op_energy)

        op_energies = [x * 1e12 for x in op_energies]
        print("\nInitial energies", energy_format(op_energies))
        op_energies = op_energies[2:]
        print("Used energies: ", energy_format(op_energies))

        print("Mean {} energy = {:.3g} pJ".format(event_name.capitalize(),
                                                  sum(op_energies) / len(op_energies)))
        return op_energies, op_period

    def analyze_leakage(self):
        time = self.sim_data.time
        num_points = 2
        leakage_start = time[-num_points]
        leakage_end = time[-1]
        total_leakage = self.analyzer.measure_energy([leakage_start, leakage_end])

        leakage_power = total_leakage / (leakage_end - leakage_start)
        leakage_write = leakage_power * self.write_period
        leakage_read = leakage_power * self.read_period

        print("Leakage Power = {:.3g} mW".format(leakage_power * 1e3))
        print("Write leakage = {:.3g} pJ".format(leakage_write * 1e12))
        print("Read leakage = {:.3g} pJ".format(leakage_read * 1e12))

    def load_events(self):
        opts = self.cmd_line_opts
        self.all_read_events = (self.analyzer.load_events("Read")
                                if not opts.skip_read_check else [])
        self.all_write_events = (self.analyzer.load_events("Write")
                                 if not opts.skip_write_check else [])

    def evaluate_num_words(self):
        from globals import OPTS
        two_bank_dependent = not OPTS.independent_banks and OPTS.num_banks == 2
        options = self.cmd_line_opts
        words_per_row = int(options.num_cols / options.word_size)
        if two_bank_dependent:
            options.num_rows *= 2
            self.num_words = words_per_row * options.num_rows
        else:
            self.num_words = words_per_row * options.num_rows * options.num_banks
        self.address_width = int(np.log2(self.num_words))

    def get_analysis_bit(self, delays_):
        """Use col with max delay if verbose save or use specified bit"""
        probe_bits = self.analyzer.probe_bits
        if self.cmd_line_opts.analysis_bit_index is None:
            if delays_:
                max_delay_bit_ = (self.word_size - 1) - np.argmax(delays_)
                if max_delay_bit_ in probe_bits:
                    return max_delay_bit_
            return probe_bits[-1]
        return probe_bits[self.cmd_line_opts.analysis_bit_index]

    def analyze_precharge_decoder(self, events):
        meas_func = self.analyzer.measure_delay_from_stim_measure

        # Precharge and Decoder delay
        max_decoder_delay = 0
        max_precharge = 0
        for event in events:
            max_dec_, dec_delays = meas_func("decoder_a[0-9]+", max_delay=0.9 * event[2],
                                             event_time=event[0])
            max_decoder_delay = max(max_decoder_delay, max_dec_)

            max_prech_, prech_delays = meas_func("precharge_delay", max_delay=0.9 * event[2],
                                                 event_time=event[0])
            max_precharge = max(max_precharge, max_prech_)

        print("\nPrecharge delay = {:.2f}p".format(max_precharge / 1e-12))
        print("Decoder delay = {:.2f}p".format(max_decoder_delay / 1e-12))
        self.max_decoder_delay, self.max_precharge = max_decoder_delay, max_precharge

    def get_analysis_events(self, events, max_event):
        op_index = self.cmd_line_opts.analysis_op_index
        if op_index is not None:
            return events[min(op_index, len(events) - 1)]
        elif max_event is not None:
            return max_event
        else:
            return None

    def get_read_negation(self):
        return False

    def check_read_correctness(self):
        negate_read = self.get_read_negation()
        settling_time = self.read_settling_time
        max_read_event = self.analyzer.check_correctness("Read", self.all_read_events,
                                                         self.analyzer.verify_read_event,
                                                         settling_time, negate_read)
        return max_read_event

    def eval_read_delays(self, max_read_event):
        def get_dout_delay(bit):
            probe = self.voltage_probes["dout"][str(bit)]
            return self.analyzer.clk_bar_to_bus_delay(probe, start_time,
                                                      end_time, num_bits=1)

        max_dout = 0

        max_read_event = self.get_analysis_events(self.all_read_events, max_read_event)
        max_delay_event = max_read_event

        max_read_bit_delays = [0] * self.word_size
        for index, read_event in enumerate(self.all_read_events):
            start_time = read_event[0]
            end_time = read_event[0] + read_event[2] + self.read_settling_time
            d_delays = [get_dout_delay(bit) for bit in range(self.word_size)]

            if max(d_delays) > max_dout or index == 0:
                max_delay_event = read_event
                max_dout = max(d_delays)
                max_read_bit_delays = d_delays
        max_read_event = max_read_event or max_delay_event
        return max_read_event, max_read_bit_delays, max_dout

    def print_read_measurements(self, max_dout):
        print("clk_bar to Read bus out delay = {:.2f}p".format(max_dout / 1e-12))

        total_read = max(self.max_precharge, self.max_decoder_delay) + max_dout
        print("Total Read delay = {:.2f}p".format(total_read / 1e-12))

        meas_func = self.analyzer.measure_energy
        read_energies = [meas_func((x[0], x[0] + x[2])) for x in self.all_read_events]
        if not read_energies:
            read_energies = [0]

        print("Max read energy = {:.2f} pJ".format(max(read_energies) / 1e-12))

    def analyze_read_events(self):
        if self.cmd_line_opts.skip_read_check:
            return
        print("----------------Read Analysis---------------")
        max_read_event = self.check_read_correctness()
        max_read_event, max_read_bit_delays, max_dout = self.eval_read_delays(max_read_event)
        self.print_read_measurements(max_dout)
        return max_read_event, max_read_bit_delays

    def get_write_negation(self):
        return False

    def check_write_correctness(self):
        negate_write = self.get_write_negation()
        settling_time = self.write_settling_time
        max_write_event = self.analyzer.check_correctness("Write", self.all_write_events,
                                                          self.analyzer.verify_write_event,
                                                          settling_time, negate_write)
        return max_write_event

    def eval_write_delays(self, max_write_event):
        max_write_event = self.get_analysis_events(self.all_write_events, max_write_event)
        max_delay_event = None
        max_q_delay = 0
        max_write_bit_delays = [0] * self.word_size

        meas_func = self.analyzer.measure_delay_from_stim_measure
        for index, write_event in enumerate(self.all_write_events):
            max_valid_delay = write_event[2]
            max_q_, q_delays = meas_func("state_delay", event_time=write_event[0],
                                         max_delay=max_valid_delay,
                                         index_pattern="a[0-9]+_c(?P<bit>[0-9]+)_")
            if max_q_ > max_q_delay or index == 0:
                max_q_delay = max_q_
                max_delay_event = write_event
                max_write_bit_delays = q_delays

        max_write_event = max_write_event or max_delay_event
        return max_write_event, max_write_bit_delays, max_q_delay

    def print_write_measurements(self, max_write_event, max_q_delay):
        print(f"Q state delay = {max_q_delay / 1e-12:.4g} ps, "
              f"address = {max_write_event[1]}, t = {max_write_event[0] * 1e9:.4g} ns")

        total_write = max(self.max_precharge, self.max_decoder_delay) + max_q_delay
        print("Total Write delay = {:.2f} ps".format(total_write / 1e-12))
        meas_func = self.analyzer.measure_energy
        write_energies = [meas_func((x[0], x[2] + x[0])) for x in self.all_write_events]
        if not write_energies:
            write_energies = [0]
        print("Max write energy = {:.2f} pJ".format(max(write_energies) / 1e-12))

    def analyze_write_events(self):
        if self.cmd_line_opts.skip_write_check:
            return
        print("----------------Write Analysis---------------")
        max_write_event = self.check_write_correctness()
        write_delays = self.eval_write_delays(max_write_event)
        max_write_event, max_write_bit_delays, max_q_delay = write_delays
        self.print_write_measurements(max_write_event, max_q_delay)
        return max_write_event, max_write_bit_delays

    # Critical paths

    def voltage_probe_delay(self, probe_key, net, bank_=None, col=None, bit=None,
                            edge=None, clk_buf=False):
        clk_bank = self.probe_bank if bank_ is None else bank_
        self.analyzer.clk_reference = self.voltage_probes["clk"][str(clk_bank)]
        probe = self.analyzer.get_probe(probe_key, net, bank_, col, bit)
        delay_func = (self.analyzer.clk_to_bus_delay
                      if clk_buf else self.analyzer.clk_bar_to_bus_delay)
        return delay_func(probe, self.probe_start_time, self.probe_end_time,
                          num_bits=1, bus_edge=edge)

    def print_wordline_en_delay(self):
        probes = self.voltage_probes["control_buffers"][str(self.probe_bank)]["wordline_en"]
        max_row = max(map(int, probes.keys()))
        delay = self.voltage_probe_delay("control_buffers", "wordline_en", self.probe_bank,
                                         bit=max_row, edge=self.RISING_EDGE)
        print_max_delay("Wordline EN", delay)

    def print_wordline_delay(self, max_read_address):
        delay = self.voltage_probe_delay("wl", None, None, bit=max_read_address,
                                         edge=self.RISING_EDGE)
        print_max_delay("Wordline ", delay)

    def print_read_sample_delay(self):
        delay_func = self.voltage_probe_delay
        bank, bit = self.probe_bank, self.probe_control_bit
        if "sample_en_bar" in self.voltage_probes["control_buffers"]:
            sample_fall_delay = delay_func("control_buffers", "sample_en_bar", bank,
                                           bit, edge=self.FALLING_EDGE)
            sample_rise_delay = delay_func("control_buffers", "sample_en_bar", bank,
                                           bit, edge=self.RISING_EDGE)
            print_max_delay("Sample Fall", sample_fall_delay)
            print_max_delay("Sample Rise", sample_rise_delay)

    def print_sense_en_delay(self):
        delay = self.voltage_probe_delay("control_buffers", "sense_en", self.probe_bank,
                                         self.probe_control_bit, edge=self.RISING_EDGE)
        print_max_delay("Sense EN", delay)

    def print_sense_bl_br_delay(self):
        bank = self.probe_bank
        voltage_probe_delay = self.voltage_probe_delay
        bl_delay = voltage_probe_delay("sense_amp_array", "bl", bank,
                                       self.probe_control_bit)
        if "br" in self.voltage_probes["sense_amp_array"][str(bank)]:
            br_delay = voltage_probe_delay("sense_amp_array", "br", bank,
                                           self.probe_control_bit)
        else:
            br_delay = voltage_probe_delay("br", None, bank, col=self.probe_col)
        print_max_delay("BL", bl_delay)
        print_max_delay("BR", br_delay)

    def print_sense_out_delay(self):
        delay = self.voltage_probe_delay("sense_amp_array", "dout", self.probe_bank,
                                         self.probe_control_bit)
        print_max_delay("Sense out", delay)

    def print_read_critical_path(self, address):
        self.print_wordline_en_delay()
        self.print_wordline_delay(address)
        self.print_sense_bl_br_delay()
        self.print_read_sample_delay()
        self.print_sense_en_delay()
        self.print_sense_out_delay()

    def set_critical_path_params(self, event, bit_delays, settling_time):
        start_time, address, period, _, row = event[:5]
        end_time = start_time + period + settling_time
        max_bit = self.get_analysis_bit(bit_delays)

        q_net = "v({})".format(self.state_probes[str(address)][max_bit])
        col = int(re.search("r[0-9]+_c([0-9]+)", q_net).group(1))
        controls_bit = int(col / self.words_per_row)
        self.probe_event = event

        bank = int(re.search("Xbank([0-9]+)", q_net).group(1))

        self.probe_start_time, self.probe_end_time = start_time, end_time
        self.probe_col = col
        self.probe_control_bit = controls_bit
        self.probe_bank = bank
        self.probe_address = address
        self.probe_row = row
        self.probe_q_net = q_net

        return period, row, max_bit, bank, address, q_net

    def evaluate_read_critical_path(self, max_read_event, max_read_bit_delays):

        path_params = self.set_critical_path_params(max_read_event, max_read_bit_delays,
                                                    self.read_settling_time)
        period, row, max_read_bit, bank, address, q_net = path_params

        print("\nRead Period: {:.3g} ns".format(period * 1e9))
        print("Read Critical Path: t = {:.3g}n row={} bit={} bank={}".
              format(max_read_event[0], row, max_read_bit, bank))

        self.print_read_critical_path(address)

    def get_write_en_delay(self):
        delay_func = self.voltage_probe_delay
        write_en_bar_delay = None
        if "write_en_bar" in self.voltage_probes["control_buffers"]:
            write_en_bar_delay = delay_func("control_buffers", "write_en_bar",
                                            self.probe_bank,
                                            self.probe_control_bit, edge=self.FALLING_EDGE)
            print_max_delay("Write ENB", write_en_bar_delay)
        write_en_delay = delay_func("control_buffers", "write_en", self.probe_bank,
                                    bit=self.probe_control_bit, edge=self.RISING_EDGE)
        return write_en_delay, write_en_bar_delay

    def get_flop_out_delay(self):
        return self.voltage_probe_delay("write_driver_array", "data", self.probe_bank,
                                        bit=self.probe_control_bit)

    def get_write_bl_br_delay(self):
        delay_func = self.voltage_probe_delay
        bl_delay = delay_func("bl", None, self.probe_bank,
                              col=self.probe_col, edge=self.FALLING_EDGE)
        br_delay = delay_func("br", None, self.probe_bank,
                              col=self.probe_col, edge=self.FALLING_EDGE)
        return bl_delay, br_delay

    def get_write_q_delay(self, q_net):
        return self.analyzer.clk_bar_to_bus_delay(q_net, self.probe_start_time,
                                                  self.probe_end_time)

    def print_write_critical_path(self, q_net):
        write_en_delay, write_en_bar_delay = self.get_write_en_delay()
        flop_out_delay = self.get_flop_out_delay()
        bl_delay, br_delay = self.get_write_bl_br_delay()
        q_delay = self.get_write_q_delay(q_net)
        print_max_delay("Write EN", write_en_delay)
        if write_en_bar_delay is not None:
            print_max_delay("Write ENB", write_en_bar_delay)
        print_max_delay("Flop out", flop_out_delay)
        print_max_delay("BL", bl_delay)
        print_max_delay("BR", br_delay)
        print_max_delay("Q", q_delay)

    def evaluate_write_critical_path(self, max_write_event, max_write_bit_delays):
        path_params = self.set_critical_path_params(max_write_event, max_write_bit_delays,
                                                    self.write_settling_time)
        period, row, max_write_bit, write_bank, address, q_net = path_params

        print("\nWrite Period: {:.3g}".format(max_write_event[2] * 1e9))
        print(f"Write Critical Path: t = {max_write_event[0]:.3g}n"
              f" row={row} bit={max_write_bit} bank={write_bank}\n")
        self.print_write_critical_path(q_net)

    def get_plot_probe(self, key, net, bit=None):
        if bit is None:
            bit = self.probe_control_bit
        return self.analyzer.get_probe(key, net, self.probe_bank, bit)

    def plot_sig(self, signal_name, label, from_t=None, to_t=None):
        if signal_name is None:
            return
        if from_t is None:
            from_t = self.probe_start_time
        if to_t is None:
            to_t = self.probe_end_time

        for excl in plot_exclusions:
            if excl in signal_name:
                return
        try:
            print(signal_name)
            signal = self.sim_data.get_signal_time(signal_name,
                                                   from_t=from_t, to_t=to_t)
            self.ax1.plot(*signal, label=label)
        except ValueError as er:
            print(er)

    def get_wl_name(self):
        return "wl"

    def plot_common_signals(self):
        self.plot_sig(self.analyzer.clk_reference, label="clk_buf")
        self.plot_sig(self.get_plot_probe("bl", None, self.probe_col),
                      label=f"bl[{self.probe_col}]")
        self.plot_sig(self.get_plot_probe("br", None, self.probe_col),
                      label=f"br[{self.probe_col}]")
        if self.words_per_row > 1 and "sense_amp_array" in self.voltage_probes:
            self.plot_sig(self.get_plot_probe("sense_amp_array", "bl"),
                          label=f"bl_out[{self.probe_control_bit}]")

        address = self.probe_address
        row = self.probe_row
        wl_name = self.get_wl_name()
        self.plot_sig(self.voltage_probes[wl_name][str(address)],
                      label=f"{wl_name}[{row}]")
        self.plot_sig(self.probe_q_net, label="Q")

    def plot_write_signals(self):
        self.plot_sig(self.get_plot_probe("control_buffers", "write_en",
                                          self.probe_control_bit),
                      label="write_en")

    def plot_mram_current(self):
        address = str(self.probe_address)
        q_bit = str(self.probe_control_bit)
        write_current_net = self.current_probes["bitcell_array"][address][q_bit]
        write_current_net = "i1({})".format(write_current_net)

        from_t = self.probe_start_time
        to_t = self.probe_end_time
        write_current_time = self.sim_data.get_signal_time(write_current_net,
                                                           from_t=from_t, to_t=to_t)
        write_current = write_current_time[1] * 1e6
        ax2 = self.ax1.twinx()

        ax2.plot(write_current_time[0], write_current, ':k', label="current")
        ax2.set_ylabel("Write Current (uA)")
        ax2.legend()

    def plot_internal_sense_amp(self):
        for net in ["out_int", "outb_int"]:
            self.plot_sig(self.get_plot_probe("sense_amp_array", net),
                          label=net)

    def plot_read_signals(self):
        from characterizer.simulation.sim_analyzer import DATA_OUT_PATTERN
        if self.words_per_row > 1:
            self.plot_sig(self.get_plot_probe("control_buffers", "sample_en_bar"),
                          label="sample_en_bar")
        self.plot_sig(self.get_plot_probe("control_buffers", "sense_en"),
                      label="sense_en")
        self.plot_internal_sense_amp()

        key = DATA_OUT_PATTERN.format(self.probe_control_bit)
        self.plot_sig(key, label=key)

    def run_plots(self):
        if self.cmd_line_opts.plot is None:
            return
        import logging
        import matplotlib
        matplotlib.use("Qt5Agg")
        from matplotlib import pyplot as plt
        logging.getLogger('matplotlib').setLevel(logging.WARNING)

        print("\nPlot Signals: ")

        if self.cmd_line_opts.plot == "write":
            self.set_critical_path_params(self.max_write_event, self.max_write_bit_delays,
                                          self.write_settling_time)
            plot_func = self.plot_write_signals
        else:
            self.set_critical_path_params(self.max_read_event, self.max_read_bit_delays,
                                          self.read_settling_time)
            plot_func = self.plot_read_signals

        self.fig, self.ax1 = plt.subplots()
        self.plot_common_signals()
        plot_func()

        plt.axhline(y=0.5 * self.sim_data.vdd, linestyle='--', linewidth=0.5)
        plt.axhline(y=self.sim_data.vdd, linestyle='--', linewidth=0.5)

        self.ax1.grid()
        self.ax1.legend(loc="center left", fontsize="x-small")
        plt.title("{}: bit = {} col = {} addr = {}".format(os.path.basename(self.temp_folder),
                                                           self.probe_control_bit,
                                                           self.probe_col,
                                                           self.probe_address))

        if not self.cmd_line_opts.verbose_save:
            print("Available bits: {}".format(", ".join(map(str, self.analyzer.probe_bits))))

        plt.tight_layout()
        plt.show()
