from base import design
from base.library_import import library_import
from base.vector import vector
from globals import OPTS
from modules.single_level_column_mux import get_inputs_for_pin
from modules.single_level_column_mux_array import single_level_column_mux_array


@library_import
class tgate_column_mux_tap(design.design):
    pin_names = []
    lib_name = getattr(OPTS, "tgate_column_mux_tap_mod", "tgate_column_mux_tap")


@library_import
class tgate_column_mux(design.design):
    pin_names = "bl br bl_out br_out sel gnd vdd".split()
    lib_name = getattr(OPTS, "tgate_column_mux_mod", "tgate_column_mux")

    def get_inputs_for_pin(self, name):
        return get_inputs_for_pin(self, name)


class tgate_column_mux_array(single_level_column_mux_array):
    """Transmission gate based column mux array"""
    def create_layout(self):
        super().create_layout()
        self.add_body_contacts()

    def create_modules(self):
        self.mux = tgate_column_mux()
        self.child_mod = self.mux
        self.add_mod(self.mux)
        if OPTS.use_x_body_taps:
            self.body_tap = tgate_column_mux_tap()

    def add_body_contacts(self):
        y_offset = self.child_insts[0].by()
        for x_offset in self.tap_offsets:
            self.add_inst(name=self.body_tap.name, mod=self.body_tap, offset=vector(x_offset, y_offset))
            self.connect_inst([])
