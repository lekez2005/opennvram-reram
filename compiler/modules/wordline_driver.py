from base import contact
from base import design
from base.vector import vector
from pgates.pinv import pinv
from pgates.pnand2 import pnand2


class wordline_driver(design.design):
    """
    Creates a Wordline Driver
    Generates the wordline-driver to drive the bitcell
    """
    BUFFER_THRESHOLD = 16  # no of cols above which buffer is added

    def __init__(self, rows, no_cols=16):
        design.design.__init__(self, "wordline_driver")

        self.rows = rows
        self.no_cols = no_cols
        self.module_insts = []
        self.output_insts = []
        self.add_pins()
        self.design_layout()
        self.DRC_LVS()

    def add_pins(self):
        # inputs to wordline_driver.
        for i in range(self.rows):
            self.add_pin("in[{0}]".format(i))
        # Outputs from wordline_driver.
        for i in range(self.rows):
            self.add_pin("wl[{0}]".format(i))
        self.add_pin("en")
        self.add_pin("vdd")
        self.add_pin("gnd")

    def design_layout(self):
        self.add_layout()
        self.offsets_of_gates()
        self.create_layout()

    def add_layout(self):
        self.inv = pinv(size=4, align_bitcell=True)
        self.add_mod(self.inv)

        self.buf_inv = pinv(size=8, align_bitcell=True)
        self.add_mod(self.buf_inv)

        self.buf = pinv(size=16, align_bitcell=True)
        self.add_mod(self.buf)

        self.inv1 = pinv(size=1, align_bitcell=True)
        self.add_mod(self.inv1)
        
        self.nand2 = pnand2(size=1, align_bitcell=True)
        self.add_mod(self.nand2)




    def offsets_of_gates(self):

        self.en_pin_x = self.m1_space + self.m1_width

        in_pin_width = self.en_pin_x + self.m2_width + self.parallel_line_space

        self.m1m2_via_x = in_pin_width + contact.m1m2.first_layer_width

        left_s_d = self.inv1.get_left_source_drain()

        self.x_offset0 = self.m1m2_via_x + self.m2_space + 0.5*contact.m1m2.first_layer_width - left_s_d
        self.x_offset1 = self.x_offset0 + self.inv1.width
        self.x_offset2 = self.x_offset1 + self.nand2.width


        if self.no_cols > self.BUFFER_THRESHOLD:
            self.x_offset3 = self.x_offset2 + self.inv.width
            self.x_offset4 = self.x_offset3 + self.buf_inv.width
            self.width = self.x_offset4 + self.buf.width
        else:
            self.width = self.x_offset2 + self.inv.width
        self.height = self.inv.height * self.rows

    def create_layout(self):
        # Wordline enable connection
        en_pin=self.add_layout_pin(text="en",
                                   layer="metal2",
                                   offset=[self.en_pin_x,0],
                                   width=self.m2_width,
                                   height=self.height)
        
        self.add_layout_pin(text="vdd",
                            layer="metal1",
                            offset=[0, -0.5*self.rail_height],
                            width=self.x_offset0,
                            height=self.rail_height)
        
        for row in range(self.rows):
            name_inv1 = "wl_driver_inv_en{}".format(row)
            name_nand = "wl_driver_nand{}".format(row)
            name_inv2 = "wl_driver_inv{}".format(row)

            if (row % 2) == 0:
                y_offset = self.inv.height*(row + 1)
                inst_mirror = "MX"

            else:
                y_offset = self.inv.height*row
                inst_mirror = "R0"

            name_inv1_offset = vector(self.x_offset0, y_offset)
            nand2_offset=vector(self.x_offset1, y_offset)
            inv2_offset=vector(self.x_offset2, y_offset)

            # Extend vdd and gnd of wordline_driver
            yoffset = (row + 1) * self.inv.height - 0.5 * self.rail_height
            if (row % 2) == 0:
                pin_name = "gnd"
            else:
                pin_name = "vdd"
                
            self.add_layout_pin(text=pin_name,
                                layer="metal1",
                                offset=[0, yoffset],
                                width=self.x_offset0,
                                height=self.rail_height)
            
            
            # add inv1 based on the info above
            inv1_inst=self.add_inst(name=name_inv1,
                                    mod=self.inv1,
                                    offset=name_inv1_offset,
                                    mirror=inst_mirror )
            self.module_insts.append(inv1_inst)
            self.connect_inst(["en",
                               "en_bar[{0}]".format(row),
                               "vdd", "gnd"])
            # add nand 2
            nand_inst=self.add_inst(name=name_nand,
                                    mod=self.nand2,
                                    offset=nand2_offset,
                                    mirror=inst_mirror)
            self.connect_inst(["en_bar[{0}]".format(row),
                               "in[{0}]".format(row),
                               "net[{0}]".format(row),
                               "vdd", "gnd"])
            self.module_insts.append(nand_inst)
            # add inv2
            inv2_inst=self.add_inst(name=name_inv2,
                                mod=self.inv,
                                    offset=inv2_offset,
                                    mirror=inst_mirror)
            self.module_insts.append(inv2_inst)


            # add buffers if necessary. # TODO tune buffer sizes
            if self.no_cols <= self.BUFFER_THRESHOLD:
                self.connect_inst(["net[{0}]".format(row),
                                   "wl[{0}]".format(row),
                                   "vdd", "gnd"])
                output_inst = inv2_inst
            else:
                self.connect_inst(["net[{0}]".format(row),
                                   "buf_inv[{0}]".format(row),
                                   "vdd", "gnd"])
                name = "wl_driver_buf_inv{}".format(row)
                offset = vector(self.x_offset3, y_offset)
                buf_inv_inst = self.add_inst(name=name,
                                          mod=self.buf_inv,
                                          offset=offset,
                                          mirror=inst_mirror)
                self.module_insts.append(buf_inv_inst)
                self.connect_inst(["buf_inv[{0}]".format(row),
                                   "buf_in[{0}]".format(row),
                                   "vdd", "gnd"])

                name = "wl_driver_buf{}".format(row)
                offset = vector(self.x_offset4, y_offset)
                buf_inst = self.add_inst(name=name,
                                             mod=self.buf,
                                             offset=offset,
                                             mirror=inst_mirror)
                self.module_insts.append(buf_inst)
                self.connect_inst(["buf_in[{0}]".format(row),
                                   "wl[{0}]".format(row),
                                   "vdd", "gnd"])
                output_inst = buf_inst

                # route buffers

                for z_pin, a_pin in [(inv2_inst.get_pin("Z"), buf_inv_inst.get_pin("A")),
                                     (buf_inv_inst.get_pin("Z"), buf_inst.get_pin("A"))]:

                    self.add_rect("metal1", offset=vector(z_pin.rx(), a_pin.cy()-0.5*self.m1_width),
                                  width=a_pin.lx()-z_pin.rx())


            self.output_insts.append(output_inst)

            # en connection
            a_pin = inv1_inst.get_pin("A")
            a_pos = a_pin.lc()
            clk_offset = vector(en_pin.bc().x,a_pos.y)
            self.add_segment_center(layer="metal1",
                                    start=clk_offset,
                                    end=a_pos)
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=clk_offset)

            # first inv to nand2 A
            self.add_path("metal1", [inv1_inst.get_pin("Z").center(), nand_inst.get_pin("A").center()])

            # Nand2 out to 2nd inv
            zr_pin = nand_inst.get_pin("Z")
            al_pin = inv2_inst.get_pin("A")
            offset = vector(zr_pin.rx(), al_pin.cy() - 0.5*self.m1_width)
            self.add_rect("metal1", offset=offset, width=al_pin.lx()-zr_pin.rx())

            # connect the decoder input pin to nand2 B
            b_pin = nand_inst.get_pin("B")

            inv_output_y = inv1_inst.get_pin("Z").cy()

            b_pos = vector(b_pin.lx(), inv_output_y)
            # needs to move down since B nand input is nearly aligned with A inv input
            en_in_space = 0.5*(contact.m1m2.first_layer_height + contact.poly.second_layer_height) + self.line_end_space

            if row % 2 == 0:
                up_or_down = en_in_space
            else:
                up_or_down = -en_in_space

            input_offset = vector(0,clk_offset.y + up_or_down)
            mid_via_offset = vector(self.m1m2_via_x+0.5*contact.m1m2.second_layer_width, input_offset.y)
            # must under the clk line in M1
            self.add_layout_pin_center_segment(text="in[{0}]".format(row),
                                               layer="metal1",
                                               start=input_offset,
                                               end=mid_via_offset)
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=mid_via_offset)

            # now connect to the nand2 B
            path = [mid_via_offset]  # via
            path.append(vector(b_pin.cx(), inv_output_y))  # at nand2
            path.append(b_pin.center())
            self.add_path("metal2", path)
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=b_pin.center(),
                                rotate=0)


            # output each WL on the right
            wl_offset = output_inst.get_pin("Z").rc()
            self.add_layout_pin_center_segment(text="wl[{0}]".format(row),
                                               layer="metal1",
                                               start=wl_offset,
                                               end=wl_offset-vector(self.m1_width,0))


    def analytical_delay(self, slew, load=0):
        # decode -> net
        decode_t_net = self.nand2.analytical_delay(slew, self.inv.input_load())

        # net -> wl
        net_t_wl = self.inv.analytical_delay(decode_t_net.slew, load)

        return decode_t_net + net_t_wl

        
    def input_load(self):
        return self.nand2.input_load()
