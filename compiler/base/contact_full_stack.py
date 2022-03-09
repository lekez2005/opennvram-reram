import tech
from base import design, utils
from base import unique_meta
from base.contact import contact
from base.vector import vector


class ContactFullStack(design.design, metaclass=unique_meta.Unique):
    """
    Object for a full metal stack power
    """
    _m1_stack = None
    _m2_stack = None

    @classmethod
    def m1mtop(cls):
        if cls._m1_stack is None:
            cls._m1_stack = cls(start_layer=0, centralize=False)
        return cls._m1_stack

    @classmethod
    def m2mtop(cls):
        if cls._m2_stack is None:
            cls._m2_stack = cls(start_layer=1)
        return cls._m2_stack

    @classmethod
    def get_name(cls, start_layer=0, stop_layer=-1, centralize=True, dimensions=None, max_width=None,
                 max_height=None):

        start_layer, stop_layer = cls.normalize_layers(start_layer, stop_layer)

        dim_str = "_" + "_".join([str(dim) for dim in dimensions]) if dimensions else ""
        width_suffix = "" if not max_width else "_w{:.5g}".format(max_width).replace(".", "__")
        height_suffix = "" if not max_height else "_h{:.5g}".format(max_height).replace(".", "__")
        alignment = "c" if centralize else "l"
        name = "via_M{0}_M{1}_{2}{3}{4}{5}".format(start_layer, stop_layer, alignment,
                                                   dim_str, width_suffix, height_suffix)
        return name

    @staticmethod
    def normalize_layers(start_layer, stop_layer):
        metal_layers, layer_numbers = utils.get_sorted_metal_layers()

        if isinstance(start_layer, str):
            start_layer = metal_layers.index(start_layer)
        if isinstance(stop_layer, str):
            stop_layer = metal_layers.index(stop_layer)

        real_start_layer = layer_numbers[start_layer]
        real_stop_layer = layer_numbers[stop_layer]
        return real_start_layer, real_stop_layer

    def __init__(self, start_layer=0, stop_layer=-1, centralize=True, dimensions=None,
                 max_width=None, max_height=None):
        dimensions = dimensions if dimensions else []
        design.design.__init__(self, self.name)

        self.start_layer, self.stop_layer = self.normalize_layers(start_layer, stop_layer)

        self.max_width = max_width
        self.max_height = max_height
        self.dimensions = dimensions
        self.centralize = centralize

        self.via_insts = []

        self.calculate_dimensions()
        self.create_stack()

    @staticmethod
    def get_via_layers(layer):
        return ("metal{}".format(layer),
                "via{}".format(layer),
                "metal{}".format(layer + 1))

    def calculate_dimensions(self):
        top_via_stack = self.get_via_layers(self.stop_layer - 1)
        if self.max_width is None:
            power_grid_num_vias = getattr(tech, "power_grid_num_vias", 1)
            if not self.dimensions:
                self.dimensions = [1, power_grid_num_vias]

            sample_contact = contact(layer_stack=top_via_stack, dimensions=self.dimensions)
            self.width = sample_contact.height
        else:
            self.width = self.max_width
            num_cols = self.calculate_num_cols(self.stop_layer - 1, self.max_width)
            self.dimensions = [1, num_cols]
        if self.max_height is not None:
            num_rows = self.calculate_num_rows(self.stop_layer - 1, self.max_height)
            self.dimensions = [max(1, num_rows), self.dimensions[1]]
        self.top_via = contact(layer_stack=top_via_stack, dimensions=self.dimensions)
        self.width = max(self.width, self.top_via.height)
        self.height = self.top_via.width

    def create_stack(self):
        bottom_via = None
        for layer_num in range(self.start_layer, self.stop_layer):
            via_stack = self.get_via_layers(layer_num)
            num_cols = self.calculate_num_cols(layer_num, self.width)
            num_rows = self.calculate_num_rows(layer_num, self.height)
            via = contact(via_stack, dimensions=[num_rows, num_cols])
            self.place_via(via, bottom_via)
            bottom_via = via

    def place_via(self, via, bottom_via):
        y_offset = utils.round_to_grid(0.5 * (self.height - via.width))
        if self.centralize:
            x_offset = 0.5 * via.height
        else:
            x_offset = 0.5 * self.width + 0.5 * via.height
        via_inst = self.add_inst(via.name, via, vector(x_offset, y_offset), rotate=90)
        self.connect_inst([])
        self.via_insts.append(via_inst)
        if bottom_via is not None:
            mid_layer_width = max(bottom_via.second_layer_height, via.first_layer_height)
            mid_layer_height = max(bottom_via.second_layer_width, via.first_layer_width)
            if self.centralize:
                x_offset = -0.5 * mid_layer_width
            else:
                x_offset = 0.5 * self.width - 0.5 * mid_layer_width
            y_offset = 0.5 * self.height - 0.5 * mid_layer_height
            self.add_rect(via.first_layer_name, offset=vector(x_offset, y_offset),
                          width=mid_layer_width, height=mid_layer_height)

    def calculate_num_cols(self, layer_num, max_width):
        via_stack = self.get_via_layers(layer_num)
        num_cols = 1
        while num_cols >= 1:
            sample_contact = contact(layer_stack=via_stack, dimensions=[1, num_cols])
            if sample_contact.height <= max_width:
                num_cols += 1
            else:
                num_cols -= 1
                break
        return max(num_cols, 1)

    def calculate_num_rows(self, layer_num, max_height):
        via_stack = self.get_via_layers(layer_num)
        num_rows = 1
        while num_rows >= 1:
            sample_contact = contact(layer_stack=via_stack, dimensions=[num_rows, 1])
            if sample_contact.width <= max_height:
                num_rows += 1
            else:
                num_rows -= 1
                break
        return num_rows
