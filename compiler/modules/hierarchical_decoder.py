import math

import debug
from base import contact
from base import design
from base import utils
from base.contact import m1m2, m2m3, cross_m2m3
from base.design import ACTIVE, PIMP, METAL2, METAL3, METAL1, NWELL
from base.vector import vector
from globals import OPTS
from modules.hierarchical_predecode2x4 import hierarchical_predecode2x4 as pre2x4
from modules.hierarchical_predecode3x8 import hierarchical_predecode3x8 as pre3x8
from pgates.pinv import pinv
from pgates.pnand2 import pnand2
from pgates.pnand3 import pnand3
from tech import drc, info, add_tech_layers


class hierarchical_decoder(design.design):
    """
    Dynamically generated hierarchical decoder.
    """

    def __init__(self, rows):
        design.design.__init__(self, "hierarchical_decoder_{0}rows".format(rows))

        c = __import__(OPTS.bitcell)
        self.mod_bitcell = getattr(c, OPTS.bitcell)()
        self.bitcell_height = self.mod_bitcell.height

        self.use_flops = OPTS.decoder_flops
        if self.use_flops:
            self.predec_in = "flop_in[{}]"
        else:
            self.predec_in = "in[{}]"

        self.pre2x4_inst = []
        self.pre3x8_inst = []

        self.rows = rows
        self.num_inputs = int(math.log(self.rows, 2))
        (self.no_of_pre2x4, self.no_of_pre3x8) = self.determine_predecodes(self.num_inputs)
        
        self.create_layout()
        self.DRC_LVS()

    def create_layout(self):
        self.create_modules()
        self.setup_layout_constants()
        self.add_pins()
        self.create_pre_decoder()
        self.create_vertical_rail()
        self.create_row_decoder()
        self.route_vertical_rail()
        self.route_vdd_gnd()
        add_tech_layers(self)

    def create_modules(self):
        kwargs = {"align_bitcell": True, "contact_nwell": False, "contact_pwell": False,
                  "same_line_inputs": True}
        self.inv = pinv(**kwargs)
        self.add_mod(self.inv)
        self.nand2 = pnand2(**kwargs)
        self.add_mod(self.nand2)
        self.nand3 = pnand3(**kwargs)
        self.add_mod(self.nand3)

        self.create_predecoders()

    def create_predecoders(self):
        # CREATION OF PRE-DECODER
        self.pre2_4 = pre2x4(route_top_rail=False, use_flops=self.use_flops)
        self.add_mod(self.pre2_4)
        self.pre3_8 = pre3x8(route_top_rail=False, use_flops=self.use_flops)
        self.add_mod(self.pre3_8)
        self.all_predecoders = ([self.pre2_4] * self.no_of_pre2x4 +
                                [self.pre3_8] * self.no_of_pre3x8)

        if OPTS.separate_vdd_wordline:
            if self.no_of_pre3x8 == 0:
                top_predecoder = pre2x4(route_top_rail=True, use_flops=self.use_flops)
            else:
                top_predecoder = pre3x8(route_top_rail=True, use_flops=self.use_flops)
            self.add_mod(top_predecoder)
            self.all_predecoders[-1] = top_predecoder
        self.top_predecoder = self.all_predecoders[-1]

    def determine_predecodes(self,num_inputs):
        """Determines the number of 2:4 pre-decoder and 3:8 pre-decoder
        needed based on the number of inputs"""
        if (num_inputs == 2):
            return (1,0)
        elif (num_inputs == 3):
            return(0,1)
        elif (num_inputs == 4):
            return(2,0)
        elif (num_inputs == 5):
            return(1,1)
        elif (num_inputs == 6):
            return(3,0)
        elif (num_inputs == 7):
            return(2,1)
        elif (num_inputs == 8):
            return(1,2)
        elif (num_inputs == 9):
            return(0,3)
        else:
            debug.error("Invalid number of inputs for hierarchical decoder",-1)

    def setup_layout_constants(self):
        # Vertical metal rail gap definition
        self.metal2_pitch = (max(self.bus_width, contact.m1m2.second_layer_width) +
                             max(self.get_parallel_space(METAL2), self.bus_space))

        self.predec_groups = []  # This array is a 2D array.

        # Distributing vertical rails to different groups. One group belongs to one pre-decoder.
        # For example, for two 2:4 pre-decoder and one 3:8 pre-decoder, we will
        # have total 16 output lines out of these 3 pre-decoders and they will
        # be distributed as [ [0,1,2,3] ,[4,5,6,7], [8,9,10,11,12,13,14,15] ]
        # in self.predec_groups
        index = 0
        for i in range(self.no_of_pre2x4):
            lines = []
            for j in range(4):
                lines.append(index)
                index = index + 1
            self.predec_groups.append(lines)

        for i in range(self.no_of_pre3x8):
            lines = []
            for j in range(8):
                lines.append(index)
                index = index + 1
            self.predec_groups.append(lines)

        bitcell_array_cls = self.import_mod_class_from_str(OPTS.bitcell_array)
        offsets = bitcell_array_cls.calculate_y_offsets(num_rows=self.rows)
        self.bitcell_offsets, self.tap_offsets, self.dummy_offsets = offsets

        self.calculate_dimensions()

        
    def add_pins(self):
        """ Add the module pins """
        
        for i in range(self.num_inputs):
            self.add_pin("A[{0}]".format(i))

        for j in range(self.rows):
            self.add_pin("decode[{0}]".format(j))
        if self.use_flops:
            self.add_pin("clk")
        self.add_pin("vdd")
        self.add_pin("gnd")

    def calculate_predecoder_height(self):
        self.predecoder_height = sum(map(lambda x: x.height, self.all_predecoders))

        if OPTS.separate_vdd_wordline:
            top_predecoder = self.all_predecoders[-1]
            pre_nwell = top_predecoder.get_max_shape(NWELL, "uy", recursive=True)
            pre_extension = pre_nwell.uy() - top_predecoder.height

            inv_nwell = self.inv.get_max_shape(NWELL, "by", recursive=True)
            inv_y_extension = inv_nwell.uy() - self.inv.height

            well_space = self.get_space(NWELL, prefix="different")

            # TODO take x space into account to reduce y_space
            self.predecoder_height += (inv_y_extension + well_space + pre_extension)

    def calculate_dimensions(self):
        """ Calculate the overal dimensions of the hierarchical decoder """

        # If we have 4 or fewer rows, the predecoder is the decoder itself
        if self.num_inputs>=4:
            self.total_number_of_predecoder_outputs = 4*self.no_of_pre2x4 + 8*self.no_of_pre3x8
        else:
            self.total_number_of_predecoder_outputs = 0            
            debug.error("Not enough rows for a hierarchical decoder. Non-hierarchical not supported yet.",-1)

        # Calculates height and width of pre-decoder,
        if(self.no_of_pre3x8 > 0):
            self.predecoder_width = self.pre3_8.width 
        else:
            self.predecoder_width = self.pre2_4.width

        self.calculate_predecoder_height()

        # Calculates height and width of row-decoder 
        if (self.num_inputs == 4 or self.num_inputs == 5):
            nand_width = self.nand2.width
        else:
            nand_width = self.nand3.width 
        self.routing_width = self.metal2_pitch*self.total_number_of_predecoder_outputs
        self.row_decoder_width = nand_width + self.routing_width + self.inv.width

        self.row_decoder_height = self.bitcell_offsets[-1] + self.bitcell_height

        # Calculates height and width of hierarchical decoder 
        self.height = self.predecoder_height + self.row_decoder_height
        self.width = self.predecoder_width + self.routing_width

    def create_pre_decoder(self):
        """ Creates pre-decoder and places labels input address [A] """
        
        for i in range(self.no_of_pre2x4):
            self.add_pre2x4(i)
            
        for i in range(self.no_of_pre3x8):
            self.add_pre3x8(i)
        if self.use_flops:
            if len(self.pre2x4_inst) > 0:
                if len(self.pre3x8_inst) > 0:
                    top_pin = self.pre3x8_inst[0].get_pin("clk")
                    bot_pin = self.pre2x4_inst[-1].get_pin("clk")
                    self.add_rect("metal2", offset=vector(bot_pin.ul() - vector(0, self.m2_width)),
                                  width=top_pin.rx() - bot_pin.lx())
                    self.add_layout_pin("clk", METAL2, offset=vector(top_pin.lx(), bot_pin.uy()),
                                        height=top_pin.by() - bot_pin.uy())
                if len(self.pre3x8_inst) > 0:
                    clk_pin = self.pre3x8_inst[0].get_pin("clk")
                    self.add_layout_pin(text="clk", layer="metal2", offset=clk_pin.ll(),
                                        height=self.pre3x8_inst[-1].get_pin("clk").uy() - clk_pin.by())

                if len(self.pre2x4_inst) > 1:  # connect the clk rails
                    clk_pin = self.pre2x4_inst[0].get_pin("clk")
                    self.add_rect("metal2", offset=clk_pin.ul(),
                                  height=self.pre2x4_inst[-1].get_pin("clk").uy() - clk_pin.uy())
            else:
                predecoder = self.pre3x8_inst[0]
                if len(self.pre3x8_inst) > 0:
                    clk_pin = predecoder.get_pin("clk")
                    self.add_rect("metal2", offset=clk_pin.ul(),
                                  height=self.pre3x8_inst[-1].get_pin("clk").by() - clk_pin.uy())
            for inst in self.pre2x4_inst + self.pre3x8_inst:
                self.copy_layout_pin(inst, "clk", "clk")

    def add_pre2x4(self,num):
        """ Add a 2x4 predecoder """
        
        if (self.num_inputs == 2):
            base = vector(self.routing_width,0)
            mirror = "RO"
            index_off1 = index_off2 = 0
        else:
            base= vector(self.routing_width+self.pre2_4.width, num * self.pre2_4.height)
            mirror = "MY"
            index_off1 = num * 2
            index_off2 = num * 4

        pins = []
        for input_index in range(2):
            pins.append("A[{0}]".format(input_index + index_off1))
        for output_index in range(4):
            pins.append("out[{0}]".format(output_index + index_off2))
        if self.use_flops:
            pins.append("clk")
        pins.extend(["vdd", "gnd"])

        self.pre2x4_inst.append(self.add_inst(name="pre_{0}".format(num),
                                                 mod=self.get_pre2x4_mod(num),
                                                 offset=base,
                                                 mirror=mirror))
        self.connect_inst(pins)

        self.add_pre2x4_pins(num)

    def get_pre2x4_mod(self, num):
        return self.all_predecoders[num]

    def add_pre2x4_pins(self,num):
        """ Add the input pins to the 2x4 predecoder """

        for i in range(2):
            pin = self.pre2x4_inst[num].get_pin(self.predec_in.format(i))
            pin_offset = pin.ll()
            
            pin = self.pre2_4.get_pin(self.predec_in.format(i))
            self.add_layout_pin(text="A[{0}]".format(i + 2*num ),
                                layer="metal2", 
                                offset=pin_offset,
                                width=pin.width(),
                                height=pin.height())

        
    def add_pre3x8(self,num):
        """ Add 3x8 numbered predecoder """
        if (self.num_inputs == 3):
            offset = vector(self.routing_width,0)
            mirror ="R0"
        else:
            height = self.no_of_pre2x4*self.pre2_4.height + num*self.pre3_8.height
            offset = vector(self.routing_width+self.pre3_8.width, height)
            mirror="MY"

        # If we had 2x4 predecodes, those are used as the lower
        # decode output bits
        in_index_offset = num * 3 + self.no_of_pre2x4 * 2
        out_index_offset = num * 8 + self.no_of_pre2x4 * 4

        pins = []
        for input_index in range(3):
            pins.append("A[{0}]".format(input_index + in_index_offset))
        for output_index in range(8):
            pins.append("out[{0}]".format(output_index + out_index_offset))
        if self.use_flops:
            pins.append("clk")
        pins.extend(["vdd", "gnd"])

        pre_num = len(self.pre2x4_inst) + num
        self.pre3x8_inst.append(self.add_inst(name="pre_{0}".format(pre_num),
                                              mod=self.get_pre3x8_mod(pre_num),
                                              offset=offset,
                                              mirror=mirror))
        self.connect_inst(pins)

        # The 3x8 predecoders will be stacked, so use yoffset
        self.add_pre3x8_pins(num,offset)

    def get_pre3x8_mod(self, num):
        return self.all_predecoders[num]

    def add_pre3x8_pins(self,num,offset):
        """ Add the input pins to the 3x8 predecoder at the given offset """

        for i in range(3):            
            pin = self.pre3x8_inst[num].get_pin(self.predec_in.format(i))
            pin_offset = pin.ll()
            self.add_layout_pin(text="A[{0}]".format(i + 3*num + 2*self.no_of_pre2x4),
                                layer="metal2", 
                                offset=pin_offset,
                                width=pin.width(),
                                height=pin.height())



    def create_row_decoder(self):
        """ Create the row-decoder by placing NAND2/NAND3 and Inverters
        and add the primary decoder output pins. """
        if (self.num_inputs >= 4):
            self.add_decoder_nand_array()
            self.add_decoder_inv_array()
            self.route_decoder()
            self.add_body_contacts()
            self.fill_predecoder_to_row_decoder_implants()

    def add_decoder_nand_array(self):
        """ Add a column of NAND gates for final decode """
        
        # Row Decoder NAND GATE array for address inputs <5.
        if len(self.predec_groups) == 2:
            self.add_nand_array(nand_mod=self.nand2)
            # FIXME: Can we convert this to the connect_inst with checks?
            for j in range(len(self.predec_groups[1])):
                for i in range(len(self.predec_groups[0])):
                    pins =["out[{0}]".format(i),
                           "out[{0}]".format(j + len(self.predec_groups[0])),
                           "Z[{0}]".format(len(self.predec_groups[0])*j + i),
                           "vdd", "gnd"]
                    self.connect_inst(args=pins, check=False)

        # Row Decoder NAND GATE array for address inputs >5.
        else:
            self.add_nand_array(nand_mod=self.nand3,
                                correct=drc["minwidth_metal1"])
            # This will not check that the inst connections match.
            for k in range(len(self.predec_groups[2])):
                for j in range(len(self.predec_groups[1])):
                    for i in range(len(self.predec_groups[0])):
                        row = len(self.predec_groups[1])*len(self.predec_groups[0]) * k \
                                  + len(self.predec_groups[0])*j + i
                        pins = ["out[{0}]".format(i),
                                "out[{0}]".format(j + len(self.predec_groups[0])),
                                "out[{0}]".format(k + len(self.predec_groups[0]) + len(self.predec_groups[1])),
                                "Z[{0}]".format(row),
                                "vdd", "gnd"]
                        self.connect_inst(args=pins, check=False)

    def add_nand_array(self, nand_mod, correct=0):
        """ Add a column of NAND gates for the decoder above the predecoders."""
        
        self.nand_inst = []
        for row in range(self.rows):
            name = "DEC_NAND[{0}]".format(row)
            y_off, mirror = self.get_row_y_offset(row)
            self.nand_inst.append(self.add_inst(name=name,
                                                mod=nand_mod,
                                                offset=[self.routing_width, y_off],
                                                mirror=mirror))

    def get_row_y_offset(self, row):
        y_off = self.predecoder_height + self.bitcell_offsets[row]
        if row % 2 == 1:
            mirror = "R0"
        else:
            y_off += self.inv.height
            mirror = "MX"

        return y_off, mirror

    def add_decoder_inv_array(self):
        """Add a column of INV gates for the decoder above the predecoders
        and to the right of the NAND decoders."""
        
        if (self.num_inputs == 4 or self.num_inputs == 5):
            x_off = self.routing_width + self.nand2.width
        else:
            x_off = self.routing_width + self.nand3.width

        self.inv_inst = []
        for row in range(self.rows):
            name = "DEC_INV_[{0}]".format(row)
            y_off, mirror = self.get_row_y_offset(row)
            offset = vector(x_off, y_off)
            
            self.inv_inst.append(self.add_inst(name=name,
                                               mod=self.inv,
                                               offset=offset,
                                               mirror=mirror))

            # This will not check that the inst connections match.
            self.connect_inst(args=["Z[{0}]".format(row),
                                    "decode[{0}]".format(row),
                                    "vdd", "gnd"],
                              check=False)

    def fill_predecoder_to_row_decoder_implants(self):
        """Fill implant and well between predecoder and row decoder
        Both predecoder top and row decoder bottom have no nwell contact
            leading to potential min-implant space issues
        """
        if OPTS.separate_vdd_wordline:
            return
        top_predecoder_inst = (self.pre2x4_inst + self.pre3x8_inst)[-1]
        predec_module = top_predecoder_inst.mod

        predecoder_inv_inst = predec_module.inv_inst[0].mod.module_insts[-1]
        predecoder_inv = predecoder_inv_inst.mod
        row_decoder_nand = self.nand_inst[0].mod

        pre_inv_implant = max(predecoder_inv.get_layer_shapes(PIMP), key=lambda x: x.by())
        row_nand_implant = min(row_decoder_nand.get_layer_shapes(PIMP), key=lambda x: x.uy())
        implant_x = min(top_predecoder_inst.rx() -
                        (predecoder_inv_inst.lx() + predec_module.inv_inst[0].rx()) +
                        (predecoder_inv.width - pre_inv_implant.rx()),
                        self.nand_inst[0].lx() + row_nand_implant.lx())
        # add extra implant width for cases when this implant overlaps with wordline driver implant
        # extend to the right of the predecoder`

        predecoder_right = top_predecoder_inst.rx() - predec_module.nand_inst[0].lx()
        row_decoder_right = self.inv_inst[0].rx()

        implant_right = max(predecoder_right, row_decoder_right)
        implant_height = 2 * self.implant_width + self.rail_height
        y_offset = top_predecoder_inst.uy() - 0.5 * implant_height

        self.add_rect(PIMP, offset=vector(implant_x, y_offset),
                      height=implant_height, width=implant_right - implant_x)

    def route_decoder(self):
        """ Route the nand to inverter in the decoder and add the pins. """

        for row in range(self.rows):

            # route nand output to output inv input
            z_pin = self.nand_inst[row].get_pin("Z")
            a_pin = self.inv_inst[row].get_pin("A")
            self.join_nand_inv_pins(z_pin, a_pin)

            z_pin = self.inv_inst[row].get_pin("Z")
            self.add_layout_pin(text="decode[{0}]".format(row),
                                layer="metal1",
                                offset=z_pin.ll(),
                                width=z_pin.width(),
                                height=z_pin.height())

    def join_nand_inv_pins(self, z_pin, a_pin):
        self.add_rect(METAL1, offset=vector(z_pin.rx(), a_pin.cy() - 0.5 * self.m1_width),
                      width=a_pin.lx() - z_pin.rx())

    def add_body_contacts(self):
        """Add contacts to the left of the nand gates"""

        active_height = contact.well.first_layer_width
        min_active_area = drc.get("minarea_cont_active_thin", self.get_min_area(ACTIVE))
        active_width = utils.ceil(min_active_area / active_height) or self.active_width
        implant_enclosure = self.implant_enclose_active

        min_implant_area = self.get_min_area("implant") or 0.0

        implant_height = max(utils.ceil(active_height + 2 * implant_enclosure),
                             self.implant_width)

        implant_width = max(utils.ceil(active_width + 2 * implant_enclosure),
                            utils.ceil(min_implant_area / implant_height),
                            self.implant_width)

        implant_x = self.nand_inst[0].lx() - 0.5 * implant_width
        num_contacts = self.calculate_num_contacts(active_width)

        min_nwell_width = self.get_min_layer_width("nwell")
        nwell_width = active_width + 2 * self.well_enclose_active
        nwell_width += 2 * min_nwell_width  # to prevent min_nwell_width
        nwell_height = max(min_nwell_width,
                           active_height + 2 * self.well_enclose_active)
        self.contact_nwell_height = nwell_height
        self.contact_mid_x = implant_x

        if info["has_pwell"]:
            min_pwell_width = self.get_min_layer_width("pwell")
            pwell_width = active_width + 2 * self.well_enclose_active + 2 * min_pwell_width
            pwell_height = max(min_pwell_width,
                               active_height + 2 * self.well_enclose_active)
            self.contact_pwell_height = pwell_height

        for row in range(self.rows):
            gnd_pin = self.nand_inst[row].get_pin("gnd")
            self.add_contact_center(contact.well.layer_stack,
                                    offset=vector(implant_x, gnd_pin.cy()), size=[num_contacts, 1])
            self.add_rect_center("pimplant", offset=vector(implant_x, gnd_pin.cy()),
                                 width=implant_width, height=implant_height)
            if info["has_pwell"]:
                self.add_rect_center("pwell", offset=(implant_x, gnd_pin.cy()),
                                     width=pwell_width, height=pwell_height)

            vdd_pin = self.nand_inst[row].get_pin("vdd")
            self.add_contact_center(contact.well.layer_stack,
                                    offset=vector(implant_x, vdd_pin.cy()), size=[num_contacts, 1])
            self.add_rect_center("nimplant", offset=vector(implant_x, vdd_pin.cy()),
                                 width=implant_width, height=implant_height)
            self.add_rect_center("nwell", offset=(implant_x, vdd_pin.cy()),
                                 width=nwell_width, height=nwell_height)

    def create_vertical_rail(self):
        """ Creates vertical metal 2 rails to connect predecoder and decoder stages."""

        # This is not needed for inputs <4 since they have no pre/decode stages.
        if (self.num_inputs >= 4):
            # Array for saving the X offsets of the vertical rails. These rail
            # offsets are accessed with indices.
            self.rail_x_offsets = []
            for i in range(self.total_number_of_predecoder_outputs):
                # The offsets go into the negative x direction
                # assuming the predecodes are placed at (self.routing_width,0)
                x_offset = self.metal2_pitch * i
                self.rail_x_offsets.append(x_offset+0.5*self.bus_width)
                self.add_rect(layer="metal2",
                              offset=vector(x_offset,0),
                              width=self.bus_width,
                              height=self.height)

    def route_vertical_rail(self):
        if (self.num_inputs >= 4):
            self.connect_rails_to_predecodes()
            self.connect_rails_to_decoder()

    def connect_rails_to_predecodes(self):
        """ Iterates through all of the predecodes and connects to the rails including the offsets """

        for pre_num in range(self.no_of_pre2x4):
            for i in range(4):
                index = pre_num * 4 + i
                out_name = "out[{}]".format(i)
                pin = self.pre2x4_inst[pre_num].get_pin(out_name)
                self.connect_rail(index, pin) 

        for pre_num in range(self.no_of_pre3x8):
            for i in range(8):
                index = pre_num * 8 + i + self.no_of_pre2x4 * 4
                out_name = "out[{}]".format(i)
                pin = self.pre3x8_inst[pre_num].get_pin(out_name)
                self.connect_rail(index, pin) 

    def connect_rails_to_decoder(self):
        """ Use the self.predec_groups to determine the connections to the decoder NAND gates.
        Inputs of NAND2/NAND3 gates come from different groups.
        For example for these groups [ [0,1,2,3] ,[4,5,6,7],
        [8,9,10,11,12,13,14,15] ] the first NAND3 inputs are connected to
        [0,4,8] and second NAND3 is connected to [1,4,8]  ........... and the
        128th NAND3 is connected to [3,7,15]
        """
        row_index = 0
        if len(self.predec_groups) == 2:
            for index_B in self.predec_groups[1]:
                for index_A in self.predec_groups[0]:
                    self.connect_rail_m2(index_A, self.nand_inst[row_index].get_pin("A"))
                    self.connect_rail_m2(index_B, self.nand_inst[row_index].get_pin("B"))
                    row_index = row_index + 1

        else:
            for index_C in self.predec_groups[2]:
                for index_B in self.predec_groups[1]:
                    for index_A in self.predec_groups[0]:
                        self.connect_rail_m2(index_A, self.nand_inst[row_index].get_pin("A"))
                        self.connect_rail_m2(index_B, self.nand_inst[row_index].get_pin("B"))
                        self.connect_rail_m2(index_C, self.nand_inst[row_index].get_pin("C"))
                        row_index = row_index + 1

    def connect_rail_m2(self, rail_index, pin):

        if pin.name == "A":  # connect directly with M1
            rail_offset = vector(self.rail_x_offsets[rail_index], pin.cy())
            self.add_path("metal1", [rail_offset, pin.center()])
            self.add_via_center(layers=contact.m1m2.layer_stack, offset=rail_offset, rotate=0)
        else:
            rail_x = self.rail_x_offsets[rail_index]
            y_space = 0.5 * m2m3.w_2 + self.get_parallel_space(METAL3)

            if pin.name == "B":
                rail_y = pin.cy() + y_space
            else:
                rail_y = pin.cy() - y_space - self.m3_width

            via_offset = vector(rail_x, rail_y + 0.5 * self.m3_width)
            self.add_cross_contact_center(cross_m2m3, offset=via_offset)

            m1_fill_width = self.nand_inst[0].mod.gate_fill_width
            m1_fill_height = self.nand_inst[0].mod.gate_fill_height
            m2_fill_height = max(m1_fill_height, m1m2.h_2, m2m3.h_1)
            min_area = self.get_min_area(METAL2) or 0.0
            m2_fill_width = utils.ceil(min_area / m2_fill_height)

            if pin.name == "B":
                if pin.cx() > rail_x:
                    fill_x = pin.cx() + 0.5 * m1_fill_width - 0.5 * m2_fill_width
                    m2m3_via_x = fill_x
                    m3_x = m2m3_via_x - 0.5 * m2m3.h_2
                else:
                    fill_x = pin.cx() - 0.5 * m1_fill_width + 0.5 * m2_fill_width
                    m2m3_via_x = fill_x
                    m3_x = m2m3_via_x + 0.5 * m2m3.h_2 - self.m3_width
                via_offset = vector(m2m3_via_x, pin.cy())
                self.add_cross_contact_center(cross_m2m3, offset=via_offset)
            else:
                closest_nand = min(self.nand_inst,
                                   key=lambda x: abs(pin.cy() - x.cy()) +
                                                 (abs(pin.cx() - x.cx())))
                b_pin = closest_nand.get_pin("B")
                via_space = (0.5 * m2m3.h_2 + self.get_space(METAL3,
                                                             prefix="dense_line_end") +
                             0.5 * m2m3.w_2)

                if rail_x < pin.cx():
                    fill_x = pin.lx() + 0.5 * m2_fill_width
                    m2m3_via_x = max(b_pin.cx() + via_space, fill_x)
                else:
                    fill_x = pin.rx() - 0.5 * m2_fill_width
                    m2m3_via_x = min(b_pin.cx() - via_space, fill_x)
                m3_x = m2m3_via_x - 0.5 * m2m3.w_2
                via_offset = vector(m2m3_via_x, pin.cy())
                self.add_contact_center(m2m3.layer_stack, via_offset)

            if m3_x > rail_x:
                rail_width = m3_x + self.m3_width - rail_x
            else:
                rail_width = m3_x - rail_x
            self.add_rect(METAL3, offset=vector(rail_x, rail_y), width=rail_width)

            self.add_rect(METAL3, offset=vector(m3_x, pin.cy()),
                          width=m2m3.w_2,
                          height=rail_y - pin.cy())

            fill_offset = vector(fill_x, pin.cy())
            self.add_via_center(layers=contact.m1m2.layer_stack, offset=fill_offset)
            self.add_rect_center(METAL2, offset=fill_offset,
                                 width=m2_fill_width, height=m2_fill_height)

    def copy_power_pin(self, pin):
        if hasattr(OPTS, 'separate_vdd_wordline'):
            width = pin.rx()
        else:
            width = self.width
        self.add_layout_pin(text=pin.name,
                            layer=pin.layer,
                            offset=vector(0, pin.by()),
                            width=width,
                            height=pin.height())

    def route_vdd_gnd(self):
        """ Add a pin for each row of vdd/gnd which are must-connects next level up. """
        for i in list(range(0, len(self.nand_inst), 2)) + [-1]:
            inst = self.nand_inst[i]
            self.copy_power_pin(inst.get_pin("vdd"))
            self.copy_power_pin(inst.get_pin("gnd"))

        extend_power = (self.pre2x4_inst + self.pre3x8_inst)[0].mod.vertical_flops
        for predecoder in self.pre2x4_inst + self.pre3x8_inst:
            if extend_power:
                self.copy_layout_pin(predecoder, "vdd")
                self.copy_layout_pin(predecoder, "gnd")
            else:
                for pin in predecoder.get_pins("vdd") + predecoder.get_pins("gnd"):
                    self.copy_power_pin(pin)

        

    def connect_rail(self, rail_index, pin):
        """ Connect the routing rail to the given metal1 pin  """
        rail_pos = vector(self.rail_x_offsets[rail_index],pin.lc().y)
        self.add_path("metal1", [rail_pos, pin.lc()])
        self.add_via_center(layers=("metal1", "via1", "metal2"),
                            offset=rail_pos,
                            rotate=0)

        
    def analytical_delay(self, slew, load = 0.0):
        # A -> out
        if self.determine_predecodes(self.num_inputs)[1]==0:
            pre = self.pre2_4
            nand = self.nand2
        else:
            pre = self.pre3_8
            nand = self.nand3
        a_t_out_delay = pre.analytical_delay(slew=slew,load = nand.input_load())

        # out -> z
        out_t_z_delay = nand.analytical_delay(slew= a_t_out_delay.slew,
                                  load = self.inv.input_load())
        result = a_t_out_delay + out_t_z_delay

        # Z -> decode_out
        z_t_decodeout_delay = self.inv.analytical_delay(slew = out_t_z_delay.slew , load = load)
        result = result + z_t_decodeout_delay
        return result

        
    def input_load(self):
        if self.determine_predecodes(self.num_inputs)[1]==0:
            pre = self.pre2_4
        else:
            pre = self.pre3_8
        return pre.input_load()


class SeparateWordlineMixin(hierarchical_decoder):

    def copy_power_pin(self, pin):
        if pin.uy() <= self.row_decoder_min_y:
            x_offset = 0
        else:
            x_offset = self.power_rail_x
        right_x = self.inv_inst[1].lx()
        self.add_layout_pin(pin.name, pin.layer, offset=vector(x_offset, pin.by()),
                            width=right_x - x_offset, height=pin.height())
