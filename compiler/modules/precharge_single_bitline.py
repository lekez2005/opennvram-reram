import debug
from base import utils
from base.contact import poly_contact, m1m2, cross_m1m2, m2m3
from base.design import design, METAL1, METAL2, METAL3, ACTIVE, NIMP, PIMP
from base.geometry import NO_MIRROR, MIRROR_X_AXIS
from base.unique_meta import Unique
from base.utils import round_to_grid as rg
from base.vector import vector
from globals import OPTS
from modules.precharge import precharge_characterization
from pgates.ptx import ptx
from tech import parameter


class PrechargeSingleBitline(precharge_characterization, design, metaclass=Unique):
    @classmethod
    def get_name(cls, name=None, size=1):
        power_name = OPTS.precharge_power_name
        pin_name = OPTS.precharge_pin_name
        name = name or f"precharge_{pin_name}_{power_name}_{size:.5g}"
        return name.replace(".", "__")

    def __init__(self, name=None, size=1):
        name = self.get_name(name, size)
        design.__init__(self, name)
        debug.info(2, "%s name = %s", self.__class__.__name__, self.name)

        self.power_name = OPTS.precharge_power_name
        self.bl_pin_name = OPTS.precharge_pin_name
        self.size = size

        self.create_layout()
        self.add_boundary()

    def create_layout(self):
        self.add_pins()
        self.add_tx()
        self.add_enable_pin()
        self.route_bitline()
        self.add_power_pin()
        self.connect_power()
        self.add_bitlines()
        self.extend_implants()

    def add_pins(self):
        if self.power_name == "vdd":
            enable_pin = "en"
        else:
            enable_pin = f"{self.bl_pin_name}_reset"
        self.enable_pin = enable_pin
        self.add_pin_list(["bl", "br", enable_pin, self.power_name])
        debug.info(2, "PrechargeSingleBitline pins is [%s]", ", ".join(self.pins))

    def add_tx(self):
        self.bitcell = self.create_mod_from_str(OPTS.bitcell)
        self.width = self.bitcell.width

        if self.power_name == "vdd":
            size = self.size * parameter["beta"]
            tx_type = "pmos"
            mirror = NO_MIRROR
        else:
            size = self.size
            tx_type = "nmos"
            mirror = MIRROR_X_AXIS
        ptx_width = rg(size * self.min_tx_width)

        width = self.width - self.bitcell.get_pin("bl").rx()
        num_fingers = int(width / self.poly_pitch) - 1
        finger_width = rg(ptx_width / num_fingers)

        while num_fingers > 1:
            finger_width = rg(ptx_width / num_fingers)
            if finger_width < self.min_tx_width:
                num_fingers -= 1
            else:
                break
        finger_width = max(finger_width, self.min_tx_width)

        debug.info(2, "Num fingers = %d, Finger width = %5.5g", num_fingers, finger_width)
        tx = ptx(width=finger_width, mults=num_fingers, tx_type=tx_type, contact_poly=True)

        y_offset = 0.5 * self.poly_vert_space
        if mirror == MIRROR_X_AXIS:
            y_offset += tx.height
        x_offset = 0.5 * (self.width - tx.width)
        self.tx_inst = self.add_inst("tx", tx, vector(x_offset, y_offset), mirror=mirror)
        self.connect_inst([self.bl_pin_name, self.enable_pin, self.power_name, self.power_name])
        self.pmos = tx  # for delay characterization

    def add_enable_pin(self):
        m1_fill_height = poly_contact.h_2
        _, m1_fill_width = self.calculate_min_area_fill(m1_fill_height, layer=METAL1)
        gate_pins = list(sorted(self.tx_inst.get_pins("G"), key=lambda x: x.lx()))

        # m1 fill
        m1_m2_x = 0.5 * (gate_pins[0].cx() + gate_pins[-1].cx())
        m1_fill_x = min(gate_pins[0].lx(), m1_m2_x - 0.5 * m1m2.h_1)
        m1_fill_width = max(m1_fill_width, gate_pins[-1].rx() - m1_fill_x)
        self.add_rect(METAL1, vector(m1_fill_x, gate_pins[0].cy() - 0.5 * m1_fill_height),
                      width=m1_fill_width, height=m1_fill_height)

        via_offset = vector(m1_m2_x, gate_pins[0].cy())
        self.add_contact_center(m1m2.layer_stack, via_offset, rotate=90)
        self.add_contact_center(m2m3.layer_stack, via_offset, rotate=90)
        # m2 fill
        m2_fill_height = max(poly_contact.h_2, m2m3.w_1)
        _, m2_fill_width = self.calculate_min_area_fill(m2_fill_height, layer=METAL2)
        if m2_fill_width > self.m2_width:
            self.add_rect_center(METAL2, via_offset, width=m2_fill_width,
                                 height=m2_fill_height)
        offset = vector(0, gate_pins[0].cy() - 0.5 * self.bus_width)
        self.add_layout_pin(self.enable_pin, METAL3, offset, width=self.width, height=self.bus_width)

    def route_bitline(self):
        active_rect = max(self.tx_inst.get_layer_shapes(ACTIVE),
                          key=lambda x: x.width * x.height)
        drain_pins = list(sorted(self.tx_inst.get_pins("D"), key=lambda x: x.lx()))
        fill_width = drain_pins[0].width()
        _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL1)
        if fill_height < drain_pins[0].height():
            fill = False
            fill_y = 0
            self.drain_top = max(active_rect.uy(), drain_pins[0].uy())
        else:
            fill_width = self.poly_pitch - self.get_parallel_space(METAL1)
            _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL1)
            fill_height = max(fill_height, drain_pins[0].height())
            gate_pin = self.tx_inst.get_pins("G")[0]
            fill_y = max(gate_pin.uy() + self.get_parallel_space(METAL1),
                         utils.round_to_grid(drain_pins[0].cy() - 0.5 * fill_height))
            fill = True
            self.drain_top = fill_y + fill_height

        via_y = max(active_rect.by() + 0.5 * m1m2.h_1, drain_pins[0].cy())

        bitcell_pin = self.bitcell.get_pin(self.bl_pin_name)

        for pin in drain_pins:
            self.add_cross_contact_center(cross_m1m2, vector(pin.cx(), via_y))
            self.add_rect(METAL2, vector(pin.cx(), via_y - 0.5 * m1m2.w_2),
                          width=bitcell_pin.cx() - pin.cx(), height=m1m2.w_2)
            if fill:
                self.add_rect(METAL1, vector(pin.cx() - 0.5 * fill_width, fill_y),
                              width=fill_width, height=fill_height)

    def add_power_pin(self):
        pin_y = self.drain_top + self.get_parallel_space(METAL1)
        self.height = pin_y + self.rail_height

        offset = vector(0.5 * self.width, pin_y + 0.5 * self.rail_height)
        for layer in [METAL1, METAL3]:
            self.add_layout_pin_center_rect(self.power_name, layer, offset, height=self.rail_height,
                                            width=self.width)

        fill_x = 0.5 * (self.bitcell.get_pin("bl").cx() +
                        self.bitcell.get_pin("br").cx())

        fill_width = m1m2.h_2
        _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL2)
        fill_y = self.height - 0.5 * fill_height
        self.add_rect_center(METAL2, vector(fill_x, fill_y), width=fill_width,
                             height=fill_height)

        via_offset = vector(fill_x, offset.y)
        for via in [m1m2, m2m3]:
            self.add_contact_center(via.layer_stack, via_offset, rotate=90)

    def connect_power(self):
        sample_pin = self.get_pins(self.power_name)[0]
        fill_width = self.poly_pitch - self.get_parallel_space(METAL1)
        for pin in self.tx_inst.get_pins("S"):
            self.add_rect(METAL1, vector(pin.cx() - 0.5 * fill_width, pin.by()),
                          width=fill_width, height=sample_pin.cy() - pin.by())

    def add_bitlines(self):
        for pin_name in ["bl", "br"]:
            bitcell_pin = self.bitcell.get_pin(pin_name)
            self.add_layout_pin(pin_name, METAL2, vector(bitcell_pin.lx(), 0),
                                width=bitcell_pin.width(), height=self.height)

    def extend_implants(self):
        if self.implant_enclose_ptx_active <= 0:
            return
        layer = PIMP if self.tx_inst.mod.tx_type == "pmos" else NIMP
        tx_implant = max(self.tx_inst.get_layer_shapes(layer), key=lambda x: x.width * x.height)
        self.add_rect(layer, vector(0, tx_implant.by()), width=self.width,
                      height=tx_implant.height)


def make_precharge(pin_name, power_name, name, size):
    power_name_ = OPTS.precharge_power_name
    pin_name_ = OPTS.precharge_pin_name
    OPTS.precharge_power_name, OPTS.precharge_pin_name = power_name, pin_name
    cell = PrechargeSingleBitline(name=name, size=size)
    OPTS.precharge_power_name, OPTS.precharge_pin_name = power_name_, pin_name_
    return cell


def precharge_bl(name=None, size=1):
    return make_precharge("bl", "vdd", name, size)


def precharge_br(name=None, size=1):
    return make_precharge("br", "vdd", name, size)
