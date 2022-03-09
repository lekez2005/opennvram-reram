import debug
from base import contact
from base import design
from base.vector import vector
from pgates.pinv import pinv
from pgates.pnand2 import pnand2
from pgates.pnor2 import pnor2


class SignalGate(design.design):
    """
    Gates a signal based on bank sel. The gated output is buffered based on the buffer sizes input list.
    The last output is labeled out and the penultimate output is labelled out_bar regardless of number of buffer stages
    """
    def __init__(self, buffer_stages, contact_pwell=True, contact_nwell=True, logic="and"):
        if buffer_stages is None or len(buffer_stages) < 1:
            debug.error("There should be at least one buffer stage", 1)
        self.buffer_stages = buffer_stages
        self.contact_pwell = contact_pwell
        self.contact_nwell = contact_nwell
        self.logic = logic

        name = self.get_name()

        design.design.__init__(self, name)
        debug.info(2, "Create signal gate with stages: [{}] ".format(",".join(map(str, buffer_stages))))
        self.x_offset = 0.0
        self.module_insts = []
        self.out_names = []
        self.total_instances = len(buffer_stages) + 1
        self.add_pins()
        self.create_layout()
        self.DRC_LVS()

    def get_name(self):
        name = "signal_gate_" + "_".join(map(str, self.buffer_stages))
        if not self.logic == "and":
            name += "_{}".format(self.logic)
        return name

    def add_pins(self):
        self.add_pin("en")
        self.add_pin("in")
        self.add_pin("out")
        self.add_pin("out_inv")
        self.add_pin("vdd")
        self.add_pin("gnd")


    def create_layout(self):
        self.add_logic()
        self.add_buffers()
        self.route_input_pins()
        self.add_out_pins()
        self.add_power_pins()
        self.width = self.x_offset
        self.height = self.module_insts[-1].height

    def create_buffer_inv(self, size):
        return pinv(size=size, contact_nwell=self.contact_nwell, contact_pwell=self.contact_pwell)

    def add_buffers(self):
        for size in self.buffer_stages:
            inv = self.create_buffer_inv(size)
            self.add_mod(inv)
            index = len(self.module_insts)
            inv_inst = self.add_inst("inv{}".format(index), inv, offset=vector(self.x_offset, 0))
            self.module_insts.append(inv_inst)
            out_name = self.get_out_pin()
            in_name = self.out_names[-1]
            self.connect_inst([in_name, out_name, "vdd", "gnd"])

            z_pin = self.module_insts[-2].get_pin("Z")
            a_pin = self.module_insts[-1].get_pin("A")
            self.add_rect("metal1", offset=vector(z_pin.rx(), a_pin.cy()-0.5*self.m1_width), width=a_pin.lx()-z_pin.rx())

            self.out_names.append(out_name)

            self.x_offset += inv.width

    def create_logic_mod(self):
        if self.logic == "and":
            self.logic_mod = pnand2(1, contact_nwell=self.contact_nwell, contact_pwell=self.contact_pwell)
        else:
            self.logic_mod = pnor2(1, contact_nwell=self.contact_nwell, contact_pwell=self.contact_pwell)

    def add_logic(self):
        """Add nand2 or nor2 instance and connect the input pins"""
        self.create_logic_mod()
        self.add_mod(self.logic_mod)

        self.logic_inst = self.add_inst(name=self.logic_mod.name, mod=self.logic_mod, offset=vector(self.x_offset, 0))
        self.module_insts.append(self.logic_inst)
        nand_out = self.get_out_pin()
        self.out_names.append(nand_out)
        self.connect_inst(["in", "en", nand_out, "vdd", "gnd"])
        self.x_offset += self.logic_mod.width



    def route_input_pins(self):
        # connect input pins
        pins = sorted([self.logic_inst.get_pin("A"), self.logic_inst.get_pin("B")], key=lambda x: x.cy(), reverse=True)
        pin_names = ["en", "in"]
        rail_x = 0.5 * self.m2_width
        for i in range(len(pins)):
            pin = pins[i]
            self.add_rect("metal2", offset=vector(rail_x, pin.cy() - 0.5 * self.m2_width), width=pin.cx() - rail_x)
            if i == 1 and self.logic == "or":
                self.add_contact(contact.m1m2.layer_stack, offset=pin.lr(), rotate=90)
            elif i == 1:
                self.add_contact(layers=contact.contact.m1m2_layers, offset=pin.lr(), rotate=90)
            else:
                y_offset = pin.uy() - contact.m1m2.second_layer_height
                self.add_contact(layers=contact.contact.m1m2_layers, offset=vector(pin.lx(), y_offset))
            self.add_layout_pin(pin_names[i], "metal2", offset=vector(rail_x, 0), height=pin.cy())
            rail_x += self.parallel_line_space + self.m2_width



    def add_out_pins(self):
        pin_names = ["out_inv", "out"]
        instances = self.module_insts[-2:]
        for i in range(2):
            instance = instances[i]
            z_pin = instance.get_pin("Z")
            self.add_layout_pin(pin_names[i], "metal2", offset=vector(z_pin.lx(), 0), height=z_pin.by())

    def add_power_pins(self):
        pin_names = ["vdd", "gnd"]
        instance = self.module_insts[-1]
        pins = [instance.get_pin("vdd"), instance.get_pin("gnd")]
        for i in range(2):
            pin = pins[i]
            self.add_layout_pin(pin_names[i], pin.layer, offset=vector(0, pin.by()),
                                height=pin.height(), width=pin.rx())


    def get_out_pin(self):
        no_modules = len(self.module_insts)
        if no_modules == self.total_instances - 1:
            return "out_inv"
        elif no_modules == self.total_instances:
            return "out"
        else:
            return "out_{}".format(no_modules)



