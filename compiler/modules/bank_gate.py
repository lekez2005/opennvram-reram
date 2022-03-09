import debug
from base import contact
from base import design
from base.vector import vector
from globals import OPTS
from .signal_gate import SignalGate


class ControlGate:
    def __init__(self, signal_name, route_complement=False, output_dir="right"):
        self.signal_name = signal_name
        if signal_name in OPTS.bank_gate_buffers:
            self.buffer_stages = OPTS.bank_gate_buffers[signal_name]
        else:
            self.buffer_stages = OPTS.bank_gate_buffers["default"]
        self.route_complement = route_complement
        self.output_dir = output_dir


class BankGate(design.design):
    """
    Gates control signals to a bank.
    The input pins is the bank_sel signal and the control pins
    The output pins are logical (bank_sel & signal) for each signal alongside the complement when necessary
    """
    def __init__(self, control_gates, contact_pwell=True, contact_nwell=True):
        self.control_gates = control_gates  # type: list[ControlGate]
        self.left_outputs = list(filter(lambda gate: gate.output_dir == "left", control_gates))
        self.right_outputs = list(filter(lambda gate: gate.output_dir == "right", control_gates))
        self.contact_pwell = contact_pwell
        self.contact_nwell = contact_nwell
        name = "bank_gate"
        design.design.__init__(self, name)
        debug.info(2, "Create bank gate")

        self.x_offset = 0.0
        self.rail_index = 0

        self.output_rail_top_index = 0
        self.top_pins = []

        self.bank_sel_name = "bank_sel"

        self.rails_y = []  # keep track of y offset of rails
        self.module_insts = []
        self.create_pins()
        self.create_layout()
        self.DRC_LVS()

    def create_pins(self):
        self.add_pin("bank_sel")
        for ctrl_gate in self.control_gates:
            self.add_pin(ctrl_gate.signal_name)
        for ctrl_gate in self.control_gates:
            if ctrl_gate.route_complement:
                self.add_pin("gated_{}_bar".format(ctrl_gate.signal_name))
            self.add_pin("gated_" + ctrl_gate.signal_name)
        self.add_pin("vdd")
        self.add_pin("gnd")

    def create_layout(self):
        self.setup_layout_constants()
        self.add_instances()

        self.width = self.module_insts[-1].rx()

        self.add_bank_sel()

        self.route_all_outputs()
        self.add_power_pins()
        if len(self.top_pins) == 0:
            self.height = self.module_insts[-1].uy()
        else:
            self.height = self.top_pins[-1].uy()

    def setup_layout_constants(self):
        num_bottom_complements = len(list(filter(lambda x: x.route_complement, self.right_outputs)))
        num_top_complements = len(list(filter(lambda x: x.route_complement, self.left_outputs)))
        self.rail_pitch = self.m1_width + self.parallel_line_space

        self.num_bottom_rails = (self.get_num_sel_signals() +
                                 max(len(self.control_gates), len(self.right_outputs)) + num_bottom_complements)

        self.num_top_rails = len(self.left_outputs) + num_top_complements

        self.bank_sel_y = (self.num_bottom_rails - 1) * self.rail_pitch
        self.instances_y = self.bank_sel_y + self.rail_pitch + 0.5*self.rail_height

    def get_num_sel_signals(self):
        return 1  # bank_sel


    def add_instances(self):
        for i in range(len(self.control_gates)):
            ctrl_gate = self.control_gates[i]
            name = ctrl_gate.signal_name
            sig_gate = SignalGate(ctrl_gate.buffer_stages, contact_pwell=self.contact_pwell,
                                  contact_nwell=self.contact_nwell)
            self.add_mod(sig_gate)
            instance = self.add_inst(name+"_inst", sig_gate,
                                     offset=vector(self.x_offset, self.instances_y))
            self.connect_inst([self.bank_sel_name, name, "gated_" + name, "gated_" + name + "_bar", "vdd", "gnd"])
            self.module_insts.append(instance)
            self.route_input(instance, ctrl_gate)

            self.rail_index += 1 + int(ctrl_gate.route_complement and ctrl_gate.output_dir == "right")

            self.x_offset += sig_gate.width

    def route_input(self, instance, ctrl_gate):
        """route signal gate input and bank_sel"""
        en_pin = instance.get_pin("en")
        in_pin = instance.get_pin("in")
        in_rail_y = self.rail_index * self.rail_pitch
        self.rails_y.append(in_rail_y)

        pins = [en_pin, in_pin]
        y_offsets = [self.bank_sel_y, in_rail_y]

        for i in range(2):
            pin = pins[i]
            self.add_via(layers=contact.contact.m1m2_layers, offset=vector(pin.rx(), y_offsets[i]), rotate=90)
            self.add_rect("metal2", offset=vector(pin.lx(), y_offsets[i]), height=pin.by()-y_offsets[i])
        pin_width = max(instance.get_pin("in").rx(), self.metal1_minwidth_fill)
        self.add_layout_pin(ctrl_gate.signal_name, "metal1", offset=vector(0, in_rail_y), width=pin_width)

    def add_bank_sel(self):
        y_offset = self.bank_sel_y
        self.add_rect("metal1", offset=vector(0, y_offset), width=self.width)
        x_offset = self.module_insts[0].get_pin("en").rx()
        self.add_layout_pin("bank_sel", "metal2", offset=vector(0, y_offset), width=x_offset)

    def route_all_outputs(self):
        for i in range(len(self.module_insts)):
            ctrl_gate = self.control_gates[i]
            if ctrl_gate.output_dir == "right":
                self.route_right_output(self.module_insts[i], self.control_gates[i], self.rails_y[i])
            else:
                self.route_left_output(self.module_insts[i], self.control_gates[i])

    def route_right_output(self, instance, ctrl_gate, y_offset):
        out_pin = instance.get_pin("out")
        out_inv = instance.get_pin("out_inv")

        # route out_inv
        if ctrl_gate.route_complement:
            self.add_rect("metal2", offset=vector(out_inv.lx(), y_offset), height=out_inv.by() - y_offset)
            self.add_contact(contact.contact.m1m2_layers,
                             offset=vector(out_inv.lx() + contact.m1m2.second_layer_height, y_offset),
                             rotate=90)
            pin_name = "gated_{}_bar".format(ctrl_gate.signal_name)
            self.add_layout_pin(pin_name, "metal1", offset=vector(out_inv.lx(), y_offset),
                                width=self.width - out_inv.lx())

            y_offset += self.rail_pitch

        # route out pin, need to move left to avoid next signal's input
        gnd_pin = instance.get_pin("gnd")
        self.add_rect("metal2", offset=vector(out_pin.lx(), gnd_pin.cy()), height=out_pin.by() - gnd_pin.cy())
        x_offset = out_pin.lx() - self.line_end_space - self.m2_width
        self.add_rect("metal2", offset=vector(x_offset, gnd_pin.cy() - 0.5*self.m2_width),
                      width=out_pin.rx()-x_offset)
        self.add_rect("metal2", offset=vector(x_offset, y_offset), height=gnd_pin.cy() - y_offset)
        self.add_contact(contact.contact.m1m2_layers,
                         offset=vector(x_offset + contact.m1m2.second_layer_height, y_offset),
                         rotate=90)
        pin_name = "gated_" + ctrl_gate.signal_name
        pin_width = max(self.metal1_minwidth_fill, self.width - x_offset)
        self.add_layout_pin(pin_name, "metal1", offset=vector(self.width - pin_width, y_offset), width=pin_width)

    def route_left_output(self, instance, ctrl_gate):

        pins = [instance.get_pin("out"), instance.get_pin("out_inv")]
        output_names = ["gated_" + ctrl_gate.signal_name, "gated_{}_bar".format(ctrl_gate.signal_name)]
        if ctrl_gate.route_complement:
            indices = [1, 0]
        else:
            indices = [0]
        for index in indices:
            pin = pins[index]
            output_name = output_names[index]
            if len(self.top_pins) == 0:
                y_offset = self.module_insts[0].uy()
            else:
                y_offset = self.top_pins[-1].by() + self.rail_pitch

            self.add_rect("metal2", offset=pin.ul(), width=pin.width(), height=y_offset - pin.uy() + self.m2_width)
            self.top_pins.append(self.add_layout_pin(output_name, "metal2", offset=vector(0, y_offset), width=pin.lx()))






    def add_power_pins(self):
        pin_names = ["vdd", "gnd"]
        instance = self.module_insts[-1]
        pins = [instance.get_pin("vdd"), instance.get_pin("gnd")]
        for i in range(2):
            pin = pins[i]
            self.add_layout_pin(pin_names[i], pin.layer, offset=vector(0, pin.by()),
                                height=pin.height(), width=pin.rx())


