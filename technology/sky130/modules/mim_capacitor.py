from base import utils
from base.design import design
from base.unique_meta import Unique
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts

from tech import drc, add_tech_layers
import tech


class MimCapacitor(design, metaclass=Unique):

    @classmethod
    def get_name(cls, width, height):
        return f"mim_cap_w{width:.4g}_h{height:.4g}".replace(".", "__")

    def __init__(self, width, height):
        name = self.get_name(width, height)
        design.__init__(self, name)
        self.cap_width = utils.round_to_grid(width)
        self.cap_height = utils.round_to_grid(height)
        self.add_pin_list(["c0", "c1"])
        self.create_layout()

    def create_layout(self):
        self.set_cap_layers()
        self.calculate_dimensions()
        self.add_layers()
        add_tech_layers(self)
        self.add_boundary()

    def set_cap_layers(self):
        self.top_layer = getattr(tech, "mim_cap_top_layer")
        self.bottom_layer = getattr(tech, "mim_cap_bottom_layer")
        self.cap_via_layer = getattr(tech, "mim_cap_via_layer")
        self.mim_cap_layer = getattr(tech, "mim_cap_cap_layer")
        self.via_stack = (self.bottom_layer, self.cap_via_layer, self.top_layer)

    def calculate_dimensions(self):
        bottom_enclosure = getattr(tech, "mim_cap_bottom_enclosure")
        top_enclosure = getattr(tech, "mim_cap_top_enclosure")

        self.bottom_width = self.width = self.cap_width + 2 * bottom_enclosure
        self.bottom_height = self.height = self.cap_height + 2 * bottom_enclosure
        self.center_pos = vector(0.5 * self.width, 0.5 * self.height)

        self.top_width = self.cap_width - 2 * top_enclosure
        self.top_height = self.cap_height - 2 * top_enclosure

        self.num_x_contacts = calculate_num_contacts(self, self.cap_width, layer_stack=self.via_stack)
        self.num_y_contacts = calculate_num_contacts(self, self.cap_height, layer_stack=self.via_stack)

    def add_layers(self):

        self.add_layout_pin_center_rect("c1", self.bottom_layer, offset=self.center_pos,
                                        width=self.bottom_width, height=self.bottom_height)
        self.add_layout_pin_center_rect("c0", self.top_layer, offset=self.center_pos,
                                        width=self.top_width, height=self.top_height)
        self.add_rect_center(self.mim_cap_layer, self.center_pos, width=self.cap_width,
                             height=self.cap_height)

        self.add_contact_center(self.via_stack, offset=self.center_pos,
                                size=[self.num_x_contacts, self.num_y_contacts])

    def sp_write_file(self, sp, usedMODS):
        model_name = tech.spice["mim_cap_name"]
        pins = " ".join(self.pins)
        spice_device = f"X0 {pins} {model_name} w={self.cap_width:.4g} l={self.cap_height:.4g}"
        sp.write(f"\n.SUBCKT {self.name} {pins}\n {spice_device}\n.ENDS\n")
