import debug
from base import unique_meta
from base.vector import vector
from tech import parameter, spice, add_tech_layers
from . import pgate
from .ptx_spice import ptx_spice


class pnand2(pgate.pgate, metaclass=unique_meta.Unique):
    """
    This module generates gds of a parametrically sized 2-input nand.
    This model use ptx to generate a 2-input nand within a cetrain height.
    """
    nmos_scale = 2
    pmos_scale = 1
    num_tracks = 2
    mod_name = "nand2"

    @classmethod
    def get_class_name(cls):
        return "pnand2"

    def __init__(self, size=1, height=None, contact_pwell=True, contact_nwell=True,
                 align_bitcell=False, same_line_inputs=False):
        """ Creates a cell for a simple 2 input nand """
        pgate.pgate.__init__(self, self.name, height, size=size,
                             contact_pwell=contact_pwell, contact_nwell=contact_nwell,
                             align_bitcell=align_bitcell, same_line_inputs=same_line_inputs)
        debug.info(2, "create {0} structure {1} with size of {2}".format(self.__class__.__name__,
                                                                         self.name, size))

        self.add_pins()
        self.create_layout()
        #self.DRC_LVS()

    def add_pins(self):
        """ Adds pins for spice netlist """
        self.add_pin_list(["A", "B", "Z", "vdd", "gnd"])

    def create_layout(self):
        """ Calls all functions related to the generation of the layout """

        self.shrink_if_needed()

        self.determine_tx_mults()
        # FIXME: Allow multiple fingers
        debug.check(self.tx_mults == 1,
                    "Only Single finger {} is supported now.".format(self.__class__.__name__))

        self.tx_mults *= self.num_tracks

        self.setup_layout_constants()
        self.add_poly()
        self.connect_inputs()

        self.add_active()
        self.calculate_source_drain_pos()

        self.connect_to_vdd(self.source_positions)
        self.connect_to_gnd(self.source_positions[:1])
        self.connect_s_or_d(self.drain_positions, self.source_positions[1:])
        self.add_implants()
        self.add_body_contacts()
        self.add_output_pin()
        self.add_ptx_inst()
        add_tech_layers(self)
        self.add_boundary()

    def connect_inputs(self):
        y_shifts = [-0.5*self.gate_rail_pitch, 0.5*self.gate_rail_pitch]
        pin_names = ["A", "B"]
        self.add_poly_contacts(pin_names, y_shifts)

    def get_ptx_connections(self):
        return [
            (self.pmos, ["vdd", "A", "Z", "vdd"]),
            (self.pmos, ["Z", "B", "vdd", "vdd"]),
            (self.nmos, ["Z", "B", "net1", "gnd"]),
            (self.nmos, ["net1", "A", "gnd", "gnd"])
        ]

    def input_load(self):
        return ((self.nmos_size+self.pmos_size)/parameter["min_tx_size"])*spice["min_tx_gate_c"]

    def analytical_delay(self, slew, load=0.0):
        r = spice["min_tx_r"]/(self.nmos_size/parameter["min_tx_size"])
        c_para = spice["min_tx_drain_c"]*(self.nmos_size/parameter["min_tx_size"])#ff
        return self.cal_delay_with_rc(r = r, c =  c_para+load, slew = slew)
        
    def analytical_power(self, proc, vdd, temp, load):
        """Returns dynamic and leakage power. Results in nW"""
        c_eff = self.calculate_effective_capacitance(load)
        freq = spice["default_event_rate"]
        power_dyn = c_eff*vdd*vdd*freq
        power_leak = spice["{}_leakage".format(self.mod_name)]
        
        total_power = self.return_power(power_dyn, power_leak)
        return total_power
        
    def calculate_effective_capacitance(self, load):
        """Computes effective capacitance. Results in fF"""
        c_load = load
        c_para = spice["min_tx_drain_c"]*(self.nmos_size/parameter["min_tx_size"])#ff
        transistion_prob = spice["{}_transisition_prob".format(self.mod_name)]
        return transistion_prob*(c_load + c_para) 
