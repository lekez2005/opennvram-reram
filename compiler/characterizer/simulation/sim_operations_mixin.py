import os
from random import randint

import numpy as np

from base import utils
from characterizer.stimuli import stimuli
from characterizer.net_probes.sram_probe import SramProbe
from globals import OPTS

SpiceCharacterizer = utils.run_time_mixin()
if not SpiceCharacterizer:
    from characterizer.simulation.spice_characterizer import SpiceCharacterizer

LH = "LH"
HL = "HL"
FALL = "FALL"
RISE = "RISE"
CROSS = "CROSS"


class SimOperationsMixin(SpiceCharacterizer):

    def create_dut(self):
        dut = stimuli(self.sf, self.corner)
        dut.words_per_row = self.words_per_row
        return dut

    def create_probe(self):
        self.probe = SramProbe(self.sram, OPTS.pex_spice)

    def get_delay_probe_cols(self):
        # probe these cols
        if OPTS.verbose_save:
            return list(range(0, self.sram.bank.num_cols, OPTS.words_per_row))
        else:
            # mix even and odd cols
            points = 5
            bits = np.linspace(0, self.word_size - 1, points)
            cols = []
            for i in range(points):
                bit = int(bits[i])
                if i == points - 1:
                    bit = self.word_size - 1
                elif not bit % 2 == i % 2:
                    bit -= 1
                bits[i] = bit
                col = bit * OPTS.words_per_row
                cols.append(col)
            return cols

    def get_energy_probe_cols(self):
        return [self.sram.bank.num_cols - 1]

    def probe_energy_addresses(self):
        OPTS.spectre_save = "selected"
        self.all_addresses = [0]

        OPTS.probe_cols = OPTS.probe_bits = []

        self.probe_all_addresses(self.all_addresses, self.get_energy_probe_cols())

        if not OPTS.verbose_save:
            # minimize saved data to make simulation faster
            self.probe.current_probes = ["vvdd"]
            self.probe.voltage_probes = {}
            self.probe.probe_labels = {"vdd", "Csb", "Web"}
            self.dout_probes = SpiceCharacterizer.mask_probes = {}

    def probe_delay_addresses(self):
        self.dummy_address = 1
        self.all_addresses = [0, self.sram.num_words - 1]
        self.probe_all_addresses(self.all_addresses + [self.dummy_address],
                                 self.get_delay_probe_cols())

    def probe_all_addresses(self, all_addresses, probe_cols):
        self.trim_address = all_addresses[0]
        probe_cols = [int(x / OPTS.words_per_row) * OPTS.words_per_row for x in probe_cols]

        OPTS.probe_cols = list(sorted(set(probe_cols)))
        OPTS.probe_bits = [int(x / self.sram.words_per_row) for x in OPTS.probe_cols]

        for i in range(self.sram.num_banks):
            self.probe.probe_bank(i)
        for address in all_addresses:
            self.probe.probe_address(address)
            self.probe.probe_address_currents(address)

    def run_pex_and_extract(self):
        self.run_drc_lvs_pex()

        self.probe.extract_probes()

        self.state_probes = self.probe.state_probes
        self.decoder_probes = self.probe.decoder_probes
        self.dout_probes = self.probe.dout_probes
        self.mask_probes = self.probe.mask_probes

    def write_delay_stimulus(self):
        self.create_probe()
        self.probe_delay_addresses()
        self.run_pex_and_extract()
        self.write_stimulus(self.generate_delay_steps)

    def write_power_stimulus(self):
        self.create_probe()
        self.probe_energy_addresses()
        self.run_pex_and_extract()
        self.write_stimulus(self.generate_energy_steps)

    def write_stimulus(self, simulation_steps_func):
        """ Override super class method to use internal logic for pwl voltages and measurement setup
        Assumes set_stimulus_params has been called to define the addresses and nodes
         Creates a stimulus file for simulations to probe a bitcell at a given clock period.
        Address and bit were previously set with set_stimulus_params().
        """

        self.prepare_netlist()

        # creates and opens stimulus file for writing
        self.current_time = 0
        if not getattr(self, "sf", None):
            temp_stim = os.path.join(OPTS.openram_temp, "stim.sp")
            self.sf = open(temp_stim, "w")
        if OPTS.spice_name == "spectre":
            self.sf.write("{} \n".format(self.sram.name))
            self.sf.write("simulator lang=spice\n")
        else:
            self.sf.write(f"{self.sram.name}\n")

        area = self.sram.width * self.sram.height
        self.sf.write(f"* Delay stimulus for read period = {self.read_period}n,"
                      f" write period = {self.write_period}n load={self.load}fF"
                      f" slew={self.slew}ns Area={area:.0f}um2 \n\n")

        if not getattr(self, "stim", None):
            self.stim = self.create_dut()
        else:
            self.stim.sf = self.sf

        self.write_generic_stimulus()

        self.initialize_output()

        simulation_steps_func()

        self.finalize_sim_file()

        self.initialize_sram()

        self.sf.close()

    def get_saved_nodes(self):
        return list(sorted(list(self.probe.saved_nodes) +
                           list(self.dout_probes.values()) +
                           list(self.probe.data_in_probes.values()) +
                           list(self.mask_probes.values())))

    def finalize_sim_file(self):
        self.saved_nodes = self.get_saved_nodes()

        self.saved_currents = self.probe.current_probes

        for node in self.saved_nodes:
            self.sf.write(".probe tran V({0}) \n".format(node))
        # self.sf.write(".probe tran v(*)\n")
        self.sf.write(".probe tran v(vdd)\n")
        self.sf.write(".probe tran I(vvdd)\n")

        for node in self.saved_currents:
            self.sf.write(".probe tran I1({0}) \n".format(node))

        self.finalize_output()

        # include files in stimulus file
        self.stim.write_include(self.trim_sp_file)

        # run until the end of the cycle time
        # Note run till at least one half cycle, this is because operations blend into each other
        self.stim.write_control(self.current_time + self.duty_cycle * self.period)

        self.save_sim_config()

        self.sf.close()

    def normalize_test_data(self, address, bank=None, dummy_address=None, data=None, mask=None):
        if bank is not None:
            address = self.offset_address_by_bank(address, bank)

        bank, _, row, col_index = self.probe.decode_address(address)

        if dummy_address is None:
            dummy_address = 1 if not address == 1 else 2
        dummy_address = self.offset_address_by_bank(dummy_address, bank)

        self.sf.write("* -- Address Test: Addr, Row, Col, bank, time, per_r, per_w, duty_r, duty_w \n")
        self.sf.write("* [{0}, {1}, {2}, {3}, {4}, {5}, {6}, {7}, {8}]\n".
                      format(address, row, col_index, bank, self.current_time, self.read_period,
                             self.write_period, self.read_duty_cycle, self.write_duty_cycle))

        if mask is None:
            mask = [1] * self.word_size
        if data is None:
            data = [1, 0] * int(self.word_size / 2)

        data_bar = [int(not x) for x in data]
        return address, bank, dummy_address, data, mask, data_bar

    def test_address(self, address, bank=None, dummy_address=None, data=None, mask=None):
        test_data = self.normalize_test_data(address, bank, dummy_address, data, mask)
        address, bank, dummy_address, data, mask, data_bar = test_data

        # initial read to charge up nodes
        self.read_address(address)

        self.setup_write_measurements(address)
        self.write_address(address, data_bar, mask)

        self.setup_read_measurements(address)
        self.read_address(address)

        self.setup_write_measurements(address)
        self.write_address(address, data, mask)

        # write data_bar to force transition on the data bus
        self.write_address(dummy_address, data_bar, mask)

        self.setup_read_measurements(address)
        self.read_address(address)

    def generate_delay_steps(self):
        addresses = self.all_addresses
        for i in range(len(addresses)):
            self.test_address(addresses[i])

    def generate_energy_steps(self):
        if OPTS.use_pex:
            decoder_clk = self.probe.extract_from_pex("decoder_clk")
        else:
            decoder_clk = "Xsram.decoder_clk"
        self.probe.saved_nodes.add(decoder_clk)
        self.sf.write(f"*-- decoder_clk = {decoder_clk}\n")

        num_sims = OPTS.energy
        for i in range(num_sims):
            op = self.generate_energy_op(i)

            self.sf.write("* -- {}: t = {:.5g} period = {}\n".
                          format(op.upper(), self.current_time - self.period,
                                 self.period))
        self.current_time += 2 * self.period  # to cool off from previous event
        self.period = max(self.read_period, self.write_period)
        self.chip_enable = 0
        self.update_output()

        self.generate_leakage_energy()

    def generate_energy_op(self, op_index):
        mask = [1] * self.word_size
        address = randint(0, self.sram.num_words - 1)
        ops = ["read", "write"]
        op = ops[op_index % 2]
        if op == "read":
            self.read_address(address)
        else:
            data = [randint(0, 1) for _ in range(self.word_size)]
            self.write_address(address, data, mask)
        return op

    def generate_leakage_energy(self):
        # clock gating
        leakage_cycles = 10000
        start_time = self.current_time
        end_time = leakage_cycles * self.read_period + start_time
        self.current_time = end_time

        self.sf.write("* -- LEAKAGE start = {:.5g} end = {:.5g}\n".format(start_time,
                                                                          self.current_time))

    def read_address(self, addr):
        """Read an address. Address is binary vector"""
        addr_v = self.convert_address(addr)

        self.command_comments.append("* [{: >20}] read {}\n".format(self.current_time, addr_v))

        self.address = list(reversed(addr_v))

        # Needed signals
        self.chip_enable = 1
        self.read = 1

        self.acc_en = 1
        self.acc_en_inv = 0

        self.duty_cycle = self.read_duty_cycle
        self.period = self.read_period

        self.update_output()

    def write_address(self, addr, data_v, mask_v):
        """Write data to an address. Data can be integer or binary vector. Address is binary vector"""

        addr_v = self.convert_address(addr)

        self.command_comments.append("* [{: >20}] write {}, {}\n".format(self.current_time, addr_v, data_v))

        self.mask = list(reversed(mask_v))
        self.address = list(reversed(addr_v))
        self.data = list(reversed(data_v))

        # Needed signals
        self.chip_enable = 1
        self.read = 0
        self.acc_en = 0
        self.acc_en_inv = 1

        self.period = self.write_period
        self.duty_cycle = self.write_duty_cycle

        self.update_output()

    def get_transition(self, bit, new_val):
        new_bits = self.convert_data(new_val)
        if new_bits[bit] == 0:
            return HL
        else:
            return LH

    def get_slew_trig_targ(self, bit, new_val):
        trig, targ = 0.1 * self.vdd_voltage, 0.9 * self.vdd_voltage
        direction = RISE
        if self.get_transition(bit, new_val) == HL:
            trig, targ = targ, trig
            direction = FALL
        return trig, targ, direction

    def get_time_suffix(self):
        return f"{self.current_time:.3g}".replace('.', '_')

    def log_event(self, event_name, address_int=0, row=0, col_index=0,
                  bank_index=0):
        self.sf.write(f"* -- {event_name} : [{address_int}, {row},"
                      f" {col_index}, {bank_index}, {self.current_time},"
                      f" {self.period}, {self.duty_cycle}]\n")

    def setup_write_measurements(self, address_int):
        self.period = self.write_period
        self.duty_cycle = self.write_duty_cycle
        """new_val is MSB first"""
        bank_index, _, row, col_index = self.probe.decode_address(address_int)
        self.log_event("Write", address_int, row, col_index, bank_index)

        time = self.current_time
        self.generate_power_measurement("WRITE")
        self.setup_decoder_delays()
        time_suffix = self.get_time_suffix()

        # Internal bitcell Q state transition delay
        state_labels = self.state_probes[address_int]
        clk_buf_probe = self.probe.clk_probes[bank_index]
        for i in range(self.word_size):
            targ_val = 0.5 * self.vdd_voltage
            targ_dir = "CROSS"

            meas_name = "STATE_DELAY_a{}_c{}_t{}".format(address_int, i, time_suffix)
            self.stim.gen_meas_delay(meas_name=meas_name,
                                     trig_name=clk_buf_probe,
                                     trig_val=0.5 * self.vdd_voltage, trig_dir="FALL",
                                     trig_td=time + self.duty_cycle * self.period,
                                     targ_name=state_labels[i],
                                     targ_val=targ_val, targ_dir=targ_dir,
                                     targ_td=time + self.duty_cycle * self.period)

    def get_decoder_trig_dir(self):
        return RISE

    def setup_decoder_delays(self):
        time_suffix = self.get_time_suffix()
        for address_int, in_nets in self.probe.decoder_inputs_probes.items():
            bank_index, _, row, col_index = self.probe.decode_address(address_int)
            clk_buf_probe = self.probe.clk_probes[bank_index]
            for i in range(len(in_nets)):
                meas_name = "decoder_in{}_{}_t{}".format(address_int, i, time_suffix)
                self.stim.gen_meas_delay(meas_name=meas_name,
                                         trig_name=clk_buf_probe,
                                         trig_val=0.5 * self.vdd_voltage, trig_dir="RISE",
                                         trig_td=self.current_time,
                                         targ_name=in_nets[i],
                                         targ_val=0.5 * self.vdd_voltage, targ_dir="CROSS",
                                         targ_td=self.current_time)

        trig_dir = self.get_decoder_trig_dir()
        for address_int, decoder_label in self.decoder_probes.items():
            bank_index, _, row, col_index = self.probe.decode_address(address_int)
            clk_buf_probe = self.probe.clk_probes[bank_index]
            meas_name = "decoder_a{}_t{}".format(address_int, time_suffix)
            self.stim.gen_meas_delay(meas_name=meas_name,
                                     trig_name=clk_buf_probe,
                                     trig_val=0.5 * self.vdd_voltage, trig_dir=trig_dir,
                                     trig_td=self.current_time,
                                     targ_name=decoder_label,
                                     targ_val=0.5 * self.vdd_voltage, targ_dir="CROSS",
                                     targ_td=self.current_time)

    def setup_precharge_measurement(self, bank, col_index):
        time = self.current_time
        # power measurement
        time_suffix = self.get_time_suffix()
        trig_val = 0.1 * self.vdd_voltage
        targ_val = 0.9 * self.vdd_voltage
        half_word = int(0.5 * self.word_size)
        for i in range(self.word_size):
            col = col_index + i * self.words_per_row
            if self.two_bank_dependent and i >= half_word:
                bank_col = col - half_word * self.words_per_row
                bank_ = bank + 1
            else:
                bank_ = bank
                bank_col = col
            clk_buf_probe = self.probe.clk_probes[bank_]
            for bitline in ["bl", "br"]:
                probe = self.probe.voltage_probes[bitline][bank_][bank_col]
                meas_name = "PRECHARGE_DELAY_{}_c{}_t{}".format(bitline, col, time_suffix)
                self.stim.gen_meas_delay(meas_name=meas_name,
                                         trig_name=clk_buf_probe,
                                         trig_val=trig_val, trig_dir="RISE",
                                         trig_td=time,
                                         targ_name=probe, targ_val=targ_val, targ_dir="RISE",
                                         targ_td=time)

    def generate_power_measurement(self, op_name):
        time = self.current_time
        meas_name = f"{op_name}_POWER_t{self.get_time_suffix()}"
        self.stim.gen_meas_power(meas_name=meas_name,
                                 t_initial=time - self.setup_time,
                                 t_final=time + self.period - self.setup_time)

    def setup_read_measurements(self, address_int, expected_data=None):
        """new_val is MSB first"""
        self.period = self.read_period
        self.duty_cycle = self.read_duty_cycle

        bank_index, _, row, col_index = self.probe.decode_address(address_int)
        clk_buf_probe = self.probe.clk_probes[bank_index]

        self.log_event("Read", address_int, row, col_index, bank_index)

        self.setup_precharge_measurement(bank_index, col_index)
        self.generate_power_measurement("READ")

        time = self.current_time
        time_suffix = self.get_time_suffix()
        # decoder delay
        self.setup_decoder_delays()

        # Data bus transition delay
        for i in range(self.word_size):
            mid_vdd = 0.5 * self.vdd_voltage

            meas_name = "READ_DELAY_a{}_c{}_t{}".format(address_int, i, time_suffix)
            self.stim.gen_meas_delay(meas_name=meas_name,
                                     trig_name=clk_buf_probe,
                                     trig_val=mid_vdd, trig_dir="FALL",
                                     trig_td=time + self.duty_cycle * self.period,
                                     targ_name=self.dout_probes[i], targ_val=mid_vdd,
                                     targ_dir="CROSS",
                                     targ_td=time + self.duty_cycle * self.period)

            if self.measure_slew and expected_data is not None:
                slew_name = "READ_SLEW_a{}_c{}_t{}".format(address_int, i, time_suffix)
                trig, targ, direction = self.get_slew_trig_targ(i, expected_data)
                time = self.current_time + self.duty_cycle * self.period
                self.stim.gen_meas_delay(meas_name=slew_name,
                                         trig_name=self.dout_probes[i], trig_val=trig,
                                         trig_dir=direction,
                                         trig_td=time,
                                         targ_name=self.dout_probes[i],
                                         targ_val=targ, targ_dir=direction,
                                         targ_td=time)

    def setup_power_measurement(self, action, transition, address_int):
        """Write Power measurement command
        action is READ or WRITE, transition is HL or LH
        """
        if transition == LH:
            value = 1
        else:
            value = 0
        meas_name = "{}{}_POWER_a{}".format(action, value, address_int)
        self.stim.gen_meas_power(meas_name=meas_name,
                                 t_initial=self.current_time - self.setup_time,
                                 t_final=self.current_time + self.period - self.setup_time)
