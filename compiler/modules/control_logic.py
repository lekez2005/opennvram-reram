import math
from importlib import reload

import debug
from base import contact
from base import design
from base.vector import vector
from globals import OPTS
from modules import control_logic_buffer
from pgates import pgate
from pgates.pinv import pinv
from pgates.pnand2 import pnand2
from pgates.pnand3 import pnand3
from pgates.pnor2 import pnor2
from tech import drc


class control_logic(design.design):
    """
    Dynamically generated Control logic for the total SRAM circuit.
    """

    def __init__(self, num_rows):
        """ Constructor """
        design.design.__init__(self, "control_logic")
        debug.info(1, "Creating {}".format(self.name))

        self.num_rows = num_rows
        self.m1m2_layers = ("metal1", "via1", "metal2")
        self.clk_buffer_stages = OPTS.control_logic_clk_buffer_stages
        self.create_layout()
        self.DRC_LVS()

    def create_layout(self):
        """ Create layout and route between modules """
        self.create_modules()
        self.setup_layout_offsets()
        self.add_modules()
        self.calculate_dimensions()
        self.add_routing()
        self.add_layout_pins()

        self.add_lvs_correspondence_points()

    def add_pins(self):
        input_lst = ["csb", "web", "oeb", "clk"]
        output_lst = ["s_en", "w_en", "tri_en", "clk_buf"]
        rails = ["vdd", "gnd"]
        for pin in input_lst + output_lst + rails:
            self.add_pin(pin)

    def create_modules(self):
        """ add all the required modules """
        self.add_pins()

        self.nand2 = pnand2(1.5)
        self.add_mod(self.nand2)
        self.nand3 = pnand3()
        self.add_mod(self.nand3)

        self.nor2 = pnor2()
        self.add_mod(self.nor2)


        # Special gates: inverters for buffering
        self.inv1 = pinv(1)
        self.add_mod(self.inv1)

        self.inv2 = pinv(2)
        self.add_mod(self.inv2)

        self.create_flops()

        self.create_logic_buffers()

        c = reload(__import__(OPTS.replica_bitline))
        replica_bitline = getattr(c, OPTS.replica_bitline)
        # FIXME: These should be tuned according to the size!
        delay_stages = 4  # This should be even so that the delay line is inverting!
        delay_fanout = 3
        bitcell_loads = int(math.ceil(self.num_rows / 5.0))
        bitcell_loads = bitcell_loads if bitcell_loads % 2 == 1 else bitcell_loads + 1
        self.replica_bitline = replica_bitline(delay_stages, delay_fanout, bitcell_loads)
        self.add_mod(self.replica_bitline)

    def create_flops(self):
        c = reload(__import__(OPTS.ms_flop_array))
        ms_flop_array = getattr(c, OPTS.ms_flop_array)
        self.msf_control = ms_flop_array(name="msf_control",
                                         columns=3,
                                         word_size=3)
        self.add_mod(self.msf_control)

    def create_logic_buffers(self):
        self.logic_buffer = control_logic_buffer.ControlLogicBuffer(OPTS.control_logic_logic_buffer_stages,
                                                                    contact_nwell=False, contact_pwell=False)
        self.add_mod(self.logic_buffer)

        self.logic_buffer_cont_pwell = control_logic_buffer.ControlLogicBuffer(OPTS.control_logic_logic_buffer_stages,
                                                                          contact_nwell=False, contact_pwell=True)
        self.add_mod(self.logic_buffer_cont_pwell)



    def setup_layout_offsets(self):
        """ Setup layout offsets, determine the size of the busses etc """
        # These aren't for instantiating, but we use them to get the dimensions
        self.poly_contact_offset = vector(0.5*contact.poly.width,0.5*contact.poly.height)

        # M1/M2 routing pitch is based on contacted pitch
        self.m1_pitch = self.m1_width + self.m1_space
        self.m2_pitch = self.m2_width + self.m2_space
        self.m3_pitch = self.m3_width + self.m3_space

        # Have the cell gap leave enough room to route an M2 wire.
        # Some cells may have pwell/nwell spacing problems too when the wells are different heights.
        self.cell_gap = max(self.m2_pitch,drc["pwell_to_nwell"])

        # First RAIL Parameters: gnd, oe, oebar, cs, we, clk_buf, clk_bar
        self.rail_1_start_x = 0
        self.num_rails_1 = 8
        self.rail_1_names = ["clk_buf", "gnd", "oe_bar", "cs", "we", "vdd",  "oe", "clk_bar"]
        self.overall_rail_1_gap = (self.num_rails_1 + 2) * self.m2_pitch
        self.rail_1_x_offsets = {}

        # GAP between main control and replica bitline
        self.replica_bitline_gap = 2*self.m2_pitch

    def calculate_dimensions(self):
        self.height = self.clk_inv1.get_pin("vdd").uy()

        msf_right_x = self.msf_inst.rx()
        self.clk_bar_rail_x = msf_right_x + self.m2_pitch
        self.clk_buf_rail_x = self.clk_bar_rail_x + self.m2_pitch

        [self.left_vdd, self.right_vdd] = sorted(self.rbl.get_pins("vdd"), key=lambda x: x.lx())



        self.width = (max(self.right_vdd.rx(), self.clk_buf_rail_x + self.m2_width) +
                     self.line_end_space + self.rail_height)
        


    def add_modules(self):
        """ Place all the modules """
        self.add_rbl()
        self.add_rbl_buffer()
        self.add_blk()
        self.add_wen_buffer()
        self.add_wen()
        self.add_tri_en()
        self.add_control_flops()
        self.add_clk_buffer()

        


    def add_routing(self):
        """ Routing between modules """
        self.route_clk()
        self.route_msf()
        self.create_output_rails()
        self.route_tri_en()
        self.route_w_en()
        self.route_blk()
        self.route_vdd()
        self.route_gnd()

    def add_rbl(self):
        """ Add the replica bitline """

        y_offset = self.replica_bitline.height - self.replica_bitline.get_pin("gnd").uy() # after mirror

        self.replica_bitline_offset = vector(0 , y_offset)
        self.rbl=self.add_inst(name="replica_bitline",
                               mod=self.replica_bitline,
                               offset=self.replica_bitline_offset + vector(0, self.replica_bitline.height),
                               mirror="MX",
                               rotate=0)

        self.connect_inst(["rblk", "pre_s_en", "vdd", "gnd"])

    def add_rbl_buffer(self):
        sen_buf = pinv(8, contact_nwell=False)
        self.add_mod(sen_buf)

        y_space = 2*self.m1_pitch
        # extra m1_width added to x_space because some rails extend past the cells
        x_space = self.rail_height + self.parallel_line_space
        # BUFFER INVERTER FOR S_EN
        # input: input: pre_s_en, output: s_en
        self.s_en_offset = self.replica_bitline_offset + vector(x_space, self.replica_bitline.height + y_space)
        self.s_en = self.add_inst(name="inv_s_en",
                                  mod=sen_buf,
                                  mirror="MY",
                                  offset=self.s_en_offset + vector(sen_buf.width, 0))
        self.connect_inst(["pre_s_en", "s_en", "vdd", "gnd"])



    def add_blk(self):

        # input: rblk_bar, output: rblk

        inv = pinv(1, contact_nwell=True)
        self.add_mod(inv)

        self.rblk_offset = self.s_en_offset + vector(0, inv.height)
        self.rblk = self.add_inst(name="inv_rblk",
                                  mod=inv,
                                  mirror="XY",
                                  offset=self.rblk_offset + vector(inv.width, inv.height))
        self.connect_inst(["rblk_bar", "rblk", "vdd", "gnd"])

        # input: OE, clk_bar,CS output: rblk_bar
        self.rblk_bar_offset = self.rblk_offset + vector(inv.width, 0)
        self.rblk_bar = self.add_inst(name="nand3_rblk_bar",
                                      mod=self.nand3,
                                      mirror="XY",
                                      offset=self.rblk_bar_offset+vector(self.nand3.width, self.nand3.height))
        pgate.pgate.equalize_nwell(self, self.rblk, self.rblk_bar, self.s_en, self.s_en)

        self.connect_inst(["clk_bar", "oe", "cs", "rblk_bar", "vdd", "gnd"])


    def add_wen_buffer(self):
        offset = self.rblk_offset + vector(0, self.rblk.height)
        self.w_en_buffer = self.add_inst("w_en_buffer", mod=self.logic_buffer, offset=offset)
        self.connect_inst(["pre_w_en", "w_en", "vdd", "gnd"])

    def add_wen(self):

        # input: w_en_bar, output: pre_w_en
        self.pre_w_en_offset = self.w_en_buffer.ul()
        self.pre_w_en = self.add_inst(name="inv_pre_w_en",
                                      mod=self.inv1,
                                      mirror="XY",
                                      offset=self.pre_w_en_offset + vector(self.inv1.width, self.inv1.height))
        self.connect_inst(["w_en_bar", "pre_w_en", "vdd", "gnd"])

        # input: WE, clk_bar, CS output: w_en_bar
        self.w_en_bar_offset = self.pre_w_en_offset + vector(self.inv1.width, 0)
        self.w_en_bar = self.add_inst(name="nand3_w_en_bar",
                                      mod=self.nand3,
                                      mirror="XY",
                                      offset=self.w_en_bar_offset + vector(self.nand3.width, self.nand3.height))
        self.connect_inst(["clk_bar", "cs", "we", "w_en_bar", "vdd", "gnd"])

    def add_tri_en(self):
        offset = self.pre_w_en.ul()
        self.tri_en_buffer = self.add_inst("tri_en_buffer", mod=self.logic_buffer, offset=offset)
        self.connect_inst(["pre_tri_en", "tri_en", "vdd", "gnd"])

        inv1 = pinv(1)
        self.add_mod(inv1)
        pnand = pnand2(1.5)
        self.add_mod(pnand)

        self.pre_tri_en_offset = self.tri_en_buffer.ul()
        self.pre_tri_en = self.add_inst(name="inv_pre_tri_en", mod=inv1,
                                        offset=self.pre_tri_en_offset + vector(inv1.width, inv1.height),
                                        mirror="XY")
        self.connect_inst(["pre_tri_en_bar", "pre_tri_en", "vdd", "gnd"])

        self.pre_tri_en_bar_offset = self.pre_tri_en_offset + vector(self.pre_tri_en.width, 0)
        self.pre_tri_en_bar = self.add_inst(name="nand2_pre_tri_en_bar", mod=pnand,
                                            offset=self.pre_tri_en_bar_offset + vector(pnand.width, pnand.height),
                                            mirror="XY")
        self.connect_inst(["clk_bar", "oe", "pre_tri_en_bar", "vdd", "gnd"])

    def add_control_flops(self):
        """ Add the control signal flops for OEb, WEb, CSb. """
        self.msf_bottom_gnd = min(self.msf_control.get_pins("gnd"), key=lambda x: x.by())
        self.h_rail_pitch = contact.m1m2.first_layer_width + self.m1_space
        y_space = (0.5*self.pre_tri_en.get_pin("vdd").height() + self.parallel_line_space +
                  3*self.h_rail_pitch + 0.5*self.msf_bottom_gnd.height())
        self.msf_offset = self.pre_tri_en_offset + vector(0, self.pre_tri_en.height + y_space)
        self.msf_inst=self.add_inst(name="msf_control",
                                    mod=self.msf_control,
                                    offset=self.msf_offset + vector(0, self.msf_control.height),
                                    mirror="MX",
                                    rotate=0)
        # don't change this order. This pins are meant for internal connection of msf array inside the control logic.
        # These pins are connecting the msf_array inside of control_logic.
        temp = ["oeb", "csb", "web",
                "oe_bar", "oe",
                "cs_bar", "cs",
                "we_bar", "we",
                "clk_buf", "vdd", "gnd"]
        self.connect_inst(temp)

    def get_ff_clk_buffer_space(self):
        return 5*self.m1_pitch + self.rail_height

    def add_clk_buffer(self):
        """ Add the multistage clock buffer above the control flops """

        y_space = self.get_ff_clk_buffer_space()


        clk_buf_mod = pinv(self.clk_buffer_stages[3])
        self.add_mod(clk_buf_mod)

        # clk_buf
        self.clk_buf_offset = self.msf_offset + vector(0, self.msf_control.height + y_space)
        self.clk_buf = self.add_inst(name="inv_clk_buf",
                                     mod=clk_buf_mod,
                                     offset=self.clk_buf_offset)
        self.connect_inst(["clk_bar", "clk_buf", "vdd", "gnd"])

        # clk_bar
        clk_bar_mod = pinv(self.clk_buffer_stages[2], contact_nwell=False)
        self.add_mod(clk_bar_mod)
        self.clk_bar_offset = self.clk_buf_offset + vector(0, self.clk_buf.height)
        self.clk_bar = self.add_inst(name="inv_clk_bar",
                                     mod=clk_bar_mod,
                                     mirror="MX",
                                     offset=self.clk_bar_offset + vector(0, clk_bar_mod.height))
        self.connect_inst(["clk2", "clk_bar", "vdd", "gnd"])

        clk_inv2_mod = pinv(self.clk_buffer_stages[1], contact_pwell=False)
        self.add_mod(clk_inv2_mod)
        self.clk_inv2_offset = self.clk_bar_offset + vector(0, clk_buf_mod.height)
        self.clk_inv2 = self.add_inst(name="inv_clk2",
                                      mod=clk_inv2_mod,
                                      mirror="MY",
                                      offset=self.clk_inv2_offset+vector(clk_inv2_mod.width, 0))
        self.connect_inst(["clk1_bar", "clk2", "vdd", "gnd"])

        clk_inv1_mod = pinv(self.clk_buffer_stages[0], contact_pwell=False)
        self.add_mod(clk_inv1_mod)
        self.clk_inv1_offset = self.clk_inv2_offset + vector(clk_inv2_mod.width, 0)
        self.clk_inv1 = self.add_inst(name="inv_clk1_bar",
                                      mod=clk_inv1_mod,
                                      mirror="MY",
                                      offset=self.clk_inv1_offset + vector(clk_inv1_mod.width, 0))
        self.connect_inst(["clk", "clk1_bar", "vdd", "gnd"])




    def route_clk(self):
        """ Route the clk and clk_bar signal internally """
        a_pin = self.clk_inv2.get_pin("A")
        z_pin = self.clk_inv1.get_pin("Z")
        self.add_rect("metal1", offset=a_pin.lr(), width=z_pin.lx() - a_pin.rx())

        # clk_bar input
        a_pin = self.clk_bar.get_pin("A")
        z_pin = self.clk_inv2.get_pin("Z")
        mid_y = a_pin.cy()-0.5*contact.m1m2.second_layer_width
        self.add_rect("metal2", offset=vector(z_pin.lx(), mid_y), height=z_pin.by()-mid_y)
        self.add_rect("metal2", offset=vector(z_pin.lx(), mid_y), width=a_pin.lx()-z_pin.lx())
        self.add_contact_center(contact.contact.m1m2_layers,
                                offset=a_pin.lc() + vector(0.5 * contact.m1m2.second_layer_height, 0), rotate=90)

        # clk_buf input
        z_pin = self.clk_bar.get_pin("Z")
        a_pin = self.clk_buf.get_pin("A")
        vdd_pin = self.clk_bar.get_pin("vdd")

        self.add_path("metal2", [
            vector(z_pin.cx(), z_pin.by()),
            vector(z_pin.cx(), vdd_pin.cy()),
            vector(self.clk_buf.lx()+self.m2_space, vdd_pin.cy()),
            vector(self.clk_buf.lx()+self.m2_space, a_pin.cy()),
            vector(a_pin.lx(), a_pin.cy())
        ])
        self.add_contact_center(contact.contact.m1m2_layers,
                                offset=a_pin.lc() + vector(0.5*contact.m1m2.second_layer_height, 0), rotate=90)


        # add clk and clk_bar rails

        bottom = self.s_en.get_pin("A").cy()
        top = self.clk_bar.get_pin("Z").by()
        self.clk_bar_rail = self.left_clk_rail = self.add_rect("metal2", width=self.m2_width, height=top-bottom,
                                                               offset=vector(self.clk_bar_rail_x, bottom))
        top = self.clk_buf.get_pin("Z").by()
        self.clk_buf_rail = self.right_clk_rail = self.add_rect("metal2", width=self.m2_width, height=top-bottom,
                      offset=vector(self.clk_buf_rail_x, bottom))

        # route clk_bar to rail
        clk_bar_z = self.clk_bar.get_pin("Z")
        self.add_rect("metal1", offset=clk_bar_z.bc()-vector(0, 0.5*self.m2_width),
                      width=self.clk_bar_rail_x - clk_bar_z.cx())
        self.add_contact_center(contact.contact.m1m2_layers, offset=vector(
            self.clk_bar_rail_x+0.5*contact.m1m2.second_layer_width, clk_bar_z.by()))

        clk_buf_z = self.clk_buf.get_pin("Z")
        self.add_rect("metal1", offset=clk_buf_z.bc() - vector(0, 0.5 * self.m2_width),
                      width=self.clk_buf_rail_x - clk_buf_z.cx())
        self.add_contact_center(contact.contact.m1m2_layers, offset=vector(
            self.clk_buf_rail_x + 0.5 * contact.m1m2.second_layer_width, clk_buf_z.by()))

    def route_pin_to_rail(self, pin, rail_rect, y_pos, x_pos):
        self.add_contact_center(layers=self.m1m2_layers,
                                offset=vector(rail_rect.offset.x + rail_rect.width - 0.5*contact.m1m2.second_layer_height,
                                                                y_pos), rotate=90)
        self.add_rect("metal1", vector(x_pos, y_pos - 0.5*self.m1_width), height=self.m1_width,
                      width=rail_rect.offset.x + 0.5*rail_rect.width - x_pos)
        self.add_contact_center(layers=self.m1m2_layers, offset=vector(pin.cx(), y_pos), rotate=90)
        self.add_path("metal2", [vector(pin.cx(), y_pos), vector(pin.cx(), pin.cy())])

    def route_msf(self):
        rail_top = self.clk_bar_rail.uy()
        rail_bottom = self.msf_inst.uy() + 2*self.m2_space
        rail_height = rail_top - rail_bottom
        rail_width = self.m2_width
        rail_pitch = rail_width + self.line_end_space
        rail_offset = vector(self.left_clk_rail.lx() - rail_pitch, rail_bottom)
        self.web_rail = self.add_rect("metal2", offset=rail_offset, height=rail_height, width=self.m2_width)
        self.csb_rail = self.add_rect("metal2", offset=rail_offset-vector(rail_pitch, -self.m1_pitch),
                                      height=rail_height-self.m1_pitch,
                                      width=self.m2_width)
        self.oeb_rail = self.add_rect("metal2", offset=rail_offset-vector(2*rail_pitch, -2*self.m1_pitch),
                                      height=rail_height-2*self.m1_pitch,
                                      width=self.m2_width)

        y_pos = self.msf_inst.uy() + self.m1_pitch
        m2_pin_lambda = lambda x: x.layer=="metal2"
        self.route_pin_to_rail(next(filter(m2_pin_lambda, self.msf_inst.get_pins("din[2]"))),
                               self.web_rail, y_pos, self.msf_inst.lx()+self.m1_space)
        self.route_pin_to_rail(next(filter(m2_pin_lambda, self.msf_inst.get_pins("din[1]"))),
                               self.csb_rail, y_pos + self.m1_pitch, self.msf_inst.lx()+self.m1_space)
        self.route_pin_to_rail(next(filter(m2_pin_lambda, self.msf_inst.get_pins("din[0]"))),
                               self.oeb_rail, y_pos + 2*self.m1_pitch, self.msf_inst.lx()+self.m1_space)

        msf_clk_pin = self.msf_inst.get_pin("clk")
        rail_left_x = self.clk_buf_rail.offset.x
        self.add_rect("metal1", width=rail_left_x - msf_clk_pin.rx(), height=msf_clk_pin.height(),
                      offset=msf_clk_pin.lr())
        self.add_contact_center(layers=self.m1m2_layers,
                                offset=vector(rail_left_x+0.5*contact.m1m2.second_layer_width,
                                              msf_clk_pin.cy()))

        # add msf output rails
        rail_width = self.m2_width
        rail_pitch = rail_width + self.m2_space

        # rail_order from left to right is [oe_bar oe we cs]
        oe_bottom = self.rblk_bar.get_pin("B").by()
        we_bottom = self.w_en_bar.get_pin("C").by()
        cs_bottom = self.rblk_bar.get_pin("C").by()

        we_pin = self.msf_inst.get_pin("dout_bar[2]")
        self.we_rail = self.add_rect("metal2", offset=vector(we_pin.lx(), we_bottom),
                                     height=we_pin.by()-we_bottom)

        bottoms = [oe_bottom, cs_bottom]
        msf_outputs = [self.msf_inst.get_pin("dout_bar[0]"),
                       self.msf_inst.get_pin("dout_bar[1]")]
        horizontal_rail_order = [2, 1]

        rail_x_offset = self.we_rail.lx() - len(bottoms) * rail_pitch
        m1_y_offset = self.msf_inst.by() - 0.5*self.msf_bottom_gnd.height() - (self.parallel_line_space-self.m1_space)
        vrails = [None]*len(bottoms)
        for i in range(0, len(bottoms)):
            output_pin = msf_outputs[i]
            # vertical rail
            v_rail_offset = vector(rail_x_offset + i*rail_pitch, bottoms[i])
            h_rail_offset = vector(output_pin.lx(), m1_y_offset - horizontal_rail_order[i] * self.h_rail_pitch)

            rail_height = h_rail_offset.y + self.m1_width - bottoms[i]
            vrails[i] = self.add_rect("metal2", width=rail_width, height=rail_height, offset=v_rail_offset)

            # horizontal rail

            h_rail_width = v_rail_offset.x - output_pin.lx() + rail_width
            self.add_rect("metal1", offset=h_rail_offset, width=h_rail_width, height=rail_width)
            self.add_rect("metal2", offset=vector(output_pin.lx(), h_rail_offset.y),
                          height=output_pin.by()-h_rail_offset.y, width=output_pin.width())

            self.add_contact(layers=self.m1m2_layers, offset=vector(output_pin.lx() + contact.m1m2.second_layer_height,
                                                                    h_rail_offset.y),
                             rotate=90)
            self.add_contact(layers=self.m1m2_layers, offset=vector(
                v_rail_offset.x + self.m2_width, h_rail_offset.y ),
                             rotate=90)

        (self.oe_rail, self.cs_rail) = vrails

    def create_output_rails(self):
        bottom = self.clk_bar_rail.by()
        tops = [self.tri_en_buffer.get_pin("out").cy(), self.w_en_buffer.get_pin("out").cy(), self.s_en.get_pin("Z").uy()]
        rail_pitch = self.m2_width + self.m2_space
        x_offsets = [self.oe_rail.offset.x-rail_pitch, self.we_rail.offset.x, self.cs_rail.offset.x]
        rails = [None]*3

        for i in range(len(tops)):
            rails[i] = self.add_rect("metal2", height=tops[i]-bottom, width=self.m2_width,
                                     offset=vector(x_offsets[i], bottom))
        (self.en_rail, self.w_en_rail, self.s_en_rail) = rails


    def route_pin_to_vertical_rail(self, pin, rail, via_x_pos, pos="center", rail_cont="vertical", rail_via_y=None):
        if isinstance(rail, float):
            rail_cx = rail + 0.5*self.m2_width
            rail_rx = rail + self.m2_width
        else:
            rail_cx = rail.offset.x + 0.5 * rail.width
            rail_rx = rail.offset.x + rail.width

        if rail_via_y is None:
            if rail_cont == "vertical":
                rail_via_y = pin.cy()
            else:
                rail_via_y = pin.by()

        if rail_cont == "vertical":
            self.add_contact_center(layers=self.m1m2_layers, offset=vector(rail_cx, rail_via_y))
        else:
            self.add_contact(layers=self.m1m2_layers,
                             offset=vector(rail_rx, rail_via_y), rotate=90)
        self.add_rect("metal1", height=self.m1_width, offset=vector(via_x_pos, pin.by()),
                      width=rail_cx-via_x_pos)
        self.add_contact(layers=self.m1m2_layers, offset=vector(via_x_pos, pin.by()), rotate=90)
        self.add_rect("metal2", height=self.m2_width, offset=pin.ll(), width=via_x_pos-pin.lx())
        if pos == "center":
            via_y = pin.cy() - 0.5*contact.m1m2.second_layer_height
        elif pos == "top":
            via_y = pin.by()
        else:
            via_y = pin.uy() - contact.m1m2.second_layer_height
        self.add_contact(layers=self.m1m2_layers, offset=vector(pin.lx(), via_y))


    def route_tri_en(self):

        b_pin = self.pre_tri_en_bar.get_pin("B")
        a_pin = self.pre_tri_en_bar.get_pin("A")

        # connect inputs
        self.add_rect("metal1", offset=a_pin.ll(), width=self.clk_bar_rail.rx() - a_pin.lx())
        self.add_contact_center(contact.contact.m1m2_layers,
                                offset=vector(self.clk_bar_rail.lx() + 0.5*contact.m1m2.second_layer_width, a_pin.cy()))

        self.add_rect("metal2", offset=b_pin.ll(), width=self.oe_rail.rx()-b_pin.lx())
        self.add_contact_center(contact.contact.m1m2_layers, b_pin.center())

        # pre_tri_en_bar to pre_tri_en

        z_pin = self.pre_tri_en_bar.get_pin("Z")
        a_pin = self.pre_tri_en.get_pin("A")
        self.add_rect("metal1", offset=a_pin.center()-vector(0, 0.5*self.m1_width), width=z_pin.lx()-a_pin.cx())

        self.route_output_to_buffer(self.pre_tri_en.get_pin("Z"), self.tri_en_buffer)
        self.route_buffer_output(self.tri_en_buffer, self.en_rail)



    def route_w_en(self):
        via_x_pos = self.w_en_bar.rx()
        self.route_pin_to_vertical_rail(self.w_en_bar.get_pin("C"), self.we_rail, via_x_pos, "center")
        self.route_pin_to_vertical_rail(self.w_en_bar.get_pin("B"), self.cs_rail, via_x_pos, "center")
        self.route_pin_to_vertical_rail(self.w_en_bar.get_pin("A"), self.clk_bar_rail, via_x_pos, "center")

        # w_en_bar to pre_w_en
        pre_w_en_a_pin = self.pre_w_en.get_pin("A")
        wen_bar_z_pin = self.w_en_bar.get_pin("Z")

        self.add_rect("metal1", offset=pre_w_en_a_pin.lr(), height=self.m1_width, width=wen_bar_z_pin.lx()-pre_w_en_a_pin.rx())

        self.route_output_to_buffer(self.pre_w_en.get_pin("Z"), self.w_en_buffer)
        self.route_buffer_output(self.w_en_buffer, self.w_en_rail)

    def route_blk(self):
        # connect rblk_bar nand inputs
        via_x_pos = self.rblk_bar.rx()
        self.route_pin_to_vertical_rail(self.rblk_bar.get_pin("C"), self.cs_rail, via_x_pos, "center")
        self.route_pin_to_vertical_rail(self.rblk_bar.get_pin("B"), self.oe_rail, via_x_pos, "center")
        self.route_pin_to_vertical_rail(self.rblk_bar.get_pin("A"), self.clk_bar_rail, via_x_pos, "center")

        # route rblk_bar to rblk
        rblk_bar_z_pin = self.rblk_bar.get_pin("Z")
        rblk_a_pin = self.rblk.get_pin("A")
        self.add_path("metal1", [rblk_a_pin.center(), vector(rblk_bar_z_pin.cx(), rblk_a_pin.cy())])


        # rblk to replica bitline en pin
        mid_x = self.rblk.lx() - self.m2_space
        sen_gnd = self.s_en.get_pin("gnd")
        mid_y = sen_gnd.cy()
        rblk_z_pin = self.rblk.get_pin("Z")
        en_pin = self.rbl.get_pin("en")

        self.add_path("metal2", [vector(rblk_z_pin.rx(), rblk_z_pin.by()),
                                 vector(mid_x, rblk_z_pin.by()),
                                 vector(mid_x, mid_y),
                                 vector(en_pin.cx(), mid_y),
                                 vector(en_pin.cx(), en_pin.by())])

        # rbl out to buffer input
        s_en_a_pin = self.s_en.get_pin("A")
        rbl_out_pin = self.rbl.get_pin("out")

        self.add_path("metal2", [vector(rbl_out_pin.cx(), s_en_a_pin.cy()),
                                 vector(rbl_out_pin.cx(), rbl_out_pin.by())])

        self.add_path("metal1", [vector(s_en_a_pin.center()),
                                 vector(rbl_out_pin.cx(), s_en_a_pin.cy())])

        self.add_contact(layers=self.m1m2_layers, offset=vector(rbl_out_pin.rx(),s_en_a_pin.by()),
                         rotate=90)


        # route s_en output to rail
        s_en_z_pin = self.s_en.get_pin("Z")
        via_x = self.s_en.rx()
        self.add_rect("metal2", offset=vector(s_en_z_pin.lx(), s_en_z_pin.uy()-0.5*self.m2_width),
                      width=via_x-s_en_z_pin.lx())
        self.add_contact_center(contact.contact.m1m2_layers, offset=vector(via_x+0.5*contact.m1m2.second_layer_height,
                                                                           s_en_z_pin.uy()),
                                rotate=90)
        if isinstance(self.s_en_rail, float):
            s_en_rail = self.s_en_rail
        else:
            s_en_rail = self.s_en_rail.lx()
        self.add_rect("metal1", offset=vector(via_x, s_en_z_pin.uy()-0.5*self.m2_width),
                      width=s_en_rail-via_x)
        self.add_contact_center(contact.contact.m1m2_layers,
                                offset=vector(s_en_rail+0.5*contact.m1m2.second_layer_width, s_en_z_pin.uy()))



    def pin_to_vdd(self, pin, vdd):
        self.add_rect("metal1", height=pin.height(), width=pin.lx()-vdd.rx(), offset=vector(vdd.rx(), pin.by()))

    def route_vdd(self):
        # extend left vdd to top
        self.vdd_rect = self.add_rect("metal1", offset=self.left_vdd.ul(),
                                      width=self.rail_height, height=self.height-self.left_vdd.uy())
        self.connect_rbl_right_vdd()

        self.pin_to_vdd(self.s_en.get_pin("vdd"), self.vdd_rect)
        self.pin_to_vdd(self.rblk.get_pin("vdd"), self.vdd_rect)
        self.pin_to_vdd(self.w_en_buffer.get_pin("vdd"), self.vdd_rect)
        self.pin_to_vdd(self.pre_w_en.get_pin("vdd"), self.vdd_rect)
        self.pin_to_vdd(self.tri_en_buffer.get_pin("vdd"), self.vdd_rect)

        for pin in self.msf_inst.get_pins("vdd"):
            if pin.layer == "metal1":
                self.pin_to_vdd(pin, self.vdd_rect)

        self.pin_to_vdd(self.clk_bar.get_pin("vdd"), self.vdd_rect)
        self.pin_to_vdd(self.clk_inv1.get_pin("vdd"), self.vdd_rect)

        self.add_rect("metal1", height=self.vdd_rect.by(), width=self.rail_height, offset=vector(0, 0))

    def connect_rbl_right_vdd(self):
        s_en_vdd = self.s_en.get_pin("vdd")
        x_offset = self.rbl.get_pin("gnd").rx() + self.wide_m1_space
        self.add_contact(contact.m1m2.layer_stack,
                         offset=vector(x_offset, s_en_vdd.cy() - 0.5*contact.m1m2.second_layer_width),
                         size=[1, 3], rotate=90)
        self.add_rect("metal1", offset=s_en_vdd.lr(), height=s_en_vdd.height(), width=x_offset - s_en_vdd.rx())

        y_offset = self.right_vdd.uy() - self.rail_height
        self.add_rect("metal2", offset=vector(x_offset, y_offset),
                      height=s_en_vdd.cy() + 0.5*contact.m1m2.second_layer_width - y_offset, width=self.rail_height)
        self.add_rect("metal2", offset=vector(x_offset, y_offset), height=self.rail_height,
                      width=self.right_vdd.cx() + 0.5*contact.m1m2.second_layer_width - x_offset)
        self.add_contact(contact.m1m2.layer_stack,
                         offset=vector(self.right_vdd.cx() + 0.5*contact.m1m2.second_layer_width, self.right_vdd.uy()),
                         rotate=180, size=[1, 3])


    def pin_to_gnd(self, pin, gnd):
        self.add_rect("metal1", height=pin.height(), width=gnd.lx()-pin.rx(), offset=vector(pin.rx(), pin.by()))

    def route_gnd(self):
        # create rail to the right
        rbl_buffer_gnd = self.s_en.get_pin("gnd")
        self.gnd_rail = self.add_rect("metal1", width=self.rail_height, height=self.height,
                      offset=vector(self.width-self.rail_height, 0))
        rbl_gnd = self.rbl.get_pin("gnd")
        self.add_rect("metal1", width=self.rail_height, height=rbl_buffer_gnd.by()-rbl_gnd.uy(),
                      offset=rbl_gnd.ul())

        self.pin_to_gnd(rbl_buffer_gnd, self.gnd_rail)
        self.pin_to_gnd(self.rblk.get_pin("gnd"), self.gnd_rail)
        self.pin_to_gnd(self.w_en_buffer.get_pin("gnd"), self.gnd_rail)
        self.pin_to_gnd(self.pre_w_en.get_pin("gnd"), self.gnd_rail)
        self.pin_to_gnd(self.tri_en_buffer.get_pin("gnd"), self.gnd_rail)
        self.pin_to_gnd(self.pre_tri_en.get_pin("gnd"), self.gnd_rail)
        self.pin_to_gnd(self.clk_buf.get_pin("gnd"), self.gnd_rail)


        for pin in self.msf_inst.get_pins("gnd"):
            if pin.layer == "metal1":
                self.pin_to_gnd(pin, self.gnd_rail)

        self.pin_to_vdd(self.clk_bar.get_pin("gnd"), self.gnd_rail)
        self.pin_to_vdd(self.clk_inv1.get_pin("gnd"), self.gnd_rail)

    def add_pin_to_top(self, text, layer, rail):
        height = rail.height
        pin_offset = vector(rail.lx(), rail.uy()-height)
        self.add_layout_pin(text=text, layer=layer,
                            width=rail.width,
                            height=height,
                            offset=pin_offset)

    def route_output_to_buffer(self, output_pin, buffer_instance):
        in_pin = buffer_instance.get_pin("in")

        self.add_path("metal2", [vector(output_pin.cx(), output_pin.by()),
                                 vector(output_pin.cx(), buffer_instance.uy()),
                                 vector(buffer_instance.lx(), buffer_instance.uy()),
                                 vector(buffer_instance.lx(), in_pin.cy()),
                                 in_pin.lc()])
        self.add_contact(contact.m1m2.layer_stack, offset=vector(in_pin.lx() + contact.m1m2.second_layer_height,
                                                                 in_pin.cy() - 0.5*contact.m1m2.second_layer_width),
                         rotate=90)

    def route_buffer_output(self, buffer_instance, rail):

        out_pin = buffer_instance.get_pin("out")
        self.add_rect("metal1", offset=out_pin.rc(), width=rail.lx() - out_pin.rx())
        self.add_contact(contact.m1m2.layer_stack, offset=vector(rail.lx(), out_pin.cy()
                                                                 - 0.5*contact.m1m2.second_layer_height))



    def add_layout_pins(self):
        """ Add the input/output layout pins. """
        self.add_pin_to_top("vdd", "metal1", self.vdd_rect)
        self.add_pin_to_top("gnd", "metal1", self.gnd_rail)

        # control inputs
        self.add_pin_to_top("web", "metal2", self.web_rail)
        self.add_pin_to_top("csb", "metal2", self.csb_rail)
        self.add_pin_to_top("oeb", "metal2", self.oeb_rail)

        # clock input
        clk_inv_a_pin = self.clk_inv1.get_pin("A")
        self.add_contact_center(layers=self.m1m2_layers,
                                offset=vector(clk_inv_a_pin.lx()+0.5*contact.m1m2.second_layer_height,
                                              clk_inv_a_pin.cy()),
                                rotate=90)
        clk_in_x_offset = self.vdd_rect.rx() - 0.5*self.m1_width
        pin_y = clk_inv_a_pin.cy()-0.5*self.m2_width
        self.add_rect("metal2", height=self.m2_width, width=clk_inv_a_pin.cx()-clk_in_x_offset,
                      offset=vector(clk_in_x_offset, pin_y))
        clk_rect = self.add_rect(layer="metal2",
                            width=self.m2_width,
                            height=self.height-pin_y,
                            offset=vector(clk_in_x_offset, pin_y))
        self.add_pin_to_top("clk", "metal2", clk_rect)

        rails = [self.clk_buf_rail, self.w_en_rail, self.s_en_rail, self.en_rail]
        pin_names = ["clk_buf", "w_en", "s_en", "tri_en"]
        for i in range(4):
            rail = rails[i]
            pin_name = pin_names[i]
            self.add_layout_pin(pin_name, "metal2", offset=rail.ll(), height=rail.height)




    def add_pin_to_bottom(self, text, layer, rail, prev_rail_y):
        rail_extension = 2*self.m2_space + rail.width
        rail_bottom = prev_rail_y - rail_extension
        self.add_rect(layer, width=rail.width, height=rail.by()-rail_bottom,
                      offset=vector(rail.lx(), rail_bottom))

        pin_offset = vector(rail.lx(), rail_bottom)
        self.add_layout_pin(text=text, layer=layer,
                            width=self.width-rail.lx(),
                            height=rail.width,
                            offset=pin_offset)
        return rail_bottom


    def add_lvs_correspondence_points(self):
        """ This adds some points for easier debugging if LVS goes wrong. 
        These should probably be turned off by default though, since extraction
        will show these as ports in the extracted netlist.
        """
        pin=self.clk_inv1.get_pin("Z")
        self.add_label_pin(text="clk1_bar",
                           layer="metal1",
                           offset=pin.ll(),
                           height=pin.height(),
                           width=pin.width())

        pin=self.clk_inv2.get_pin("Z")
        self.add_label_pin(text="clk2",
                           layer="metal1",
                           offset=pin.ll(),
                           height=pin.height(),
                           width=pin.width())

        pin=self.rbl.get_pin("out")
        self.add_label_pin(text="pre_s_en",
                           layer="metal1",
                           offset=pin.ll(),
                           height=pin.height(),
                           width=pin.width())


