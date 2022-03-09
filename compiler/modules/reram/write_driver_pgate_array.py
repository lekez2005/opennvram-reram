import debug
from globals import OPTS
from modules.write_driver_array import write_driver_array


class WriteDriverPgateArray(write_driver_array):
    def create_child_mod(self):
        logic_size = OPTS.write_driver_logic_size
        buffer_size = OPTS.write_driver_buffer_size
        self.child_mod = self.create_mod_from_str(OPTS.write_driver_mod, logic_size=logic_size,
                                                  buffer_size=buffer_size)
        debug.info(1, "Using module {} for {}".format(self.child_mod.name,
                                                      self.name))
        self.height = self.child_mod.height
        self.driver = self.child_mod
