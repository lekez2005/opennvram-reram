from abc import ABC
from itertools import groupby
from typing import List

from tech import drc, spice, layer as tech_layers


class RC:
    cap_scale = 1e-15

    def __init__(self, width, space, res, cap):
        """width, space in um, c in cap/um^2, r in ohm/square"""
        self.width = width
        self.space = space
        self.__cap = cap
        self.res = res

    @property
    def cap(self):
        return self.cap_scale * self.__cap

    def __str__(self):
        return "(c = {:.3g} r = {:.3g} width = {:.3g} space = {:.3g}".format(self.cap, self.res,
                                                                             self.width, self.space)


class DelayParamsBase(ABC):
    """
    The following params must be defined in concrete class as imported from tech.py script
    If layer isn't defined in the concrete class, default value from wire_unit_c and wire_unit_r are used
    c_drain, c_gate, r_pmos, r_nmos, r_intrinsic, beta
    """
    # example
    # metal100 = [RC(0.1, 0.1, 0.1, 0.1)]
    min_width = drc["minwidth_metal1"]
    min_space = drc["metal1_to_metal1"]
    rc_map = {}

    @classmethod
    def initialize(cls):
        if len(cls.rc_map) > 0:  # RC map has been initialized
            return

        # set default map for layers that weren't explicitly set
        for layer in cls.get_routing_layers():
            if not hasattr(cls, layer):
                setattr(cls, layer, [RC(cls.min_width, cls.min_space, spice["wire_unit_r"],
                                        spice["wire_unit_c"])])

        for i in range(1, 20):
            layer = "metal{}".format(i)
            if hasattr(cls, layer):
                layer_rc = getattr(cls, layer)  # type: List[RC]
                layer_map = {}
                for width, width_matches in groupby(layer_rc, key=lambda x: x.width):
                    width_map = {}
                    for rc_param in width_matches:
                        width_map[rc_param.space] = rc_param
                    layer_map[width] = width_map
                cls.rc_map[layer] = layer_map

    @classmethod
    def get_routing_layers(cls):
        # find metal layers
        metal_layer_suffixes = []
        for key in tech_layers:
            if key.startswith("metal") and key[5:].isnumeric():
                metal_layer_suffixes.append(int(key[5:]))
        return ["metal{}".format(i) for i in metal_layer_suffixes]

    @classmethod
    def get_rc(cls, layer=None, width=None, space=None):
        """Return cap in F per um and r in ohm per micron """
        if not cls.rc_map:
            cls.initialize()
        if layer is None:
            layer = "metal1"
        if not width:
            width = cls.min_width
        if not space:
            space = cls.min_space

        rc_def = cls.find_closest(layer, width, space)
        c = rc_def.cap * width
        r = rc_def.res / width
        return c, r

    @classmethod
    def find_closest(cls, layer, width, space) -> RC:
        layer_map = cls.rc_map[layer]
        closest_width = min(layer_map.keys(), key=lambda x: abs(x - width))
        width_map = layer_map[closest_width]
        closest_space = min(width_map.keys(), key=lambda x: abs(x - space))
        return width_map[closest_space]
