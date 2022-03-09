# pip install libpsf (patched version available at https://github.com/lekez2005/libpsf
import os

import libpsf

from characterizer.simulation.sim_reader import SimReader


class PsfReader(SimReader):
    data = None
    is_open = False

    def initialize(self):
        assert os.path.exists(self.simulation_file), f"{self.simulation_file} does not exist"
        self.data = libpsf.PSFDataSet(self.simulation_file)
        self.time = self.data.get_sweep_values()
        self.all_signal_names = list(self.get_signal_names())
        if self.vdd_name:
            try:
                self.vdd = self.data.get_signal(self.vdd_name)[0]
            except:
                pass
        self.is_open = True

        self.cache = {}

    def close(self):
        self.data.close()
        self.is_open = False

    def get_signal_names(self):
        return self.data.get_signal_names()

    def is_valid_signal(self, signal_name):
        return self.convert_signal_name(signal_name) is not None

    def convert_signal_name(self, signal_name):
        if signal_name in self.all_signal_names:
            return signal_name
        # try add v()
        signal_name_ = "v({})".format(signal_name)
        if signal_name_ in self.all_signal_names:
            return signal_name_
        # try hspice name conversion
        signal_name_ = signal_name.lower().replace("v(", "")
        if signal_name_.endswith(")"):
            signal_name_ = signal_name_[:-1]
        if signal_name_ in self.all_signal_names:
            return signal_name_
        return None

    def get_signal(self, signal_name, from_t=0.0, to_t=None):

        if not self.is_open:
            self.initialize()
        if signal_name in self.cache:
            signal = self.cache[signal_name]
        else:
            real_signal_name = self.convert_signal_name(signal_name)
            if real_signal_name is None:
                raise ValueError("Signal {} not found".format(signal_name))
            signal = self.data.get_signal(real_signal_name)
            self.cache[signal_name] = signal
        return self.slice_array(signal, from_t, to_t)
