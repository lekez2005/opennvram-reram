import copy

from base.design import design
from base.hierarchy_layout import GDS_ROT_90, GDS_ROT_270
from base.vector import vector


class RotationWrapper(design):
    def __init__(self, child_mod, rotation_angle: int):
        assert rotation_angle in [GDS_ROT_90, GDS_ROT_270]
        name = child_mod.name + "_rot_{}".format(str(rotation_angle))
        super().__init__(name)

        self.width = child_mod.height
        self.height = child_mod.width
        if rotation_angle == GDS_ROT_90:
            offset = vector(child_mod.height, 0)
        else:
            offset = vector(0, child_mod.width)

        child_inst = self.add_inst("child_mod", mod=child_mod, offset=offset,
                                   rotate=rotation_angle)
        self.connect_inst(child_mod.pins)
        self.add_mod(child_mod)
        self.add_pin_list(child_mod.pins)
        for pin_name in child_mod.pins:
            if pin_name in child_mod.pin_map:
                self.copy_layout_pin(child_inst, pin_name, pin_name)

        self.child_mod = child_mod
        self.child_inst = child_inst

    def get_gds_layer_rects(self, layer, purpose=None, recursive=False):
        return self.get_layer_shapes(layer, purpose, recursive)

    def get_layer_shapes(self, layer, purpose=None, recursive=False):
        rects = self.child_mod.get_layer_shapes(layer, purpose, recursive)
        results = []
        if self.child_inst.rotate == GDS_ROT_90:
            scale = [-1, 1]
        else:
            scale = [1, -1]
        # rotate in place
        for rect in rects:
            rect = copy.copy(rect)
            ll = rect.ll().rotate_scale(*scale) + self.child_inst.offset
            ur = rect.ur().rotate_scale(*scale) + self.child_inst.offset
            rect.boundary = [ll, ur]
            rect.normalize()
            results.append(rect)
        return results
