
import datetime
import os
from math import log, sqrt

import debug
import verify
from base import contact
from base import design
from base.vector import vector
from characterizer import lib
from globals import OPTS, print_time
from modules import sram_power_grid_old
from modules.bank import bank
from modules.hierarchical_predecode2x4 import hierarchical_predecode2x4 as pre2x4
from tech import drc


class sram(design.design, sram_power_grid_old.Mixin):
    """
    Dynamically generated SRAM by connecting banks to control logic. The
    number of banks should be 1 , 2 or 4
    """

    def __init__(self, word_size, num_words, num_banks, name, words_per_row=None):

        c = __import__(OPTS.bitcell)
        self.mod_bitcell = getattr(c, OPTS.bitcell)
        self.bitcell = self.mod_bitcell()

        self.word_size = word_size
        self.num_words = num_words
        self.num_banks = num_banks
        self.words_per_row = words_per_row

        debug.info(2, "create sram of size {0} with {1} num of words".format(self.word_size, 
                                                                             self.num_words))
        start_time = datetime.datetime.now()

        design.design.__init__(self, name)

        # For different layer width vias
        self.m2m3_offset_fix = vector(0, 0.5*(self.m3_width-self.m2_width))
        
        # M1/M2 routing pitch is based on contacted pitch of the biggest layer
        self.m1_pitch = self.m1_width + self.get_parallel_space("metal1")
        self.m2_pitch = self.m2_width + self.get_parallel_space("metal2")
        self.m3_pitch = self.m3_width + self.get_parallel_space("metal3")
        self.m4_pitch = self.m4_width + self.get_parallel_space("metal4")


        self.control_size = 4
        self.bank_to_bus_distance = 5*self.m3_width
        
        self.compute_sizes()

        self.create_layout()
        self.add_pins()
        
        # Can remove the following, but it helps for debug!
        self.add_lvs_correspondence_points()
        
        self.offset_all_coordinates()
        sizes = self.find_highest_coords()
        self.width = sizes[0]
        self.height = sizes[1]
        
        self.DRC_LVS(final_verification=True)

        if not OPTS.is_unit_test:
            print_time("SRAM creation", datetime.datetime.now(), start_time)


    def compute_sizes(self):
        """  Computes the organization of the memory using bitcell size by trying to make it square."""

        debug.check(self.num_banks in [1,2,4], "Valid number of banks are 1 , 2 and 4.")

        self.num_words_per_bank = int(self.num_words/self.num_banks)
        self.num_bits_per_bank = self.word_size*self.num_words_per_bank

        # Compute the area of the bitcells and estimate a square bank (excluding auxiliary circuitry)
        self.bank_area = self.bitcell.width*self.bitcell.height*self.num_bits_per_bank
        self.bank_side_length = sqrt(self.bank_area)

        # Estimate the words per row given the height of the bitcell and the square side length
        if self.words_per_row is not None:
            self.tentative_num_cols = self.words_per_row * self.word_size
        else:
            self.tentative_num_cols = int(self.bank_side_length/self.bitcell.width)
            self.words_per_row = self.estimate_words_per_row(self.tentative_num_cols, self.word_size)

        # Estimate the number of rows given the tentative words per row
        self.tentative_num_rows = self.num_bits_per_bank / (self.words_per_row*self.word_size)
        self.words_per_row = self.amend_words_per_row(self.tentative_num_rows, self.words_per_row)
        
        # Fix the number of columns and rows
        self.num_cols = self.words_per_row*self.word_size
        self.num_rows = int(self.num_words_per_bank/self.words_per_row)

        # Compute the address and bank sizes
        self.row_addr_size = int(log(self.num_rows, 2))
        self.col_addr_size = int(log(self.words_per_row, 2))
        self.bank_addr_size = self.col_addr_size + self.row_addr_size
        self.addr_size = self.bank_addr_size + int(log(self.num_banks, 2))
        
        debug.info(1, "Words per row: {}".format(self.words_per_row))

    def estimate_words_per_row(self,tentative_num_cols, word_size):
        """This provides a heuristic rounded estimate for the number of words
        per row."""

        if tentative_num_cols < 1.5*word_size:
            return 1
        elif tentative_num_cols > 3*word_size:
            return 4
        else:
            return 2

    def amend_words_per_row(self,tentative_num_rows, words_per_row):
        """This picks the number of words per row more accurately by limiting
        it to a minimum and maximum.
        """
        # Recompute the words per row given a hard max
        if tentative_num_rows > 512:
            debug.check(tentative_num_rows*words_per_row <= 2048, "Number of words exceeds 2048")
            return int(words_per_row*tentative_num_rows/512)
        # Recompute the words per row given a hard min
        if tentative_num_rows < 16:
            debug.check(tentative_num_rows*words_per_row >= 16, "Minimum number of rows is 16, but given {0}".format(tentative_num_rows))
            return int(words_per_row*tentative_num_rows/16)
            
        return words_per_row

    def add_pins(self):
        """ Add pins for entire SRAM. """

        for i in range(self.word_size):
            self.add_pin("DATA[{0}]".format(i),"INOUT")
        for i in range(self.addr_size):
            self.add_pin("ADDR[{0}]".format(i),"INPUT")

        # These are used to create the physical pins too
        self.control_logic_inputs=["CSb", "WEb",  "OEb", "clk"]
        self.control_logic_outputs=["s_en", "w_en", "tri_en", "clk_buf"]
        
        self.add_pin_list(self.control_logic_inputs,"INPUT")
        self.add_pin("vdd","POWER")
        self.add_pin("gnd","GROUND")

    def create_layout(self):
        """ Layout creation """
        
        self.create_modules()

        if self.num_banks == 1:
            self.add_single_bank_modules()
            self.add_single_bank_pins()
            self.route_single_bank()
        elif self.num_banks == 2:
            self.add_two_bank_modules()
            self.route_two_banks()
        elif self.num_banks == 4:
            self.add_four_bank_modules()
            self.route_four_banks()
        else:
            debug.error("Invalid number of banks.",-1)


    def add_four_bank_modules(self):
        """ Adds the modules and the buses to the top level """

        self.bank_offsets()

        self.add_four_banks()

        self.compute_four_bank_logic_locs()

        self.add_horizontal_busses()
        self.add_four_bank_logic()

        self.width = self.bank_inst[1].rx()
        self.height = self.bank_inst[3].uy()


    def add_two_bank_modules(self):
        """ Adds the modules and the buses to the top level """

        self.bank_offsets()
        self.add_two_banks()
        

        self.compute_two_bank_logic_locs()
        self.add_two_bank_logic()
        self.add_horizontal_busses()

        self.width = self.bank_inst[1].ur().x
        hoz_max = max(self.horz_control_bus_positions.values(), key=lambda v: v.y)
        self.height = hoz_max.y + 0.5*self.m1_width
        
        
    def route_shared_banks(self):
        """ Route the shared signals for two and four bank configurations. """
        # connect the data output to the data bus
        self.route_data_bus(self.data_bus_names, self.data_bus_positions, contact.m2m3.layer_stack)
        # create the input control pins
        for n in self.control_logic_inputs:
            self.copy_layout_pin(self.control_logic_inst, n.lower(), n)

    def route_data_bus(self, bus_names, bus_positions, via_layers):
        # connect the data output to the data bus
        for n in bus_names:
            for i in range(self.num_banks):
                pin = self.bank_inst[i].get_pin(n)
                if i < 2:
                    pin_pos = pin.uc()
                else:
                    pin_pos = pin.bc()
                rail_pos = vector(pin_pos.x, bus_positions[n].y)
                self.add_path("metal3", [pin_pos, rail_pos])
                self.add_via_center(via_layers, rail_pos, rotate=90)

        
            
    def route_four_banks(self):
        """ Route all of the signals for the four bank SRAM. """

        self.route_shared_banks()

        # connect address pins
        for i in range(self.bank_addr_size):
            addr_name = "ADDR[{}]".format(i)

            (bl_pin, br_pin, tl_pin, tr_pin) = list(map(lambda x:self.bank_inst[x].get_pin(addr_name),
                                                        range(self.num_banks)))
            for left, right in [(bl_pin, br_pin), (tl_pin, tr_pin)]:
                self.add_rect(left.layer, offset=left.lr(), width=right.lx() - left.rx())
            rail_x = self.addr_bus_x + i*self.m2_pitch
            self.add_layout_pin(addr_name, "metal3", offset=vector(rail_x, bl_pin.by()), height=tl_pin.uy() - bl_pin.uy())

            if bl_pin.layer == "metal4":
                layer_stack = contact.m3m4.layer_stack
                via_x = rail_x + contact.m3m4.second_layer_height
            else:
                layer_stack = contact.m2m3.layer_stack
                via_x = rail_x + contact.m2m3.second_layer_height

            for y_offset in [bl_pin.by(), tl_pin.by()]:
                self.add_contact(layer_stack, vector(via_x, y_offset),
                                        rotate=90)

        self.route_four_bank_logic()

        # route msb address bits
        # route 2:4 decoder
        self.route_double_msb_address()

        self.route_four_banks_power()





        

    def compute_bus_sizes(self):
        """ Compute the independent bus widths shared between two and four bank SRAMs """
        
        # address size + control signals + one-hot bank select signals
        self.num_vertical_line = self.bank_addr_size + self.control_size + self.num_banks
        # data bus size
        self.num_horizontal_line = self.word_size

        if self.num_banks == 2:
            self.vertical_bus_wire_width = self.m3_pitch * self.num_vertical_line
            self.vertical_bus_width = max(self.vertical_bus_wire_width, self.control_logic.width)
        elif self.num_banks == 4:
            # bank sel rails should be to the right of address rails or flip flop dout pin
            dout_1_pin = self.msb_address.get_pin("dout[1]")
            self.bank_sel_x = max(self.m2_pitch * self.bank_addr_size, dout_1_pin.rx() + self.m3_space)
            self.vertical_bus_wire_width = self.bank_sel_x + (self.num_banks + self.control_size) * self.m3_pitch

            self.vertical_bus_width = max(self.vertical_bus_wire_width,
                                          self.control_logic.width, self.msb_decoder.width)

        # vertical bus height depends on 2 or 4 banks
        
        self.data_bus_height = self.m3_pitch*self.num_horizontal_line
        self.data_bus_width = 2*(self.bank.width + self.bank_to_bus_distance) + self.vertical_bus_width

        self.supply_bus_width = self.data_bus_width

        # Sanity check to ensure we can fit the control logic above a single bank (0.9 is a hack really)
        debug.check(self.bank.width + self.vertical_bus_width > 0.9*self.control_logic.width, "Bank is too small compared to control logic.")
        
        

    def compute_four_bank_logic_locs(self):

        self.compute_two_bank_logic_locs()

        predecoder_space = 2*self.wide_m1_space
        predecoder_x = self.bank_inst[0].rx() + self.bank_to_bus_distance

        self.msb_decoder_position = vector(predecoder_x, self.bottom_control_pin.by() - predecoder_space
                                           - self.msb_decoder.height)

        module_spacing = drc["pwell_to_nwell"]

        self.control_logic_position = vector(predecoder_x, self.msb_decoder_position.y - module_spacing
                                             - self.control_logic.height)

        # address bus is to the left of bank_sel
        self.bank_sel_x = self.bank_sel_x + self.msb_address_position.x
        self.addr_bus_x = self.bank_sel_x - self.m2_pitch * self.bank_addr_size
        self.control_bus_x = self.bank_sel_x + self.m2_pitch * self.num_banks

    def get_precharge_vdd_to_top(self):
        """Distance from precharge vdd to top of bank"""
        precharge_vdd = self.bank.precharge_array_inst.get_pin("vdd")
        return (self.bank.height - precharge_vdd.uy(), precharge_vdd.height())



    def bank_offsets(self):
        """ Compute the overall offsets for a two bank SRAM """

        self.compute_bus_sizes()

        (vdd_to_top, vdd_height) = self.get_precharge_vdd_to_top()
        self.bank_y_offset = self.power_rail_pitch + self.power_rail_width - vdd_to_top - vdd_height

        self.data_bus_offset = vector(0, self.bank_y_offset + self.bank.height + self.bank_to_bus_distance)
        self.supply_bus_offset = vector(0, self.data_bus_offset.y + self.data_bus_height)



    def compute_two_bank_logic_locs(self):


        # Control is placed below the bank control signals
        # align control_logic vdd with first bank's vdd
        bank_inst = self.bank_inst[0]
        control_pins = list(map(bank_inst.get_pin, self.control_logic_outputs + ["bank_sel"]))
        self.bottom_control_pin = min(control_pins, key=lambda x: x.by())
        self.top_control_pin = max(control_pins, key=lambda x: x.uy())

        self.msb_address_position = vector(self.bank.width + self.bank_to_bus_distance,
                                           self.top_control_pin.uy() + self.wide_m1_space)

        control_gap = self.wide_m1_space
        control_logic_x = bank_inst.rx() + self.bank_to_bus_distance
        self.control_logic_position = vector(control_logic_x, self.bottom_control_pin.by() - control_gap - self.control_logic.height)


    def add_horizontal_busses(self):
        """ Add the horizontal and vertical busses """

        # Horizontal data bus
        self.data_bus_names = ["DATA[{}]".format(i) for i in range(self.word_size)]
        self.data_bus_positions = self.create_bus(layer="metal2",
                                                  pitch=self.m2_pitch,
                                                  offset=self.data_bus_offset,
                                                  names=self.data_bus_names,
                                                  length=self.data_bus_width,
                                                  vertical=False,
                                                  make_pins=True)

        # Horizontal control logic bus
        # vdd/gnd in bus go along whole SRAM
        # FIXME: Fatten these wires?
        self.horz_control_bus_positions = self.create_bus(layer="metal1",
                                                          pitch=self.m1_pitch,
                                                          offset=self.supply_bus_offset,
                                                          names=["vdd"],
                                                          length=self.supply_bus_width,
                                                          vertical=False)
        # The gnd rail must not be the entire width since we protrude the right-most vdd rail up for
        # the decoder in 4-bank SRAMs
        left_bank_vdd = min(filter(lambda x: x.layer=="metal1", self.bank.get_pins("vdd")),
                            key=lambda x: x.lx())
        space_to_vdd = left_bank_vdd.lx()
        # leave space to left and right for vdd connection
        cutout = space_to_vdd + left_bank_vdd.width() + 2*self.m1_space
        self.horz_control_bus_positions.update(self.create_bus(layer="metal2",
                                                               pitch=self.m1_pitch,
                                                               offset=self.supply_bus_offset + vector(0, self.wide_m1_space),
                                                               names=["gnd"],
                                                               length=self.supply_bus_width,
                                                               vertical=False))
        
    def add_two_bank_logic(self):
        """ Add the control and MSB logic """

        self.add_control_logic(position=self.control_logic_position)

        self.msb_address_inst = self.add_inst(name="msb_address",
                                              mod=self.msb_address,
                                              offset=self.msb_address_position+vector(self.msb_address.width,
                                                                                      self.msb_address.height),
                                              mirror="XY",
                                              rotate=0)
        self.msb_bank_sel_addr = "ADDR[{}]".format(self.addr_size-1)
        self.connect_inst([self.msb_bank_sel_addr,"bank_sel[1]","bank_sel[0]","clk_buf", "vdd", "gnd"])

    def get_msb_address_locations(self):
        return self.msb_address_position + vector(0, self.msb_address.height), "MX"

    def add_four_bank_logic(self):
        """ Add the control and MSB decode/bank select logic for four banks """


        self.add_control_logic(position=self.control_logic_position)

        offset, mirror = self.get_msb_address_locations()

        self.msb_address_inst = self.add_inst(name="msb_address",
                                              mod=self.msb_address,
                                              offset=offset,
                                              mirror=mirror)

        self.msb_bank_sel_addr = ["ADDR[{}]".format(i) for i in range(self.addr_size-2,self.addr_size,1)]        
        temp = list(self.msb_bank_sel_addr)
        temp.extend(["msb{0}[{1}]".format(j,i) for i in range(2) for j in ["","_bar"]])
        temp.extend(["clk_buf", "vdd", "gnd"])
        self.connect_inst(temp)
        
        self.msb_decoder_inst = self.add_inst(name="msb_decoder",
                                              mod=self.msb_decoder,
                                              offset=self.msb_decoder_position + vector(0, self.msb_decoder.height),
                                              mirror="MX"
                                              )
        temp = ["msb[{}]".format(i) for i in range(2)]
        temp.extend(["bank_sel[{}]".format(i) for i in range(4)])
        temp.extend(["vdd", "gnd"])
        self.connect_inst(temp)
        
        
    def route_two_banks(self):
        """ Route all of the signals for the two bank SRAM. """

        self.route_shared_banks()

        # connect address pins
        for i in range(self.bank_addr_size):
            addr_name = "ADDR[{}]".format(i)
            left_pin = self.bank_inst[0].get_pin(addr_name)
            right_pin = self.bank_inst[1].get_pin(addr_name)
            self.add_layout_pin(addr_name, layer=left_pin.layer, offset=left_pin.lr(),
                                width=right_pin.lx() - left_pin.lx())

        self.route_two_bank_logic()

        self.route_single_msb_address()

        self.route_two_banks_power()
        
        
    def route_double_msb_address(self):
        """ Route two MSB address bits and the bank decoder for 4-bank SRAM """

        # connect the MSB flops to the address input bus
        rail_separation = contact.m3m4.first_layer_height + self.m3_space
        rail_y = 0
        for i in [0,1]:
            msb_pin = self.msb_address_inst.get_pin("dout[{}]".format(i))
            self.add_contact(contact.m2m3.layer_stack, offset=msb_pin.ll())
            in_pin = self.msb_decoder_inst.get_pin("in[{}]".format(i))
            if i == 0: # left then right
                self.add_rect("metal3", offset=vector(in_pin.lx(), msb_pin.by()), width=msb_pin.rx() - in_pin.lx())
                self.add_rect("metal3", offset=in_pin.ul(), height=msb_pin.by() - in_pin.uy())
                self.add_contact(contact.m2m3.layer_stack,
                                 offset=vector(in_pin.lx(), in_pin.uy() - contact.m2m3.second_layer_height))
            else: # down then left
                self.add_rect("metal3", offset=vector(msb_pin.lx(), in_pin.uy()), height=msb_pin.by() - in_pin.uy())
                self.add_rect("metal3", offset=in_pin.ul(), width=msb_pin.rx() - in_pin.lx())
                self.add_contact(contact.m2m3.layer_stack,
                                 offset=in_pin.ul() + vector(contact.m2m3.second_layer_height, 0), rotate=90)
                # add a fill to prevent line end drc spacing violation
                fill_height = 2 * self.m3_width
                self.add_rect("metal3", offset=vector(in_pin.lx(), in_pin.uy() - fill_height), height=fill_height)

            self.copy_layout_pin(self.msb_address_inst, "din[{}]".format(i), "ADDR[{}]".format(self.bank_addr_size + i))

        # Connect clk
        clk_pin = self.msb_address_inst.get_pin("clk")
        clk_pos = clk_pin.lr()
        rail_pos = self.vert_control_bus_positions["clk_buf"]
        self.add_contact(contact.m1m2.layer_stack, offset=clk_pos + vector(contact.m1m2.second_layer_height, 0),
                         rotate=90)
        self.add_rect("metal2", offset=clk_pos, width=rail_pos - clk_pos.x)
        self.add_contact(contact.m2m3.layer_stack,
                         offset=vector(rail_pos, clk_pin.uy() - contact.m2m3.second_layer_height))

        # Connect bank decoder outputs to the bank select vertical bus wires

        rightmost_control = max(self.vert_control_bus_positions.values())
        via_x = rightmost_control + self.m3_pitch + self.m3_space
        fill_height = self.metal1_minwidth_fill

        for i in range(self.num_banks):
            msb_pin = self.msb_decoder_inst.get_pin("out[{}]".format(i))


            # route m2 to rail through bottom
            self.add_rect("metal2", offset=msb_pin.ll(), width=via_x - msb_pin.lx())
            via_offset = vector(via_x, msb_pin.by())
            self.add_contact(contact.m2m3.layer_stack, offset=via_offset)
            self.add_contact(contact.m3m4.layer_stack, offset=via_offset)
            # add fill
            self.add_rect("metal3", offset=via_offset, height=fill_height)

            # m4 to railx
            rail_x = self.bank_sel_x + i * self.m3_pitch
            self.add_rect("metal4", offset=vector(rail_x, via_offset.y), width=via_offset.x - rail_x)
            self.add_contact(contact.m3m4.layer_stack, offset=vector(rail_x, via_offset.y))

            # m3 to bank sel
            bank_sel_pin = self.bank_inst[i].get_pin("bank_sel")

            if i < 2: # bottom
                m2m3_via_offset = vector(rail_x, bank_sel_pin.uy() - contact.m2m3.second_layer_height)
            else:
                m2m3_via_offset = vector(rail_x, bank_sel_pin.by())
            if i % 2 == 0: # left
                path_start = bank_sel_pin.rc()
            else:
                path_start = bank_sel_pin.lc()
                if i == 1: # prevent via spacing issue
                    m2m3_via_offset.y -= self.wide_m1_space
                    self.add_rect("metal2", offset=m2m3_via_offset, height=bank_sel_pin.by() - m2m3_via_offset.y)
                elif i == 3:
                    m2m3_via_offset.y += self.wide_m1_space
                    self.add_rect("metal2",
                                  offset=vector(m2m3_via_offset.x, bank_sel_pin.by()), height=m2m3_via_offset.y - bank_sel_pin.by())
            self.add_rect("metal3", offset=vector(rail_x, via_offset.y), height=m2m3_via_offset.y - via_offset.y)

            self.add_contact(layers=contact.m2m3.layer_stack, offset=m2m3_via_offset)
            self.add_path("metal2", [path_start, vector(rail_x, bank_sel_pin.cy())])


    def route_four_bank_logic(self):
        self.vert_control_bus_positions = {}
        control_pin_names = ["tri_en", "s_en", "w_en", "clk_buf"]
        control_pins = list(map(self.control_logic_inst.get_pin, control_pin_names))
        control_pins = sorted(control_pins, key=lambda x: x.lx()) # sort from left to right

        if control_pins[0].lx() < self.control_bus_x:
            # rail should go down then left
            control_pins = sorted(control_pins, key=lambda x: x.uy(), reverse=True)
            wide_address = True
            x_offsets = list(map(lambda i: self.control_bus_x + i*self.m3_pitch, range(4)))
        else:
            x_offsets = list(map(lambda x: x.lx(), control_pins))
            wide_address = False

        bank_pins = sorted(map(self.bank_inst[0].get_pin, control_pin_names), key=lambda x: x.by())

        for i in range(len(control_pin_names)):
            control_pin = control_pins[i]
            pin_name = control_pin.name

            x_offset = x_offsets[i]
            self.vert_control_bus_positions[pin_name] = x_offset

            (bl_pin, br_pin, tl_pin, tr_pin) = list(map(lambda x:self.bank_inst[x].get_pin(pin_name),
                                                   range(self.num_banks)))

            # connect accross from left to right
            for left, right in [(bl_pin, br_pin), (tl_pin, tr_pin)]:
                self.add_rect(left.layer, offset=left.lr(), width=right.lx() - left.rx())


            self.add_contact(contact.m2m3.layer_stack,
                             offset=vector(x_offset, control_pin.uy() - contact.m2m3.second_layer_height))
            # pin should be on the left
            if wide_address:
                self.add_rect("metal3", offset=vector(control_pin.lx(), control_pin.uy() - self.m3_width),
                              width=x_offset - control_pin.lx())


            for pin in [bl_pin, tl_pin]:
                bank_pin_index = bank_pins.index(bl_pin)

                down_via_offset = vector(x_offset, pin.uy() - contact.m2m3.second_layer_height)
                up_via_offset = vector(x_offset, pin.by())

                # connect with via
                # This assumes there is vertical space between the second and third rails. otherwise, different via arrangement may be needed

                if pin == bl_pin:
                    if bank_pin_index == 2:
                        via_offset = down_via_offset
                    else:
                        via_offset = up_via_offset
                else: # the top needs to be reversed
                    if bank_pin_index == 2:
                        via_offset = up_via_offset
                    else:
                        via_offset = down_via_offset

                self.add_contact(contact.m2m3.layer_stack, offset=via_offset)

                # create m3 rail
                self.add_rect("metal3", offset=vector(x_offset, control_pin.uy()), height=tl_pin.uy() - control_pin.uy())



    def route_two_bank_logic(self):
        self.vert_control_bus_positions = {}
        control_pin_names = ["tri_en", "s_en", "w_en", "clk_buf"]
        via_directions = [1, 1, -1, -1]
        for i in range(len(control_pin_names)):
            pin_name = control_pin_names[i]
            # connect bank input from right to left
            left_pin = self.bank_inst[0].get_pin(pin_name)
            right_pin = self.bank_inst[1].get_pin(pin_name)
            self.add_rect(left_pin.layer, offset=left_pin.lr(), width=right_pin.lx() - left_pin.rx())

            # create rail from control logic
            control_pin = self.control_logic_inst.get_pin(pin_name)
            self.add_contact(contact.m2m3.layer_stack,
                             offset=control_pin.ul() - vector(0, contact.m2m3.second_layer_height))
            x_offset = control_pin.lx()
            self.vert_control_bus_positions[pin_name] = x_offset
            self.add_rect("metal3", offset=vector(x_offset, control_pin.uy()), height=left_pin.uy() - control_pin.uy())
            # connect with via
            if via_directions[i] == 1:
                via_offset = vector(control_pin.rx(), left_pin.by())
            else:
                via_offset = vector(control_pin.lx() + contact.m2m3.second_layer_height, left_pin.by())
            self.add_contact(contact.m2m3.layer_stack, offset=via_offset, rotate=90)


    def route_single_msb_address(self):
        """ Route one MSB address bit for 2-bank SRAM """

        # connect bank sel pins
        pin_names = ["dout_bar[0]", "dout[0]"]
        for i in range(2):
            pin_name = pin_names[i]
            pin = self.msb_address_inst.get_pin(pin_name)
            self.add_contact(layers=contact.m2m3.layer_stack, offset=pin.ll())
            bank_sel_pin = self.bank_inst[i].get_pin("bank_sel")
            self.add_rect("metal3", offset=vector(pin.lx(), bank_sel_pin.by()), height=pin.by() - bank_sel_pin.by())

            if i == 0:
                offset = bank_sel_pin.lr()
                width = pin.lx() - bank_sel_pin.rx()
                via_offset = vector(pin.rx(), bank_sel_pin.by())
            else:
                offset = vector(pin.lx(), bank_sel_pin.by())
                width = bank_sel_pin.lx() - offset.x
                via_offset = offset + vector(contact.m2m3.second_layer_height, 0)
            self.add_contact(layers=contact.m2m3.layer_stack, offset=via_offset, rotate=90)
            self.add_rect("metal2", offset=offset, width=width)

        # Connect clk
        clk_pin = self.msb_address_inst.get_pin("clk")
        clk_pos = clk_pin.lr()
        rail_pos = self.vert_control_bus_positions["clk_buf"]

        bank_clk_y = self.bank_inst[0].get_pin("clk_buf").by()
        # extend rail height to msb_address
        self.add_rect("metal3", offset=vector(rail_pos, bank_clk_y), height=clk_pos.y - bank_clk_y)

        self.add_contact(contact.m1m2.layer_stack, offset=clk_pos + vector(contact.m1m2.second_layer_height, 0),
                         rotate=90)
        self.add_rect("metal2", offset=clk_pos, width=rail_pos - clk_pos.x)
        self.add_contact(contact.m2m3.layer_stack,
                         offset=vector(rail_pos, clk_pin.uy() - contact.m2m3.second_layer_height))

        self.copy_layout_pin(self.msb_address_inst, "din[0]", "ADDR[{}]".format(self.addr_size-1))



    def connect_m2_m4_rails(self, m2_rail, m4_rail_x):
        if m4_rail_x < m2_rail.lx():
            self.add_rect("metal3", width=m2_rail.rx()-m4_rail_x+0.5*self.m3_width,
                          offset=vector(m4_rail_x-0.5*self.m3_width, m2_rail.by()))
            self.add_via(("metal2", "via2", "metal3"), offset=m2_rail.lr(), rotate=90)
        else:
            self.add_rect("metal3", width=m4_rail_x+0.5*self.m3_width-m2_rail.lx(),
                          offset=m2_rail.ll())
            self.add_via(("metal2", "via2", "metal3"), offset=m2_rail.ll()+vector(contact.m2m3.second_layer_height, 0),
                         rotate=90)

        self.add_via_center(("metal3", "via3", "metal4"), vector(m4_rail_x, m2_rail.by()+0.5*self.m3_width))


        
    def create_multi_bank_modules(self):
        """ Create the multibank address flops and bank decoder """
        self.msb_address = self.mod_ms_flop_array(name="msb_address",
                                                  columns=int(self.num_banks/2),
                                                  word_size=int(self.num_banks/2))
        self.add_mod(self.msb_address)

        if self.num_banks > 2:
            self.msb_decoder = pre2x4(route_top_rail=True)
            self.add_mod(self.msb_decoder)

    def create_modules(self):
        """ Create all the modules that will be used """

        # Create the control logic module
        self.control_logic = self.mod_control_logic(num_rows=self.num_rows)
        self.add_mod(self.control_logic)

        # Create the bank module (up to four are instantiated)
        self.bank = bank(word_size=self.word_size,
                         num_words=self.num_words_per_bank,
                         words_per_row=self.words_per_row,
                         num_banks=self.num_banks,
                         name="bank")
        self.add_mod(self.bank)

        # Conditionally create the 
        if(self.num_banks > 1):
            self.create_multi_bank_modules()

        self.bank_count = 0

        self.power_rail_width = self.bank.vdd_rail_width
        # Leave some extra space for the pitch
        self.power_rail_pitch = self.bank.vdd_rail_width + self.wide_m1_space



    def add_bank(self, bank_num, position, x_flip, y_flip):
        """ Place a bank at the given position with orientations """

        # x_flip ==  1 --> no flip in x_axis
        # x_flip == -1 --> flip in x_axis
        # y_flip ==  1 --> no flip in y_axis
        # y_flip == -1 --> flip in y_axis

        # x_flip and y_flip are used for position translation
        bank_mod = self.get_bank_mod(bank_num)
        position_copy = vector(position)

        position_copy.x += int(y_flip == -1) * bank_mod.width
        position_copy.y += int(x_flip == -1) * bank_mod.height

        if x_flip == -1 and y_flip == -1:
            bank_mirror = "XY"
        elif x_flip == -1:
            bank_mirror = "MX"
        elif y_flip == -1:
            bank_mirror = "MY"
        else:
            bank_mirror = "R0"

        bank_inst = self.add_inst(name="bank{0}".format(bank_num),
                                  mod=self.get_bank_mod(bank_num),
                                  offset=position_copy,
                                  mirror=bank_mirror)

        self.connect_inst(self.get_bank_connections(bank_num))

        return bank_inst

    def get_bank_mod(self, bank_num):
        return self.bank

    def get_bank_connections(self, bank_num):
        connections = []
        for i in range(self.word_size):
            connections.append("DATA[{0}]".format(i))
        for i in range(self.bank_addr_size):
            connections.append("ADDR[{0}]".format(i))
        if self.num_banks > 1:
            connections.append("bank_sel[{0}]".format(bank_num))
        else:
            connections.append("vdd")
        connections.extend(["s_en", "w_en", "tri_en", "clk_buf", "vdd", "gnd"])
        return connections

    # FIXME: This should be in geometry.py or it's own class since it is
    # reusable
    def create_bus(self, layer, pitch, offset, names, length, vertical=False, make_pins=False):
        """ Create a horizontal or vertical bus. It can be either just rectangles, or actual
        layout pins. It returns an map of line center line positions indexed by name.  """

        # half minwidth so we can return the center line offsets
        half_minwidth = 0.5*drc["minwidth_{}".format(layer)]
        
        line_positions = {}
        if vertical:
            for i in range(len(names)):
                line_offset = offset + vector(i*pitch,0)
                if make_pins:
                    self.add_layout_pin(text=names[i],
                                        layer=layer,
                                        offset=line_offset,
                                        height=length)
                else:
                    self.add_rect(layer=layer,
                                  offset=line_offset,
                                  height=length)
                line_positions[names[i]]=line_offset+vector(half_minwidth,0)
        else:
            for i in range(len(names)):
                line_offset = offset + vector(0,i*pitch + half_minwidth)
                if make_pins:
                    self.add_layout_pin(text=names[i],
                                        layer=layer,
                                        offset=line_offset,
                                        width=length)
                else:
                    self.add_rect(layer=layer,
                                  offset=line_offset,
                                  width=length)
                line_positions[names[i]]=line_offset+vector(0,half_minwidth)

        return line_positions


    def add_control_logic(self, position, rotate=0, mirror="R0"):
        """ Add and place control logic """
        self.control_logic_inst=self.add_inst(name="control",
                                              mod=self.control_logic,
                                              offset=position,
                                              mirror=mirror,
                                              rotate=rotate)
        self.connect_inst(self.control_logic_inputs + self.control_logic_outputs + ["vdd", "gnd"])


    def add_lvs_correspondence_points(self):
        """ This adds some points for easier debugging if LVS goes wrong.
        """

        for n in self.control_logic_outputs:
            pin = self.control_logic_inst.get_pin(n)
            self.add_label(text=n,
                           layer=pin.layer,
                           offset=pin.ll())
        bank_insts = [self.bank_inst] if self.num_banks == 1 else self.bank_inst
        if self.num_banks == 1:
            return
        for i in range(len(bank_insts)):
            bank_sel_pin = bank_insts[i].get_pin("bank_sel")
            self.add_label(text="bank_sel[{}]".format(i),
                           layer=bank_sel_pin.layer,
                           offset=bank_sel_pin.ll())

    def get_control_logic_names(self):
        return ["s_en", "w_en", "tri_en", "clk_buf" ]

    def add_single_bank_modules(self):
        """ 
        This adds the moduels for a single bank SRAM with control
        logic. 
        """

        # No orientation or offset
        self.bank_inst = self.add_bank(0, [0, 0], -1, 1)

        bottom_control_pin = min(map(self.bank_inst.get_pin, self.get_control_logic_names() + ["bank_sel"]),
                                 key=lambda x: x.by())

        y_offset = bottom_control_pin.by() - self.wide_m1_space - self.control_logic.height
        x_offset = self.bank_inst.rx() + self.wide_m1_space

        self.add_control_logic(position=vector(x_offset, y_offset), mirror="R0")

        self.width = self.control_logic_inst.rx()
        self.height = self.bank.height

    def add_single_bank_pins(self):
        """
        Add the top-level pins for a single bank SRAM with control.
        """

        for i in range(self.word_size):
            self.copy_layout_pin(self.bank_inst, "DATA[{}]".format(i))

        for i in range(self.addr_size):
            self.copy_layout_pin(self.bank_inst, "ADDR[{}]".format(i))            

        for (old,new) in zip(["csb","web","oeb","clk"],["CSb","WEb","OEb","clk"]):
            self.copy_layout_pin(self.control_logic_inst, old, new)



    def add_two_banks(self):
        # Placement of bank 0 (left)
        bank_position_0 = vector(0, self.bank_y_offset)
        self.bank_inst=[self.add_bank(0, bank_position_0, -1, 1)]

        # Placement of bank 1 (right)
        x_off = bank_position_0.x + self.bank.width + self.vertical_bus_width + 2*self.bank_to_bus_distance
        bank_position_1 = vector(x_off, bank_position_0.y)
        self.bank_inst.append(self.add_bank(1, bank_position_1, -1, -1))


    def add_four_banks(self):
        
        # Placement of bank 0 (bottom left)
        bank_position_0 = vector(0, self.bank_y_offset)
        self.bank_inst = [self.add_bank(0, bank_position_0, -1, 1)]

        # Placement of bank 1 (bottom right)
        x_off = bank_position_0.x + self.bank.width + self.vertical_bus_width + 2 * self.bank_to_bus_distance
        bank_position_1 = vector(x_off, bank_position_0.y)
        self.bank_inst.append(self.add_bank(1, bank_position_1, -1, -1))

        # Placement of bank 2 (upper left)
        bank_position_2 = vector(bank_position_0.x, bank_position_0.y + self.bank.height + self.data_bus_height +
                                 2 * self.bank_to_bus_distance + 2 * self.m1_pitch)
        self.bank_inst.append(self.add_bank(2, bank_position_2, 1, 1))

        # Placement of bank 3 (upper right)
        bank_position_3 = vector(bank_position_1.x, bank_position_2.y)
        self.bank_inst.append(self.add_bank(3, bank_position_3, 1, -1))
        

    def connect_rail_from_left_m3m4(self, src_pin, dest_pin):
        """ Helper routine to connect an unrotated/mirrored oriented instance to the rails """
        in_pos = src_pin.rc()
        out_pos = vector(dest_pin.cx(), in_pos.y)
        self.add_wire(("metal4","via3","metal3"),[in_pos, out_pos, out_pos - vector(0,self.m3_pitch)])
        # centralize the via
        via_offset = (src_pin.rx(), src_pin.cy() - 0.5*contact.m3m4.second_layer_width) - self.m3m4_offset_fix
        self.add_via(layers=("metal3","via3","metal4"),
                     offset=via_offset,
                     rotate=90)

    def connect_rail_from_left_m2m3(self, src_pin, dest_pin):
        """ Helper routine to connect an unrotated/mirrored oriented instance to the rails """
        in_pos = src_pin.rc()
        out_pos = vector(dest_pin.cx(), in_pos.y)
        self.add_wire(("metal3","via2","metal2"),[in_pos, out_pos, out_pos - vector(0,self.m2_pitch)])
        # centralize the via
        via_offset = (src_pin.rx(), src_pin.cy() - 0.5*contact.m2m3.second_layer_width) - self.m2m3_offset_fix
        self.add_via(layers=("metal2","via2","metal3"),
                     offset=via_offset,
                     rotate=90)
        
    def connect_rail_from_left_m2m1(self, src_pin, dest_pin):
        """ Helper routine to connect an unrotated/mirrored oriented instance to the rails """
        in_pos = src_pin.rc()
        out_pos = vector(dest_pin.cx(), in_pos.y)
        self.add_wire(("metal2","via1","metal1"),[in_pos, out_pos, out_pos - vector(0,self.m2_pitch)])

    def route_single_bank(self):
        """ Route a single bank SRAM """

        # route control logic output pins to bank control inputs

        control_logic_pins = list(map(self.control_logic_inst.get_pin, self.get_control_logic_names()))

        pitch = self.m3_width + 2*self.m3_width

        for i in range(len(control_logic_pins)):
            src_pin = control_logic_pins[i]
            pin_name = src_pin.name
            dest_pin = self.bank_inst.get_pin(pin_name)

            self.add_rect("metal3", offset=src_pin.ul(), height= dest_pin.uy() - src_pin.uy())
            self.add_contact(contact.m2m3.layer_stack, offset=src_pin.ul())
            self.add_rect("metal2", offset=dest_pin.lr(), width=src_pin.rx() - dest_pin.rx())
            self.add_contact(contact.m2m3.layer_stack, offset=vector(src_pin.lx(), dest_pin.by()))


        # route bank_sel to vdd
        bank_sel_pin = self.bank_inst.get_pin("bank_sel")
        self.add_rect("metal1", offset=bank_sel_pin.ll(), width=self.bank_inst.rx() - bank_sel_pin.lx())
        self.add_contact(contact.m1m2.layer_stack, offset=vector(self.bank_inst.rx(), bank_sel_pin.by()),
                         size=[1, 2], rotate=90)

        self.route_one_bank_power()

        


    def sp_write(self, sp_name):
        # Write the entire spice of the object to the file
        ############################################################
        # Spice circuit
        ############################################################
        sp = open(sp_name, 'w')

        sp.write("**************************************************\n")
        sp.write("* OpenRAM generated memory.\n")
        sp.write("* Words: {}\n".format(self.num_words))
        sp.write("* Data bits: {}\n".format(self.word_size))
        sp.write("* Banks: {}\n".format(self.num_banks))
        sp.write("* Column mux: {}:1\n".format(self.words_per_row))
        sp.write("**************************************************\n")        
        # This causes unit test mismatch
        # sp.write("* Created: {0}\n".format(datetime.datetime.now()))
        # sp.write("* User: {0}\n".format(getpass.getuser()))
        # sp.write(".global {0} {1}\n".format(spice["vdd_name"], 
        #                                     spice["gnd_name"]))
        usedMODS = list()
        self.sp_write_file(sp, usedMODS)
        del usedMODS
        sp.close()

    def analytical_delay(self,slew,load):
        """ LH and HL are the same in analytical model. """
        return self.bank.analytical_delay(slew,load)

    def save_output(self):
        """ Save all the output files while reporting time to do it as well. """

        # Save the spice file
        start_time = datetime.datetime.now()
        spname = os.path.join(OPTS.output_path, self.name + ".sp")
        gdsname = os.path.join(OPTS.output_path, self.name + ".gds")
        debug.print_str("SP: Writing to {0}".format(spname))
        self.sp_write(spname)
        print_time("Spice writing", datetime.datetime.now(), start_time)

        # Save the extracted spice file
        if OPTS.use_pex:
            start_time = datetime.datetime.now()
            # Output the extracted design if requested
            sp_file = os.path.join(OPTS.output_path, "temp_pex.sp")
            verify.run_pex(self.name, gdsname, spname, output=sp_file)
            print_time("Extraction", datetime.datetime.now(), start_time)
        else:
            # Use generated spice file for characterization
            sp_file = spname
        
        # Characterize the design
        start_time = datetime.datetime.now()        

        debug.print_str("LIB: Characterizing... ")
        if OPTS.analytical_delay:
            debug.print_str("Using analytical delay models (no characterization)")
        else:
            if OPTS.spice_name != "":
                debug.print_str("Performing simulation-based characterization with {}".format(OPTS.spice_name))
            if OPTS.trim_netlist:
                debug.print_str("Trimming netlist to speed up characterization.")
        lib(out_dir=OPTS.output_path, sram=self, sp_file=sp_file)
        print_time("Characterization", datetime.datetime.now(), start_time)

        # Write the layout
        start_time = datetime.datetime.now()
        debug.print_str("GDS: Writing to {0}".format(gdsname))
        self.gds_write(gdsname)
        print_time("GDS", datetime.datetime.now(), start_time)

        # Create a LEF physical model
        start_time = datetime.datetime.now()
        lefname = os.path.join(OPTS.output_path, self.name + ".lef")
        debug.print_str("LEF: Writing to {0}".format(lefname))
        self.lef_write(lefname)
        print_time("LEF", datetime.datetime.now(), start_time)

        # Write a verilog model
        start_time = datetime.datetime.now()
        vname = os.path.join(OPTS.output_path, self.name + ".v")
        debug.print_str("Verilog: Writing to {0}".format(vname))
        self.verilog_write(vname)
        print_time("Verilog", datetime.datetime.now(), start_time)
