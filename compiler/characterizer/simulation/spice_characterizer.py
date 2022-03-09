import os
import shutil

import debug
import tech
from characterizer import charutils as ch
from characterizer.simulation.pulse_gen_mixin import PulseGenMixin
from characterizer.simulation.sim_data_mixin import SimDataMixin
from characterizer.simulation.sim_operations_mixin import SimOperationsMixin
from characterizer.trim_spice import trim_spice
from globals import OPTS


class SpiceCharacterizer(SimDataMixin, PulseGenMixin, SimOperationsMixin):
    """Functions to measure the delay and power of an SRAM at a given address and
    data bit.

    In general, this will perform the following actions:
    1) Trim the netlist to remove unnecessary logic.
    2) Find a feasible clock period using max load/slew on the trimmed netlist.
    3) Characterize all loads/slews and consider fail when delay is greater than 5% of feasible delay using trimmed netlist.
    4) Measure the leakage during the last cycle of the trimmed netlist when there is no operation.
    5) Measure the leakage of the whole netlist (untrimmed) in each corner.
    6) Subtract the trimmed leakage and add the untrimmed leakage to the power.

    Netlist trimming can be removed by setting OPTS.trim_netlist to
    False, but this is VERY slow.

    """

    def __init__(self, sram, spfile, corner, initialize=True):
        # sram params
        self.sram = sram
        self.name = sram.name
        self.word_size = self.sram.word_size
        self.addr_size = self.sram.addr_size
        self.num_cols = self.sram.num_cols
        self.words_per_row = self.sram.words_per_row
        self.num_rows = self.sram.num_rows
        self.num_banks = self.sram.num_banks
        self.two_bank_dependent = not OPTS.independent_banks and self.sram.num_banks == 2
        self.sp_file = spfile

        # These are the member variables for a simulation
        self.current_time = 0
        self.period = 0
        self.measure_slew = False
        self.set_load_slew(0, 0)
        self.set_corner(corner)

        self.v_data = {}  # saves PWL command for each voltage source
        self.v_comments = {}
        self.saved_nodes = set()
        self.command_comments = []

        self.define_signals()

        if initialize:
            self.initialize_output()

    def set_corner(self, corner):
        """ Set the corner values """
        self.corner = corner
        (self.process, self.vdd_voltage, self.temperature) = corner

    def set_load_slew(self, load, slew):
        """ Set the load and slew """
        self.load = load
        self.slew = slew

    def configure_timing(self, sram):
        if hasattr(OPTS, "configure_timing"):
            timings = OPTS.configure_timing(sram, OPTS)
            first_read, first_write, second_read, second_write = timings
            write_period = first_write + second_write
            write_duty = first_write / write_period
            read_period = first_read + second_read
            read_duty = first_read / read_period
        else:
            if hasattr(OPTS, 'feasible_period'):
                feasible_period = OPTS.period
            else:
                feasible_period = float(tech.spice["feasible_period"])
            write_period = getattr(OPTS, "write_period", feasible_period)
            read_period = getattr(OPTS, "read_period", feasible_period)
            write_duty = getattr(OPTS, "write_duty", 0.5)
            read_duty = getattr(OPTS, "read_duty", 0.5)
        self.write_period = write_period
        self.write_duty_cycle = write_duty
        self.read_period = read_period
        self.read_duty_cycle = read_duty
        self.period = self.read_period
        self.duty_cycle = self.read_duty_cycle
        self.slew = OPTS.slew_rate

        self.setup_time = OPTS.setup_time

    def prepare_netlist(self):
        """ Prepare a trimmed netlist and regular netlist. """

        # Set up to trim the netlist here if that is enabled
        if OPTS.use_pex:
            self.trim_sp_file = OPTS.pex_spice
        elif OPTS.trim_netlist:
            self.trim_sp_file = os.path.join(OPTS.openram_temp, "reduced.sp")
            self.trimsp = trim_spice(self.sp_file, self.trim_sp_file)
            self.trimsp.set_configuration(self.num_banks,
                                          self.num_rows,
                                          self.num_cols,
                                          self.word_size)
            trim_address = "".join(map(str, self.convert_address(self.trim_address)))
            trim_data = getattr(self, "trim_data", self.sram.word_size - 1)
            self.trimsp.trim(trim_address, trim_data)
        else:
            # The non-reduced netlist file when it is disabled
            self.trim_sp_file = os.path.join(OPTS.openram_temp, "sram.sp")

        # The non-reduced netlist file for power simulation
        self.sim_sp_file = os.path.join(OPTS.openram_temp, "sram.sp")
        # Make a copy in temp for debugging
        shutil.copy(self.sp_file, self.sim_sp_file)

        self.replace_spice_models(self.sim_sp_file)

    def find_feasible_period(self):
        """
        Uses an initial period and finds a feasible period before we
        run the binary search algorithm to find min period. We check if
        the given clock period is valid and if it's not, we continue to
        double the period until we find a valid period to use as a
        starting point. 
        """

        feasible_period = float(tech.spice["feasible_period"])
        time_out = 8
        while True:
            debug.info(1, "Trying feasible period: {0}ns".format(feasible_period))
            time_out -= 1

            if time_out <= 0:
                debug.error("Timed out, could not find a feasible period.", 2)
            self.period = feasible_period
            (success, results) = self.run_delay_simulation()
            if not success:
                feasible_period = 2 * feasible_period
                continue
            feasible_delay_lh = results["delay_lh"]
            feasible_slew_lh = results["slew_lh"]
            feasible_delay_hl = results["delay_hl"]
            feasible_slew_hl = results["slew_hl"]

            debug.info(1, f"Found feasible_period: {feasible_period}ns feasible_delay "
                          f"{feasible_delay_lh}ns/{feasible_delay_hl}ns"
                          f" slew {feasible_slew_lh}ns/{feasible_slew_hl}ns")
            self.period = feasible_period
            return feasible_delay_lh, feasible_delay_hl

    def run_delay_simulation(self):
        """
        This tries to simulate a period and checks if the result works. If
        so, it returns True and the delays, slews, and powers.  It
        works on the trimmed netlist by default, so powers do not
        include leakage of all cells.
        """

        # Checking from not data_value to data_value
        self.write_delay_stimulus()
        self.stim.run_sim()
        delay_hl = ch.parse_output("timing", ".*delay_hl.*")
        delay_lh = ch.parse_output("timing", ".*delay_lh.*")
        slew_hl = ch.parse_output("timing", ".*slew_hl.*")
        slew_lh = ch.parse_output("timing", ".*slew_lh.*")
        delays = (delay_hl, delay_lh, slew_hl, slew_lh)

        read0_power = ch.parse_output("timing", "read0_power.*")
        write0_power = ch.parse_output("timing", "write0_power.*")
        read1_power = ch.parse_output("timing", "read1_power.*")
        write1_power = ch.parse_output("timing", "write1_power.*")

        if not self.check_valid_delays(delays):
            return False, {}

        # For debug, you sometimes want to inspect each simulation.
        # key=raw_input("press return to continue")

        # Scale results to ns and mw, respectively
        result = {"delay_hl": delay_hl * 1e9,
                  "delay_lh": delay_lh * 1e9,
                  "slew_hl": slew_hl * 1e9,
                  "slew_lh": slew_lh * 1e9,
                  "read0_power": read0_power * 1e3,
                  "read1_power": read1_power * 1e3,
                  "write0_power": write0_power * 1e3,
                  "write1_power": write1_power * 1e3}

        # The delay is from the negative edge for our SRAM
        return True, result

    def run_power_simulation(self):
        """ 
        This simulates a disabled SRAM to get the leakage power when it is off.
        
        """
        OPTS.trim_netlist = False
        self.write_power_stimulus()
        self.stim.run_sim()
        leakage_power = ch.parse_output("timing", "leakage_power")
        debug.check(leakage_power != "Failed", "Could not measure leakage power.")

        OPTS.trim_netlist = OPTS.schematic
        self.write_power_stimulus()
        self.stim.run_sim()
        trim_leakage_power = ch.parse_output("timing", "leakage_power")
        debug.check(trim_leakage_power != "Failed", "Could not measure leakage power.")

        # For debug, you sometimes want to inspect each simulation.
        # key=raw_input("press return to continue")
        return leakage_power * 1e3, trim_leakage_power * 1e3

    def check_valid_delays(self, delay_tuple):
        """ Check if the measurements are defined and if they are valid. """

        (delay_hl, delay_lh, slew_hl, slew_lh) = delay_tuple

        message = (f"period {self.period} load {self.load} "
                   f"slew {self.slew}, delay_hl={delay_hl}n delay_lh={delay_lh}ns"
                   f" slew_hl={slew_hl}n slew_lh={slew_lh}n")

        # if it failed or the read was longer than a period
        if (type(delay_hl) != float or type(delay_lh) != float or
                type(slew_lh) != float or type(slew_hl) != float):
            debug.info(2, f"Failed simulation: {message}")
            return False
        # Scale delays to ns (they previously could have not been floats)
        delay_hl *= 1e9
        delay_lh *= 1e9
        slew_hl *= 1e9
        slew_lh *= 1e9
        if (delay_hl > self.period or delay_lh > self.period or
                slew_hl > self.period or slew_lh > self.period):
            debug.info(2, f"Unsuccessful simulation: {message}")
            return False
        else:
            debug.info(2, f"Successful simulation: {message}")
        return True

    def find_min_period(self, feasible_delay_lh, feasible_delay_hl):
        """
        Searches for the smallest period with output delays being within 5% of 
        long period. 
        """

        previous_period = ub_period = self.period
        lb_period = 0.0

        # Binary search algorithm to find the min period (max frequency) of design
        time_out = 25
        while True:
            time_out -= 1
            if time_out <= 0:
                debug.error("Timed out, could not converge on minimum period.", 2)

            target_period = 0.5 * (ub_period + lb_period)
            self.period = target_period
            debug.info(1, "MinPeriod Search: {0}ns (ub: {1} lb: {2})".format(target_period,
                                                                             ub_period,
                                                                             lb_period))

            if self.try_period(feasible_delay_lh, feasible_delay_hl):
                ub_period = target_period
            else:
                lb_period = target_period

            if ch.relative_compare(ub_period, lb_period, error_tolerance=0.05):
                # ub_period is always feasible
                return ub_period

    def try_period(self, feasible_delay_lh, feasible_delay_hl):
        """ 
        This tries to simulate a period and checks if the result
        works. If it does and the delay is within 5% still, it returns True.
        """

        # Checking from not data_value to data_value
        self.write_delay_stimulus()
        self.stim.run_sim()
        delay_hl = ch.parse_output("timing", ".*delay_hl.*")
        delay_lh = ch.parse_output("timing", ".*delay_lh.*")
        slew_hl = ch.parse_output("timing", ".*slew_hl.*")
        slew_lh = ch.parse_output("timing", ".*slew_lh.*")
        # if it failed or the read was longer than a period
        if (type(delay_hl) != float or type(delay_lh) != float or
                type(slew_lh) != float or type(slew_hl) != float):
            debug.info(2, f"Invalid measures: Period {self.period}, delay_hl={delay_hl}ns,"
                          f" delay_lh={delay_lh}ns slew_hl={slew_hl}ns"
                          f" slew_lh={slew_lh}ns")
            return False
        delay_hl *= 1e9
        delay_lh *= 1e9
        slew_hl *= 1e9
        slew_lh *= 1e9
        if (delay_hl > self.period or delay_lh > self.period or
                slew_hl > self.period or slew_lh > self.period):
            debug.info(2, f"Too long delay/slew: Period {self.period}, "
                          f"delay_hl={delay_hl}ns, delay_lh={delay_lh}ns "
                          f"slew_hl={slew_hl}ns slew_lh={slew_lh}ns")
            return False
        else:
            if not ch.relative_compare(delay_lh, feasible_delay_lh, error_tolerance=0.05):
                debug.info(2, "Delay too big {0} vs {1}".format(delay_lh, feasible_delay_lh))
                return False
            elif not ch.relative_compare(delay_hl, feasible_delay_hl, error_tolerance=0.05):
                debug.info(2, "Delay too big {0} vs {1}".format(delay_hl, feasible_delay_hl))
                return False

        # key=raw_input("press return to continue")
        debug.info(2, f"Successful period {self.period}, delay_hl={delay_hl}ns,"
                      f" delay_lh={delay_lh}ns slew_hl={slew_hl}ns slew_lh={slew_lh}ns")
        return True

    def analyze(self, slews, loads):
        """
        Main function to characterize an SRAM for a table. Computes both delay and power characterization.
        """
        # 1) Find a feasible period and it's corresponding delays using the trimmed array.
        self.load = max(loads)
        self.slew = max(slews)
        (feasible_delay_lh, feasible_delay_hl) = self.find_feasible_period()
        debug.check(feasible_delay_lh > 0, "Negative delay may not be possible")
        debug.check(feasible_delay_hl > 0, "Negative delay may not be possible")

        # 2) Measure the delay, slew and power for all slew/load pairs.
        # Make a list for each type of measurement to append results to
        char_data = {}
        for m in ["delay_lh", "delay_hl", "slew_lh", "slew_hl", "read0_power",
                  "read1_power", "write0_power", "write1_power", "leakage_power"]:
            char_data[m] = []

        # 2a) Find the leakage power of the trimmmed and  UNtrimmed arrays.
        (full_array_leakage, trim_array_leakage) = self.run_power_simulation()
        char_data["leakage_power"] = full_array_leakage

        for slew in slews:
            for load in loads:
                self.set_load_slew(load, slew)
                # 2c) Find the delay, dynamic power, and leakage power of the trimmed array.
                (success, delay_results) = self.run_delay_simulation()
                debug.check(success, "Couldn't run a simulation. slew={0} load={1}\n".format(self.slew, self.load))
                for k, v in delay_results.items():
                    if "power" in k:
                        # Subtract partial array leakage and add full array leakage for the power measures
                        char_data[k].append(v - trim_array_leakage + full_array_leakage)
                    else:
                        char_data[k].append(v)

        # 3) Finds the minimum period without degrading the delays by X%
        self.set_load_slew(max(loads), max(slews))
        min_period = self.find_min_period(feasible_delay_lh, feasible_delay_hl)
        debug.check(type(min_period) == float, "Couldn't find minimum period.")
        debug.info(1, "Min Period: {0}n with a delay of {1} / {2}".format(min_period, feasible_delay_lh,
                                                                          feasible_delay_hl))

        # 4) Pack up the final measurements
        char_data["min_period"] = ch.round_time(min_period)

        return char_data

    def analytical_delay(self, sram, slews, loads):
        """ Just return the analytical model results for the SRAM. 
        """
        delay_lh = []
        delay_hl = []
        slew_lh = []
        slew_hl = []
        for slew in slews:
            for load in loads:
                self.set_load_slew(load, slew)
                bank_delay = sram.analytical_delay(self.slew, self.load)
                # Convert from ps to ns
                delay_lh.append(bank_delay.SpiceCharacterizer / 1e3)
                delay_hl.append(bank_delay.SpiceCharacterizer / 1e3)
                slew_lh.append(bank_delay.slew / 1e3)
                slew_hl.append(bank_delay.slew / 1e3)

        power = sram.analytical_power(self.process, self.vdd_voltage, self.temperature, load)
        # convert from nW to mW
        power.dynamic /= 1e6
        power.leakage /= 1e6
        debug.info(1, "Dynamic Power: {0} mW".format(power.dynamic))
        debug.info(1, "Leakage Power: {0} mW".format(power.leakage))

        data = {"min_period": 0,
                "delay_lh": delay_lh,
                "delay_hl": delay_hl,
                "slew_lh": slew_lh,
                "slew_hl": slew_hl,
                "read0_power": power.dynamic,
                "read1_power": power.dynamic,
                "write0_power": power.dynamic,
                "write1_power": power.dynamic,
                "leakage_power": power.leakage
                }
        return data
