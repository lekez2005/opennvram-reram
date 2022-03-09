from typing import List, Union

import debug
import tech
from base import contact
from base import utils
from base.utils import round_to_grid as round_g
from base.contact import m2m3, m3m4
from base.design import design, NWELL, NIMP, PIMP, METAL1, PO_DUMMY, POLY, DRAWING, \
    METAL2, PWELL, METAL3, METAL4, ACTIVE, TAP_ACTIVE
from base.geometry import instance
from base.hierarchy_layout import GDS_ROT_270, GDS_ROT_90
from base.rotation_wrapper import RotationWrapper
from base.vector import vector

TOP = "top"
BOTTOM = "bottom"
VERTICAL = "vertical"
HORIZONTAL = "horizontal"

design_inst = Union[design, instance]


def calculate_tx_metal_fill(tx_width, design_mod: design, contact_if_none=False):
    """Calculate metal fill properties
    if tx is wide enough to not need to be filled,
        just return None unless contact_if_none in which case return dimensions of contact
    design_mod acts as gateway to design class parameters
    """
    num_contacts = design_mod.calculate_num_contacts(tx_width)
    test_contact = contact.contact(contact.active.layer_stack,
                                   dimensions=[1, num_contacts])
    if test_contact.second_layer_height > design_mod.metal1_minwidth_fill:
        if contact_if_none:
            fill_height = test_contact.second_layer_height
            y_offset = 0.5 * tx_width - 0.5 * fill_height
            return y_offset, y_offset + fill_height, test_contact.second_layer_width, fill_height
        return None
    fill_width = utils.round_to_grid(2 * (design_mod.poly_pitch - 0.5 * design_mod.m1_width
                                          - design_mod.m1_space))

    m1_space = design_mod.get_space_by_width_and_length(METAL1, max_width=fill_width,
                                                        min_width=design_mod.m1_width,
                                                        run_length=tx_width)
    # actual fill width estimate based on space
    fill_width = utils.round_to_grid(2 * (design_mod.poly_pitch
                                          - 0.5 * design_mod.m1_width - m1_space))

    min_area = design_mod.get_min_area(METAL1)
    fill_height = utils.ceil(max(min_area / fill_width,
                                 test_contact.first_layer_height))
    fill_width = utils.ceil(max(design_mod.m1_width,
                                min_area / fill_height))
    y_offset = 0.5 * tx_width - 0.5 * max(test_contact.second_layer_height,
                                          contact.m1m2.first_layer_height)
    fill_top = y_offset + fill_height
    return y_offset, fill_top, fill_width, fill_height


def get_default_fill_layers():
    """Get layers that result in min spacing issues when two modules are placed side by side"""
    if hasattr(tech, "default_fill_layers"):
        layers = tech.default_fill_layers
    else:
        layers = [NWELL, NIMP, PIMP]
    if hasattr(tech, "default_fill_purposes"):
        purposes = tech.default_fill_purposes
    else:
        purposes = ["drawing"] * len(layers)
    assert len(layers) == len(purposes), "Number of layers and purposes specified not equal"
    return layers, purposes


def create_wells_and_implants_fills(left_mod: design_inst, right_mod: design_inst,
                                    layers=None, purposes=None):
    """
    Create all rects needed to fill between two adjacent modules to prevent minimum DRC spacing rules
    :param left_mod: The module on the left
    :param right_mod: The module on the right
    :param layers: The layers to be filled. Leave empty to use specifications from technology file
    :param purposes: The purposes of the layers to be filled. Can also leave empty
    :return: Fill list of rects tuples of (rect_layer, rect_bottom, rect_top,
                                           reference_rect_on_left, reference_rect_on_right)
    """
    default_layers, default_purposes = get_default_fill_layers()
    if layers is not None and purposes is None:
        purposes = [DRAWING] * len(layers)
    if layers is None:
        layers = default_layers
    if purposes is None:
        purposes = default_purposes

    all_fills = []

    for i in range(len(layers)):
        layer = layers[i]
        purpose = purposes[i]

        left_mod_rects = left_mod.get_layer_shapes(layer, purpose=purpose, recursive=True)
        right_mod_rects = right_mod.get_layer_shapes(layer, purpose=purpose, recursive=True)

        for left_mod_rect in left_mod_rects:
            if (round_g(left_mod_rect.rx()) < round_g(left_mod.width) and
                    isinstance(left_mod, design)):
                continue
            # find right mod rect which overlaps
            for right_mod_rect in right_mod_rects:
                if round_g(right_mod_rect.lx()) > 0 and isinstance(right_mod, design):
                    continue
                if isinstance(left_mod, instance):
                    if round_g(right_mod_rect.lx()) > round_g(right_mod.lx()):
                        continue
                    if round_g(left_mod_rect.rx()) < round_g(left_mod.rx()):
                        continue
                    if round_g(right_mod_rect.lx()) <= round_g(left_mod_rect.lx()):  # overlap
                        continue

                if left_mod_rect.by() < right_mod_rect.by():
                    lowest_rect, highest_rect = left_mod_rect, right_mod_rect
                else:
                    lowest_rect, highest_rect = right_mod_rect, left_mod_rect
                if lowest_rect.uy() < highest_rect.by():  # no overlap
                    continue
                rect_top = min(right_mod_rect.uy(), left_mod_rect.uy())
                rect_bottom = max(right_mod_rect.by(), left_mod_rect.by())

                fill_rect = (layer, rect_bottom, rect_top, left_mod_rect, right_mod_rect)
                all_fills.append(fill_rect)
    return all_fills


def well_implant_instance_fills(source_inst: instance, target_inst: instance,
                                direction=VERTICAL,
                                layers=None, purposes=None):
    default_layers, default_purposes = get_default_fill_layers()
    is_vertical = direction == VERTICAL

    if layers is None:
        layers = default_layers
    if purposes is None:
        purposes = default_purposes

    def source_func(x):
        return x.uy() if is_vertical else x.rx()

    def target_func(x):
        return x.by() if is_vertical else x.lx()

    def is_edge_rect(rect, inst, prop_scale):
        """Considered edge rect if it's extremity is within the layer space"""
        layer_space = source_inst.mod.get_space(layer)

        if prop_scale == 1:
            if is_vertical:
                return rect.uy() + layer_space > inst.height
            else:
                return rect.rx() + layer_space > inst.width
        else:
            if is_vertical:
                return rect.by() - layer_space < 0
            else:
                return rect.lx() - layer_space < 0

    def get_extremity_rects(inst, property_func, prop_scale):
        """prop_scale = 1 for max comparison and -1 for min comparison"""
        rects = inst.get_layer_shapes(layer, purpose=purpose, recursive=True)
        if not rects:
            return []
        max_val = max([prop_scale * x for x in map(utils.floor, map(property_func, rects))])
        extremity_rects = [x for x in rects if prop_scale * utils.floor(property_func(x)) >= max_val]
        return [x for x in extremity_rects if is_edge_rect(x, inst, prop_scale)]

    results = []

    for i in range(len(layers)):
        layer = layers[i]
        purpose = purposes[i]
        min_width = source_inst.mod.get_min_layer_width(layer)
        source_rects = get_extremity_rects(source_inst, source_func, 1)
        target_rects = get_extremity_rects(target_inst, target_func, -1)
        for source_rect in source_rects:
            for target_rect in target_rects:
                if is_vertical:
                    start = max(source_rect.lx(), target_rect.lx())
                    end = min(source_rect.rx(), target_rect.rx())
                    width = end - start
                    x_offset = start
                    y_offset = source_rect.uy()
                    height = (source_inst.height - y_offset) + target_rect.by()
                else:
                    start = max(source_rect.by(), target_rect.by())
                    end = min(source_rect.uy(), target_rect.uy())
                    x_offset = source_rect.rx()
                    y_offset = start
                    width = (source_inst.width - x_offset) + target_rect.lx()
                    height = end - start
                if end - start > min_width:
                    results.append((layer, x_offset, y_offset, width, height))
    return results


def fill_horizontal_poly(self: design, reference_inst: instance, direction=TOP):
    """
    Fill dummy poly for instances which have been rotated by 90 or 270
    :param self: The parent module where the fills are inserted
    :param reference_inst: The instance around which the fills will be inserted
    :param direction: Whether to insert above or below. Options: top, bottom
    :return:
    """
    if isinstance(reference_inst.mod, RotationWrapper):
        original_vertical_mod = reference_inst.mod.child_mod
        rotation = reference_inst.mod.child_inst.rotate
    else:
        original_vertical_mod = reference_inst.mod
        rotation = reference_inst.rotate

    dummy_fills = self.get_poly_fills(original_vertical_mod)

    if not dummy_fills:
        return

    if ((direction == TOP and rotation == GDS_ROT_90)
            or direction == BOTTOM and rotation == GDS_ROT_270):
        key = "right"
    else:
        key = "left"

    real_poly = original_vertical_mod.get_layer_shapes(POLY)
    max_width = max(real_poly, key=lambda x: x.width).width

    for rect in dummy_fills[key]:
        fill_x = 0.5 * self.poly_to_field_poly
        fill_width = reference_inst.width - 2 * fill_x
        ll, ur = map(vector, rect)
        if direction == TOP:
            if key == "left":
                y_shift = original_vertical_mod.width - ur[0]
            else:
                y_shift = ll[0]
            y_shift += 2 * (max_width - self.poly_width)
        else:
            if key == "left":
                y_shift = ll[0]
            else:
                y_shift = original_vertical_mod.width - ur[0]
            y_shift -= (max_width - self.poly_width)

        y_offset = reference_inst.by() + y_shift
        x_offset = reference_inst.lx() + fill_x
        self.add_rect(PO_DUMMY, offset=vector(x_offset, y_offset),
                      width=fill_width, height=self.poly_width)


def evaluate_vertical_metal_spacing(top_module: design, bottom_module: design,
                                    num_rails=0, layers=None, vias=None, via_space=False):
    """
    Evaluate minimum spacing between top and bottom module
    :param top_module:
    :param bottom_module:
    :param num_rails: number of parallel rails that will pass between top and bottom modules
    :param layers: Which layers to check min space for, M2, M3 by default
    :param vias: via heights to us. m2m3 by default
    :param via_space: whether to use only reserve space for one via fitting below the top mod,
                        num_rails is ignored in this case
    :return:
    """
    if layers is None:
        layers = [METAL2, METAL3, METAL4]
    if not vias:
        vias = [m2m3, m3m4]
    via_height = max(vias, key=lambda x: x.height).height
    metal_space = max(top_module.get_line_end_space(METAL2),
                      top_module.get_line_end_space(METAL3))
    if num_rails >= 2:
        metal_space = max(metal_space, top_module.get_line_end_space(METAL4))

    space = -top_module.height
    for layer in layers:
        top_rects = top_module.get_layer_shapes(layer)
        bottom_rects = bottom_module.get_layer_shapes(layer)
        if not top_rects or not bottom_rects:
            continue

        top_rect = min(top_rects, key=lambda x: x.by())
        bottom_rect = max(bottom_rects, key=lambda x: x.uy())

        top_rect_y = top_rect.by() + bottom_module.height
        bottom_rect_top = bottom_rect.uy()
        min_space = metal_space + (bottom_rect_top - top_rect_y)
        if via_space:
            min_space += via_height
        else:
            min_space += (via_height + metal_space) * num_rails
        space = max(space, min_space)
    return space


def evaluate_well_active_enclosure_spacing(top_module: design, bottom_module: design,
                                           min_space):
    def top_bot_rect(module, layer):
        rects = module.get_layer_shapes(layer)
        if not rects:
            return None
        if module == top_module:
            return min(rects, key=lambda x: x.by())
        else:
            return max(rects, key=lambda x: x.uy())

    # get top and bottom wells and actives
    bottom_well = top_bot_rect(bottom_module, NWELL)
    bottom_active = top_bot_rect(bottom_module, ACTIVE)
    top_well = top_bot_rect(top_module, NWELL)
    top_active = top_bot_rect(top_module, ACTIVE)

    # determine what well the actives are in
    top_is_nwell = top_well and top_active and (
            top_active.by() >= top_well.by() and top_active.uy() <= top_well.uy())
    bot_is_nwell = bottom_well and bottom_active and (bottom_active.by() >= bottom_well.by() and
                                                      bottom_active.uy() <= bottom_well.uy())

    # space by top active
    space = min_space
    if top_active:
        if top_is_nwell:
            space = - top_active.by() + top_module.well_enclose_active
        elif top_active:  # space to next nwell
            bot_nwell_y = bottom_well.uy() if bottom_well else 0
            space = (-(top_active.by() + (bottom_module.height - bot_nwell_y)) +
                     top_module.well_enclose_active)
        min_space = max(min_space, space)

    # space by bottom active
    if bottom_active:
        if bot_is_nwell:
            space = (-(bottom_module.height - bottom_active.uy()) +
                     top_module.well_enclose_active)
        elif bottom_active:
            top_nwell_y = top_well.by() if top_well else top_module.height
            space = (-(bottom_module.height - bottom_active.uy() + top_nwell_y) +
                     top_module.well_enclose_active)

        min_space = max(min_space, space)

    return min_space


def evaluate_vertical_module_spacing(top_modules: List[design_inst],
                                     bottom_modules: List[design_inst],
                                     layers=None, min_space=None, num_cols=64):
    """
    Evaluate spacing between two modules vertically arranged
    :param top_modules: The modules placed on top (e.g. main module and its body tap)
    :param bottom_modules: The modules placed below
    :param layers: Layers to compare
    :param min_space: minimum space, uses complete overlap as starting space if not specified
    :param num_cols: number of columns, used in evaluating run length for parallel space calculation
    :return: minimum space
    """
    if layers is None:
        layers = [METAL1, POLY, PO_DUMMY, NIMP, PIMP]
    if PO_DUMMY not in tech.layer and PO_DUMMY in layers:
        layers.remove(PO_DUMMY)

    if min_space is None:
        min_space = - top_modules[0].height  # start with overlap
    for top_module in top_modules:
        if isinstance(top_module, instance):
            top_inst, top_module = top_module, top_module.mod
        else:
            top_inst = top_module

        for bottom_module in bottom_modules:
            if isinstance(bottom_module, instance):
                bottom_inst, bottom_module = bottom_module, bottom_module.mod
            else:
                bottom_inst = bottom_module

            min_space = max(min_space,
                            evaluate_well_active_enclosure_spacing(top_module, bottom_module,
                                                                   min_space))
            for layer in layers:

                wide_space = design.get_wide_space(layer)

                top_rects = top_inst.get_layer_shapes(layer, recursive=True)
                top_rects = [x for x in top_rects if x.by() < wide_space]
                top_rects = list(sorted(top_rects, key=lambda x: x.by()))

                bottom_rects = bottom_inst.get_layer_shapes(layer, recursive=True)
                bottom_rects = [x for x in bottom_rects
                                if x.uy() > bottom_module.height - wide_space]
                bottom_rects = list(sorted(bottom_rects, key=lambda x: x.uy(), reverse=True))
                if not (top_rects or bottom_rects):  # layer does not exist
                    continue

                for bottom_rect in bottom_rects:
                    bottom_clearance = bottom_module.height - bottom_rect.uy()
                    for top_rect in top_rects:
                        # don't bother if spacing is greater than wide spacing
                        top_clearance = top_rect.by()
                        total_clearance = top_clearance + bottom_clearance + min_space
                        if total_clearance > wide_space:
                            continue
                        # permit overlaps for implants
                        if layer in [NIMP, PIMP] and total_clearance <= 0:
                            continue
                        # else calculate desired space, note the width/height flip since vertical space is needed
                        widths = [bottom_rect.rx() - bottom_rect.lx(),
                                  top_rect.rx() - top_rect.lx()]
                        heights = [bottom_rect.uy() - bottom_rect.by(),
                                   top_rect.uy() - top_rect.by()]

                        if ((bottom_rect.rx() - bottom_rect.lx()) >= bottom_module.width and
                                (top_rect.rx() - top_rect.lx()) >= top_module.width):
                            run_length = num_cols * bottom_module.width
                        else:
                            right_most = max([top_rect, bottom_rect], key=lambda x: x.lx())
                            left_most = min([top_rect, bottom_rect], key=lambda x: x.lx())
                            run_length = min(abs(right_most.rx()),
                                             abs(left_most.rx() - right_most.lx()))

                        target_space = design. \
                            get_space_by_width_and_length(layer,
                                                          max_width=max(widths),
                                                          min_width=min(widths),
                                                          run_length=run_length,
                                                          heights=heights)
                        # TODO look up table POLY DRC rules
                        if layer in [POLY, PO_DUMMY]:
                            if top_rect.rx() - top_rect.lx() > top_rect.uy() - top_rect.by():
                                target_space = bottom_module.poly_space
                            else:
                                target_space = bottom_module.poly_vert_space
                        evaluated_space = -top_clearance + -bottom_clearance + target_space
                        if evaluated_space > min_space:
                            min_space = evaluated_space
    # nwell to tap active
    tap_to_nwell = tech.drc.get("nwell_to_tap_active_space",
                                tech.drc.get("nwell_to_active_space", 0))

    def get_tap_nwell(mod, layer):
        return get_ptaps(mod) if layer == TAP_ACTIVE else mod.get_layer_shapes(layer, recursive=True)

    for top_module in top_modules:
        for bottom_module in bottom_modules:
            for top_layer, bottom_layer in [(NWELL, TAP_ACTIVE), (TAP_ACTIVE, NWELL)]:
                top_rects = get_tap_nwell(top_module, top_layer)
                bottom_rects = get_tap_nwell(bottom_module, bottom_layer)
                if not top_rects or not bottom_rects:
                    continue
                bottom_rect = max(bottom_rects, key=lambda x: x.uy())
                top_rect = min(top_rects, key=lambda x: x.by())
                evaluated_space = (bottom_rect.uy() - bottom_module.height +
                                   tap_to_nwell - top_rect.by())
                min_space = max(min_space, evaluated_space)

    min_space = utils.round_to_grid(min_space)
    # evaluate well spacing to prevent nwell pwell overlap
    if tech.info["has_pwell"]:
        top_module = top_modules[0]
        bottom_module = bottom_modules[0]
        layer_pairs = [(NWELL, PWELL), (PWELL, NWELL)]
        for top_layer, bottom_layer in layer_pairs:
            top_rects = top_module.get_layer_shapes(top_layer, recursive=True)
            bottom_rects = bottom_module.get_layer_shapes(bottom_layer, recursive=True)
            if not top_rects or not bottom_rects:
                continue
            top_rect = min(top_rects, key=lambda x: x.by())
            bottom_rect = max(bottom_rects, key=lambda x: x.uy())

            top_rect_y = top_rect.by() + bottom_module.height + min_space
            bottom_rect_y = bottom_rect.uy()

            if top_rect_y < bottom_rect_y:  # zero spacing
                min_space = bottom_rect_y - (top_rect.by() + bottom_module.height)

    return min_space


def calculate_modules_implant_space(left_module: design, right_module: design):
    """Calculate the space between implants to prevent nimplant/pimplant overlap"""
    for (left_layer, right_layer) in [(PIMP, NIMP), (NIMP, PIMP)]:
        left_rect = left_module.get_max_shape(left_layer, "rx", True)
        right_rect = right_module.get_max_shape(right_layer, "lx", True)
        left_extension = round_g((left_rect.rx() - left_module.width))
        right_extension = round_g(right_rect.lx())
        space = 0
        if left_extension > 0 or right_extension < 0:
            space = round_g(max(0, left_extension - right_extension))
            if left_module.has_dummy and space >= 0:
                space = max(space, left_module.poly_pitch)
    return space


def get_ptaps(obj: design):
    tap_actives = obj.get_layer_shapes(TAP_ACTIVE, recursive=True)
    nwells = obj.get_layer_shapes(NWELL, recursive=True)
    ptaps = []
    for tap_active in tap_actives:
        for nwell in nwells:
            if nwell.overlaps(tap_active):
                break
        ptaps.append(tap_active)
    return ptaps


def get_layer_space(obj: design, layer_1, layer_2):
    if layer_1 == layer_2:
        layer_space = obj.get_wide_space(layer_1)
        if layer_space is not None:
            return layer_space
    else:
        for prefix in ["wide_", ""]:
            for src, dest in [(layer_1, layer_2), (layer_2, layer_1)]:
                drc_key = "{}{}_to_{}".format(prefix, src, dest)
                if drc_key in tech.drc:
                    return tech.drc[drc_key]
    debug.check(False, "Layer space not defined for {} and {}".format(layer_1, layer_2))


def join_vertical_adjacent_module_wells(bank: design, bottom_inst, top_inst):
    layers = [(NWELL, NWELL)]
    if tech.info["has_pwell"]:
        layers.append((PWELL, PWELL))
        layers.append((NWELL, PWELL))
        layers.append((PWELL, NWELL))
    if hasattr(tech, "vertical_mod_fill_layers"):
        layers.extend(tech.vertical_mod_fill_layers)

    top_child_inst = top_inst.mod.child_insts[0]
    bottom_mod = bottom_inst.mod.child_mod  # type: design
    bottom_child_inst = bottom_inst.mod.child_insts[0]

    for top_layer, bottom_layer in layers:
        layer_space = get_layer_space(bank, top_layer, bottom_layer)
        top_rects = top_child_inst.get_layer_shapes(top_layer, recursive=True)
        bottom_rects = bottom_child_inst.get_layer_shapes(bottom_layer, recursive=True)
        if not top_rects or not bottom_rects:
            continue
        top_rect = min(top_rects, key=lambda x: x.by())
        bottom_rect = max(bottom_rects, key=lambda x: x.uy())

        bottom_y = utils.round_to_grid(bottom_inst.by() +
                                       bottom_rect.uy())
        top_y = utils.round_to_grid(top_inst.by() +
                                    top_rect.by())
        if top_y > bottom_y and top_y - bottom_y < layer_space:
            x_offset = (bottom_inst.lx() + max(bottom_rect.lx(), top_rect.lx()))

            rect_right = min(bottom_rect.rx(), top_rect.rx())
            rect_right_extension = rect_right - bottom_mod.width
            right_x = bottom_inst.rx() + rect_right_extension
            height = top_y - bottom_y
            if top_layer == bottom_layer:
                height = max(height, bank.get_min_layer_width(bottom_layer))
            bank.add_rect(bottom_layer, vector(x_offset, bottom_y),
                          width=right_x - x_offset, height=height)
