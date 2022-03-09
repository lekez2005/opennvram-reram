"""
This file generates simple spice cards for simulation.  There are
various functions that can be be used to generate stimulus for other
simulations as well.
"""

import os

import numpy as np

import debug
import tech
from base import utils
from globals import OPTS

class stimuli:
    """ Class for providing stimuli functions """

    def __init__(self, stim_file, corner):
        self.vdd_name = tech.spice["vdd_name"]
        self.gnd_name = tech.spice["gnd_name"]
        self.pmos_name = tech.spice["pmos"]
        self.nmos_name = tech.spice["nmos"]
        self.tx_width = tech.spice["minwidth_tx"]
        self.tx_length = tech.spice["channel"]
        self.tx_prefix = tech.spice["tx_instance_prefix"]

        self.sf = stim_file

        (self.process, self.voltage, self.temperature) = corner
        # try simulation specific model, otherwise, use 'fet_models'
        self.device_models = tech.spice.get("fet_models_" + OPTS.spice_name,
                                            tech.spice["fet_models"])[self.process]
        stim_file.write("* OpenRAM Simulation \n")

    def inst_sram(self, abits, dbits, sram_name):
        """ Function to instatiate an SRAM subckt. """
        self.sf.write("Xsram ")
        for i in range(dbits):
            self.sf.write("D[{0}] ".format(i))
        for i in range(abits):
            self.sf.write("A[{0}] ".format(i))
        for i in tech.spice["control_signals"]:
            self.sf.write("{0} ".format(i))
        self.sf.write("{0} ".format(tech.spice["clk"]))
        self.sf.write("{0} {1} ".format(self.vdd_name, self.gnd_name))
        self.sf.write("{0}\n".format(sram_name))

    @staticmethod
    def get_sram_pin_replacements(sram):
        return [("ADDR[", "A["),
                ("DATA[", "D["), ("DATA_1[", "D["),
                ("MASK_1[", "MASK[")]

    def instantiate_sram(self, sram):
        replacements = self.get_sram_pin_replacements(sram)
        connections = " ".join(sram.bank.connections_from_mod(sram.pins, replacements))
        self.sf.write(f"Xsram {connections} {sram.name} \n")

    def inst_model(self, pins, model_name):
        """ Function to instantiate a generic model with a set of pins """
        self.sf.write("X{0} ".format(model_name))
        for pin in pins:
            self.sf.write("{0} ".format(pin))
        self.sf.write("{0}\n".format(model_name))

    def create_inverter(self, size=1, beta=2.5):
        """ Generates inverter for the top level signals (only for sim purposes) """
        self.sf.write(".SUBCKT test_inv in out {0} {1}\n".format(self.vdd_name, self.gnd_name))
        self.sf.write("mpinv out in {0} {0} {1} w={2}u l={3}u\n".format(self.vdd_name,
                                                                        self.pmos_name,
                                                                        beta * size * self.tx_width,
                                                                        self.tx_length))
        self.sf.write("mninv out in {0} {0} {1} w={2}u l={3}u\n".format(self.gnd_name,
                                                                        self.nmos_name,
                                                                        size * self.tx_width,
                                                                        self.tx_length))
        self.sf.write(".ENDS test_inv\n")

    def create_buffer(self, buffer_name, size=[1, 3], beta=2.5):
        """
            Generates buffer for top level signals (only for sim
            purposes). Size is pair for PMOS, NMOS width multiple. 
            """

        self.sf.write(".SUBCKT test_{2} in out {0} {1}\n".format(self.vdd_name,
                                                                 self.gnd_name,
                                                                 buffer_name))
        self.sf.write("mpinv1 out_inv in {0} {0} {1} w={2}u l={3}u\n".format(self.vdd_name,
                                                                             self.pmos_name,
                                                                             beta * size[0] * self.tx_width,
                                                                             self.tx_length))
        self.sf.write("mninv1 out_inv in {0} {0} {1} w={2}u l={3}u\n".format(self.gnd_name,
                                                                             self.nmos_name,
                                                                             size[0] * self.tx_width,
                                                                             self.tx_length))
        self.sf.write("mpinv2 out out_inv {0} {0} {1} w={2}u l={3}u\n".format(self.vdd_name,
                                                                              self.pmos_name,
                                                                              beta * size[1] * self.tx_width,
                                                                              self.tx_length))
        self.sf.write("mninv2 out out_inv {0} {0} {1} w={2}u l={3}u\n".format(self.gnd_name,
                                                                              self.nmos_name,
                                                                              size[1] * self.tx_width,
                                                                              self.tx_length))
        self.sf.write(".ENDS test_{0}\n\n".format(buffer_name))

    def inst_buffer(self, buffer_name, signal_list):
        """ Adds buffers to each top level signal that is in signal_list (only for sim purposes) """
        for signal in signal_list:
            self.sf.write("X{0}_buffer {0} {0}_buf {1} {2} test_{3}\n".format(signal,
                                                                              "test" + self.vdd_name,
                                                                              "test" + self.gnd_name,
                                                                              buffer_name))

    def inst_inverter(self, signal_list):
        """ Adds inv for each signal that needs its inverted version (only for sim purposes) """
        for signal in signal_list:
            self.sf.write("X{0}_inv {0} {0}_inv {1} {2} test_inv\n".format(signal,
                                                                           "test" + self.vdd_name,
                                                                           "test" + self.gnd_name))

    def inst_accesstx(self, dbits):
        """ Adds transmission gate for inputs to data-bus (only for sim purposes) """
        self.sf.write("* Tx Pin-list: Drain Gate Source Body\n")
        if not tech.spice["scale_tx_parameters"]:
            unit = ""
        else:
            unit = "u"
        for i in range(dbits):
            self.sf.write(f"{self.tx_prefix}p{i} DATA[{i}] acc_en D[{i}] test{self.vdd_name} "
                          f"{self.pmos_name} w={20 * self.tx_width}{unit} l={self.tx_length}{unit}\n")

            self.sf.write(f"{self.tx_prefix}n{i} DATA[{i}] acc_en_inv D[{i}] test{self.gnd_name} "
                          f"{self.nmos_name} w={10 * self.tx_width}{unit} l={self.tx_length}{unit}\n")

    def gen_pulse(self, sig_name, v1, v2, offset, period, t_rise, t_fall):
        """ 
            Generates a periodic signal with 50% duty cycle and slew rates. Period is measured
            from 50% to 50%.
        """
        self.sf.write("* PULSE: period={0}\n".format(period))
        pulse_string = "V{0} {0} 0 PULSE ({1} {2} {3}n {4}n {5}n {6}n {7}n)\n"
        self.sf.write(pulse_string.format(sig_name,
                                          v1,
                                          v2,
                                          offset,
                                          t_rise,
                                          t_fall,
                                          0.5 * period - 0.5 * t_rise - 0.5 * t_fall,
                                          period))

    def gen_pwl(self, sig_name, clk_times, data_values, period, slew, setup):
        """ 
            Generate a PWL stimulus given a signal name and data values at each period.
            Automatically creates slews and ensures each data occurs a setup before the clock
            edge. The first clk_time should be 0 and is the initial time that corresponds
            to the initial value.
        """
        # the initial value is not a clock time
        debug.check(len(clk_times) == len(data_values), "Clock and data value lengths don't match.")

        # shift signal times earlier for setup time
        times = np.array(clk_times) - setup * period
        values = np.array(data_values) * self.voltage
        half_slew = 0.5 * slew
        self.sf.write("* (time, data): {}\n".format(zip(clk_times, data_values)))
        self.sf.write("V{0} {0} 0 PWL (0n {1}v ".format(sig_name, values[0]))
        for i in range(1, len(times)):
            self.sf.write("{0}n {1}v {2}n {3}v ".format(times[i] - half_slew,
                                                        values[i - 1],
                                                        times[i] + half_slew,
                                                        values[i]))
        self.sf.write(")\n")

    def gen_constant(self, sig_name, v_val, gnd_node="0"):
        """ Generates a constant signal with reference voltage and the voltage value """
        self.sf.write("V{0} {0} {1} DC {2}\n".format(sig_name, gnd_node, v_val))

    def get_inverse_voltage(self, value):
        if value > 0.5 * self.voltage:
            return 0
        elif value <= 0.5 * self.voltage:
            return self.voltage
        else:
            debug.error("Invalid value to get an inverse of: {0}".format(value))

    def get_inverse_value(self, value):
        if value > 0.5:
            return 0
        elif value <= 0.5:
            return 1
        else:
            debug.error("Invalid value to get an inverse of: {0}".format(value))

    def gen_meas_delay(self, meas_name, trig_name, targ_name, trig_val, targ_val, trig_dir, targ_dir, trig_td, targ_td):
        """ Creates the .meas statement for the measurement of delay """
        measure_string = ".meas tran {0} TRIG v({1}) VAL={2} {3}=1 TD={4}n TARG v({5}) VAL={6} {7}=1 TD={8}n\n\n"
        self.sf.write(measure_string.format(meas_name,
                                            trig_name,
                                            trig_val,
                                            trig_dir,
                                            trig_td,
                                            targ_name,
                                            targ_val,
                                            targ_dir,
                                            targ_td))

    def gen_meas_power(self, meas_name, t_initial, t_final):
        """ Creates the .meas statement for the measurement of avg power """
        # power mea cmd is different in different spice:
        if OPTS.spice_name == "hspice":
            power_exp = "power"
        else:
            power_exp = "par('(-1*v(" + str(self.vdd_name) + ")*I(v" + str(self.vdd_name) + "))')"
        self.sf.write(".meas tran {0} avg {1} from={2}n to={3}n\n\n".format(meas_name,
                                                                            power_exp,
                                                                            t_initial,
                                                                            t_final))

    def write_control(self, end_time):
        """ Write the control cards to run and end the simulation """
        if OPTS.spice_name == "spectre":
            self.write_control_spectre(end_time)
            return

        if OPTS.spice_name == "ngspice":
            # UIC is needed for ngspice to converge
            self.sf.write(".TRAN 5p {0}n UIC\n".format(end_time))
            # ngspice sometimes has convergence problems if not using gear method
            # which is more accurate, but slower than the default trapezoid method
            # Do not remove this or it may not converge due to some "pa_00" nodes
            # unless you figure out what these are.
            self.sf.write(".OPTIONS POST=1 RUNLVL=4 PROBE method=gear TEMP={}\n".format(self.temperature))
        else:
            self.sf.write(".TRAN 5p {0}n \n".format(end_time))
            self.sf.write(".OPTIONS RUNLVL=4 PROBE MEASFAIL=1 MEASFORM=2\n".format(self.temperature))
            self.sf.write(".TEMP={}\n".format(self.temperature))
            self.sf.write(".OPTION GMIN={0} GMINDC={0}\n".format(tech.spice["gmin"]))
            # only one of POST or PSF should be specified
            # self.sf.write(".OPTION POST=1\n".format(tech.spice["gmin"]))
            self.sf.write(".OPTIONS PSF=1 \n")
            self.sf.write(".OPTIONS HIER_DELIM=1 \n")

        # create plots for all signals
        self.sf.write("* probe is used for hspice/xa, while plot is used in ngspice\n")
        if not OPTS.use_pex:
            if OPTS.debug_level > 1:
                if OPTS.spice_name in ["hspice", "xa"]:
                    self.sf.write(".probe V(*)\n")
                else:
                    self.sf.write(".plot V(*)\n")
            else:
                self.sf.write("*.probe V(*)\n")
                self.sf.write("*.plot V(*)\n")

        # end the stimulus file
        self.sf.write(".end\n\n")

    def write_control_spectre(self, end_time):
        self.sf.write("simulator lang=spectre\n")
        use_ultrasim = OPTS.use_ultrasim
        if use_ultrasim:
            from globals import find_exe
            OPTS.spice_exe = find_exe("ultrasim")
            self.sf.write("""
usim_opt  dc=3
usim_opt  sim_mode={}
usim_opt  speed={}
usim_opt  mt={}
usim_opt  wf_format=psf
usim_opt  postl=1
usim_opt  rcr_fmax=20G
                        """.format(OPTS.ultrasim_mode, OPTS.ultrasim_speed, OPTS.simulator_threads))
            self.sf.write("\ntran tran step={} stop={}n ic={} write=spectre.dc \n".format("5p", end_time,
                                                                                          OPTS.spectre_ic_mode))
            self.sf.write("simulator lang=spice\n")
            self.sf.write(".probe v(*) depth=1 \n")  # save top level signals
        else:
            self.sf.write("simulatorOptions options reltol=1e-3 vabstol=1e-6 iabstol=1e-12 temp={0} try_fast_op=no "
                          "rforce=10m maxnotes=10 maxwarns=10 "
                          " preservenode=all topcheck=fixall "
                          "digits=5 cols=80 dc_pivot_check=yes pivrel=1e-3 {1} "
                          " \n".format(self.temperature, OPTS.spectre_simulator_options))
            if "gmin" in tech.spice:
                self.sf.write("simulatorOptions options gmin={0}\n".
                              format(tech.spice["gmin"]))

            # self.sf.write('dcOp dc write="spectre.dc" readns="spectre.dc" maxiters=150 maxsteps=10000 annotate=status\n')
            tran_options = OPTS.tran_options if hasattr(OPTS, "tran_options") else ""
            self.sf.write('tran tran step={} stop={}n ic={} write=spectre.dc'
                          ' annotate=status maxiters=5 {}\n'.format("5p", end_time,
                                                                    OPTS.spectre_ic_mode,
                                                                    tran_options))
            if OPTS.use_pex:
                nestlvl = 1
            else:
                nestlvl = OPTS.nestlvl if hasattr(OPTS, 'nestlvl') else 2

            spectre_save = getattr(OPTS, "spectre_save", "lvlpub")

            self.sf.write('saveOptions options save={} nestlvl={} pwr=total \n'.format(
                spectre_save, nestlvl))
            # self.sf.write('saveOptions options save=all pwr=total \n')

            self.sf.write("simulator lang=spice\n")

    def write_include(self, circuit):
        """Writes include statements, inputs are lists of model files"""
        includes = self.device_models + [circuit]
        if OPTS.spice_name == "spectre":
            self.sf.write("simulator lang=spectre\n")
            self.sf.write("// {} process corner\n".format(self.process))
            for item in list(includes):
                if len(item) == 2:
                    (item, section) = item
                    section = " section={}".format(section)
                else:
                    section = ""
                if os.path.isfile(item):
                    self.sf.write("include \"{0}\" {1} \n".format(item, section))
                else:
                    debug.error(
                        "Could not find spice model: {0}\nSet SPICE_MODEL_DIR to over-ride path.\n".format(item))

            self.sf.write("\nsimulator lang=spice\n")
        else:
            self.sf.write("* {} process corner\n".format(self.process))
            for item in list(includes):
                if len(item) == 2:
                    (item, corner) = item
                    self.sf.write(".lib \"{0}\" {1} \n".format(item, corner))
                elif os.path.isfile(item):
                    self.sf.write(".include \"{0}\"\n".format(item))
                else:
                    debug.error(
                        "Could not find spice model: {0}\nSet SPICE_MODEL_DIR to over-ride path.\n".format(item))
        # initial condition file
        if hasattr(OPTS, 'ic_file') and os.path.isfile(OPTS.ic_file):
            self.sf.write(".include {}\n".format(OPTS.ic_file))

    def remove_subckt(self, subckt, model_file):
        subckt_start = ".subckt {}".format(subckt)
        subckt_end = ".ends"
        lines = []
        skip_next = False
        with open(model_file, 'r') as f:
            for line in f.readlines():
                if line.lower().startswith(subckt_start):
                    skip_next = True
                elif skip_next:
                    if line.lower().startswith(subckt_end):
                        skip_next = False
                else:
                    lines.append(line)
                    skip_next = False
        with open(model_file, 'w') as f:
            for line in lines:
                f.write(line)

    def write_supply(self):
        """ Writes supply voltage statements """
        self.sf.write("V{0} {0} 0 {1}\n".format(self.vdd_name, self.voltage))
        # self.sf.write("V{0} {0} 0 {1}\n".format(self.gnd_name, 0))
        # This is for the test power supply
        self.sf.write("V{0} {0} 0 {1}\n".format("test" + self.vdd_name, self.voltage))
        self.sf.write("V{0} {0} 0 {1}\n".format("test" + self.gnd_name, 0))

    def run_sim(self):
        """ Run hspice in batch mode and output rawfile to parse. """
        temp_stim = self.sf.name
        import datetime
        start_time = datetime.datetime.now()
        debug.check(OPTS.spice_exe != "", "No spice simulator has been found.")

        if OPTS.spice_name == "xa":
            # Output the xa configurations here. FIXME: Move this to write it once.
            xa_cfg = open(os.path.join(OPTS.openram_temp, "xa.cfg"), "w")
            xa_cfg.write("set_sim_level -level 7\n")
            xa_cfg.write("set_powernet_level 7 -node vdd\n")
            xa_cfg.close()
            cmd = "{0} {1} -c {2}xa.cfg -o {2} -mt {3}".format(OPTS.spice_exe,
                                                               temp_stim,
                                                               os.path.join(OPTS.openram_temp, "xa"),
                                                               OPTS.simulator_threads)
            valid_retcode = 0
        elif OPTS.spice_name == "hspice":
            display_out = "-d" * (OPTS.debug_level > 0)
            cmd = "{0} -mt {1} -hpp -i {2} {3} -o {4}".format(OPTS.spice_exe, OPTS.simulator_threads,
                                                              temp_stim, display_out,
                                                              os.path.join(OPTS.openram_temp, "timing"))
            valid_retcode = 0
        elif OPTS.spice_name == "spectre":
            use_ultrasim = OPTS.use_ultrasim
            if use_ultrasim:
                cmd = "{0} -64 {1} -raw {2}".format(OPTS.spice_exe, temp_stim, OPTS.openram_temp)
            else:
                if hasattr(OPTS, "spectre_command_options"):
                    extra_options = OPTS.spectre_command_options
                else:
                    extra_options = " +aps +mt={} ".format(OPTS.simulator_threads)
                if OPTS.use_pex:
                    # postlayout is more aggressive than +parasitics
                    extra_options += " +dcopt +postlayout "
                    # extra_options += " +dcopt +parasitics=20 "
                cmd = "{0} -64 {1} -format {2} -raw {3} {4} -maxwarnstolog 1000 -maxnotestolog 1000 ".format(OPTS.spice_exe,
                # cmd = "{0} -64 {1} -format {2} -raw {3} +aps {4} ".format(OPTS.spice_exe,
                                                                           temp_stim,
                                                                           OPTS.spectre_format,
                                                                           OPTS.openram_temp,
                                                                           extra_options)
            valid_retcode = 0
        else:
            # ngspice 27+ supports threading with "set num_threads=4" in the stimulus file or a .spiceinit
            cmd = "{0} -b -o {2} {1}".format(OPTS.spice_exe,
                                                       temp_stim,
                                                       os.path.join(OPTS.openram_temp, "timing.lis"))
            # for some reason, ngspice-25 returns 1 when it only has acceptable warnings
            valid_retcode = 1

        retcode = utils.run_command(cmd, stdout_file=os.path.join(OPTS.openram_temp, "spice_stdout.log"),
                                    stderror_file=os.path.join(OPTS.openram_temp, "spice_stderr.log"),
                                    verbose_level=1)

        if retcode > valid_retcode:
            debug.error("Spice simulation error: " + cmd, -1)
        else:
            end_time = datetime.datetime.now()
            delta_time = round((end_time - start_time).total_seconds(), 1)
            debug.info(2, "*** Spice: {} seconds".format(delta_time))
        return retcode
