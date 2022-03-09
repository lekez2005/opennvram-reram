import math

import debug
from base import design
from base import utils
from base.contact import contact
from base.vector import vector
from globals import OPTS
from pgates.pinv import pinv


class delay_chain(design.design):
    """
    Generate a delay chain with the given number of stages and fanout.
    This automatically adds an extra inverter with no load on the input.
    Input is a list contains the electrical effort of each stage.
    """

    def __init__(self, fanout_list, cells_per_row=2, name="delay_chain"):
        """init function"""
        design.design.__init__(self, name)
        # FIXME: input should be logic effort value 
        # and there should be functions to get 
        # area efficient inverter stage list
        self.cells_per_row = int(cells_per_row)

        for f in fanout_list:
            debug.check(f>0,"Must have non-zero fanouts for each stage.")

        # number of inverters including any fanout loads.
        self.fanout_list = fanout_list
        self.num_inverters = 1 + sum(fanout_list)
        self.rows = int(math.ceil(self.num_inverters / float(cells_per_row)))
        
        c = __import__(OPTS.bitcell)
        self.mod_bitcell = getattr(c, OPTS.bitcell)
        self.bitcell = self.mod_bitcell()

        self.add_pins()
        self.create_module()
        self.route_inv()
        self.add_layout_pins()
        self.DRC_LVS()

    def add_pins(self):
        """ Add the pins of the delay chain"""
        self.add_pin("in")
        self.add_pin("out")
        self.add_pin("vdd")
        self.add_pin("gnd")

    def create_module(self):
        """ Add the inverter logical module """

        self.create_inv_list()

        self.inv = pinv()
        self.add_mod(self.inv)

        # half chain length is the width of the layout 
        # invs are stacked into 2 levels so input/output are close
        # extra metal is for the gnd connection U
        self.width = self.cells_per_row * self.inv.width
        self.height = self.rows * self.inv.height

        self.add_inv_list()
        
    def create_inv_list(self):
        """ 
        Generate a list of inverters. Each inverter has a stage
        number and a flag indicating if it is a dummy load. This is 
        the order that they will get placed too.
        """
        # First stage is always 0 and is not a dummy load
        self.inv_list=[[0,False]]
        for stage_num,fanout_size in zip(range(len(self.fanout_list)),self.fanout_list):
            for i in range(fanout_size-1):
                # Add the dummy loads
                self.inv_list.append([stage_num+1, True])
                
            # Add the gate to drive the next stage
            self.inv_list.append([stage_num+1, False])

    def add_inv_list(self):
        """ Add the inverters and connect them based on the stage list """
        dummy_load_counter = 1
        self.inv_inst_list = []
        for i in range(self.num_inverters):
            current_row = 1 + math.floor(i/float(self.cells_per_row)) # row numbers start from 1 to rows
            # First place the gates
            if current_row % 2 == 1:
                col = i % self.cells_per_row
                # add upside down
                inv_offset = vector(col * self.inv.width, self.inv.height * (1+self.rows-current_row))
                inv_mirror="MX"
            else:
                col = self.cells_per_row - (i % self.cells_per_row)
                # add bottom level from right to left
                inv_offset = vector(col * self.inv.width, self.inv.height * (self.rows-current_row))
                inv_mirror="MY"

            cur_inv=self.add_inst(name="dinv{}".format(i),
                                  mod=self.inv,
                                  offset=inv_offset,
                                  mirror=inv_mirror)
            # keep track of the inverter instances so we can use them to get the pins
            self.inv_inst_list.append(cur_inv)

            # Second connect them logically
            cur_stage = self.inv_list[i][0]
            next_stage = self.inv_list[i][0]+1
            if i == 0:
                input = "in"
            else:
                input = "s{}".format(cur_stage)
            if i == self.num_inverters-1:
                output = "out"
            else:                
                output = "s{}".format(next_stage)

            # if the gate is a dummy load don't connect the output
            # else reset the counter
            if self.inv_list[i][1]: 
                output = output+"n{0}".format(dummy_load_counter)
                dummy_load_counter += 1
            else:
                dummy_load_counter = 1
                    
            self.connect_inst(args=[input, output, "vdd", "gnd"])

            if i != 0:
                self.add_via_center(layers=contact.m1m2_layers,
                                    rotate=90,
                                    offset=cur_inv.get_pin("A").center())

    def add_route(self, pin1, pin2, source_inv, dest_inv):
        """ This guarantees that we route from the top to bottom row correctly. """
        pin1_pos = pin1.center()
        pin2_pos = pin2.center()
        if utils.round_to_grid(pin1_pos.y - pin2_pos.y) < self.m1_width:
            self.add_path("metal2", [pin1_pos, pin2_pos])
        else:

            # go to cell edge, then down
            if pin1_pos.x > 0.5*self.width:  # need to go down then right
                mid_x = source_inv.rx() + self.m2_space
            else:
                mid_x = source_inv.lx() - self.m2_space

            self.add_path("metal2", [pin1_pos, vector(mid_x, pin1_pos.y),
                                     vector(mid_x, pin2_pos.y), pin2_pos])

    def route_inv(self):
        """ Add metal routing for each of the fanout stages """
        start_inv = end_inv = 0
        for fanout in self.fanout_list:
            # end inv number depends on the fan out number
            end_inv = start_inv + fanout
            start_inv_inst = self.inv_inst_list[start_inv]
            
            self.add_via_center(layers=("metal1", "via1", "metal2"),
                                offset=start_inv_inst.get_pin("Z").center()),

            # route from output to first load
            start_inv_pin = start_inv_inst.get_pin("Z")
            load_inst = self.inv_inst_list[start_inv+1]
            load_pin = load_inst.get_pin("A")
            self.add_route(start_inv_pin, load_pin, start_inv_inst, load_inst)
            
            next_inv = start_inv+2
            while next_inv <= end_inv:
                prev_load_inst = self.inv_inst_list[next_inv-1]
                prev_load_pin = prev_load_inst.get_pin("A")
                load_inst = self.inv_inst_list[next_inv]
                load_pin = load_inst.get_pin("A")
                self.add_route(prev_load_pin, load_pin, prev_load_inst, load_inst)
                next_inv += 1
            # set the start of next one after current end
            start_inv = end_inv

    def add_layout_pins(self):
        """ Add vdd and gnd rails and the input/output. Connect the gnd rails internally on
        the top end with no input/output to obstruct. """
        num_grounds = 0
        for i in range(self.rows+1):
            offset = vector(0, (self.rows-i)*self.inv.height-0.5*self.inv.rail_height)
            rail_width = self.cells_per_row * self.inv.width
            if i % 2:
                self.add_layout_pin(text="vdd",
                                    layer="metal1",
                                    offset=offset,
                                    width=rail_width,
                                    height=self.inv.rail_height)
            else:
                num_grounds += 1
                self.add_layout_pin(text="gnd",
                                    layer="metal1",
                                    offset=offset,
                                    width=rail_width,
                                    height=self.inv.rail_height)


        
        # input is A pin of first inverter
        a_pin = self.inv_inst_list[0].get_pin("A")
        self.add_layout_pin(text="in",
                            layer="metal1",
                            offset=a_pin.ll(),
                            width=a_pin.width(),
                            height=a_pin.height())


        # output is Z pin of last inverter
        self.output_inv = self.inv_inst_list[-1]
        z_pin = self.output_inv.get_pin("Z")
        self.add_layout_pin(text="out",
                            layer="metal1",
                            offset=z_pin.ll(),
                            width=z_pin.width())
