from base.design import design
from base.hierarchy_spice import INPUT, OUTPUT
from globals import OPTS
from tech import parameter


class pgates_characterization_base:
    def is_delay_primitive(self: design):
        """Whether to descend into this module to evaluate sub-modules for delay"""
        return True

    def get_char_data_file_suffixes(self: design, **kwargs):
        return [("beta", parameter["beta"]),
                ("contacts", int(self.contact_nwell))]

    def get_char_data_size_suffixes(self: design, **kwargs):
        """
        Get filters for characterized size look up table
        :return: list of (filter_name, filter_value) tuples
        """
        return [("height", self.height)]

    def get_pin_dir(self: design, name):
        if name.lower() in ["a", "b", "c"]:
            return INPUT
        elif name.lower() == "z":
            return OUTPUT
        return super().get_pin_dir(name)

    def get_char_data_name(self: design, **kwargs) -> str:
        return self.__class__.__name__

    def get_char_data_size(self: design):
        return self.size

    def get_input_cap(self: design, pin_name, num_elements: int = 1, wire_length: float = 0.0,
                      interpolate=None, **kwargs):
        total_cap, cap_per_unit = super().get_input_cap(pin_name=pin_name, num_elements=self.size,
                                                        wire_length=wire_length, **kwargs)
        return total_cap * num_elements, cap_per_unit

    def get_input_cap_from_instances(self: design, pin_name, wire_length: float = 0.0, **kwargs):
        total_cap, cap_per_unit = super().get_input_cap_from_instances(pin_name, wire_length, **kwargs)
        # super class method doesn't consider size in calculating
        cap_per_unit /= self.size
        return total_cap, cap_per_unit

    def compute_input_cap(self: design, pin_name, wire_length: float = 0.0):
        total_cap = super().compute_input_cap(pin_name, wire_length)
        # super class method doesn't consider size in calculating
        cap_per_unit = total_cap / self.size
        return total_cap, cap_per_unit

    def get_driver_resistance(self: design, pin_name, use_max_res=False, interpolate=None, corner=None):
        if interpolate is None:
            interpolate = OPTS.interpolate_characterization_data
        resistance = self.get_input_cap_from_char("resistance", interpolate=interpolate,
                                                  corner=corner)
        if resistance:
            return resistance / self.size
        return super().get_driver_resistance(pin_name, use_max_res, interpolate, corner)
