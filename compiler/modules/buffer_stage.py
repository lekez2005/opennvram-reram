import debug
from base import design
from base.unique_meta import Unique
from base.vector import vector
from pgates.pinv import pinv


class BufferStage(design.design, metaclass=Unique):
    """
    Buffers the in pin
    The last output is labeled out and the penultimate output is labelled out_bar regardless of number of buffer stages
    """

    def __init__(self, buffer_stages, height=None, route_outputs=True, contact_pwell=True,
                 contact_nwell=True, align_bitcell=False, fake_contacts=False):
        if buffer_stages is None or len(buffer_stages) < 1:
            debug.error("There should be at least one buffer stage", 1)
        self.buffer_stages = buffer_stages
        self.contact_pwell = contact_pwell
        self.contact_nwell = contact_nwell
        self.route_outputs = route_outputs
        self.align_bitcell = align_bitcell
        self.fake_contacts = fake_contacts

        self.module_insts = []
        self.buffer_invs = []

        if height is None:
            height = pinv.bitcell.height
        self.height = height

        design.design.__init__(self, self.name)
        debug.info(2, "Create logic buffers with stages: [{}] ".format(",".join(map(str, buffer_stages))))

        self.height = height  # init resets height

        self.x_offset = 0.0
        self.out_names = []
        self.total_instances = len(buffer_stages)
        self.add_pins()
        self.create_layout()
        self.DRC_LVS()

    @classmethod
    def get_name(cls, buffer_stages, height=None, route_outputs=True, contact_pwell=True,
                 contact_nwell=True, align_bitcell=False, fake_contacts=False):
        name = "buffer_stage_" + "_".join(['{:.3g}'.format(x) for x in buffer_stages])
        if not route_outputs:
            name += "_no_out"
        if not contact_nwell:
            name += "_no_nwell_cont"
        if not contact_pwell:
            name += "_no_pwell_cont"
        if not height == pinv.bitcell.height:
            name += "_h_{:.4g}".format(height)
        if align_bitcell:
            name += "_align"
        if fake_contacts:
            name += "_fake_c"

        return name.replace(".", "__")

    def add_pins(self):
        self.add_pin("in")
        self.add_pin("out_inv")
        self.add_pin("out")
        self.add_pin("vdd")
        self.add_pin("gnd")

    def create_layout(self):
        self.add_buffers()
        self.route_in_pin()
        self.route_out_pins()
        self.fill_wells()
        self.add_power_pins()
        self.width = self.x_offset
        self.height = self.module_insts[-1].height

    def create_buffer_inv(self, size, index=None):
        return pinv(size=size, height=self.height, contact_nwell=self.contact_nwell,
                    contact_pwell=self.contact_pwell, align_bitcell=self.align_bitcell,
                    fake_contacts=self.fake_contacts)

    def join_a_z_pins(self, a_pin, z_pin):
        self.add_rect("metal1", offset=vector(z_pin.rx(), a_pin.cy() - 0.5 * self.m1_width),
                      width=a_pin.lx() - z_pin.rx())

    def add_buffers(self):
        for i in range(self.total_instances):
            size = self.buffer_stages[i]
            inv = self.create_buffer_inv(size, index=i)
            self.add_mod(inv)
            self.buffer_invs.append(inv)

            if i > 0:
                self.x_offset += inv.calculate_min_space(self.module_insts[-1].mod, inv)

            index = len(self.module_insts)
            inv_inst = self.add_inst("inv{}".format(index), inv, offset=vector(self.x_offset, 0))
            self.module_insts.append(inv_inst)
            out_name = self.get_out_pin()

            if i == 0:
                in_name = "in"
            else:
                in_name = self.out_names[-1]
                z_pin = self.module_insts[-2].get_pin("Z")
                a_pin = self.module_insts[-1].get_pin("A")
                self.join_a_z_pins(a_pin, z_pin)

            self.connect_inst([in_name, out_name, "vdd", "gnd"])

            self.out_names.append(out_name)

            self.x_offset += inv.width

    def route_in_pin(self):
        self.copy_layout_pin(self.module_insts[0], "A", "in")

    def route_out_pins(self):
        if self.total_instances == 1:
            pin_names = ["out_inv"]
            instances = self.module_insts[-1:]
        elif self.total_instances % 2 == 0:
            pin_names = ["out_inv", "out"]
            instances = self.module_insts[-2:]
        else:
            pin_names = ["out", "out_inv"]
            instances = self.module_insts[-2:]

        for i in range(len(instances)):
            instance = instances[i]
            if self.route_outputs:
                z_pin = instance.get_pin("Z")
                self.add_layout_pin(pin_names[i], "metal2", offset=vector(z_pin.lx(), 0), height=z_pin.by())
            else:
                self.copy_layout_pin(instance, "Z", pin_names[i])

    def fill_wells(self):
        for left_inst, right_inst in zip(self.module_insts[:-1], self.module_insts[1:]):
            pinv.fill_adjacent_wells(self, left_inst, right_inst)

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
        if no_modules == self.total_instances:
            return "out" if (self.total_instances % 2) == 0 else "out_inv"
        elif no_modules == self.total_instances - 1:
            return "out_inv" if (self.total_instances % 2) == 0 else "out"
        else:
            return "out_{}".format(no_modules)
