from base import utils
from globals import OPTS

SpiceCharacterizer = utils.run_time_mixin()
if not SpiceCharacterizer:
    from characterizer.simulation.spice_characterizer import SpiceCharacterizer


class PulseGenMixin(SpiceCharacterizer):
    """
    Helper functions to generate pwl signals
    """

    def write_generic_stimulus(self):
        """ Overrides super class method to use internal logic for measurement setup
        Create the sram instance, supplies, loads, and access transistors. """

        # add vdd/gnd statements
        self.sf.write("\n* Global Power Supplies\n")
        self.stim.write_supply()

        # instantiate the sram
        self.sf.write("\n* Instantiation of the SRAM\n")
        self.stim.instantiate_sram(sram=self.sram)

        self.sf.write("\n* SRAM output loads\n")
        for i in range(self.word_size):
            self.sf.write("CD{0} d[{0}] 0 {1}f\n".format(i, self.load))

        # add access transistors for data-bus
        self.sf.write("\n* Transmission Gates for data-bus and control signals\n")
        self.stim.inst_accesstx(dbits=self.word_size)

    def define_signals(self):
        """Define pwl signals"""
        self.control_sigs = ["web", "acc_en", "acc_en_inv", "csb"]
        self.acc_en = self.prev_acc_en = self.web = self.prev_web = 0
        self.acc_en_inv = self.prev_acc_en_inv = 1
        self.csb = self.prev_csb = 0
        self.web = self.prev_web = 0
        self.read = 1
        self.chip_enable = 1

        self.two_step_pulses = {"clk": 1, "precharge_trig": 1, "sense_trig": 1}
        # ensure pulse in sram pins
        for key in list(self.two_step_pulses.keys()):
            if key not in self.sram.pins:
                del self.two_step_pulses[key]

        self.sense_trig = self.prev_sense_trig = 0
        self.precharge_trig = self.prev_precharge_trig = 0

        # define address, data and mask bus_sigs
        self.bus_sigs = []
        for i in range(self.addr_size):
            self.bus_sigs.append("A[{}]".format(i))
        self.address = self.prev_address = [0] * self.addr_size

        for i in range(self.word_size):
            self.bus_sigs.append("data[{}]".format(i))
        self.data = self.prev_data = [0] * self.word_size

        self.has_masks = self.sram.bank.has_mask_in
        if self.has_masks:
            for i in range(self.word_size):
                self.bus_sigs.append("mask[{}]".format(i))
            self.mask = self.prev_mask = [1] * self.word_size

    def initialize_output(self):
        """initialize pwl signals"""

        for key in self.control_sigs + list(self.two_step_pulses.keys()) + self.bus_sigs:
            self.v_data[key] = "V{0} {0} gnd PWL ( ".format(key)
            self.v_comments[key] = "* (time, data): [ "

        self.current_time = self.setup_time + 0.5 * self.slew
        self.update_output(increment_time=False)
        self.current_time += 2 * self.slew
        # to prevent clashes when initialization period is different from first operation period
        self.current_time += abs(self.read_period * self.read_duty_cycle -
                                 self.write_period * self.write_duty_cycle)

    def finalize_output(self):
        """Complete pwl statements"""
        self.sf.write("\n* Command comments\n")
        for comment in self.command_comments:
            self.sf.write(comment)
        self.sf.write("\n* Generation of control signals\n")
        keys = sorted(self.control_sigs + list(self.two_step_pulses.keys()) + self.bus_sigs)
        for key in keys:
            self.sf.write(self.v_comments[key][:-1] + " ] \n")
            self.sf.write(self.v_data[key] + " )\n")

    def get_setup_time(self, key, prev_val, curr_val):
        if key == "clk":
            if curr_val == 1:
                setup_time = 0
            else:
                setup_time = -self.duty_cycle * self.period
        elif key == "sense_trig":
            trigger_delay = OPTS.sense_trigger_delay
            if prev_val == 0:
                setup_time = -(self.duty_cycle * self.period + trigger_delay)
            else:
                # This adds some delay to enable tri-state driver
                setup_time = -(self.period + self.slew + OPTS.sense_trigger_setup)
        elif key == "precharge_trig":
            trigger_delay = OPTS.precharge_trigger_delay
            if prev_val == 1:
                setup_time = -trigger_delay
            else:
                setup_time = 0
        elif key in ["acc_en", "acc_en_inv"]:  # to prevent contention with tri-state buffer
            setup_time = - getattr(OPTS, "acc_en_setup_time", -0.75 * self.duty_cycle * self.period)
        else:
            setup_time = self.setup_time
        return setup_time

    def write_pwl(self, key, prev_val, curr_val):
        """Append current time's data to pwl. Transitions from the previous value to the new value using the slew"""

        if prev_val == curr_val and self.current_time > 1.5 * self.period:
            return

        setup_time = self.get_setup_time(key, prev_val, curr_val)
        t2 = max(self.slew, self.current_time + 0.5 * self.slew - setup_time)
        t1 = max(0.0, self.current_time - 0.5 * self.slew - setup_time)
        self.v_data[key] += " {0:8.8g}n {1}v {2:8.8g}n {3}v ". \
            format(t1, self.vdd_voltage * prev_val, t2, self.vdd_voltage * curr_val)
        self.v_comments[key] += " ({0}, {1}) ".format(int(self.current_time / self.period),
                                                      curr_val)

    def write_pwl_from_key(self, key):
        curr_val = getattr(self, key)
        prev_val = getattr(self, "prev_" + key)
        self.write_pwl(key, prev_val, curr_val)
        setattr(self, "prev_" + key, curr_val)

    def update_address(self):
        # write address
        for i in range(self.addr_size):
            key = "A[{}]".format(i)
            self.write_pwl(key, self.prev_address[i], self.address[i])
        self.prev_address = self.address

    def update_data(self):
        # write data
        for i in range(self.word_size):
            key = "data[{}]".format(i)
            self.write_pwl(key, self.prev_data[i], self.data[i])
        self.prev_data = self.data

    def update_mask(self):
        # write mask
        if self.sram.bank.has_mask_in:
            for i in range(self.word_size):
                key = "mask[{}]".format(i)
                self.write_pwl(key, self.prev_mask[i], self.mask[i])
            self.prev_mask = self.mask

    def update_control_sigs(self):
        # control signals
        for key in self.control_sigs:
            if key in self.two_step_pulses:
                continue
            self.write_pwl_from_key(key)

    def is_signal_updated(self, key):
        """Determine whether signal should be updated depending on key and current operation"""
        if key == "sense_trig" and not self.read:
            return False
        return True

    def update_two_step_pulses(self, increment_time):
        if not increment_time:
            return
        for key, initial_val in self.two_step_pulses.items():
            if not self.is_signal_updated(key):
                continue
            prev_val = int(not initial_val)
            self.write_pwl(key, prev_val, initial_val)
            self.write_pwl(key, initial_val, prev_val)

    def update_output(self, increment_time=True):
        """Generate voltage at current time for each pwl voltage supply"""
        # bank_sel
        self.csb = not self.chip_enable
        self.web = self.read

        self.update_control_sigs()
        self.update_address()
        self.update_data()
        self.update_mask()
        self.update_two_step_pulses(increment_time)

        self.current_time += self.period
