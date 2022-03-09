from base import contact
from base.contact import m1m2, m2m3
from base.design import METAL1, METAL2, METAL3
from base.vector import vector
from modules.ms_flop_array import ms_flop_array


class ms_flop_array_horizontal(ms_flop_array):
    def get_name(self):
        return super().get_name() + "_horiz"

    def add_layout_pins(self):
        super().add_layout_pins()
        self.ms_inst = self.child_insts
        self.add_in_out_pins()
        self.translate_all(vector(0, self.min_y))

    def add_in_out_pins(self):
        m1m2_layers = contact.contact.m1m2_layers
        via_space = self.get_space("via2")
        rail_pitch = self.bus_width + self.get_parallel_space(METAL3)

        self.m1_rail_height = 0.5 * m1m2.first_layer_width + self.m1_space + self.word_size * rail_pitch - self.m2_space
        self.min_y = -via_space - 0.5 * m1m2.second_layer_width - self.m1_rail_height

        gnd_pins = self.ms_inst[0].get_pins("gnd")
        top_gnd_pin = max(gnd_pins, key=lambda x: x.uy())

        self.max_y = top_gnd_pin.uy() + self.m1_space + 0.5 * m1m2.second_layer_width + self.m1_rail_height
        for i in range(self.word_size):
            for pin_name in ["din", "dout"]:
                self.remove_layout_pin("{}[{}]".format(pin_name, i))

            # din
            din_pin = self.ms_inst[i].get_pin("din")

            rail_y = self.min_y + i * rail_pitch

            self.add_rect(METAL2, offset=vector(din_pin.lx(), rail_y + 0.5 * self.bus_width),
                          width=din_pin.width(),
                          height=din_pin.by() - rail_y + 0.5 * self.bus_width)
            via_y = rail_y + 0.5 * self.bus_width
            self.add_contact_center(m2m3.layer_stack, offset=vector(din_pin.cx(), via_y), rotate=90)
            rail_x = din_pin.cx() - 0.5 * m2m3.height
            self.add_layout_pin("din[{}]".format(i), METAL3, offset=vector(rail_x, rail_y),
                                height=self.bus_width, width=self.width - rail_x)

            # dout

            dout_pin = self.ms_inst[i].get_pin("dout")

            rail_y = top_gnd_pin.uy() + 2 * self.m1_space + m1m2.first_layer_width + i * rail_pitch
            self.add_rect(METAL2, offset=dout_pin.ul(), width=dout_pin.width(),
                          height=rail_y - dout_pin.uy() + 0.5 * self.bus_width)
            via_y = rail_y + 0.5 * self.bus_width
            self.add_contact_center(m2m3.layer_stack, offset=vector(dout_pin.cx(), via_y), rotate=90)
            rail_x = dout_pin.cx() - 0.5 * m2m3.height
            self.add_layout_pin("dout[{}]".format(i), METAL3, offset=vector(rail_x, rail_y),
                                height=self.bus_width, width=self.width - rail_x)

            self.height = self.max_y - self.min_y
