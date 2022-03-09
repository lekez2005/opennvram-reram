import debug
from base import design
from base.vector import vector
from pgates.pinv import pinv


class ControlLogicBuffer(design.design):

    def __init__(self, buffers, contact_nwell=True, contact_pwell=True):
        name = "ctrl_buffer_{}_{}".format(buffers[0], buffers[1])
        if not contact_nwell:
            name += "_no_nwell"
        if not contact_pwell:
            name += "_no_pwell"

        name = name.replace(".", "_")

        design.design.__init__(self, name)

        debug.info(2, "Create control logic buffer of size {}-{}".format(buffers[0], buffers[1]))
        self.contact_nwell = contact_nwell
        self.contact_pwell = contact_pwell
        self.buffers = buffers

        self.create_layout()

    def create_layout(self):
        self.add_pins()
        self.create_modules()
        self.add_modules()
        self.add_contact_implants()
        self.route()
        self.add_layout_pins()

    def add_pins(self):
        self.add_pin_list(["in", "out", "vdd", "gnd"])

    def create_modules(self):
        self.input_inv = pinv(size=self.buffers[0], contact_nwell=self.contact_nwell, contact_pwell=self.contact_pwell)
        self.output_inv = pinv(size=self.buffers[1], contact_nwell=self.contact_nwell, contact_pwell=self.contact_pwell)
        self.add_mod(self.input_inv)
        self.add_mod(self.output_inv)

    def add_modules(self):
        offset = vector(0, 0)
        self.input_inv_inst = self.add_inst("input_inv", self.input_inv, offset=offset)
        self.connect_inst(["in", "in_bar", "vdd", "gnd"])
        self.output_inv_inst = self.add_inst("output_inv", self.output_inv,
                                             offset=offset + vector(self.input_inv.width, 0))
        self.connect_inst(["in_bar", "out", "vdd", "gnd"])

        self.width = self.output_inv_inst.rx()
        self.height = self.output_inv_inst.height

    def add_contact_implants(self):
        pimplants = self.input_inv.get_layer_shapes("pimplant")
        nimplants = self.input_inv.get_layer_shapes("nimplant")
        if not self.contact_nwell:
            top_pimplant = max(pimplants, key=lambda x: x.uy())
            self.add_rect("nimplant", offset=top_pimplant.ul(), width=self.width,
                          height=2 * (self.height - top_pimplant.uy()))
        if not self.contact_nwell:
            bot_nimplant = min(nimplants, key=lambda x: x.by())
            self.add_rect("pimplant", offset=vector(0, -bot_nimplant.by()), width=self.width,
                          height=2*bot_nimplant.by())


    def route(self):
        z_pin = self.input_inv_inst.get_pin("Z")
        a_pin = self.output_inv_inst.get_pin("A")
        self.add_rect("metal1", offset=vector(z_pin.rx(), a_pin.by()), width=a_pin.lx() - z_pin.rx())


    def add_layout_pins(self):
        self.copy_layout_pin(self.input_inv_inst, "A", "in")
        self.copy_layout_pin(self.output_inv_inst, "Z", "out")

        vdd_pin = self.input_inv_inst.get_pin("vdd")
        self.add_layout_pin("vdd", "metal1", offset=vdd_pin.ll(), height=vdd_pin.height(), width=self.width)

        gnd_pin = self.input_inv_inst.get_pin("gnd")
        self.add_layout_pin("gnd", "metal1", offset=gnd_pin.ll(), height=gnd_pin.height(), width=self.width)




