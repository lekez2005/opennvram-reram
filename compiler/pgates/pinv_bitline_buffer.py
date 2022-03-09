from base.utils import round_to_grid
from base.vector import vector
from pgates.pinv import pinv
from tech import drc


class pinv_bitine_buffer(pinv):
    """
    inverter with the number of fingers specified
    """
    @classmethod
    def get_name(cls, *args, size=1, fingers=None, **kwargs):
        name = "pinv_bitline_buffer_{:.2g}".format(size).replace(".", "_")
        if fingers is not None:
            name += "_f_{}".format(fingers)
        return name

    def __init__(self, *args, fingers=None, **kwargs):
        self.fingers = fingers
        super().__init__(*args, **kwargs)

    @classmethod
    def get_number_fingers(cls, fingers):
        if isinstance(fingers, int):
            return fingers

        poly_width = drc["minwidth_poly"]
        poly_space = drc["poly_to_poly"]
        poly_pitch = poly_width + poly_space

        bitcell = cls.bitcell
        num_poly = round(bitcell.width/poly_pitch) - 1
        return int(num_poly/2)

    def shrink_if_needed(self):
        pass

    def determine_tx_mults(self):

        self.tx_mults = self.get_number_fingers(self.fingers)
        spaces = self.get_total_vertical_space()

        self.nmos_size = self.nmos_scale * self.size
        self.pmos_size = self.beta * self.pmos_scale * self.size

        min_tx_width = drc["minwidth_tx"]

        self.nmos_width = max(round_to_grid(self.nmos_size * drc["minwidth_tx"]/self.tx_mults),
                              min_tx_width)
        self.pmos_width = max(round_to_grid(self.pmos_size * drc["minwidth_tx"]/self.tx_mults),
                              min_tx_width)

        self.height = self.nmos_width + self.pmos_width + spaces

    def setup_layout_constants(self):
        super().setup_layout_constants()

    def add_poly(self):
        poly_offsets = []
        half_dummy = int(0.5*self.no_dummy_poly)
        poly_layers = half_dummy * ["po_dummy"] + self.tx_mults * ["poly"] + half_dummy * ["po_dummy"]
        skipped_rects = [0, len(poly_layers)-2, len(poly_layers)-1]
        for i in range(len(poly_layers)):
            mid_offset = vector(self.poly_x_start + i*self.poly_pitch, self.mid_y)
            poly_offsets.append(mid_offset)
            offset = mid_offset - vector(0.5*self.poly_width,
                                         0.5*self.middle_space + self. nmos_width + self.poly_extend_active)
            if i in skipped_rects:
                continue
            self.add_rect(poly_layers[i], offset=offset, width=self.poly_width, height=self.poly_height)

        if half_dummy > 0:
            self.dummy_x = poly_offsets[1][0]
            self.poly_offsets = poly_offsets[half_dummy: -half_dummy]
        else:
            self.poly_offsets = poly_offsets

    def connect_to_out_pin(self, positions, mid_y, contact_shift):
        offset = vector(positions[0] - 0.5*self.m2_width, mid_y - 0.5 * self.m2_width)
        self.add_layout_pin("Z", "metal2", offset=offset, width=self.m2_width, height=self.m2_width)
        return

    def add_output_pin(self):
        pass

    def add_implants(self):
        well_x = 0.5 * (self.width - self.implant_width)

        implant_width = self.active_width + 2 * self.implant_enclose_ptx_active
        implant_x = 0.5*(self.width - implant_width)

        self.extra_implant = max(0.0, drc["ptx_implant_enclosure_active"] - 0.5 * self.poly_to_field_poly)
        nimplant_y = -self.extra_implant
        self.nimplant_height = self.mid_y + self.extra_implant
        self.pimplant_height = self.nwell_height = self.height - self.mid_y + self.extra_implant

        self.add_rect("nimplant", offset=vector(implant_x, nimplant_y),
                      width=implant_width, height=self.nimplant_height)
        self.add_rect("pimplant", offset=vector(implant_x, self.mid_y), width=implant_width,
                      height=self.pimplant_height)
        self.add_rect("nwell", offset=vector(well_x, self.mid_y), width=self.nwell_width, height=self.nwell_height)

        x_offset = 0.5 * (self.width - self.pmet_width)
        self.add_rect("pmet", offset=vector(x_offset, self.mid_y), width=self.pmet_width, height=self.nwell_height)




