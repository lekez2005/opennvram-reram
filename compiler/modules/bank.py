from importlib import reload
from math import log

import debug
from base import contact
from base import design
from base import utils
from base.contact_full_stack import ContactFullStack
from base.vector import vector
from globals import OPTS
from tech import drc, power_grid_layers
from .bank_gate import BankGate, ControlGate
from .column_decoder import ColumnDecoder


class bank(design.design):
    """
    Dynamically generated a single Bank including bitcell array,
    hierarchical_decoder, precharge, column_mux, write driver and sense amplifiers.
    """

    def __init__(self, word_size, num_words, words_per_row, num_banks=1, name=""):

        self.set_modules(self.get_module_list())

        if name == "":
            name = "bank_{0}_{1}".format(word_size, num_words)
        design.design.__init__(self, name)
        debug.info(2, "create sram of size {0} with {1} words".format(word_size,num_words))

        self.word_size = word_size
        self.num_words = num_words
        self.words_per_row = words_per_row

        # The local control signals are gated when we have bank select logic,
        # so this prefix will be added to all of the input signals.
        self.prefix = "gated_"
        
        self.compute_sizes()
        self.add_pins()
        self.create_modules()
        self.add_modules()
        self.setup_layout_constraints()
        self.route_layout()



        # Can remove the following, but it helps for debug!
        self.add_lvs_correspondence_points() 

        self.offset_all_coordinates()
        
        self.DRC_LVS()

    def add_pins(self):
        """ Adding pins for Bank module"""
        for i in range(self.word_size):
            self.add_pin("DATA[{0}]".format(i))
        for i in range(self.addr_size):
            self.add_pin("ADDR[{0}]".format(i))

        for pin in ["bank_sel", "s_en", "w_en", "tri_en", "clk_buf", "vdd", "gnd"]:
            self.add_pin(pin)

    def route_layout(self):
        """ Create routing amoung the modules """
        self.create_central_bus()
        self.route_precharge_to_bitcell_array()
        self.connect_bitlines()
        self.route_sense_amp_to_trigate()
        self.route_tri_gate_out()
        self.route_wordline_driver()
        self.route_row_decoder()
        self.route_control_lines()
        # Add and route the bank select logic
        self.route_bank_sel()
        if self.msf_address_inst is not None:
            self.route_msf_address()
        else:
            self.route_column_decoder()

        if self.col_mux_array_inst is not None:
            self.route_col_mux_to_sense_amp_array()

        self.add_control_pins()
        self.calculate_rail_vias()
        self.route_vdd_supply()
        self.route_gnd_supply()

    @staticmethod
    def get_module_list():
        return ["tri_gate", "bitcell", "decoder", "ms_flop_array", "ms_flop_array_horizontal", "wordline_driver",
                    "bitcell_array", "sense_amp_array", "precharge_array",
                    "column_mux_array", "write_driver_array", "tri_gate_array"]

    def set_modules(self, mod_list):
        for mod_name in mod_list:
            config_mod_name = getattr(OPTS, mod_name)
            class_file = reload(__import__(config_mod_name))
            mod_class = getattr(class_file, config_mod_name)
            setattr(self, "mod_"+mod_name, mod_class)
        
    def add_modules(self):
        """ Add modules. The order should not matter! """
        self.add_bitcell_array()
        self.add_precharge_array()
        
        if self.col_addr_size > 0:
            # The m2 width is because the 6T cell may have vias on the boundary edge for
            # overlapping when making the array
            self.add_column_mux_array()
        else:
            self.col_mux_array_inst = None

        self.add_sense_amp_array()
        self.add_write_driver_array()
        self.add_msf_data_in()
        self.add_tri_gate_array()
        self.add_bank_gate()
        self.add_wordline_and_decoder()
        if self.col_addr_size == 0 and self.row_decoder_inst.by() > self.bank_gate_inst.by():
            self.add_msf_address()
            self.column_decoder_inst = None
        else:
            self.add_column_decoder()
            self.msf_address_inst = None

    def compute_sizes(self):
        """  Computes the required sizes to create the bank """

        self.num_cols = int(self.words_per_row*self.word_size)
        self.num_rows = int(self.num_words / self.words_per_row)

        self.row_addr_size = int(log(self.num_rows, 2))
        self.col_addr_size = int(log(self.words_per_row, 2))
        self.addr_size = self.col_addr_size + self.row_addr_size

        debug.check(self.num_rows*self.num_cols==self.word_size*self.num_words,"Invalid bank sizes.")
        debug.check(self.addr_size==self.col_addr_size + self.row_addr_size,"Invalid address break down.")

        # Width for left gnd rail
        self.vdd_rail_width = 5*self.m2_width
        self.gnd_rail_width = 5*self.m2_width

        # m2 fill width for m1-m3 via
        min_area = drc["minarea_metal1_contact"]
        self.via_m2_fill_height = contact.m1m2.second_layer_height
        self.via_m2_fill_width = utils.ceil(min_area/self.via_m2_fill_height)

        # Number of control lines in the bus
        self.num_control_lines = 6
        # The order of the control signals on the control bus:
        self.input_control_signals = ["clk_buf", "tri_en", "w_en", "s_en"]
        self.control_signals = list(map(lambda x: self.prefix + x,
                                        ["s_en", "clk_bar", "clk_buf", "tri_en_bar", "tri_en", "w_en"]))

        # The central bus is the column address (both polarities), row address
        self.num_addr_lines = self.row_addr_size

        # M1/M2 routing pitch is based on contacted pitch
        self.m1_pitch = contact.m1m2.width + self.parallel_line_space
        self.m2_pitch = contact.m2m3.width + self.parallel_line_space

        # Overall central bus gap. It includes all the column mux lines,
        # control lines, address flop to decoder lines and a GND power rail in M2
        # 1.5 pitches on the right on the right of the control lines for vias (e.g. column mux addr lines)
        self.start_of_right_central_bus = -self.m2_pitch * (self.num_control_lines + 1.5)
        # one pitch on the right on the addr lines and one on the right of the gnd rail

        self.gnd_x_offset = self.start_of_right_central_bus - self.gnd_rail_width - self.m2_pitch

        self.start_of_left_central_bus = self.gnd_x_offset - self.m2_pitch*(self.num_addr_lines+1)
        # add a pitch on each end and around the gnd rail
        self.overall_central_bus_width = - self.start_of_left_central_bus + self.m2_width







    def create_modules(self):
        """ Create all the modules using the class loader """
        self.tri = self.mod_tri_gate()
        self.bitcell = self.mod_bitcell()

        nwell_top = self.bitcell.get_nwell_top()
        self.nwell_extension = nwell_top - self.bitcell.height  # extension of nwell above bitcell
        
        self.bitcell_array = self.mod_bitcell_array(cols=self.num_cols,
                                                    rows=self.num_rows)
        self.add_mod(self.bitcell_array)

        self.precharge_array = self.mod_precharge_array(columns=self.num_cols, size=OPTS.precharge_size)
        self.add_mod(self.precharge_array)

        if(self.col_addr_size > 0):
            self.column_mux_array = self.mod_column_mux_array(columns=self.num_cols, 
                                                              word_size=self.word_size)
            self.add_mod(self.column_mux_array)


        self.sense_amp_array = self.mod_sense_amp_array(word_size=self.word_size, 
                                                       words_per_row=self.words_per_row)
        self.add_mod(self.sense_amp_array)

        self.write_driver_array = self.mod_write_driver_array(columns=self.num_cols,
                                                              word_size=self.word_size)
        self.add_mod(self.write_driver_array)

        self.decoder = self.mod_decoder(rows=self.num_rows)
        self.add_mod(self.decoder)

        self.msf_address = self.mod_ms_flop_array_horizontal(name="msf_address",
                                                  columns=self.row_addr_size,
                                                  word_size=self.row_addr_size)
        self.add_mod(self.msf_address)
        
        self.msf_data_in = self.mod_ms_flop_array(name="msf_data_in", 
                                                  columns=self.num_cols, 
                                                  word_size=self.word_size,
                                                  align_bitcell=True)
        self.add_mod(self.msf_data_in)
        
        self.tri_gate_array = self.mod_tri_gate_array(columns=self.num_cols, 
                                                      word_size=self.word_size)
        self.add_mod(self.tri_gate_array)

        self.wordline_driver = self.mod_wordline_driver(rows=self.num_rows, no_cols=self.num_cols)
        self.add_mod(self.wordline_driver)
        self.create_bank_gate()

        self.create_column_decoder()


    def create_bank_gate(self):
        control_gates = [
            ControlGate("s_en"),
            ControlGate("clk",  route_complement=True),
            ControlGate("tri_en",  route_complement=True),
            ControlGate("w_en")
        ]
        self.bank_gate = BankGate(control_gates, contact_nwell=False)
        self.add_mod(self.bank_gate)

    def create_column_decoder(self):
        self.column_decoder = ColumnDecoder(self.row_addr_size, self.col_addr_size)
        self.add_mod(self.column_decoder)

    def add_bitcell_array(self):
        """ Adding Bitcell Array """

        self.bitcell_array_inst=self.add_inst(name="bitcell_array", 
                                              mod=self.bitcell_array,
                                              offset=vector(0,0))
        temp = []
        for i in range(self.num_cols):
            temp.append("bl[{0}]".format(i))
            temp.append("br[{0}]".format(i))
        for j in range(self.num_rows):
            temp.append("wl[{0}]".format(j))
        temp.extend(["vdd", "gnd"])
        self.connect_inst(temp)

            

    def add_precharge_array(self):
        """ Adding Precharge """

        nwell_top = self.bitcell.get_nwell_top()
        nwell_extension = nwell_top - self.bitcell.height
        y_space = nwell_extension
        y_offset = self.bitcell_array.height + y_space
        self.precharge_array_inst=self.add_inst(name="precharge_array",
                                                mod=self.precharge_array, 
                                                offset=vector(0,y_offset))
        temp = []
        for i in range(self.num_cols):
            temp.append("bl[{0}]".format(i))
            temp.append("br[{0}]".format(i))
        temp.extend([self.prefix+"clk_bar", "vdd"])
        self.connect_inst(temp)

    def add_column_mux_array(self):
        """ Adding Column Mux when words_per_row > 1 . """

        y_offset = self.column_mux_array.height
        self.col_mux_array_inst=self.add_inst(name="column_mux_array",
                                              mod=self.column_mux_array,
                                              offset=vector(0,y_offset).scale(-1,-1))
        temp = []
        for i in range(self.num_cols):
            temp.append("bl[{0}]".format(i))
            temp.append("br[{0}]".format(i))
        for k in range(self.words_per_row):
                temp.append("sel[{0}]".format(k))
        for j in range(self.word_size):
            temp.append("bl_out[{0}]".format(j))
            temp.append("br_out[{0}]".format(j))
        temp.append("gnd")
        self.connect_inst(temp)

    def get_sense_amp_offset(self):
        if self.col_addr_size > 0:
            y_offset = self.col_mux_array_inst.by() - self.sense_amp_array.height
        else:
            y_offset = - self.sense_amp_array.height
        return vector(0, y_offset).scale(-1, 1)

    def add_sense_amp_array(self):
        """ Adding Sense amp  """
        self.sense_amp_array_offset = self.get_sense_amp_offset()
        self.sense_amp_array_inst=self.add_inst(name="sense_amp_array",
                                                mod=self.sense_amp_array,
                                                offset=self.sense_amp_array_offset)
        temp = []
        for i in range(self.word_size):
            temp.append("data_out[{0}]".format(i))
            if self.words_per_row == 1:
                temp.append("bl[{0}]".format(i))
                temp.append("br[{0}]".format(i))
            else:
                temp.append("bl_out[{0}]".format(i))
                temp.append("br_out[{0}]".format(i))

        temp.extend([self.prefix+"s_en", "vdd", "gnd"])
        self.connect_inst(temp)

    def add_write_driver_array(self):
        """ Adding Write Driver  """

        y_offset = self.sense_amp_array_inst.by() - self.write_driver_array.height
        self.write_driver_array_inst=self.add_inst(name="write_driver_array", 
                                                   mod=self.write_driver_array, 
                                                   offset=vector(0,y_offset).scale(-1,1))

        temp = []
        for i in range(self.word_size):
            temp.append("data_in[{0}]".format(i))
        for i in range(self.word_size):            
            if (self.words_per_row == 1):            
                temp.append("bl[{0}]".format(i))
                temp.append("br[{0}]".format(i))
            else:
                temp.append("bl_out[{0}]".format(i))
                temp.append("br_out[{0}]".format(i))
        temp.extend([self.prefix+"w_en", "vdd", "gnd"])
        self.connect_inst(temp)

    def get_msf_data_in_y_offset(self):
        return self.write_driver_array_inst.by() - self.msf_data_in.height

    def add_msf_data_in(self):
        """ data_in flip_flop """

        y_offset = self.get_msf_data_in_y_offset()
        self.msf_data_in_inst=self.add_inst(name="data_in_flop_array", 
                                            mod=self.msf_data_in, 
                                            offset=vector(0,y_offset).scale(-1,1))

        temp = []
        for i in range(self.word_size):
            temp.append("DATA[{0}]".format(i))
        for i in range(self.word_size):
            temp.append("data_in[{0}]".format(i))
            temp.append("data_in_bar[{0}]".format(i))
        temp.extend([self.prefix+"clk_bar", "vdd", "gnd"])
        self.connect_inst(temp)

    def get_tri_gate_offset(self):
        return self.msf_data_in_inst.by()

    def add_tri_gate_array(self):
        """ data tri gate to drive the data bus """
        y_offset = self.get_tri_gate_offset()
        self.tri_gate_array_inst=self.add_inst(name="tri_gate_array", 
                                              mod=self.tri_gate_array, 
                                               offset=vector(0,y_offset).scale(-1, 1),
                                               mirror="MX")
        temp = []
        for i in range(self.word_size):
            temp.append("data_out[{0}]".format(i))
        for i in range(self.word_size):
            temp.append("DATA[{0}]".format(i))
        temp.extend([self.prefix+"tri_en", self.prefix+"tri_en_bar", "vdd", "gnd"])
        self.connect_inst(temp)

    def add_bank_gate(self):
        """Add bank gate instance"""
        tri_gate_vdd = self.tri_gate_array_inst.get_pin("vdd")
        y_offset = tri_gate_vdd.by() + 0.5*self.bank_gate.rail_height - self.bank_gate.height
        # distribute around the middle
        x_offset = max(0, 0.5*self.bitcell_array_inst.rx() - 0.5*self.bank_gate.width) + self.bank_gate.width
        self.bank_gate_inst = self.add_inst(name="bank_gate", mod=self.bank_gate,
                                            offset=vector(x_offset, y_offset),
                                            mirror="MY")
        self.connect_inst(["bank_sel", "s_en", "clk_buf", "tri_en", "w_en"] + self.control_signals + ["vdd", "gnd"])


    def add_wordline_and_decoder(self):
        """Fill space between row decoder and wordline driver with implants/nwell/pmet to prevent drc spacing issues"""
        self.wordline_x_offset = self.gnd_x_offset - self.wordline_driver.width - self.m2_pitch
        x_space = self.line_end_space
        self.decoder_x_offset = self.wordline_x_offset - (self.decoder.row_decoder_width + x_space)

        # decoder inverter and wordline_driver inverters should be the same, otherwise, these calculations may need
        # to be adjusted
        inv = self.wordline_driver.inv1
        fill_width = inv.width + x_space
        mid_x = self.wordline_x_offset - 0.5*x_space

        contact_implant_height = inv.well_contact_implant_height

        cont_pimp_y = 0
        nimp_y = inv.mid_y - 0.5 * inv.nimplant_height
        pimp_y = inv.mid_y + 0.5 * inv.pimplant_height
        cont_nimp_y = inv.height
        nwell_y = pmet_y = inv.mid_y + 0.5 * inv.nwell_height

        layers = ["pimplant", "nimplant", "pimplant", "nimplant", "nwell", "pmet"]
        y_mids = [cont_pimp_y, cont_nimp_y, pimp_y, nimp_y, nwell_y, pmet_y]
        heights = [contact_implant_height, contact_implant_height, inv.pimplant_height, inv.nimplant_height,
                   inv.nwell_height, inv.nwell_height]

        if OPTS.use_x_body_taps:
            layers_index = range(2, len(layers))
        else:
            layers_index = range(len(layers))

        # tx_implant_extension = 0
        # contact_implant_extension = 0.5*(inv.implant_width - inv.width)
        #
        # pmet_extension = 0.5*(inv.pmet_width - inv.width)
        # nwell_extension = 0.5*(inv.nwell_width - inv.width)

        for row in range(self.decoder.rows):
            y_offset = row * inv.height
            for i in layers_index:
                if row % 2 == 1:
                    mid_y = y_offset + y_mids[i]
                else:
                    mid_y = y_offset + inv.height - y_mids[i]
                self.add_rect_center(layers[i], offset=vector(mid_x, mid_y), width=fill_width, height=heights[i])
            if OPTS.use_x_body_taps:
                # extend nwell to bitcells
                body_tap = self.bitcell_array.body_tap
                x_offset = self.wordline_x_offset + self.wordline_driver.width
                output_inv = self.wordline_driver.module_insts[-1].mod
                nwell_height = output_inv.nwell_height
                if row % 2 == 0:
                    well_y = y_offset + (output_inv.height - output_inv.mid_y) - nwell_height
                else:
                    well_y = y_offset + output_inv.mid_y
                self.add_rect("nwell", offset=vector(x_offset, well_y), height=nwell_height,
                              width=self.bitcell_array_inst.lx() + 0.5*body_tap.width - x_offset)


        self.add_row_decoder()
        self.add_wordline_driver()

    def add_row_decoder(self):
        """  Add the hierarchical row decoder  """

        
        # The address and control bus will be in between decoder and the main memory array 
        # This bus will route address bits to the decoder input and column mux inputs. 
        # The wires are actually routed after we placed the stuff on both sides.
        # The predecoder is below the x-axis and the main decoder is above the x-axis
        # The address flop and decoder are aligned in the x coord.

        offset = vector(self.decoder_x_offset, -self.decoder.predecoder_height)
        self.row_decoder_inst=self.add_inst(name="row_decoder", 
                                            mod=self.decoder, 
                                            offset=offset)

        temp = []
        for i in range(self.row_addr_size):
            temp.append("A[{0}]".format(i))
        for j in range(self.num_rows):
            temp.append("dec_out[{0}]".format(j))
        temp.extend(["vdd", "gnd"])
        self.connect_inst(temp)

    def add_wordline_driver(self):
        """ Wordline Driver """

        # The wordline driver is placed to the right of the main decoder width.
        # This means that it slightly overlaps with the hierarchical decoder,
        # but it shares power rails. This may differ for other decoders later...
        self.wordline_driver_inst=self.add_inst(name="wordline_driver",
                                                mod=self.wordline_driver, 
                                                offset=vector(self.wordline_x_offset, 0))

        temp = []
        for i in range(self.num_rows):
            temp.append("dec_out[{0}]".format(i))
        for i in range(self.num_rows):
            temp.append("wl[{0}]".format(i))
        temp.append(self.prefix+"clk_buf")
        temp.append("vdd")
        temp.append("gnd")
        self.connect_inst(temp)

    def add_msf_address(self):
        """ Adding address Flip-flops """

        # A gap between the hierarchical decoder and addr flops
        gap = max(drc["pwell_to_nwell"], 2*self.m2_pitch)
        gap = 2*self.m2_pitch  # no need for well spacing for vertical flip flop array

        # The address flops go below the hierarchical decoder
        addr_x_offset = self.decoder_x_offset
        # msf_address is not in the y-coord because it is rotated
        # TODO place msf_address
        offset = vector(addr_x_offset + 2*self.m1_space + contact.m1m2.first_layer_height,
                        self.decoder.predecoder_height +  gap + self.msf_address.height)
        self.msf_address_inst=self.add_inst(name="address_flop_array", 
                                            mod=self.msf_address, 
                                            offset=offset.scale(1,-1),
                                            rotate=0)
        temp = []
        for i in range(self.row_addr_size):
            temp.append("ADDR[{0}]".format(i))
        for i in range(self.row_addr_size):
                temp.extend(["A[{0}]".format(i),"A_bar[{0}]".format(i)])
        temp.append(self.prefix+"clk_buf")
        temp.extend(["vdd", "gnd"])
        self.connect_inst(temp)

    def add_column_decoder(self):
        """Add column decoder"""
        # stagger the decoder dout connection vias to prevent minimum via spacing rules
        rightmost_rail = self.start_of_right_central_bus + self.num_control_lines*self.m2_pitch-self.parallel_line_space
        self.decoder_even_via_x = rightmost_rail + self.line_end_space
        self.decoder_odd_via_x = self.decoder_even_via_x + drc["parallel_via_space"] + contact.m1m2.contact_width
        gap = max(self.metal1_minwidth_fill,
                  self.decoder_odd_via_x + contact.m1m2.second_layer_height - rightmost_rail) + self.m2_space
        y_offset = self.bank_gate_inst.by() - gap - self.column_decoder.height
        x_offset = self.bitcell_array_inst.lx() + gap

        self.column_decoder_inst = self.add_inst("column_decoder", mod=self.column_decoder,
                                                 offset=vector(x_offset + self.column_decoder.width,
                                                               y_offset + self.column_decoder.height),
                                                 mirror="XY")
        temp = []
        for i in range(self.row_addr_size + self.col_addr_size):
            temp.append("ADDR[{0}]".format(i))
        for i in range(self.row_addr_size):
            temp.append("A[{0}]".format(i))
        if self.col_addr_size > 0:
            for i in range(2**self.col_addr_size):
                temp.append("sel[{}]".format(i))
        temp.extend([self.prefix+"clk_buf", "vdd", "gnd"])
        self.connect_inst(temp)

    def route_bank_sel(self):
        # connect bank gate outputs outputs
        control_to_pin = dict(zip(self.control_signals, self.control_signals))
        control_to_pin[self.prefix + "clk_buf"] = self.prefix + "clk"
        for control_name, pin_name in control_to_pin.items():
            if pin_name == "clk_buf":
                pin_name = "clk"
            v_rail_x = self.central_line_xoffset[control_name]
            pin = self.bank_gate_inst.get_pin(pin_name)
            self.add_rect("metal1", offset=vector(v_rail_x, pin.by()), width=pin.lx()-v_rail_x)
            via_y = pin.cy() - 0.5*self.m1_width + 0.5*contact.m1m2.first_layer_height
            self.add_contact_center(layers=contact.contact.m1m2_layers, offset=vector(v_rail_x, via_y))

        # add input pins
        m1_extension = 0.5*contact.m1m2.second_layer_height + self.line_end_space   #space to prevent via clash
        stagger_width = contact.m1m2.second_layer_height
        pin_names = ["bank_sel"] + self.input_control_signals
        for i in range(len(pin_names)):
            pin_name = pin_names[i]
            if pin_name == "clk_buf":
                gate_pin_name = "clk"
            else:
                gate_pin_name = pin_name
            pin = self.bank_gate_inst.get_pin(gate_pin_name)
            if pin.layer == "metal1":
                via_x = pin.rx() + m1_extension + contact.m1m2.second_layer_height + (i % 2)*stagger_width
                self.add_rect("metal1", offset=pin.lr(), width=via_x - pin.rx())
                self.add_contact(layers=contact.m1m2.layer_stack, offset=vector(via_x, pin.by()), rotate=90)
                self.add_layout_pin(pin_name, "metal2", offset=vector(via_x, pin.by()), width=self.right_edge - via_x)
            else:
                self.add_layout_pin(pin_name, "metal2", offset=pin.lr(), width=self.right_edge - pin.rx())



    def setup_layout_constraints(self):
        """ Calculating layout constraints, width, height etc """

        (self.bitcell_offsets, self.tap_offsets) = utils.get_tap_positions(self.num_cols)

        # bend for tri gate to sense amp
        self.bendX = 3*self.m3_width
        self.bendY = 2*self.m3_width

        # The minimum point is either the bottom of the address flops,
        # the bank_gate or the column decoder
        # driver.
        min_points = []
        if hasattr(self, "row_decoder_inst"):
            min_points.append(self.row_decoder_inst.by())
        bank_gate_min_point = self.bank_gate_inst.by()
        min_points.append(bank_gate_min_point)
        if self.msf_address_inst is not None:
            addr_min_point = self.msf_address_inst.by()
            min_points.append(addr_min_point)
        if self.column_decoder_inst is not None:
            col_decoder_min_point = self.column_decoder_inst.by()
            min_points.append(col_decoder_min_point)

        self.min_point = min(min_points) - self.wide_m1_space


        # The max point is always the top of the precharge bitlines
        self.max_point = self.precharge_array_inst.uy()

        self.height = self.max_point - self.min_point

        self.compute_width()
        


    def compute_width(self):
        # Add an extra gap between the bitcell and the rail
        self.right_vdd_x_offset = (
                    max(self.bitcell_array_inst.rx(), self.bank_gate_inst.rx() + 2 * self.wide_m1_space) +
                    self.wide_m1_space + self.m1_space)

        # from the edge of the decoder is another 2 times minwidth metal1
        # flip flop vertical m2 vdd rails extend to the left
        self.left_vdd_x_offset = self.row_decoder_inst.lx() - self.vdd_rail_width - 2 * self.m1_width

        self.right_edge = self.right_vdd_x_offset + self.vdd_rail_width
        self.width = self.right_edge - self.left_vdd_x_offset



    def connect_bitlines(self):
        if self.col_addr_size > 0:
            dest_instance = self.col_mux_array_inst
        else:
            dest_instance = self.sense_amp_array_inst
        # connect bl, br to bitcell pins
        for i in range(self.num_cols):
            for pin_name in ["bl[{}]", "br[{}]"]:
                col_pin_name = pin_name.format(i)
                bitcell_pin = self.bitcell_array_inst.get_pin(col_pin_name)
                dest_pin = dest_instance.get_pin(col_pin_name)
                self.add_rect(dest_pin.layer, offset=dest_pin.ul(), height=bitcell_pin.by() - dest_pin.uy(),
                              width=dest_pin.width())

    def create_central_bus(self):
        """ Create the address, supply, and control signal central bus lines. """

        # Address lines in central line connection are 2*col_addr_size 
        # number of connections for the column mux (for both signal and _bar) and row_addr_size (no _bar) 

        self.central_line_xoffset = {}

        # Control lines (to the right of the GND rail)
        for i in range(self.num_control_lines):
            x_offset = self.start_of_right_central_bus + i*self.m2_pitch
            self.central_line_xoffset[self.control_signals[i]]=x_offset + 0.5*self.m2_width
            # Pins are added later if this is a single bank, so just add rectangle now
            self.add_rect(layer="metal2",  
                          offset=vector(x_offset, self.min_point), 
                          width=self.m2_width, 
                          height=self.height)

        # row address lines
        # goes from just below row decoder to lowest msf_address_int output pin
        if self.msf_address_inst is not None:
            data_pin_names = list(map("dout[{}]".format, range(self.row_addr_size)))
            addr_pins = sorted(map(self.msf_address_inst.get_pin, data_pin_names), key=lambda x: x.by())
            rail_min_point = addr_pins[0].by()
            for i in range(self.row_addr_size):
                x_offset = self.start_of_left_central_bus + i*self.m2_pitch
                name = "A[{}]".format(i)
                self.central_line_xoffset[name]=x_offset + 0.5*self.m2_width
                # Add a label pin for LVS correspondence and visual help inspecting the rail.
                self.add_label_pin(text=name,
                                   layer="metal2",
                                   offset=vector(x_offset, rail_min_point),
                                   width=self.m2_width,
                                   height=-rail_min_point - self.line_end_space)
        else:
            data_pin_names = list(map("dout[{}]".format, range(self.row_addr_size)))
            addr_pins = sorted(map(self.column_decoder_inst.get_pin, data_pin_names), key=lambda x: x.by())
            bottom_rail = min(addr_pins[0].by(), self.row_decoder_inst.by())
            top_rail = self.wordline_driver_inst.by() - 0.5*self.wordline_driver.rail_height - self.line_end_space
            for i in range(self.row_addr_size):
                x_offset = self.start_of_left_central_bus + i*self.m2_pitch
                name = "A[{}]".format(i)
                self.central_line_xoffset[name]=x_offset + 0.5*self.m2_width
                # Add a label pin for LVS correspondence and visual help inspecting the rail.
                self.add_label_pin(text=name,
                                   layer="metal2",
                                   offset=vector(x_offset, bottom_rail),
                                   width=self.m2_width,
                                   height=top_rail - bottom_rail)

    def route_precharge_to_bitcell_array(self):
        """ Routing of BL and BR between pre-charge and bitcell array """
        self.connect_array_bitlines(self.precharge_array_inst, self.bitcell_array_inst)

    def route_col_mux_to_sense_amp_array(self):
        for i in range(self.word_size):
            for (top_name, bot_name) in [("bl_out[{}]", "bl[{}]"), ("br_out[{}]", "br[{}]")]:
                top_pin = self.col_mux_array_inst.get_pin(top_name.format(i))
                bot_pin = self.sense_amp_array_inst.get_pin(bot_name.format(i*self.words_per_row))
                self.add_path(top_pin.layer, [bot_pin.uc(), top_pin.bc()])

    def connect_array_bitlines(self, top_array, bottom_array, top_bl_name="bl[{}]", top_br_name="br[{}]",
                               bot_bl_name="bl[{}]", bot_br_name="br[{}]"):
        for i in range(self.num_cols):
            for (top_name, bot_name) in [(top_bl_name, bot_bl_name), (top_br_name, bot_br_name)]:
                top_pin = top_array.get_pin(top_name.format(i))
                bot_pin = bottom_array.get_pin(bot_name.format(i))
                self.add_path(top_pin.layer, [bot_pin.uc(), top_pin.bc()])

    def route_sense_amp_to_trigate(self):
        """ Routing of sense amp output to tri_gate input """

        for i in range(self.word_size):


            # Connection of data_out of sense amp to data_ in of msf_data_out
            tri_gate_in = self.tri_gate_array_inst.get_pin("in[{}]".format(i)).bc()
            sa_data_out = self.sense_amp_array_inst.get_pin("data[{}]".format(i)).rc()

            # add m2-m3 via at input of tri_gate_in
            via_offset = self.tri_gate_array_inst.get_pin("out[{}]".format(i)).ul() - vector(0, contact.m2m3.second_layer_height)
            self.add_contact(contact.contact.m2m3_layers, offset=via_offset)

            bendX = tri_gate_in.x - self.bendX
            bendY = tri_gate_in.y - self.bendY

            # Connection point of M2 and M3 paths, below the tri gate and
            # to the left of the tri gate input
            bend = vector(bendX, bendY)

            # Connect an M2 path to the gate
            mid3 = [tri_gate_in.x, bendY] # guarantee down then left
            self.add_path("metal2", [bend, mid3, tri_gate_in])

            # connect up then right to sense amp
            mid1 = vector(bendX,sa_data_out.y)
            self.add_path("metal3", [bend, mid1, sa_data_out])


            offset = bend - vector([0.5*drc["minwidth_metal3"]] * 2)
            self.add_via(("metal2", "via2", "metal3"),offset)

    def route_tri_gate_out(self):
        """ Metal 3 routing of tri_gate output data """
        for i in range(self.word_size):
            tri_gate_out_position = self.tri_gate_array_inst.get_pin("out[{}]".format(i)).ul()
            data_line_position = vector(tri_gate_out_position.x, self.min_point)
            self.add_layout_pin(text="DATA[{}]".format(i), layer="metal3",
                          offset=data_line_position, 
                          width=drc["minwidth_metal3"], 
                          height=tri_gate_out_position.y - self.min_point)


    def route_row_decoder(self):
        """ Routes the row decoder inputs and supplies """

        
        for i in range(self.row_addr_size):
            # before this index, we are using 2x4 decoders
            switchover_index = 2*self.decoder.no_of_pre2x4
            # so decide what modulus to perform the height spacing
            if i < switchover_index:
                position_heights = i % 2
            else:
                position_heights = (i-switchover_index) % 3
                
            # Connect the address rails to the decoder
            # Note that the decoder inputs are long vertical rails so spread out the connections vertically.
            y_offset = position_heights*self.bitcell.height
            in_pin = self.row_decoder_inst.get_pin("A[{}]".format(i))
            via_space = 0.5*self.decoder.rail_height + self.line_end_space
            decoder_in_via = in_pin.ll() + vector(0, y_offset + via_space)
            decoder_in_position = decoder_in_via + vector(0, 0.5*contact.m1m2.second_layer_height)
            rail_position = vector(self.central_line_xoffset["A[{}]".format(i)],decoder_in_position.y)
            self.add_path("metal1",[decoder_in_position,rail_position])

            self.add_via(layers=("metal1", "via1", "metal2"),
                         offset=decoder_in_via)
            
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                         offset=rail_position)

        # Route the power and ground, but only BELOW the y=0 since the
        # others are connected with the wordline driver.

        for gnd_pin in self.row_decoder_inst.get_pins("gnd"):
            if gnd_pin.uy()>0:
                continue
            self.route_gnd_from_left(gnd_pin)

        # route the vdd rails
        for vdd_pin in self.row_decoder_inst.get_pins("vdd"):
            if vdd_pin.uy()>0:
                continue
            self.add_rect("metal1", height=vdd_pin.height(),
                          width=vdd_pin.rx()-self.left_vdd_x_offset,
                          offset=vector(self.left_vdd_x_offset, vdd_pin.by()))

    
    def route_wordline_driver(self):
        """ Connecting Wordline driver output to Bitcell WL connection  """
        
        # we don't care about bends after connecting to the input pin, so let the path code decide.
        for i in range(self.num_rows):
            # The pre/post is to access the pin from "outside" the cell to avoid DRCs
            decoder_out_pin = self.row_decoder_inst.get_pin("decode[{}]".format(i))
            driver_in_pin = self.wordline_driver_inst.get_pin("in[{}]".format(i))

            mid1 = vector(decoder_out_pin.cx(), decoder_out_pin.cy())
            mid2 = vector(decoder_out_pin.cx(), driver_in_pin.cy())
            self.add_path("metal1", [mid1, mid2, driver_in_pin.center()])

            # The mid guarantees we exit the input cell to the right.
            driver_wl_pos = self.wordline_driver_inst.get_pin("wl[{}]".format(i)).rc()
            bitcell_wl_pos = self.bitcell_array_inst.get_pin("wl[{}]".format(i)).lc()
            self.add_path("metal1", [vector(driver_wl_pos.x, bitcell_wl_pos.y), bitcell_wl_pos])

        
        # route the gnd rails, add contact to rail as well
        for gnd_pin in self.wordline_driver_inst.get_pins("gnd"):
            self.route_gnd_from_left(gnd_pin)
            self.add_rect("metal1", offset=gnd_pin.lr(), height=gnd_pin.height(),
                          width=self.bitcell_array_inst.ll().x-gnd_pin.rx())
                        
        # route the vdd rails
        for vdd_pin in self.wordline_driver_inst.get_pins("vdd"):
            self.add_rect("metal1", height=vdd_pin.height(),
                          offset=vector(self.left_vdd_x_offset, vdd_pin.by()),
                          width=self.right_vdd_x_offset-self.left_vdd_x_offset)

    def route_column_decoder(self):

        # Connect dout to rails
        for i in range(self.row_addr_size):

            # Connect the ff outputs to the rails
            dout_pin = self.column_decoder_inst.get_pin("dout[{}]".format(i))

            if i % 2 == 0:
                via_x = self.decoder_even_via_x
            else:
                via_x = self.decoder_odd_via_x

            via_offset = vector(via_x + contact.m2m3.second_layer_height, dout_pin.by())

            self.add_rect("metal1", offset=vector(via_x, dout_pin.by()), width=dout_pin.lx()-via_x)

            self.add_contact(contact.m1m2.layer_stack, offset=via_offset, rotate=90)
            self.add_contact(contact.m2m3.layer_stack, offset=via_offset, rotate=90)
            fill_width = self.metal1_minwidth_fill
            self.add_rect("metal2", offset=vector(via_x, dout_pin.by()), width=fill_width)

            rail_pos = vector(self.central_line_xoffset["A[{}]".format(i)], dout_pin.cy())
            self.add_path("metal3",[rail_pos, vector(via_x, dout_pin.cy())])

            contact_pos = vector(rail_pos.x, dout_pin.uy()-0.5*contact.m2m3.first_layer_height)
            self.add_via_center(layers=contact.m2m3.layer_stack,
                                offset=contact_pos)
        # add address input rails
        even_via_x = self.right_vdd_x_offset - self.line_end_space
        odd_via_x = even_via_x - drc["parallel_via_space"] - contact.m1m2.contact_width
        for i in range(self.addr_size):
            din_pin = self.column_decoder_inst.get_pin("din[{}]".format(i))
            if i % 2 == 0:
                via_x = even_via_x
            else:
                via_x = odd_via_x
            self.add_rect("metal1", offset=din_pin.lr(), width=via_x - din_pin.rx())
            self.add_contact(contact.m1m2.layer_stack, offset=vector(via_x, din_pin.by()), rotate=90)

            pin_width = max(self.metal1_minwidth_fill, self.right_vdd_x_offset - via_x)
            self.add_layout_pin(text="ADDR[{}]".format(i),
                                layer="metal2",
                                offset=vector(self.right_vdd_x_offset - pin_width, din_pin.by()),
                                width=pin_width)

        # route clk
        control_signal = self.prefix + "clk_buf"
        pin = self.column_decoder_inst.get_pin("clk")
        control_pos = vector(self.central_line_xoffset[control_signal], pin.cy())
        self.add_rect("metal1", height=pin.height(), width=pin.lx()-control_pos.x,
                      offset=control_pos-vector(0, 0.5*self.m1_width))
        self.add_via_center(layers=("metal1", "via1", "metal2"),
                            offset=control_pos,
                            rotate=0)
        if self.col_addr_size == 0:
            return

        # route sel pins
        obstructions = []
        tri_gate_in_pins = list(map(self.tri_gate_array_inst.get_pin, map("in[{0}]".format, range(self.word_size))))
        m3_pitch = self.m3_width + self.m3_space
        blocked_regions = list(map(lambda x: (x.lx() - self.bendX - 0.5*self.m1_width - m3_pitch,
                                         x.rx() + m3_pitch), tri_gate_in_pins))


        def find_no_collision(x, direction=1.0):
            while True:
                x += direction*self.wide_m1_space
                clash = False
                for blocked_region in blocked_regions:
                    if blocked_region[0] < x < blocked_region[1]:
                        clash = True
                if not clash:
                    return x
        def find_left(x):
            return find_no_collision(x, -1.0)

        def find_right(x):
            return find_no_collision(x, 1.0)

        def connect_to_mux(pin, direction, min_x):
            pin_name = pin.name
            pin_number = int(pin_name[4:-1])

            mid_y = pin.uy() + self.line_end_space + (pin_number % 3)*self.m2_pitch
            self.add_rect("metal2", offset=pin.ul(), height=mid_y - pin.uy())
            if direction == "left":
                x_offset = find_left(pin.cx())
                self.add_rect("metal2", offset=vector(x_offset, mid_y), width=pin.rx() - x_offset)
            else:
                x_offset = find_right(max(pin.cx(), min_x))
                self.add_rect("metal2", offset=vector(pin.lx(), mid_y), width=x_offset - pin.lx())
            self.add_contact(contact.m2m3.layer_stack, offset=vector(x_offset, mid_y))

            mux_sel_pin = self.col_mux_array_inst.get_pin(pin.name)
            self.add_rect("metal3", offset=vector(x_offset, mid_y), height=mux_sel_pin.uy() - mid_y)



            # find closest middle cell

            cell_width = self.bitcell.width
            for j in range(self.num_cols):
                if not j % 2**self.col_addr_size == pin_number:  # match pin index to m2 sel location
                    continue
                mid_cell = self.bitcell_offsets[j] + 0.5*cell_width
                if mid_cell > x_offset:
                    break
            # extend m3 to closest mid_cell
            self.add_rect("metal3", offset=vector(x_offset, mux_sel_pin.by()), width=mid_cell - x_offset)
            self.add_contact_center(contact.m2m3.layer_stack, offset=vector(mid_cell, mux_sel_pin.cy()), rotate=90)
            return mid_cell

        sel_pins = list(map(self.column_decoder_inst.get_pin,
                            ["sel[{}]".format(i) for i in range(2**self.col_addr_size)]))
        if self.col_addr_size == 1:
            connect_to_mux(sel_pins[0], "left", 0.0)
            connect_to_mux(sel_pins[1], "right", 0.0)
        else:
            min_x = 0
            for pin in reversed(sel_pins):
                min_x = connect_to_mux(pin, "left", min_x)
                min_x += 0.5*contact.m2m3.second_layer_height + self.line_end_space





    def route_msf_address(self):
        """ Routing the row address lines from the address ms-flop array to the row-decoder  """

        # Create the address input pins
        for i in range(self.addr_size):
            msf_din_pin = self.msf_address_inst.get_pin("din[{}]".format(i))
            self.add_layout_pin(text="ADDR[{}]".format(i),
                                layer="metal4",
                                offset=msf_din_pin.lr(),
                                width=self.right_edge - msf_din_pin.rx())


        for i in range(self.row_addr_size):

            # Connect the ff outputs to the rails
            dout_pos = self.msf_address_inst.get_pin("dout[{}]".format(i)).rc()
            rail_pos = vector(self.central_line_xoffset["A[{}]".format(i)], dout_pos.y)
            self.add_path("metal1",[dout_pos, rail_pos])
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=dout_pos,
                                rotate=90)
            contact_pos = vector(rail_pos.x, dout_pos.y+0.5*self.m2_width-0.5*contact.m2m3.second_layer_height)
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=contact_pos)

        # clk to msf address
        control_signal = self.prefix + "clk_buf"
        pin = self.msf_address_inst.get_pin("clk")
        control_pos = vector(self.central_line_xoffset[control_signal], pin.cy())
        self.add_rect("metal1", height=pin.height(), width=control_pos.x - pin.rx(),
                      offset=pin.lr())
        self.add_via_center(layers=("metal1", "via1", "metal2"),
                            offset=control_pos,
                            rotate=0)

        # Connect address FF gnd
        for gnd_pin in self.msf_address_inst.get_pins("gnd"):
            if gnd_pin.layer != "metal1":
                continue
            self.route_gnd_from_left(gnd_pin)

            
        # Connect address FF vdd
        for vdd_pin in self.msf_address_inst.get_pins("vdd"):
            if vdd_pin.layer != "metal1":
                continue
            self.add_rect("metal1", height=vdd_pin.height(),
                          width=vdd_pin.lx()-self.left_vdd_x_offset,
                          offset=vector(self.left_vdd_x_offset, vdd_pin.by()))


    def add_lvs_correspondence_points(self):
        """ This adds some points for easier debugging if LVS goes wrong. 
        These should probably be turned off by default though, since extraction
        will show these as ports in the extracted netlist.
        """
        # Add the wordline names
        for i in range(self.num_rows):
            wl_name = "wl[{}]".format(i)
            wl_pin = self.bitcell_array_inst.get_pin(wl_name)
            self.add_label(text=wl_name,
                           layer="metal1",  
                           offset=wl_pin.ll())
        
        # Add the bitline names
        for i in range(self.num_cols):
            bl_name = "bl[{}]".format(i)
            br_name = "br[{}]".format(i)
            bl_pin = self.bitcell_array_inst.get_pin(bl_name)
            br_pin = self.bitcell_array_inst.get_pin(br_name)
            self.add_label(text=bl_name,
                           layer="metal2",  
                           offset=bl_pin.ll())
            self.add_label(text=br_name,
                           layer="metal2",  
                           offset=br_pin.ll())

        # Add the data input names to the data flop output
        for i in range(self.word_size):
            dout_name = "dout[{}]".format(i)
            dout_pin = self.msf_data_in_inst.get_pin(dout_name)
            self.add_label(text="data_in[{}]".format(i),
                           layer="metal2",  
                           offset=dout_pin.ll())

        # Add the data output names to the sense amp output     
        for i in range(self.word_size):
            data_name = "data[{}]".format(i)
            data_pin = self.sense_amp_array_inst.get_pin(data_name)
            self.add_label(text="data_out[{}]".format(i),
                           layer="metal3",  
                           offset=data_pin.ll())
            
            
    def route_control_lines(self):
        """ Route the control lines of the entire bank """
        
        # Make a list of tuples that we will connect.
        # From control signal to the module pin 
        # Connection from the central bus to the main control block crosses
        # pre-decoder and this connection is in metal3
        # add offsets away from rails when necessary. These spaces should be tuned based on manually layout out cells
        connection = []
        connection.append((self.prefix+"clk_bar", self.msf_data_in_inst.get_pin("clk"), self.line_end_space))
        connection.append((self.prefix+"tri_en_bar", self.tri_gate_array_inst.get_pin("en_bar"), 0.0))
        connection.append((self.prefix+"tri_en", self.tri_gate_array_inst.get_pin("en"), 0.0))
        connection.append((self.prefix+"clk_bar", self.precharge_array_inst.get_pin("en"), 0.0))
        connection.append((self.prefix+"w_en", self.write_driver_array_inst.get_pin("en"), -self.line_end_space))
        connection.append((self.prefix+"s_en", self.sense_amp_array_inst.get_pin("en"), 0.0))

        for (control_signal, pin, via_offset) in connection:
            if pin.layer == "metal2":
                via_pos = vector(pin.lx()-self.line_end_space+0.5*contact.m1m2.second_layer_height, pin.by())
                self.add_contact(contact.contact.m1m2_layers, offset=via_pos, rotate=90)
                self.add_rect("metal2", offset=via_pos, width=pin.lx()-via_pos.x)
                pin_pos = vector(via_pos.x, pin.cy())
            else:
                pin_pos = pin.lc()

            control_pos = vector(self.central_line_xoffset[control_signal], pin.cy())
            self.add_path("metal1", [control_pos, pin_pos])

            x_offset = control_pos.x-0.5*contact.m1m2.width

            if via_offset > 0.0:
                y_offset = control_pos.y - 0.5*self.m1_width
            else:
                y_offset = control_pos.y + via_offset + 0.5*self.m1_width
            self.add_rect("metal1", offset=vector(x_offset, y_offset), width=contact.m1m2.width, height=abs(via_offset))
            control_pos.y = control_pos.y + via_offset


            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=control_pos)

        # route clk above decoder
        en_pin = self.wordline_driver_inst.get_pin("en")
        control_signal = self.prefix+"clk_buf"
        pin_pos = en_pin.uc()

        # prevent clash with precharge en pin
        precharge_en = self.precharge_array_inst.get_pin("en")
        mid_pos_y = precharge_en.uy() + self.line_end_space + contact.m1m2.first_layer_height

        mid_pos = vector(en_pin.cx(), mid_pos_y)

        control_x_offset = self.central_line_xoffset[control_signal]
        control_pos = vector(control_x_offset + 0.5*self.m1_width, mid_pos.y)
        self.add_wire(("metal1","via1","metal2"),[pin_pos, mid_pos, control_pos])
        control_via_pos = vector(control_x_offset, mid_pos.y)
        self.add_via_center(layers=("metal1", "via1", "metal2"),
                            offset=control_via_pos)

        # route clk below decoder
        via_x = self.start_of_left_central_bus - self.parallel_line_space - 0.5 * contact.m1m2.first_layer_width
        bottom_wordline = self.wordline_driver_inst.by()
        self.add_rect("metal2", offset=vector(en_pin.lx(), bottom_wordline), height=en_pin.by() - bottom_wordline)
        self.add_rect("metal2", offset=vector(en_pin.lx(), bottom_wordline), width=via_x - en_pin.lx())

        if self.col_mux_array_inst is not None:
            via_y = (self.col_mux_array_inst.get_pin("gnd").by() - 0.5 * self.wordline_driver.rail_height -
                     self.line_end_space - 0.5 * contact.m1m2.first_layer_height)
        else:
            via_y = (bottom_wordline - 0.5 * self.wordline_driver.rail_height - self.line_end_space -
                     0.5 * contact.m1m2.first_layer_height)

        self.add_contact_center(layers=contact.contact.m1m2_layers, offset=vector(via_x, via_y))
        self.add_rect("metal2", offset=vector(via_x-0.5*self.m2_width, via_y),
                      height=bottom_wordline-via_y+self.m2_width)
        self.add_rect("metal1", offset=vector(via_x, via_y - 0.5 * self.m1_width),
                      width=control_x_offset + 0.5 * self.m1_width - via_x)

        self.add_contact_center(layers=contact.contact.m1m2_layers, offset=vector(control_x_offset, via_y))

    def get_collisions(self):
        collisions = []

        addr_in_pin_names = list(map("ADDR[{}]".format, range(self.addr_size)))

        addr_in_pins = sorted(map(self.get_pin, addr_in_pin_names), key=lambda x: x.by())

        collisions.append((addr_in_pins[0].by(), addr_in_pins[-1].uy()))

        if self.column_decoder_inst is not None:
            addr_out_pin_names = map("dout[{}]".format, range(self.row_addr_size))
            addr_out_pins = sorted(map(self.column_decoder_inst.get_pin, addr_out_pin_names), key=lambda x: x.by())
            collisions.append((addr_out_pins[0].by(), addr_out_pins[-1].uy()))

        control_pins = sorted(map(self.get_pin, self.input_control_signals + ["bank_sel"]), key=lambda x: x.by())
        collisions.append((control_pins[0].by(), control_pins[-1].uy()))
        return collisions

    def calculate_rail_vias(self):
        """Calculates positions of power grid rail to M1/M2 vias. Avoids internal metal3 control pins"""
        # need to avoid the metal3 control signals

        via_positions = []

        self.m1mtop = m1mtop = ContactFullStack.m1mtop()
        self.add_mod(m1mtop)
        self.m2mtop = m2mtop = ContactFullStack.m2mtop()
        self.add_mod(m2mtop)

        self.bottom_power_layer = power_grid_layers[0]
        self.top_power_layer = power_grid_layers[1]

        self.grid_rail_height = grid_rail_height = max(m1mtop.first_layer_height, m2mtop.first_layer_height)
        self.grid_rail_width = m1mtop.second_layer_width

        grid_space = drc["power_grid_space"]
        grid_pitch = grid_space + grid_rail_height
        via_space = self.wide_m1_space

        bank_top = self.min_point + self.height

        collisions = list(sorted(self.get_collisions() +
                                 [(self.min_point, self.min_point + 2*self.wide_m1_space),
                                  (bank_top - grid_pitch, bank_top)],
                                 key=lambda x: x[0]))

        # combine/collapse overlapping collisions
        while True:
            i = 0
            num_overlaps = 0
            num_iterations = len(collisions)
            new_collisions = []
            while i < num_iterations:

                collision = collisions[i]
                if i < num_iterations - 1:
                    next_collision = collisions[i + 1]
                    if next_collision[0] <= collision[1]:
                        collision = (collision[0], max(collision[1], next_collision[1]))
                        num_overlaps += 1
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
                new_collisions.append(collision)
            collisions = new_collisions
            if num_overlaps == 0:
                break

        # calculate via positions
        for i in range(len(collisions)-1):
            collision = collisions[i]
            current_y = collision[1] + self.wide_m1_space
            next_collision = collisions[i+1][0]
            while True:
                via_top = current_y + grid_rail_height
                if via_top > bank_top or via_top + via_space > next_collision:
                    break
                via_positions.append(current_y)
                current_y += grid_pitch

        self.power_grid_vias = via_positions

    def route_vdd_supply(self):
        """ Route vdd for the precharge, sense amp, write_driver, data FF, tristate """
        # add vertical rails
        self.vdd_grid_vias = self.power_grid_vias[1::2]
        self.vdd_grid_rects = []

        vdd_x_offsets = [self.left_vdd_x_offset, self.right_vdd_x_offset]
        mirrors = ["R0", "MY"]
        mirror_shifts = [0.0, self.vdd_rail_width-self.m1mtop.second_layer_width]
        via_mirror_shifts = [0.0, self.vdd_rail_width]
        for i in range(len(vdd_x_offsets)):
            vdd_x_offset = vdd_x_offsets[i]
            offset = vector(vdd_x_offset, self.min_point)
            self.add_layout_pin(text="vdd",
                                layer="metal1",
                                offset=offset,
                                width=self.vdd_rail_width,
                                height=self.height)
            m9_x_offset = vdd_x_offset + mirror_shifts[i]
            self.add_layout_pin("vdd",
                                layer=self.top_power_layer,
                                offset=vector(m9_x_offset, self.min_point),
                                width=self.grid_rail_width,
                                height=self.height)
            for via_y in self.vdd_grid_vias:
                self.add_inst(self.m1mtop.name, self.m1mtop,
                              offset=vector(vdd_x_offset + via_mirror_shifts[i], via_y),
                              mirror=mirrors[i])
                self.connect_inst([])


        for via_y in self.vdd_grid_vias:
            self.vdd_grid_rects.append(self.add_rect(self.bottom_power_layer, offset=vector(self.left_vdd_x_offset, via_y),
                          height=self.grid_rail_height,
                          width=self.right_vdd_x_offset-self.left_vdd_x_offset))



        for inst in [self.precharge_array_inst, self.sense_amp_array_inst,
                     self.write_driver_array_inst, self.msf_data_in_inst,
                     self.tri_gate_array_inst, self.bank_gate_inst, self.column_decoder_inst]:
            if inst is None:
                continue
            for vdd_pin in inst.get_pins("vdd"):
                self.add_rect(layer="metal1", 
                              offset=vdd_pin.lr(),
                              width=self.right_vdd_x_offset - vdd_pin.rx(),
                              height=vdd_pin.height())

    def route_gnd_supply(self):
        """ Route gnd for the precharge, sense amp, write_driver, data FF, tristate """
        # add vertical rail

        offset = vector(self.gnd_x_offset, self.min_point)
        self.add_layout_pin(text="gnd",
                            layer="metal2",
                            offset=offset,
                            width=self.gnd_rail_width,
                            height=self.height)

        # add grid
        self.gnd_grid_vias = self.power_grid_vias[0::2]
        self.gnd_grid_rects = []
        rect_x_offset = self.gnd_x_offset + 0.5*(self.gnd_rail_width - self.grid_rail_width)
        self.add_layout_pin("gnd", self.top_power_layer,
                      offset=vector(rect_x_offset, self.min_point),
                      width=self.grid_rail_width,
                      height=self.height)

        via_x_offset = self.gnd_x_offset + 0.5*self.gnd_rail_width
        for via_y in self.gnd_grid_vias:
            self.gnd_grid_rects.append(self.add_inst(self.m2mtop.name, self.m2mtop,
                          offset=vector(via_x_offset, via_y)))
            self.connect_inst([])

        # precharge is connected by abutment
        layers=("metal1", "via1", "metal2")
        contact_size = [2, 1]
        # make dummy contact for measurements
        dummy_contact = contact.contact(layer_stack=layers, dimensions=contact_size)
        contact_width = dummy_contact.first_layer_width + dummy_contact.first_layer_vertical_enclosure
        decoder_gnds = self.row_decoder_inst.get_pins("gnd")
        gnd_modules = [ self.tri_gate_array_inst, self.sense_amp_array_inst, self.msf_data_in_inst,
                      self.write_driver_array_inst, self.bank_gate_inst, self.column_decoder_inst]
        if self.col_mux_array_inst is not None:
            gnd_modules.append(self.col_mux_array_inst)
        for inst in gnd_modules:
            if inst is None:
                continue
            for gnd_pin in inst.get_pins("gnd"):
                if gnd_pin.layer != "metal1":
                    continue
                # route to the right hand side of the big rail to reduce via overlaps
                # avoid clashing with row decoder gnds
                # assumes height of this pin is about the same height as the others
                clash = False
                via_space = drc["parallel_via_space"]
                for decoder_gnd in decoder_gnds:
                    slightly_above = gnd_pin.uy() + via_space > decoder_gnd.by() > gnd_pin.by()  # decoder_gnd is above
                    slightly_below = gnd_pin.by() - via_space < decoder_gnd.uy() < gnd_pin.uy()  # decoder_gnd is below
                    if slightly_above or slightly_below:
                        clash = True
                        break


                pin_pos = gnd_pin.ll()
                gnd_offset = vector(self.gnd_x_offset+self.gnd_rail_width-contact_width, pin_pos.y)
                self.add_rect("metal1", gnd_offset, width=pin_pos.x-gnd_offset.x, height=gnd_pin.height())
                contact_offset = gnd_offset
                if not clash:
                    self.add_via(layers=layers,
                                 offset=contact_offset,
                                 size=contact_size,
                                 rotate=0)
                else:
                    # connect with M1 to the via location
                    height = max(abs(decoder_gnd.uy() - gnd_pin.by()), abs(gnd_pin.uy()-decoder_gnd.by()))
                    width = self.double_via_width
                    if slightly_below:
                        y_offset = decoder_gnd.by()
                    else:
                        y_offset = gnd_pin.by()
                    self.add_rect("metal1", offset=vector(self.gnd_x_offset, y_offset), width=width, height=height)

    def route_gnd_from_left(self, pin):
        layers = ("metal1", "via1", "metal2")
        contact_size = [2, 1]
        # make dummy contact for measurements
        dummy_contact = contact.contact(layer_stack=layers, dimensions=contact_size)
        self.double_via_width = dummy_contact.first_layer_width
        rect_width = self.gnd_x_offset + self.double_via_width - pin.rx()
        self.add_rect("metal1", offset=pin.lr(), height=pin.height(), width=rect_width)
        contact_offset = vector(self.gnd_x_offset, pin.by())
        self.add_via(layers=layers, offset=contact_offset, size=contact_size)

    def add_control_pins(self):
        """ Add the control signal input pins """

        for ctrl in self.control_signals:
            x_offset = self.central_line_xoffset[ctrl]
            self.add_label_pin(text=ctrl,
                               layer="metal2",
                               offset=vector(x_offset - 0.5 * self.m2_width, self.min_point),
                               width=self.m2_width,
                               height=self.height)

    def connect_rail_from_right(self,inst, pin, rail):
        """ Helper routine to connect an unrotated/mirrored oriented instance to the rails """
        in_pin = inst.get_pin(pin).lc()
        rail_pos = vector(self.rail_1_x_offsets[rail], in_pin.y)
        self.add_wire(("metal3","via2","metal2"),[in_pin, rail_pos, rail_pos - vector(0,self.m2_pitch)])
        # Bring it up to M2 for M2/M3 routing
        self.add_via(layers=("metal1","via1","metal2"),
                     offset=in_pin + contact.m1m2.offset,
                     rotate=90)
        self.add_via(layers=("metal2","via2","metal3"),
                     offset=in_pin + self.m2m3_via_offset,
                     rotate=90)

    def connect_rail_from_left(self,inst, pin, rail):
        """ Helper routine to connect an unrotated/mirrored oriented instance to the rails """
        in_pin = inst.get_pin(pin).rc()
        rail_pos = vector(self.rail_1_x_offsets[rail], in_pin.y)
        self.add_wire(("metal3","via2","metal2"),[in_pin, rail_pos, rail_pos - vector(0,self.m2_pitch)])
        self.add_via(layers=("metal1","via1","metal2"),
                     offset=in_pin + contact.m1m2.offset,
                     rotate=90)
        self.add_via(layers=("metal2","via2","metal3"),
                     offset=in_pin + self.m2m3_via_offset,
                     rotate=90)

    def create_module(self, mod_name, *args, **kwargs):
        mod = getattr(self, 'mod_' + mod_name)(*args, **kwargs)
        self.add_mod(mod)
        return mod
        
    def analytical_delay(self, slew, load):
        """ return  analytical delay of the bank"""
        msf_addr_delay = self.msf_address.analytical_delay(slew, self.decoder.input_load())

        decoder_delay = self.decoder.analytical_delay(msf_addr_delay.slew, self.wordline_driver.input_load())

        word_driver_delay = self.wordline_driver.analytical_delay(decoder_delay.slew, self.bitcell_array.input_load())

        bitcell_array_delay = self.bitcell_array.analytical_delay(word_driver_delay.slew)

        bl_t_data_out_delay = self.sense_amp_array.analytical_delay(bitcell_array_delay.slew,
                                                                    self.bitcell_array.output_load())
        # output load of bitcell_array is set to be only small part of bl for sense amp.

        data_t_DATA_delay = self.tri_gate_array.analytical_delay(bl_t_data_out_delay.slew, load)

        result = decoder_delay + word_driver_delay + bitcell_array_delay + bl_t_data_out_delay + data_t_DATA_delay
        return result
