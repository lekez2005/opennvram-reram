import debug
from base import contact, utils
from base import unique_meta
from base.design import METAL1, POLY
from base.vector import vector
from tech import parameter, spice, add_tech_layers
from . import pgate


class pinv(pgate.pgate, metaclass=unique_meta.Unique):
    """
    Pinv generates gds of a parametrically sized inverter. The
    size is specified as the drive size (relative to minimum NMOS) and
    a beta value for choosing the pmos size.  The inverter's cell
    height is usually the same as the 6t library cell and is measured
    from center of rail to rail..  The route_output will route the
    output to the right side of the cell for easier access.
    """

    @classmethod
    def get_class_name(cls):
        return "pinv"

    num_tracks = 1

    def __init__(self, size=1, beta=None, height=None,
                 contact_pwell=True, contact_nwell=True, align_bitcell=False,
                 same_line_inputs=True, fake_contacts=False):
        # We need to keep unique names because outputting to GDSII
        # will use the last record with a given name. I.e., you will
        # over-write a design in GDS if one has and the other doesn't
        # have poly connected, for example.
        if beta is None:
            beta = parameter["beta"]
        if beta * size < 1:
            beta = parameter["beta"]

        pgate.pgate.__init__(self, self.name, height, size=size, beta=beta,
                             contact_pwell=contact_pwell,
                             contact_nwell=contact_nwell, align_bitcell=align_bitcell,
                             same_line_inputs=same_line_inputs, fake_contacts=fake_contacts)
        debug.info(2, "create pinv structure {0} with size of {1}".format(self.name, size))

        self.add_pins()
        self.create_layout()

        # for run-time, we won't check every transitor DRC/LVS independently
        # but this may be uncommented for debug purposes
        # self.DRC_LVS()

    def add_pins(self):
        """ Adds pins for spice netlist """
        self.add_pin_list(["A", "Z", "vdd", "gnd"])

    def create_layout(self):

        self.nmos_scale = 1
        self.pmos_scale = 1

        # sometimes width/tx_mults < min_width,
        # in such case, round up to min_width and scale width accordingly
        try:
            self.determine_tx_mults()
        except AssertionError:
            self.size = self.tx_mults
            self.determine_tx_mults()
        self.determine_tx_mults()
        self.setup_layout_constants()
        self.add_poly()
        self.add_poly_contacts()
        self.add_active()
        self.calculate_source_drain_pos()
        self.connect_to_vdd(self.source_positions)
        self.connect_to_gnd(self.source_positions)
        self.connect_s_or_d(self.drain_positions, self.drain_positions)
        self.add_implants()
        self.add_body_contacts()
        self.add_output_pin()
        self.add_ptx_inst()
        add_tech_layers(self)
        self.add_boundary()

    def validate_min_widths(self):
        # logic gates must pass min-width requirement, inverter width is determined later
        return self.min_tx_width, max(1, self.beta) * self.min_tx_width

    def get_tx_widths(self):
        nmos_width, pmos_width = super().get_tx_widths()
        return max(nmos_width, self.min_tx_width), max(pmos_width, self.min_tx_width)

    def get_total_vertical_space(self, nmos_width=None, pmos_width=None):
        """Use min-tx width for calculating vertical spaces"""
        if nmos_width is None:
            nmos_width = utils.ceil(self.nmos_scale * self.min_tx_width)
        if pmos_width is None:
            pmos_width = utils.ceil(self.pmos_scale * self.beta * self.min_tx_width)
        return super().get_total_vertical_space(nmos_width, pmos_width)

    def add_poly_contacts(self):
        if self.tx_mults == 1:
            pin_height = contact.poly.second_layer_height
            _, width = self.calculate_min_area_fill(pin_height, layer=METAL1)
            width = max(width, self.m1_width)
            offset = vector(self.active_mid_x, self.mid_y)
            self.add_layout_pin_center_rect("A", METAL1, offset, width=width,
                                            height=pin_height)
            offset = vector(self.active_mid_x, self.mid_y)
            self.add_contact_center(layers=contact.poly.layer_stack, offset=offset)

        else:
            contact_width = contact.poly.second_layer_width
            for i in range(len(self.poly_offsets)):
                offset = vector(self.poly_offsets[i].x, self.mid_y)
                self.add_contact_center(layers=contact.poly.layer_stack, offset=offset)

            min_poly = min(self.poly_offsets, key=lambda x: x.x).x
            max_poly = max(self.poly_offsets, key=lambda x: x.x).x
            pin_left = min_poly - 0.5 * contact_width
            pin_right = max_poly + 0.5 * contact_width
            offset = vector(0.5 * (pin_left + pin_right), self.mid_y)
            self.add_layout_pin_center_rect("A", METAL1, offset, width=pin_right - pin_left)
            # join space between poly
            poly_width = self.ptx_poly_width
            poly_cont_width = contact.poly.first_layer_width
            if poly_cont_width > poly_width:  # horizontal poly allowed
                actual_poly_space = self.ptx_poly_space - (poly_cont_width - poly_width)
                if actual_poly_space < self.poly_space:
                    self.add_rect(POLY,
                                  vector(min_poly, self.mid_y - 0.5 * contact.poly.first_layer_height),
                                  width=max_poly - min_poly, height=contact.poly.first_layer_height)

    def get_ptx_connections(self):
        return [
            (self.pmos, ["Z", "A", "vdd", "vdd"]),
            (self.nmos, ["Z", "A", "gnd", "gnd"])
        ]

    def input_load(self):
        return ((self.nmos_size + self.pmos_size) / parameter["min_tx_size"]) * spice["min_tx_gate_c"]

    def analytical_delay(self, slew, load=0.0):
        r = spice["min_tx_r"] / (self.nmos_size / parameter["min_tx_size"])
        c_para = spice["min_tx_drain_c"] * (self.nmos_size / parameter["min_tx_size"])  # ff
        return self.cal_delay_with_rc(r=r, c=c_para + load, slew=slew)

    def analytical_power(self, proc, vdd, temp, load):
        """Returns dynamic and leakage power. Results in nW"""
        c_eff = self.calculate_effective_capacitance(load)
        freq = spice["default_event_rate"]
        power_dyn = c_eff * vdd * vdd * freq
        power_leak = spice["inv_leakage"]

        total_power = self.return_power(power_dyn, power_leak)
        return total_power

    def calculate_effective_capacitance(self, load):
        """Computes effective capacitance. Results in fF"""
        c_load = load
        c_para = spice["min_tx_drain_c"] * (self.nmos_size / parameter["min_tx_size"])  # ff
        transistion_prob = spice["inv_transisition_prob"]
        return transistion_prob * (c_load + c_para)
