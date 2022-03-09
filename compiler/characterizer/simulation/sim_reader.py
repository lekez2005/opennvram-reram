from abc import ABC

import numpy as np

RISING_EDGE = "rising"
FALLING_EDGE = "falling"
EITHER_EDGE = "either"

FIRST_EDGE = "first"
LAST_EDGE = "last"


class SimReader(ABC):
    time = vdd = None

    def initialize(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def get_signal(self, signal_name, from_t=0.0, to_t=None):
        raise NotImplementedError

    def get_signal_names(self):
        raise NotImplementedError

    def is_valid_signal(self, signal_name):
        return signal_name in self.get_signal_names()

    def __init__(self, simulation_file, vdd_name="vdd"):
        self.simulation_file = simulation_file
        self.vdd_name = vdd_name
        self.thresh = 0.5

        self.initialize()

    def find_nearest(self, time_t):
        idx = (np.abs(self.time - time_t)).argmin()
        return idx

    def get_time_indices(self, from_t=0.0, to_t=None):
        if to_t is None:
            to_t = self.time[-1]
        from_index = self.find_nearest(from_t)
        to_index = self.find_nearest(to_t)
        return from_index, to_index

    def slice_array(self, array_, from_t=0.0, to_t=None):

        from_index, to_index = self.get_time_indices(from_t, to_t)

        if from_index == to_index:
            return array_[from_index: from_index + 1]
        elif to_index == array_.size - 1:
            return array_[from_index:]
        else:
            return array_[from_index:to_index + 1]

    def get_signal_time(self, signal_name, from_t=0.0, to_t=None):
        return self.slice_array(self.time, from_t, to_t), self.get_signal(signal_name, from_t, to_t)

    def get_binary(self, signal_name, from_t, to_t=None, thresh=None):
        if to_t is None:
            to_t = from_t
        if thresh is None:
            thresh = self.thresh
        signal = self.get_signal(signal_name, from_t=from_t, to_t=to_t)
        return 1 * (signal.flatten() > thresh * self.vdd)

    def get_transition_time_thresh(self, signal_name, start_time, stop_time=None,
                                   edgetype=None, edge=None, thresh=None):
        if edge is None:
            edge = FIRST_EDGE
        if edgetype is None:
            edgetype = EITHER_EDGE
        if stop_time is None:
            stop_time = self.time[-1]
        if thresh is None:
            thresh = self.thresh
        signal_binary = self.get_binary(signal_name, start_time, to_t=stop_time, thresh=thresh)
        sig_prev = signal_binary[0]
        start_time_index = self.find_nearest(start_time)
        time = np.inf
        for i in range(len(signal_binary)):
            sig = signal_binary[i]
            if (sig != sig_prev) and (edgetype == EITHER_EDGE):
                time = self.time[i + start_time_index]
            elif (sig > sig_prev) and (edgetype == RISING_EDGE):
                time = self.time[i + start_time_index]
            elif (sig < sig_prev) and (edgetype == FALLING_EDGE):
                time = self.time[i + start_time_index]

            if edge == FIRST_EDGE and time != np.inf:
                return time
            sig_prev = sig
        return time

    def get_delay(self, signal_name1, signal_name2, t1=0, t2=None, stop_time=None,
                  edgetype1=None, edgetype2=None, edge1=None, edge2=None,
                  thresh1=None, thresh2=None, num_bits=1, bit=0):

        if t2 is None:
            t2 = t1
        if stop_time is None:
            stop_time = self.time[-1]
        if edge1 is None:
            edge1 = FIRST_EDGE
        if edge2 is None:
            edge2 = FIRST_EDGE
        if edgetype1 is None:
            edgetype1 = EITHER_EDGE
        if edgetype2 is None:
            edgetype2 = edgetype1
        if thresh1 is None:
            thresh1 = self.thresh
        if thresh2 is None:
            thresh2 = self.thresh

        trans1 = self.get_transition_time_thresh(signal_name1, t1, stop_time, edgetype1, edge=edge1, thresh=thresh1)

        def internal_delay(name):
            trans2 = self.get_transition_time_thresh(name, t2, stop_time,
                                                     edgetype2, edge=edge2, thresh=thresh2)
            if trans1 == np.inf or trans2 == np.inf:
                return -np.inf  # -inf to make max calculations easier
            else:
                return trans2 - trans1

        if num_bits == 1:
            return internal_delay(signal_name2.format(bit))
        else:
            return list(reversed([internal_delay(signal_name2.format(i))
                                  for i in range(num_bits)]))

    def ref_to_bus_delay(self, ref_name, ref_edge_type, bus_pattern,
                         start_time, end_time, num_bits=1,
                         bit=0, edgetype2=None):
        if edgetype2 is None:
            edgetype2 = EITHER_EDGE

        def internal_delay(signal):
            return self.get_delay(ref_name, signal, start_time, start_time, end_time,
                                  edgetype1=ref_edge_type, edgetype2=edgetype2,
                                  edge1=FIRST_EDGE, edge2=LAST_EDGE,
                                  num_bits=1, bit=bit)

        if isinstance(bus_pattern, list):
            return [internal_delay(x) for x in bus_pattern]

        if num_bits == 1 and bit >= 0:
            signal_name = bus_pattern.format(0)
            if self.is_valid_signal(signal_name):
                return internal_delay(signal_name)
            return - np.inf
        else:
            results = []
            for i in range(num_bits):
                signal_name = bus_pattern.format(i)
                if self.is_valid_signal(signal_name):
                    results.append(internal_delay(signal_name))
            return list(reversed(results))

    def get_bus(self, bus_pattern, bus_size, from_t=0.0, to_t=None):
        # type: (str, int, float, float) -> np.ndarray
        sig_zero = self.get_signal(bus_pattern.format(0), from_t, to_t)
        result = np.zeros([sig_zero.size, bus_size])
        result[:, 0] = sig_zero
        for i in range(1, bus_size):
            result[:, i] = self.get_signal(bus_pattern.format(i), from_t, to_t)
        return result

    def get_bus_binary(self, bus_pattern, bus_size, time_t):
        bus_data = self.get_bus(bus_pattern, bus_size, time_t, time_t)
        bus_data = bus_data.flatten()
        return 1 * np.flipud(bus_data > 0.5 * self.vdd)
