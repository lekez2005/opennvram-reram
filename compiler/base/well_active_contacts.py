import math

from base import utils
from base.contact import contact, well as well_contact
from base.design import design, ACTIVE, PWELL, NWELL, METAL1, TAP_ACTIVE, PIMP, NIMP
from base.vector import vector
from tech import drc, info as tech_info


def calculate_num_contacts(design_obj, tx_width, return_sample=False,
                           layer_stack=None, contact_spacing=None):
    """
    Calculates the possible number of source/drain contacts in a finger.
    """
    layer_stack = layer_stack or well_contact.layer_stack
    if isinstance(layer_stack, contact):
        layer_stack = layer_stack.layer_stack
    cont_layer = layer_stack[1]

    contact_spacing = contact_spacing or well_contact.get_space(cont_layer)
    contact_width = well_contact.get_min_layer_width(cont_layer)

    num_contacts = int(math.ceil(tx_width / (contact_width + contact_spacing)))

    def create_array():
        return contact(layer_stack=layer_stack, dimensions=[1, num_contacts],
                       implant_type=None, well_type=None)

    while num_contacts > 1:
        contact_array = create_array()
        if (contact_array.first_layer_height < tx_width and
                contact_array.second_layer_height < tx_width):
            if return_sample:
                return contact_array
            break
        num_contacts -= 1

    if return_sample and num_contacts == 0:
        num_contacts = 1
    if num_contacts == 1 and return_sample:
        return create_array()
    return num_contacts


def get_max_contact(layer_stack, height):
    """Get contact that can fit the given height"""
    from base.contact import contact
    num_contacts = 1
    prev_contact = None
    while True:
        sample_contact = contact(layer_stack, dimensions=[1, num_contacts])
        if num_contacts == 1:
            prev_contact = sample_contact
        if sample_contact.height > height:
            return prev_contact
        prev_contact = sample_contact
        num_contacts += 1


def calculate_contact_width(design_obj: design, width, well_contact_active_height):
    body_contact = calculate_num_contacts(design_obj, width - well_contact.contact_pitch,
                                          return_sample=True)

    contact_extent = body_contact.first_layer_height

    min_active_area = drc.get("minarea_cont_active_thin", design_obj.get_min_area(ACTIVE))
    min_active_width = utils.ceil(min_active_area / well_contact_active_height)
    active_width = max(contact_extent, min_active_width)

    # prevent minimum spacing drc
    active_width = max(active_width, width)
    return active_width, body_contact


def get_well_type(pin_name):
    if pin_name == "gnd":
        well_type = PWELL
        implant = PIMP
    else:
        well_type = NWELL
        implant = NIMP
    return well_type, implant


def add_power_tap(self, y_offset, pin_name, pin_width):
    well_type, implant = get_well_type(pin_name)

    active_width, sample_contact = calculate_contact_width(self, self.width, well_contact.w_1)

    x_offset = 0.5 * (self.width - pin_width)
    pin = self.add_layout_pin(pin_name, METAL1, offset=vector(x_offset, y_offset),
                              height=self.rail_height, width=pin_width)
    cont = self.add_contact_center(well_contact.layer_stack, pin.center(), rotate=90,
                                   size=sample_contact.dimensions,
                                   implant_type=implant[0],
                                   well_type=well_type[0])
    if active_width > sample_contact.h_1:
        self.add_rect_center(TAP_ACTIVE, pin.center(), width=active_width, height=well_contact.w_1)
        implant_height = cont.get_layer_shapes(implant)[0].height
        self.add_rect_center(implant, pin.center(), height=implant_height,
                             width=active_width + 2 * self.implant_enclose_active)
        if tech_info.get(f"has_{well_type}"):
            existing_wells = cont.get_layer_shapes(well_type)
            if existing_wells:
                existing_well = existing_wells[0]
                well_width = max(existing_well.width, active_width + 2 * self.well_enclose_active)
                self.add_rect_center(well_type, pin.center(), height=existing_well.height,
                                     width=well_width)

    return pin, cont, well_type


def extend_tx_well(self, tx_inst, pin):
    well_type, implant = get_well_type(pin.name)

    tap_rects = self.get_layer_shapes(TAP_ACTIVE, recursive=True)
    valid_tap_rects = [rect for rect in tap_rects if rect.overlaps(pin)]
    if not valid_tap_rects:
        return
    tap_rect = max(valid_tap_rects, key=lambda x: x.width)

    if tech_info[f"has_{well_type}"]:
        well_width = max(self.width, tap_rect.width + 2 * self.well_enclose_active)

        ptx_rects = tx_inst.get_layer_shapes(well_type)
        ptx_rect = max(ptx_rects, key=lambda x: x.width * x.height)
        well_width = max(well_width, ptx_rect.width)

        x_offset = 0.5 * (self.width - well_width)
        min_x = tap_rect.lx() - self.well_enclose_active
        max_x = max(tap_rect.rx() + self.well_enclose_active, x_offset + well_width)
        x_offset = min(x_offset, min_x)
        well_width = max_x - x_offset

        if pin.cy() < tx_inst.cy():
            well_top = ptx_rect.uy()
            well_bottom = (pin.cy() - 0.5 * well_contact.first_layer_width -
                           self.well_enclose_active)
        else:
            well_top = (pin.cy() + 0.5 * well_contact.first_layer_width +
                        self.well_enclose_active)
            well_bottom = ptx_rect.by()
            if self.has_pwell:
                opposite_well = NWELL if well_type == PWELL else PWELL
                adjacent_wells = self.get_layer_shapes(opposite_well, recursive=True)
                adjacent_wells = [x for x in adjacent_wells if x.uy() > well_top]
                if adjacent_wells:
                    closest = min(adjacent_wells, key=lambda x: x.by())
                    well_top = min(well_top, closest.by())

        self.add_rect(well_type, vector(x_offset, well_bottom), width=well_width,
                      height=well_top - well_bottom)
