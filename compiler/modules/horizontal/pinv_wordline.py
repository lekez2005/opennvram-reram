from base import utils, contact, unique_meta
from base.design import METAL1
from base.vector import vector
from modules.horizontal.wordline_pgate_horizontal import wordline_pgate_horizontal


class pinv_wordline(wordline_pgate_horizontal, metaclass=unique_meta.Unique):
    nmos_pmos_nets_aligned = True
    pgate_name = "pinv_wordline"

    def get_ptx_connections(self):
        return [
            (self.pmos, ["Z", "A", "vdd", "vdd"]),
            (self.nmos, ["Z", "A", "gnd", "gnd"])
        ]

    def get_source_drain_connections(self):
        sources = list(range(0, self.num_fingers + 1, 2))
        drains = list(range(1, self.num_fingers + 1, 2))
        return [
            (sources, sources),
            (drains, drains)
        ]

    def add_pins(self):
        """ Adds pins for spice netlist """
        self.add_pin_list(["A", "Z", "vdd", "gnd"])

    def calculate_constraints(self):
        """Evaluate finger widths and number of fingers"""
        nmos_width = max(self.size * self.min_tx_width, self.min_tx_width)
        pmos_width = max(self.beta * self.size * self.min_tx_width, self.min_tx_width)

        self.num_fingers = 2
        max_fingers = self.max_num_fingers
        if self.bitcell_top_overlap and max_fingers % 2 == 1:
            max_fingers -= 1

        num_fingers = max_fingers
        finger_width = 0
        while finger_width < self.min_tx_width:
            finger_width = min(nmos_width, pmos_width) / num_fingers
            num_fingers -= 1
        self.num_fingers = max(num_fingers, 1)
        self.tx_mults = self.num_fingers

        self.nmos_finger_width = utils.round_to_grid(nmos_width / self.num_fingers)
        self.pmos_finger_width = utils.round_to_grid(pmos_width / self.num_fingers)

    def connect_inputs(self):
        poly_y, _, _ = self.get_poly_y_offsets(self.num_fingers)
        for i in range(len(poly_y)):
            self.add_poly_contact(self.gate_contact_x + 0.5 * self.contact_width,
                                  poly_y[i] + 0.5 * self.poly_width)

        x_extension = utils.round_to_grid(0.5 * (contact.poly.second_layer_height
                                                 - contact.poly.contact_width))
        y_extension = utils.round_to_grid(0.5 * (contact.poly.second_layer_width
                                                 - contact.poly.contact_width))
        pin_y = poly_y[0] + 0.5 * self.poly_width - 0.5 * self.contact_width - y_extension
        pin_width = self.contact_width + 2 * x_extension
        pin_top = poly_y[-1] + 0.5 * self.poly_width + 0.5 * self.contact_width + y_extension
        pin_x = self.gate_contact_x - x_extension
        self.add_layout_pin("A", METAL1, offset=vector(pin_x, pin_y),
                            width=pin_width, height=pin_top - pin_y)
