import debug
import tech
from base.contact import m1m2
from base.design import design, ACTIVE, PIMP, NWELL, TAP_ACTIVE
from base.unique_meta import Unique
from base.utils import round_to_grid as rg
from base.vector import vector
from base.well_implant_fills import get_default_fill_layers
from modules.buffer_stage import BufferStage


class FlopBuffer(design, metaclass=Unique):
    """
    Flop a signal and buffer given input buffer sizes
    """

    @classmethod
    def get_name(cls, _, buffer_stages, negate=False, name=None):
        if name is not None:
            return name
        name = "flop_buffer_{}".format("_".join(
            ["{:.3g}".format(x).replace(".", "__") for x in buffer_stages]))
        if negate:
            name += "_neg"
        return name

    def __init__(self, flop_module_name, buffer_stages, negate=False, name=None):

        if buffer_stages is None or len(buffer_stages) < 1:
            debug.error("There should be at least one buffer stage", 1)

        self.buffer_stages = buffer_stages

        self.flop_module_name = flop_module_name
        self.negate = negate

        super().__init__(name=self.name)

        self.create_layout()

    def create_layout(self):
        self.add_pins()
        self.create_modules()
        self.add_modules()
        self.width = self.buffer_inst.rx()
        self.fill_layers()
        self.add_layout_pins()
        tech.add_tech_layers(self)

    def add_pins(self):
        self.add_pin_list(["din", "clk", "dout", "vdd", "gnd"])

    def create_modules(self):

        self.flop = self.create_mod_from_str(self.flop_module_name)

        self.height = self.flop.height

        self.buffer = BufferStage(self.buffer_stages, height=self.height, route_outputs=False,
                                  contact_pwell=False, contact_nwell=False, align_bitcell=False)
        self.add_mod(self.buffer)

    def connect_flop(self):
        self.connect_inst(["din", "flop_out", "flop_out_bar", "clk", "vdd", "gnd"])

    def connect_buffer(self):
        if ((len(self.buffer_stages) % 2 == 0 and not self.negate) or
                (len(self.buffer_stages) % 2 == 1 and self.negate)):
            if self.negate:
                nets = ["flop_out", "dout", "dout_bar"]
            else:
                nets = ["flop_out", "dout_bar", "dout"]
            flop_out = self.flop_inst.get_pin("dout")
        else:
            if self.negate:
                nets = ["flop_out_bar", "dout_bar", "dout"]
            else:
                nets = ["flop_out_bar", "dout", "dout_bar"]
            flop_out = self.flop_inst.get_pin("dout_bar")
        self.connect_inst(nets + ["vdd", "gnd"])
        return flop_out

    def add_modules(self):
        self.flop_inst = self.add_inst("flop", mod=self.flop, offset=vector(0, 0))
        self.connect_flop()

        if self.has_dummy:
            poly_dummies = self.flop.get_gds_layer_rects("po_dummy", "po_dummy", recursive=True)
            right_most = max(poly_dummies, key=lambda x: x.rx())
            center_poly = 0.5 * (right_most.lx() + right_most.rx())
            x_space = center_poly - self.flop.width
        else:
            nwell_left = min(self.buffer.get_layer_shapes(NWELL, recursive=True),
                             key=lambda x: x.lx())
            active_right = max(self.flop.get_layer_shapes(ACTIVE, recursive=True),
                               key=lambda x: x.rx())
            allowance = (self.flop.width - active_right.rx()) + nwell_left.lx()
            nwell_active_space = tech.drc.get("nwell_to_active_space", 0)
            x_space = max(0, nwell_active_space - allowance)

        self.buffer_inst = self.add_inst("buffer", mod=self.buffer,
                                         offset=self.flop_inst.lr() + vector(x_space, 0))

        flop_out = self.connect_buffer()

        buffer_in = self.buffer_inst.get_pin("in")
        via_x = buffer_in.lx() + m1m2.second_layer_height
        via_y = buffer_in.cy() - 0.5 * m1m2.second_layer_width
        self.add_contact(m1m2.layer_stack, offset=vector(via_x, via_y), rotate=90)

        path_start = vector(flop_out.rx(), flop_out.uy() - 0.5 * self.m2_width)
        via_m2_x = via_x - 0.5 * m1m2.height - 0.5 * m1m2.h_2
        mid_x = min(0.5 * (buffer_in.lx() + flop_out.rx()),
                    via_m2_x - self.m2_space - 0.5 * self.m2_width)
        self.add_path("metal2", [path_start, vector(mid_x, path_start[1]), buffer_in.lc()])

    def fill_layers(self):
        layers, purposes = get_default_fill_layers()
        for i in range(len(layers)):
            layer = layers[i]
            if layer in [ACTIVE, TAP_ACTIVE]:
                continue
            buffer_shapes = self.buffer_inst.get_layer_shapes(layer, purposes[i], recursive=True)
            flop_shapes = self.flop_inst.get_layer_shapes(layer, purposes[i], recursive=True)
            if not flop_shapes or not buffer_shapes:
                continue

            # there could be multiple implants, one for the tx and one for the tap
            if "implant" in layer:
                right_most_flop_rect = max(flop_shapes, key=lambda x: x.rx())
                all_right_rects = list(filter(lambda x: x.rx() == right_most_flop_rect.rx(),
                                              flop_shapes))
                right_most_flop_rect = max(all_right_rects, key=lambda x: x.height)
                left_most_buffer_rect = min(buffer_shapes, key=lambda x: x.lx())
                x_offset = right_most_flop_rect.rx()
                width = left_most_buffer_rect.rx() - x_offset
                if layer == PIMP:
                    top, bottom = self.height + 0.5 * self.implant_width, left_most_buffer_rect.by()
                else:
                    top, bottom = left_most_buffer_rect.uy(), - 0.5 * self.implant_width
                self.add_rect(layer, offset=vector(x_offset, bottom), width=width,
                              height=top - bottom)
                rightmost_buffer_rect = max(buffer_shapes, key=lambda x: x.rx())
                if rg(rightmost_buffer_rect.rx()) > rg(left_most_buffer_rect.rx()):
                    width = rightmost_buffer_rect.rx() - x_offset
                    y_offset = top - self.implant_width if layer == PIMP else bottom
                    self.add_rect(layer, offset=vector(x_offset, y_offset),
                                  width=width, height=self.implant_width)
            else:
                right_most_flop_rect = max(flop_shapes, key=lambda x: x.rx())
                left_most_buffer_rect = min(buffer_shapes, key=lambda x: x.lx())
                top = min(right_most_flop_rect.uy(), left_most_buffer_rect.uy())
                left = right_most_flop_rect.rx()
                right = left_most_buffer_rect.lx()
                bottom = max(right_most_flop_rect.by(), left_most_buffer_rect.by())
                width = right - left
                if width > 0:
                    self.add_rect(layer, offset=vector(left, bottom), width=right - left,
                                  height=top - bottom)

    def add_layout_pins(self):
        self.copy_layout_pin(self.flop_inst, "clk", "clk")
        self.copy_layout_pin(self.flop_inst, "din", "din")
        if len(self.buffer_stages) % 2 == 1:
            flop_out = "out_inv"
        else:
            flop_out = "out"
        self.copy_layout_pin(self.buffer_inst, flop_out, "dout")
        self.add_power_layout_pins()

    def add_power_layout_pins(self):
        for pin_name in ["vdd", "gnd"]:
            buffer_pin = self.buffer_inst.get_pin(pin_name)
            flop_pin = self.flop_inst.get_pin(pin_name)
            if pin_name == "gnd":
                y_offset = max(buffer_pin.by(), flop_pin.by())
                y_top = min(buffer_pin.uy(), flop_pin.uy())
            else:
                y_offset = max(buffer_pin.by(), flop_pin.by())
                y_top = min(buffer_pin.uy(), flop_pin.uy())
            self.add_layout_pin(pin_name, buffer_pin.layer, offset=vector(0, y_offset), width=self.width,
                                height=y_top - y_offset)
