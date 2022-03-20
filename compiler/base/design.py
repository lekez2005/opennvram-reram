import copy
import os
from collections import Iterable

import debug
from base.hierarchy_layout import layout as hierarchy_layout, get_purpose
from base import hierarchy_spice
from base import utils
from base.geometry import rectangle
from base.vector import vector
from globals import OPTS
from tech import drc, info
from tech import layer as tech_layers

DRAWING = "drawing"
POLY = "poly"
PO_DUMMY = "po_dummy"
NWELL = "nwell"
PWELL = "pwell"
ACTIVE = "active"
TAP_ACTIVE = "tap_active"
CONTACT = "contact"
NIMP = "nimplant"
PIMP = "pimplant"
BOUNDARY = "boundary"
METAL1 = "metal1"
METAL2 = "metal2"
METAL3 = "metal3"
METAL4 = "metal4"
METAL5 = "metal5"


class design(hierarchy_spice.spice, hierarchy_layout):
    """
    Design Class for all modules to inherit the base features.
    Class consisting of a set of modules and instances of these modules
    """
    name_map = []
    has_dummy = PO_DUMMY in tech_layers
    num_poly_dummies = info.get("num_poly_dummies", int(has_dummy))
    has_pwell = info["has_pwell"]

    def __init__(self, name):
        self.gds_file = os.path.join(OPTS.openram_tech, "gds_lib", name + ".gds")
        self.sp_file = os.path.join(OPTS.openram_tech, "sp_lib", name + ".sp")
        name = name.split("/")[-1]

        self.name = name
        hierarchy_layout.__init__(self, name)
        hierarchy_spice.spice.__init__(self, name)

        self.setup_drc_constants()

        # Check if the name already exists, if so, give an error
        # because each reference must be a unique name.
        # These modules ensure unique names or have no changes if they
        # aren't unique
        # TODO: sky_tapeout: fix uniqueness
        ok_list = [
            'GdsLibImport',
            'ms_flop',
            'ms_flop_horz_pitch',
            'FlopBuffer',
            'bitcell',
            'body_tap',
            'cam_bitcell',
            'cam_bitcell_12t',
            'contact',
            'ptx',
            'pinv',
            'ptx_spice',
            'SignalGate',
            'sram',
            'hierarchical_predecode2x4',
            'hierarchical_predecode3x8',
            'RotationWrapper',
            'reram_bitcell',
        ]
        if name not in design.name_map:
            design.name_map.append(name)
        elif self.__class__.__name__ in ok_list:
            pass
        else:
            debug.error("Duplicate layout reference name {0} of class {1}."
                        " GDS2 requires names be unique.".format(name, self.__class__), -1)

    def rename(self, new_name):
        self.name = new_name
        self.drc_gds_name = new_name
        self.name_map.append(new_name)
        self.gds_read()

    def setup_drc_constants(self):
        """ These are some DRC constants used in many places in the compiler."""

        self.well_width = drc["minwidth_well"]
        self.poly_width = drc["minwidth_poly"]
        self.poly_space = drc["poly_to_poly"]
        self.poly_pitch = self.poly_width + self.poly_space
        self.m1_width = drc["minwidth_metal1"]

        self.medium_m1 = self.get_medium_layer_width(METAL1)
        self.medium_m2 = self.get_medium_layer_width(METAL2)
        self.medium_m3 = self.get_medium_layer_width(METAL3)

        self.m1_space = drc["metal1_to_metal1"]
        self.m2_width = drc["minwidth_metal2"]
        self.m2_space = drc["metal2_to_metal2"]
        self.m3_width = drc["minwidth_metal3"]
        self.m3_space = drc["metal3_to_metal3"]
        self.m4_width = drc["minwidth_metal4"]
        self.m4_space = drc["metal4_to_metal4"]
        self.active_width = drc["minwidth_active"]
        self.min_tx_width = drc["minwidth_tx"]
        self.contact_width = drc["minwidth_contact"]
        self.contact_spacing = drc["contact_to_contact"]
        self.rail_height = drc["rail_height"]  # height for inverter/logic gates power

        self.poly_to_active = drc["poly_to_active"]
        self.poly_extend_active = drc["poly_extend_active"]
        self.poly_to_field_poly = drc["poly_to_field_poly"]
        self.contact_to_gate = drc["contact_to_gate"]

        self.well_enclose_active = drc.get("well_enclosure_active")
        self.well_enclose_ptx_active = drc.get("ptx_well_enclosure_active", self.well_enclose_active)

        self.implant_enclose_active = drc["implant_enclosure_active"]
        self.implant_enclose_ptx_active = drc.get("ptx_implant_enclosure_active", self.implant_enclose_active)
        self.implant_enclose_poly = drc.get("implant_enclosure_poly")
        self.implant_width = drc["minwidth_implant"]
        self.implant_space = drc["implant_to_implant"]

        self.wide_m1_space = self.get_wide_space(METAL1)
        self.line_end_space = self.get_line_end_space(METAL1)
        self.parallel_line_space = self.get_parallel_space(METAL1)
        _, self.metal1_minwidth_fill = self.calculate_min_area_fill(self.m1_width, layer=METAL1)
        self.poly_vert_space = drc.get("poly_end_to_end")
        self.parallel_via_space = self.get_space("via1")

        self.bus_width = self.get_bus_width() or self.m3_width
        self.bus_space = drc.get("bus_space", self.get_parallel_space(METAL3))
        self.bus_pitch = self.bus_width + self.bus_space

    @classmethod
    def get_min_layer_width(cls, layer):
        if layer in [PIMP, NIMP]:
            layer = "implant"
        elif layer in [NWELL, PWELL]:
            layer = "well"
        return drc["minwidth_{}".format(layer)]

    @classmethod
    def get_medium_layer_width(cls, layer):
        return cls.get_drc_by_layer(layer, "medium_width")

    @classmethod
    def get_bus_width(cls):
        return cls.get_medium_layer_width(METAL3)

    @classmethod
    def get_space_by_width_and_length(cls, layer, max_width=None, min_width=None,
                                      run_length=None, heights=None):
        # TODO more robust lookup table
        if cls.is_thin_implant(layer, min_width):
            return cls.get_space(layer, prefix="thin")
        elif cls.is_line_end(layer, heights):
            return cls.get_line_end_space(layer)
        elif cls.is_above_layer_threshold(layer, "wide", max_width, run_length):
            return cls.get_wide_space(layer)
        elif cls.is_above_layer_threshold(layer, "parallel", max_width, run_length):
            return cls.get_parallel_space(layer)
        else:
            return cls.get_space(layer, prefix=None)

    @classmethod
    def get_drc_by_layer(cls, layer, prefix):
        if "metal" in layer:
            # check for example [metal3, metal2, metal1, ""] for metal3 input
            layer_num = int(layer[5:])
            suffixes = ["_metal{}".format(x) for x in range(layer_num, 0, -1)] + [""]
        else:
            suffixes = ["_" + layer, ""]
        keys = ["{}{}".format(prefix, suffix) for suffix in suffixes]
        for key in keys:
            if key in drc:
                return drc[key]
        return None

    @classmethod
    def is_line_end(cls, layer, heights=None):
        if heights is None or "metal" not in layer:
            return False
        if not isinstance(heights, Iterable) or not len(heights) == 2:
            raise ValueError("heights must be iterable of length 2")
        min_height = min(heights)
        line_end_threshold = cls.get_drc_by_layer(layer, "line_end_threshold")
        return line_end_threshold and min_height < line_end_threshold

    @classmethod
    def is_thin_implant(cls, layer, min_width):
        if min_width is not None and "implant" in layer:
            threshold = cls.get_drc_by_layer(layer, "thin_threshold")
            return threshold and min_width < threshold

    @classmethod
    def get_line_end_space(cls, layer):
        return cls.get_space(layer, "line_end")

    @classmethod
    def get_wide_space(cls, layer):
        return cls.get_space(layer, "wide")

    @classmethod
    def get_parallel_space(cls, layer):
        return cls.get_space(layer, "parallel")

    @classmethod
    def is_above_layer_threshold(cls, layer, prefix, max_width, run_length):
        """
        :param layer:
        :param prefix: parallel, wide, ""
        :param max_width: if None returns False, else checks if
            max_width > threshold and run_length > threshold
        :param run_length: if None and max_width > threshold
            (we don't know length yet, just be conservative) -> return True
        :return:
        """
        if max_width is None:
            return False

        width_threshold = cls.get_drc_by_layer(layer, prefix + "_width_threshold")
        if width_threshold is None or max_width < width_threshold:
            return False

        if run_length is None:
            return True

        length_threshold = cls.get_drc_by_layer(layer, prefix + "_length_threshold")
        if length_threshold is None or run_length < length_threshold:
            return False
        return True

    @classmethod
    def get_space(cls, layer, prefix=None):
        """
        finds space min space between parallel lines on layer
        for metals, counts down from layer to metal1 until match it found
        first checks for wide, then checks for regular space and returns the max of the two
        Assumes spaces increase with layer
        :param prefix: e.g. parallel, wide
        :param layer:
        :return: parallel space
        """

        if layer == PO_DUMMY:
            layer = POLY

        if "implant" in layer:
            layer_to_layer_space = drc["implant_to_implant"]
        else:
            layer_to_layer_space = drc["{0}_to_{0}".format(layer)]
        space_for_prefix = None
        if prefix:
            space_for_prefix = cls.get_drc_by_layer(layer, prefix + "_line_space")

        if space_for_prefix is not None:
            return max(space_for_prefix, layer_to_layer_space)
        return layer_to_layer_space

    @classmethod
    def get_via_space(cls, via):
        return cls.get_space(via.via_layer_name)

    def get_layout_pins(self, inst):
        """ Return a map of pin locations of the instance offset """
        # find the instance
        for i in self.insts:
            if i.name == inst.name:
                break
        else:
            debug.error("Couldn't find instance {0}".format(inst.name), -1)
        inst_map = inst.mod.pin_map
        return inst_map

    def calculate_num_contacts(self, tx_width, return_sample=False):
        """
        Calculates the possible number of source/drain contacts in a finger.
        """
        from base.contact import active
        from base.well_active_contacts import calculate_num_contacts as calc_func
        return calc_func(self, tx_width, return_sample, layer_stack=active.layer_stack)

    @staticmethod
    def get_min_area(layer, prefix=None):
        prefix = "_{}".format(prefix) if prefix else ""
        return design.get_drc_by_layer(layer, "{}minarea".format(prefix))

    @staticmethod
    def calculate_min_area_fill(width=None, min_height=None, layer=METAL1):
        """Given width calculate the height, if height is less than min_height,
         set height to min_height and re-adjust width"""
        min_area = design.get_min_area(layer) or 0.0
        min_side = design.get_drc_by_layer(layer, "minside_contact")
        min_layer_width = design.get_min_layer_width(layer)

        if width is None:
            width = min_layer_width

        if min_height is None:
            min_height = min_layer_width

        height = max(utils.ceil(min_area / width), min_height)
        if min_side and height < min_side and width < min_side:
            height = min_side

        return width, height

    def get_layer_shapes(self, layer, purpose=None, recursive=False, insts=None):

        if self.gds.from_file:
            return self.get_gds_layer_rects(layer, purpose, recursive=recursive)

        def filter_match(x):
            if isinstance(x, rectangle):
                if layer is None:
                    return True
                return (x.layerNumber == tech_layers[layer] and
                        x.layerPurpose == get_purpose(layer))
            return False

        pin_rects = []
        for pins in self.pin_map.values():
            for pin in pins:
                if layer and not pin.layer == layer:
                    continue
                layer_purpose = get_purpose(pin.layer)
                pin_rects.append(rectangle(layerNumber=tech_layers[pin.layer],
                                           layerPurpose=layer_purpose,
                                           offset=pin.ll(), width=pin.rx() - pin.lx(),
                                           height=pin.uy() - pin.by()))
        shapes = list(filter(filter_match, self.objs + pin_rects))
        if recursive or insts:
            if insts is None:
                insts = self.insts
            for inst in insts:
                shapes.extend(inst.get_layer_shapes(layer, purpose, recursive))
        return shapes

    def get_max_shape(self, layer, prop_name, recursive=False):
        shapes = self.get_layer_shapes(layer, recursive=recursive)
        return self.get_max_shape_(shapes, prop_name)

    @staticmethod
    def get_max_shape_(shapes, prop_name):
        if prop_name in ["by", "lx"]:
            scale = -1
        else:
            scale = 1

        def get_prop(shape):
            return scale * getattr(shape, prop_name)()

        return max(shapes, key=get_prop)

    @staticmethod
    def get_gds_layer_shapes(cell, layer, purpose=None, recursive=False):
        if layer is None:
            layer_number = purpose_number = None
        else:
            layer_number = tech_layers[layer]
            purpose_number = get_purpose(layer)
        if recursive:
            return cell.gds.getShapesInLayerRecursive(layer_number, purpose_number)
        else:
            return cell.gds.getShapesInLayer(layer_number, purpose_number)

    def get_gds_layer_rects(self, layer, purpose=None, recursive=False):

        def rect(shape):
            return rectangle(tech_layers[layer], shape[0], width=shape[1][0] - shape[0][0],
                             height=shape[1][1] - shape[0][1],
                             layerPurpose=get_purpose(layer))
        shapes = self.get_gds_layer_shapes(self, layer, purpose, recursive)
        return [rect(shape) for shape in shapes]

    def get_poly_fills(self, cell):
        if not self.has_dummy:
            return {}

        def to_boundary(fill_dict):
            for key in fill_dict:
                boundaries = []
                for rect in fill_dict[key]:
                    rect.normalize()
                    boundaries.append([[rect.lx(), rect.by()], [rect.rx(), rect.uy()]])
                fill_dict[key] = boundaries
            return fill_dict

        poly_dummies = cell.get_layer_shapes(PO_DUMMY, recursive=True)
        poly_rects = cell.get_layer_shapes(POLY, recursive=True)

        # only polys with active layer interaction need to be filled
        polys = []
        actives = cell.get_layer_shapes(ACTIVE, recursive=True)
        for poly_rect in poly_rects:
            for active in actives:
                if active.overlaps(poly_rect):
                    polys.append(poly_rect)
        if len(polys) == 0 and len(poly_dummies) == 2:
            result = {}
            left = copy.deepcopy(min(poly_dummies, key=lambda rect: rect.lx()))
            left.boundary[0].x -= self.poly_pitch
            left.boundary[1].x -= self.poly_pitch
            result["left"] = [left]
            right = copy.deepcopy(max(poly_dummies, key=lambda rect: rect.rx()))
            left.boundary[0].x += self.poly_pitch
            left.boundary[1].x += self.poly_pitch
            result["right"] = [right]
            return to_boundary(result)

        fills = []
        for poly_rect in polys:
            x_offset = poly_rect.lx()
            potential_fills = [-2, 2]  # need -2 and +2 poly pitches from current x offset filled
            mid_point = poly_rect.cy()  # y midpoint
            for candidate in polys + poly_dummies:
                if not candidate.by() < mid_point < candidate.uy():  # not on the same row
                    continue
                integer_space = int(
                    round((candidate.lx() - x_offset) / self.poly_pitch))  # space away from current poly
                if integer_space in potential_fills:
                    potential_fills.remove(integer_space)
            for potential_fill in potential_fills:  # fill unfilled spaces
                fill_copy = copy.deepcopy(poly_rect)
                x_space = potential_fill * self.poly_pitch
                fill_copy.boundary[0].x += x_space
                fill_copy.boundary[1].x += x_space
                fills.append(fill_copy)
        # make the fills unique by x_offset by combining fills with the same x offset
        fills = list(sorted(fills, key=lambda x: x.lx()))
        merged_fills = {"left": [], "right": []}

        def add_to_merged(fill):
            # discard fills that appear within cell
            if fill.lx() > 0 and fill.rx() < cell.width:
                return
            if fill.lx() < 0.5 * cell.width:
                merged_fills["left"].append(fill)
            else:
                merged_fills["right"].append(fill)

        if len(fills) > 0:
            current_fill = copy.deepcopy(fills[0])
            x_offset = utils.ceil(current_fill.lx())
            for fill in fills:
                if utils.ceil(fill.lx()) == x_offset:
                    current_fill.boundary[0].y = min(fill.by(), current_fill.by())
                    current_fill.boundary[1].y = max(fill.uy(), current_fill.uy())
                else:
                    add_to_merged(current_fill)
                    current_fill = fill
                    x_offset = utils.ceil(current_fill.lx())
            add_to_merged(current_fill)
        return to_boundary(merged_fills)

    def add_dummy_poly(self, cell, instances, words_per_row, from_gds=True):
        if PO_DUMMY not in tech_layers:
            return []
        _, min_height = self.calculate_min_area_fill(self.poly_width, layer=PO_DUMMY)
        instances = list(instances)
        cell_fills = self.get_poly_fills(cell)
        rects = []

        def add_fill(x_offset, direction="left"):
            for rect in cell_fills[direction]:
                height = max(rect[1][1] - rect[0][1], min_height)
                if instances[0].mirror == "MX":
                    y_offset = instances[0].by() + instances[0].height - height - rect[0][1]
                else:
                    y_offset = instances[0].by() + rect[0][1]
                rects.append(self.add_rect(PO_DUMMY,
                                           offset=vector(x_offset + rect[0][0], y_offset),
                                           width=self.poly_width, height=height))

        if len(cell_fills.values()) > 0:
            if words_per_row > 1:
                for inst in instances:
                    add_fill(inst.lx(), "left")
                    add_fill(inst.lx(), "right")
            else:
                add_fill(instances[0].lx(), "left")
                add_fill(instances[-1].lx(), "right")

            if hasattr(self, "tap_offsets") and len(self.tap_offsets) > 0:
                tap_width = utils.get_body_tap_width()
                tap_offsets = self.tap_offsets
                for offset in tap_offsets:
                    if offset > tap_width:
                        add_fill(offset - instances[-1].width, "right")
                        add_fill(offset + tap_width, "left")

                if hasattr(OPTS, "repeaters_array_space_offsets") and len(OPTS.repeaters_array_space_offsets) > 0:
                    add_fill(OPTS.repeaters_array_space_offsets[-1] + tap_width, "left")
                    add_fill(OPTS.repeaters_array_space_offsets[0] - instances[0].width, "right")

        return rects

    @staticmethod
    def import_mod_class_from_str(module_name, **kwargs):
        if "class_name" in kwargs and kwargs["class_name"]:
            class_name = kwargs["class_name"]
            del kwargs["class_name"]
        elif '.' in module_name:
            module_name, class_name = module_name.split('.')
        else:
            class_name = module_name
        module = __import__(module_name)
        mod_class = getattr(module, class_name)
        return mod_class

    def create_mod_from_str(self, module_name, *args, **kwargs):
        mod = self.create_mod_from_str_(module_name, *args, **kwargs)
        self.add_mod(mod)
        return mod

    @staticmethod
    def create_mod_from_str_(module_name, *args, **kwargs):
        """Helper method to create modules from string specification
        *args and **kwargs are passed to the class instantiation
        specify class name using .delimiter in module_name or as separate parameter
        specify rotation as 'rotation' parameter
        """
        if 'rotation' in kwargs:
            rotation = kwargs['rotation']
            del kwargs['rotation']
        else:
            rotation = None

        mod_class = design.import_mod_class_from_str(module_name, **kwargs)
        mod = mod_class(*args, **kwargs)

        if rotation is not None:
            from base.rotation_wrapper import RotationWrapper
            mod = RotationWrapper(mod, rotation_angle=rotation)

        return mod

    def DRC_LVS(self, final_verification=False):
        """Checks both DRC and LVS for a module"""
        import verify
        if OPTS.check_lvsdrc:
            tempspice = OPTS.openram_temp + "/temp.sp"
            tempgds = OPTS.openram_temp + "/temp.gds"
            self.sp_write(tempspice)
            self.gds_write(tempgds)
            debug.check(verify.run_drc(self.name, tempgds, exception_group=self.__class__.__name__) == 0,
                        "DRC failed for {0}".format(self.name))
            debug.check(verify.run_lvs(self.name, tempgds, tempspice, final_verification) == 0,
                        "LVS failed for {0}".format(self.name))
            os.remove(tempspice)
            os.remove(tempgds)

    def DRC(self):
        """Checks DRC for a module"""
        import verify
        if OPTS.check_lvsdrc:
            tempgds = OPTS.openram_temp + "/temp.gds"
            self.gds_write(tempgds)
            debug.check(verify.run_drc(self.name, tempgds, exception_group=self.__class__.__name__) == 0,
                        "DRC failed for {0}".format(self.name))
            os.remove(tempgds)

    def LVS(self, final_verification=False):
        """Checks LVS for a module"""
        import verify
        if OPTS.check_lvsdrc:
            tempspice = OPTS.openram_temp + "/temp.sp"
            tempgds = OPTS.openram_temp + "/temp.gds"
            self.sp_write(tempspice)
            self.gds_write(tempgds)
            debug.check(verify.run_lvs(self.name, tempgds, tempspice, final_verification) == 0,
                        "LVS failed for {0}".format(self.name))
            os.remove(tempspice)
            os.remove(tempgds)

    def __str__(self):
        """ override print function output """
        return "design: " + self.name

    def __repr__(self):
        """ override print function output """
        if self.width and self.height:
            text = "design: {} {:.3g} x {:.3g} \n".format(self.name, self.width, self.height)
        else:
            text = f"design: {self.name}"
        return text

    def analytical_power(self, proc, vdd, temp, load):
        """ Get total power of a module  """
        total_module_power = self.return_power()
        for inst in self.insts:
            total_module_power += inst.mod.analytical_power(proc, vdd, temp, load)
        return total_module_power
