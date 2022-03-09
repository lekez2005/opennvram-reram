import debug
from base import design
from base import unique_meta
from base import utils
from base.vector import vector
from tech import drc, layer as tech_layer


class contact(design.design, metaclass=unique_meta.Unique):
    """
    Object for a contact shape with its conductor enclosures.
    Creates a contact array minimum active or poly enclosure and metal1 enclosure.
    This class has enclosure on multiple sides of the contact whereas a via may
    have extension on two or four sides.
    The well/implant_type is an option to add a select/implant layer enclosing the contact. This is
    necessary to import layouts into Magic which requires the select to be in the same GDS
    hierarchy as the contact.
    """

    active_layers = ("active", "contact", "metal1")
    poly_layers = ("poly", "contact", "metal1")
    m1m2_layers = ("metal1", "via1", "metal2")
    m2m3_layers = ("metal2", "via2", "metal3")

    @classmethod
    def get_name(cls, layer_stack, dimensions=[1,1], implant_type=None, well_type=None,
                 area_fill=False):
        if implant_type or well_type:
            name = "{0}_{1}_{2}_{3}x{4}_{5}{6}".format(layer_stack[0],
                                                       layer_stack[1],
                                                       layer_stack[2],
                                                       dimensions[0],
                                                       dimensions[1],
                                                       implant_type,
                                                       well_type)
        else:
            name = "{0}_{1}_{2}_{3}x{4}".format(layer_stack[0],
                                                       layer_stack[1],
                                                       layer_stack[2],
                                                       dimensions[0],
                                                       dimensions[1])
        if area_fill:
            name += "_fill"
        return name

    def __init__(self, layer_stack, dimensions=[1,1], implant_type=None, well_type=None,
                 area_fill=False):

        design.design.__init__(self, self.name)
        debug.info(4, "create contact object {0}".format(self.name))

        self.layer_stack = layer_stack
        self.dimensions = dimensions
        self.offset = vector(0,0)
        self.implant_type = implant_type
        self.well_type = well_type
        self.area_fill = area_fill
        self.pins = [] # used for matching parm lengths
        self.create_layout()
        self.h_1, self.w_1 = self.first_layer_height, self.first_layer_width
        self.h_2, self.w_2 = self.second_layer_height, self.second_layer_width

    def create_layout(self):
        self.setup_layers()
        self.setup_layout_constants()
        self.create_contact_array()
        self.create_first_layer_enclosure()
        self.create_second_layer_enclosure()
        
        self.height = max(obj.offset.y + obj.height for obj in self.objs)
        self.width = max(obj.offset.x + obj.width for obj in self.objs)

        # Do not include the select layer in the height/width
        if self.implant_type and self.well_type:
            self.create_implant_well_enclosures()
        elif self.implant_type or self.well_type:
            debug.error("Must define both implant and well type or none at all.", -1)

    def setup_layers(self):
        (first_layer, via_layer, second_layer) = self.layer_stack
        self.first_layer_name = first_layer
        self.via_layer_name = via_layer
        # Some technologies have a separate active contact from the poly contact
        # We will use contact for DRC, but active_contact for output
        if first_layer=="active" or second_layer=="active":
            self.via_layer_name_expanded = "active_"+via_layer
        else:
            self.via_layer_name_expanded = via_layer
        self.second_layer_name = second_layer

    def setup_layout_constants(self):
        self.contact_width = drc["minwidth_{0}". format(self.via_layer_name)]
        contact_to_contact = drc["{0}_to_{0}".format(self.via_layer_name)]
        self.contact_pitch = self.contact_width + contact_to_contact
        self.contact_array_width = self.contact_width + (self.dimensions[0] - 1) * self.contact_pitch
        self.contact_array_height = self.contact_width + (self.dimensions[1] - 1) * self.contact_pitch

        # DRC rules
        first_layer_minwidth = drc["minwidth_{0}".format(self.first_layer_name)]
        first_layer_minarea = self.get_min_area(self.first_layer_name)
        first_layer_enclosure = drc["{0}_enclosure_{1}".format(self.first_layer_name, self.via_layer_name)]
        first_layer_extend = drc["{0}_extend_{1}".format(self.first_layer_name, self.via_layer_name)]
        second_layer_minwidth = drc["minwidth_{0}".format(self.second_layer_name)]
        second_layer_minarea = self.get_min_area(self.second_layer_name)
        second_layer_enclosure = drc["{0}_enclosure_{1}".format(self.second_layer_name, self.via_layer_name)]
        second_layer_extend = drc["{0}_extend_{1}".format(self.second_layer_name, self.via_layer_name)]

        self.first_layer_horizontal_enclosure = max((first_layer_minwidth - self.contact_array_width) / 2,
                                                    first_layer_enclosure)

        self.first_layer_vertical_enclosure = max((first_layer_minwidth - self.contact_array_height)/2,
                                                  first_layer_extend)

        self.second_layer_horizontal_enclosure = max((second_layer_minwidth - self.contact_array_width) / 2,
                                                     second_layer_enclosure)
        self.second_layer_vertical_enclosure = max((second_layer_minwidth - self.contact_array_height)/2,
                                                   second_layer_extend)

        if self.area_fill:
            first_layer_width = self.contact_array_width + 2 * self.first_layer_horizontal_enclosure
            enclosure = utils.ceil(first_layer_minarea / first_layer_width) - self.contact_array_height
            self.first_layer_vertical_enclosure = max(self.first_layer_vertical_enclosure,
                                                      enclosure / 2)
            second_layer_width = self.contact_array_width + 2 * self.second_layer_horizontal_enclosure
            enclosure = utils.ceil((second_layer_minarea / second_layer_width) - self.contact_array_height)
            self.second_layer_vertical_enclosure = max(self.second_layer_vertical_enclosure,
                                                       enclosure / 2)

    def get_base_contact_offset(self):
        return vector(max(self.first_layer_horizontal_enclosure,
                          self.second_layer_horizontal_enclosure),
                      max(self.first_layer_vertical_enclosure,
                          self.second_layer_vertical_enclosure))

    def create_contact_array(self):
        """ Create the contact array at the origin"""
        # offset for the via array
        self.via_layer_position = self.get_base_contact_offset()

        for i in range(self.dimensions[1]):
            offset = self.via_layer_position + vector(0, self.contact_pitch * i)
            for j in range(self.dimensions[0]):
                self.add_rect(layer=self.via_layer_name_expanded,
                              offset=offset,
                              width=self.contact_width,
                              height=self.contact_width)
                offset = offset + vector(self.contact_pitch,0)

    def create_first_layer_enclosure(self):
        # this is if the first and second layers are different
        self.first_layer_position = vector(max(self.second_layer_horizontal_enclosure - self.first_layer_horizontal_enclosure,0),
                                           max(self.second_layer_vertical_enclosure - self.first_layer_vertical_enclosure,0))

        self.first_layer_width = self.contact_array_width + 2*self.first_layer_horizontal_enclosure
        self.first_layer_height = self.contact_array_height + 2*self.first_layer_vertical_enclosure
        self.add_rect(layer=self.first_layer_name,
                      offset=self.first_layer_position,
                      width=self.first_layer_width,
                      height=self.first_layer_height)

    def create_second_layer_enclosure(self):
        # this is if the first and second layers are different
        self.second_layer_position = vector(max(self.first_layer_horizontal_enclosure - self.second_layer_horizontal_enclosure,0),
                                            max(self.first_layer_vertical_enclosure - self.second_layer_vertical_enclosure,0))

        self.second_layer_width = self.contact_array_width  + 2*self.second_layer_horizontal_enclosure
        self.second_layer_height = self.contact_array_height + 2*self.second_layer_vertical_enclosure
        self.add_rect(layer=self.second_layer_name,
                      offset=self.second_layer_position,
                      width=self.second_layer_width,
                      height=self.second_layer_height)

    def create_implant_well_enclosures(self):
        implant_width = max(self.first_layer_width + 2 * drc["implant_enclosure_active"],
                            self.implant_width)
        implant_height = max(self.first_layer_height + 2 * drc["implant_enclosure_active"],
                             self.implant_width)
        implant_position = vector(0.5 * self.width - 0.5 * implant_width,
                                  0.5 * self.height - 0.5 * implant_height)
        self.add_rect(layer="{}implant".format(self.implant_type),
                      offset=implant_position,
                      width=implant_width,
                      height=implant_height)
        well_position = self.first_layer_position - [drc["well_enclosure_active"]]*2
        well_width = self.first_layer_width + 2*drc["well_enclosure_active"]
        well_height = self.first_layer_height + 2*drc["well_enclosure_active"]

        well_layer = "{}well".format(self.well_type)
        # avoid potential pwell issue since pwell could be implicit
        if well_layer not in tech_layer:
            return
        self.add_rect(layer="{}well".format(self.well_type),
                      offset=well_position,
                      width=well_width,
                      height=well_height)

    @staticmethod
    def get_layer_vias(layer1, layer2, cross_via=True):
        layer_nums = list(sorted([int(x[5:]) for x in [layer1, layer2]]))
        via_maps = {
            1: cross_m1m2 if cross_via else m1m2,
            2: cross_m2m3 if cross_via else m2m3,
            3: cross_m3m4 if cross_via else m3m4
        }
        vias = []
        via_rotates = []
        for layer_num in range(layer_nums[0], layer_nums[1]):
            vias.append(via_maps[layer_num])
            via_rotates.append(layer_num % 2 == 1)
        fill_layers = []
        for layer_num in range(layer_nums[0]+1, layer_nums[1]):
            fill_layers.append("metal" + str(layer_num))
        return vias, via_rotates, fill_layers

    @staticmethod
    def fill_via(self: design.design, via_inst):
        layer = via_inst.mod.first_layer_name
        fill_height = via_inst.height
        fill_height, fill_width = self.calculate_min_area_fill(fill_height, layer=layer)
        self.add_rect_center(layer, offset=vector(via_inst.cx(), via_inst.cy()), width=fill_width,
                             height=fill_height)


class cross_contact(contact):
    def get_name(*args, **kwargs):
        name = contact.get_name(*args, **kwargs)
        return "cross_" + name

    def create_layout(self):
        super().create_layout()
        self.offset_all_coordinates()
        highest_offset = self.find_highest_coords()
        self.width = highest_offset.x
        self.height = highest_offset.y

    def get_base_contact_offset(self):
        return vector(self.first_layer_horizontal_enclosure,
                      self.first_layer_vertical_enclosure)

    def create_first_layer_enclosure(self):
        # this is if the first and second layers are different
        self.first_layer_position = vector(0, 0)

        self.first_layer_width = self.contact_array_width + 2*self.first_layer_horizontal_enclosure
        self.first_layer_height = self.contact_array_height + 2*self.first_layer_vertical_enclosure
        self.add_rect(layer=self.first_layer_name,
                      offset=self.first_layer_position,
                      width=self.first_layer_width,
                      height=self.first_layer_height)

    def create_second_layer_enclosure(self):
        self.second_layer_width = self.contact_array_width + \
            2 * self.second_layer_vertical_enclosure
        self.second_layer_height = self.contact_array_height + \
            2 * self.second_layer_horizontal_enclosure

        via_center = vector(0.5 * self.first_layer_width,
                            0.5 * self.first_layer_height)
        self.second_layer_position = vector(via_center.x - 0.5 * self.second_layer_width,
                                            via_center.y - 0.5 * self.second_layer_height)

        self.add_rect(layer=self.second_layer_name,
                      offset=self.second_layer_position,
                      width=self.second_layer_width,
                      height=self.second_layer_height)


# This is not instantiated and used for calculations only.
# These are static 1x1 contacts to reuse in all the design modules.
well = well_contact = contact(layer_stack=("tap_active", "contact", "metal1"))
active = active_contact = contact(layer_stack=("active", "contact", "metal1"))
poly = poly_contact = contact(layer_stack=("poly", "contact", "metal1"))
m1m2 = contact(layer_stack=("metal1", "via1", "metal2"))
m2m3 = contact(layer_stack=("metal2", "via2", "metal3"))
m3m4 = contact(layer_stack=("metal3", "via3", "metal4"))

cross_poly = cross_contact(layer_stack=poly.layer_stack)
cross_m1m2 = cross_contact(layer_stack=m1m2.layer_stack)
cross_m2m3 = cross_contact(layer_stack=m2m3.layer_stack)
cross_m3m4 = cross_contact(layer_stack=m3m4.layer_stack)
