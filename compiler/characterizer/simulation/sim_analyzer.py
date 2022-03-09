import json
import os
import re

import numpy as np

import debug
from characterizer import SpiceReader
from characterizer.charutils import get_measurement_file, get_sim_file
from characterizer.simulation.sim_reader import FALLING_EDGE, RISING_EDGE
from globals import OPTS

digit_regex = r"([0-9\.]+)"
MEAS_PATTERN = r'meas tran {}.*TD=(?P<start_time>\S+)n.*TD=(?P<end_time>\S+)n'
MASK_PATTERN = 'MASK[{}]'
DATA_IN_PATTERN = 'DATA[{}]'
DATA_OUT_PATTERN = 'D[{}]'
VDD_CURRENT = 'i(vvdd)'

brief_errors = False
probe_bits = [0]


def search_str(content, pattern):
    matches = re.findall(pattern, content)
    if len(matches) == 1:
        return matches[0]
    else:
        return matches


def search_file(filename, pattern):
    with open(filename, 'r') as file:
        content = file.read()
        return search_str(content, pattern)


def vector_to_int(vec):
    return int("".join(map(str, vec)), 2)


def int_to_vec(int_, word_size):
    str_format = "0{}b".format(word_size)
    return list(map(int, [x for x in format(int_, str_format)]))


def address_to_int(vec_str):
    return vector_to_int(vec_str.replace(",", "").replace(" ", ""))


def print_vectors(comments, data):
    widths = [len(str(x)) for x in data[0]]
    str_formats = ["{:<" + str(x) + "}" for x in widths]

    for i in range(3):
        print("{:<10}: \t[{}]".
              format(comments[i],
                     " ".join([str_formats[j].format(data[i][j]) for j in
                               range(len(data[i]))])))


def debug_error(comment, expected_data, actual_data):
    equal_vec = np.equal(actual_data, expected_data)
    if not np.all(equal_vec):
        wrong_bits = [(len(actual_data) - 1 - x) for x in
                      np.nonzero(np.invert(equal_vec))[0]]
        print("{} btw bits {}, {}".format(comment, wrong_bits[0], wrong_bits[-1]))
        if brief_errors:
            debug_bits = [x for x in reversed(probe_bits)]
            expected_data = [expected_data[debug_bits[i]] for i in range(len(debug_bits))]
            actual_data = [actual_data[debug_bits[i]] for i in range(len(debug_bits))]
        else:
            debug_bits = list(reversed(range(len(actual_data))))
        print_data = [debug_bits, expected_data, actual_data]
        print_comments = ["", "expected", "actual"]
        print_vectors(print_comments, print_data)

    return np.all(equal_vec)


def measure_delay_from_meas_str(meas_str, prefix, max_delay=None, event_time=None,
                                index_pattern=""):
    """Get measured delay from measurement result file"""
    if event_time is not None:
        time_suffix = "t{:.3g}".format(event_time * 1e9).replace('.', '_')
    else:
        time_suffix = ""

    pattern_str = rf'{prefix}_{index_pattern}.*{time_suffix}' + r"\s*=\s+(?P<delay>\S+)\s?\n"

    pattern = re.compile(pattern_str)
    invalid_results = ["failed"]

    if index_pattern:
        matches = [x for x in pattern.findall(meas_str)
                   if x[1] not in invalid_results]
        bit_delays = [(int(x), float(y)) for x, y in matches]
        delays = [0] * len(bit_delays)
        for bit_, delay_ in bit_delays:
            delays[bit_] = delay_
        delays = list(reversed(delays))
    else:
        delays = [float(x) for x in pattern.findall(meas_str)
                  if not x.lower() == "failed"]

    if max_delay is None:
        max_delay = np.inf
    valid_delays = list(filter(lambda x: x < max_delay, delays))
    if len(valid_delays) > 0:
        max_delay = max(valid_delays)
    else:
        max_delay = 0
    return max_delay, delays


class SimAnalyzer:
    RISING_EDGE = RISING_EDGE
    FALLING_EDGE = FALLING_EDGE

    def __init__(self, sim_dir):
        self.sim_dir = sim_dir

        self.word_size = OPTS.word_size

        self.stim_file = os.path.join(sim_dir, "stim.sp")
        sim_file = os.path.join(sim_dir, get_sim_file())
        self.sim_file = os.path.join(sim_dir, sim_file)
        measure_file = get_measurement_file()
        self.meas_file = os.path.join(sim_dir, measure_file)

        self.sim_data = SpiceReader(sim_file)
        self.address_data_threshold = None

        self.all_saved_list = list(self.sim_data.get_signal_names())
        self.all_saved_signals = "\n".join(sorted(self.all_saved_list))

        file_contents = []
        for file_name in [self.meas_file, self.stim_file]:
            if os.path.exists(file_name):
                with open(file_name, "r") as f:
                    file_contents.append(f.read())
            else:
                file_contents.append(None)
        self.meas_str, self.stim_str = file_contents

        self.load_probes()
        self.load_periods()

    def load_events(self, op_name):
        event_pattern = r"-- {}.*\[(.*)\]".format(op_name)
        matches = search_str(self.stim_str, event_pattern)
        events_ = []

        for match in matches:
            split_str = match.split(",")
            addr_, row_, col_index_, bank_ = [int(x) for x in split_str[:4]]
            event_time_, event_period_, event_duty_ = [float(x) for x in split_str[4:]]
            events_.append((event_time_ * 1e-9, addr_, event_period_ * 1e-9, event_duty_, row_,
                            col_index_, bank_))

        return events_

    def load_probes(self):
        global probe_bits
        json_contents = []
        for file_name in ["state_probes", "voltage_probes", "current_probes"]:
            with open(os.path.join(OPTS.openram_temp, f"{file_name}.json"), "r") as f:
                json_contents.append(json.load(f))
        self.state_probes, self.voltage_probes, self.current_probes = json_contents

        if "clk" in self.voltage_probes:
            self.clk_reference = self.voltage_probes["clk"]["0"]

        values = []
        for name in ["cols", "bits"]:
            value_str = search_str(self.stim_str, rf"Probe {name} = \[(.*)\]")
            values.append(list(map(int, value_str.split(","))))
        self.probe_cols, self.probe_bits = values
        debug.info(1, "Probe cols = %s \nProbe bits = %s", self.probe_cols,
                   self.probe_bits)
        probe_bits = self.probe_bits

    def load_periods(self):
        names = ['read period', 'write period']
        values = []
        for name in names:
            values.append(float(search_str(self.stim_str, f"{name} = {digit_regex}n"))
                          * 1e-9)
        self.period = max(values)
        self.read_period, self.write_period = values
        debug.info(1, "Read period  = %.3g ns Write period = %.3g ns",
                   self.read_period * 1e9, self.write_period * 1e9)

    def get_command(self, label):
        command_pattern = re.compile(MEAS_PATTERN.format(label), re.IGNORECASE)
        result = command_pattern.search(self.stim_str)
        debug.info(2, "Command for label %s = %s", label, result)
        return result

    def get_probe(self, probe_key, net, bank=None, col=None, bit=None):
        probes = self.voltage_probes[probe_key]
        if bank is not None:
            probes = probes[str(bank)]
        if net is not None:
            if net not in probes:
                return None
            probes = probes[net]

        col_bit = col if col is not None else bit
        if isinstance(probes, dict):
            probe = probes[str(col_bit)]
        elif len(probes) == 1:
            probe = probes[0]
        else:
            container = self.probe_cols if col is not None else self.probe_bits
            col_bit_index = container.index(col_bit)
            probe = probes[col_bit_index]
        debug.info(2, "Probe for %s net %s = %s", probe_key, net, probe)
        return probe

    def measure_energy(self, times):
        if isinstance(times, str):
            times = float(times) * 1e-9
        if isinstance(times, float):
            times = (times, times + self.period)
        current = self.sim_data.get_signal(VDD_CURRENT, times[0], times[1])
        time = self.sim_data.slice_array(self.sim_data.time, times[0], times[1])
        power = -np.trapz(current, time) * 0.9

        return power

    def measure_delay_from_stim_measure(self, prefix, max_delay=None, event_time=None,
                                        index_pattern=""):
        return measure_delay_from_meas_str(self.meas_str, prefix, max_delay,
                                           event_time, index_pattern)

    def get_address_data(self, address, time, threshold=None):
        threshold  = threshold or self.address_data_threshold
        if threshold is None:
            threshold = 0.5 * self.sim_data.vdd

        address_probes = list(reversed(self.state_probes[str(address)]))
        address_probes = ["v({})".format(x) for x in address_probes]

        address_data = [self.sim_data.get_signal(x, time)[0] > threshold
                        for x in address_probes]
        address_data = [int(x) for x in address_data]
        return address_data

    def get_msb_first_binary(self, probe_dict, time):
        sorted_keys = list(sorted(probe_dict.keys(), key=int, reverse=True))
        values = [self.sim_data.get_binary(probe_dict[key], time)[0]
                  for key in sorted_keys]
        return values

    def get_mask(self, time):
        if "mask" in self.voltage_probes:
            return self.get_msb_first_binary(self.voltage_probes["mask"], time)
        return [1] * self.word_size

    def get_data_in(self, time):
        return self.get_msb_first_binary(self.voltage_probes["data_in"], time)

    def get_data_out(self, time):
        return self.get_msb_first_binary(self.voltage_probes["dout"], time)

    def verify_write_event(self, write_time, write_address, write_period,
                           write_duty, negate=False):

        current_data = self.get_address_data(write_address, write_time)
        current_mask = self.get_mask(write_time)
        new_data = self.get_data_in(write_time + write_period * write_duty)

        expected_data = [0] * self.word_size
        for i in range(self.word_size):
            if current_mask[i]:
                if negate:
                    expected_data[i] = int(not new_data[i])
                else:
                    expected_data[i] = new_data[i]
            else:
                expected_data[i] = current_data[i]
        settling_time = write_period
        actual_data = self.get_address_data(write_address, write_time + settling_time)

        correct = debug_error(f"Write failure: At time {write_time * 1e9:.3g} n "
                              f"address {write_address}",
                              expected_data, actual_data)
        return correct

    def verify_read_event(self, read_time, read_address, read_period, read_duty,
                          negate=False):
        expected_data = self.get_address_data(read_address, read_time + read_duty * read_period)
        settling_time = read_period
        actual_data = self.get_data_out(read_time + settling_time)

        if negate:
            actual_data = [int(not x) for x in actual_data]

        correct = debug_error(f"Read failure: At time {read_time * 1e9:.3g} n"
                              f" address {read_address}", expected_data, actual_data)
        return correct

    @staticmethod
    def check_correctness(event_name, events, verification_func, settling_time, negate):
        max_event = None
        for event in events:
            print(f"{event_name} {event[1]} at time: {event[0] * 1e9:.4g} n")
            correct = verification_func(event[0], event[1],
                                        event[2] + settling_time,
                                        event[3], negate=negate)
            if not correct:
                max_event = event
        return max_event

    def clk_bar_to_bus_delay(self, pattern, start_time, end_time,
                             num_bits=1, bit=0, bus_edge=None):
        return self.sim_data.ref_to_bus_delay(self.clk_reference, FALLING_EDGE, pattern,
                                              start_time, end_time, num_bits, bit,
                                              edgetype2=bus_edge)

    def clk_to_bus_delay(self, pattern, start_time, end_time,
                         num_bits=1, bit=0, bus_edge=None):
        return self.sim_data.ref_to_bus_delay(self.clk_reference, RISING_EDGE, pattern,
                                              start_time, end_time, num_bits, bit,
                                              edgetype2=bus_edge)
