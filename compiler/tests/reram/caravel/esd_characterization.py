#!/usr/bin/env python3
import argparse
import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from reram_test_base import ReRamTestBase


# diode_cap = 1.36fF * diode_area

data_dir = os.path.join(os.path.dirname(__file__), "diode_data")
parser = argparse.ArgumentParser()

# defaults pulled out of a fancy hat. Tune as appropriate
parser.add_argument("--pad_capacitance", default=100e-15, type=float, help="Pad Capacitance")
parser.add_argument("-d", "--driver_size", default=4, type=float, help="Inverter driver size")
parser.add_argument("--min_diode_size", default=0.2, type=float, help="Minimum diode size")
parser.add_argument("--max_diode_size", default=100, type=float, help="Maximum diode size")
parser.add_argument("-N", "--num_diode_sizes", default=30, type=float, help="Number of diode sizes")
parser.add_argument("--num_segments", default=20, type=int, help="Number of t-line segments")
parser.add_argument("--series_resistance", default=100,
                    type=float, help="Series resistance between diode and wire")
parser.add_argument("--wire_length", default=1000)
parser.add_argument("--wire_width", default=0.56)
parser.add_argument("--wire_layer", default="metal4")
parser.add_argument("--force_pex", action="store_true")
parser.add_argument("--skip_drc_lvs", action="store_true")
parser.add_argument("--sim_length", default=200e-9, type=float)


class EsdCharacterization(ReRamTestBase):
    temp_folder = "esd_characterization"

    @staticmethod
    def prefix(filename):
        from globals import OPTS
        return os.path.join(OPTS.openram_temp, filename)

    def run_pex(self, module):
        import verify
        gds_file = self.prefix(f"{module.name}.gds")
        spice_file = self.prefix(f"{module.name}_schem.spice")
        pex_file = self.prefix(f"{module.name}.pex.sp")

        run_pex = options.force_pex or not os.path.exists(pex_file)
        if not run_pex:
            return pex_file

        module.sp_write(spice_file)
        module.gds_write(gds_file)

        verify.run_pex(module.name, gds_file, spice_file, pex_file, port_spice_file=spice_file,
                       run_drc_lvs=not options.skip_drc_lvs,
                       exception_group=module.__class__.__name__)
        return pex_file

    def create_inverter(self):
        from pgates.pinv import pinv
        from base.analog_cell_mixin import AnalogMixin
        inverter = pinv(size=options.driver_size)
        for pin_name in ["vdd", "gnd"]:
            for pin in inverter.get_pins(pin_name):
                AnalogMixin.add_m1_m3_power_via(inverter, pin, recursive=True)
            inverter.pin_map[pin_name] = [x for x in inverter.pin_map[pin_name]
                                          if x.layer == "metal3"]
        pex_file = self.run_pex(inverter)
        return pex_file, inverter

    def create_transmission_line(self, inverter):
        wire_length = options.wire_length
        wire_width = options.wire_width
        wire_layer = options.wire_layer
        resistance = inverter.get_wire_res(wire_layer=wire_layer, wire_width=wire_width,
                                           wire_length=wire_length)
        res_per_stage = resistance / options.num_segments
        capacitance = inverter.get_wire_cap(wire_layer=wire_layer, wire_width=wire_width,
                                            wire_length=wire_length)
        cap_per_stage = capacitance / options.num_segments
        transmission_line = ""
        for i in range(options.num_segments):
            start_node = f"line_n{i}"
            end_node = f"line_n{i + 1}"
            if i == 0:
                start_node = "driver_out"
            if i == options.num_segments - 1:
                end_node = "tline_out"

            transmission_line += f"R_tline_{i} {start_node} {end_node} {res_per_stage:.4g}\n"
            transmission_line += f"C_tline_{i} {end_node} 0 {cap_per_stage:.4g}\n"
        return transmission_line

    def run_sim(self, inverter_pex, diode_pex, inverter_name, diode_name, transmission_line):
        from characterizer import stimuli
        from characterizer.charutils import get_measurement_file
        from tests.characterizer.characterization_utils import search_meas
        vdd_value = self.corner[1]
        kwargs = {
            "diode_name": diode_name,
            "inverter_name": inverter_name,
            "transmission_line": transmission_line,
            "series_resistance": options.series_resistance,
            "pad_capacitance": options.pad_capacitance,
            "sim_length": options.sim_length,
            "vdd_value": vdd_value,
            "low_vdd": 0.1 * vdd_value,
            "high_vdd": 0.9 * vdd_value
        }
        sim_file = self.prefix("stim.sp")
        with open(sim_file, "w") as stim_file:
            stim = stimuli(stim_file, corner=self.corner)
            stim.write_include(inverter_pex)
            stim_file.write(".include \"{0}\" \n".format(diode_pex))
            stim_file.write(spice_template.format(**kwargs))

        ret_code = stim.run_sim()
        assert ret_code == 0, "Failed simulation"

        meas_file = self.prefix(get_measurement_file())

        rise_time = float(search_meas("rise_time", meas_file))
        fall_time = float(search_meas("fall_time", meas_file))
        return rise_time, fall_time

    @staticmethod
    def get_diode_sizes():
        # min_log = np.log10(options.min_diode_size)
        # max_log = np.log10(options.max_diode_size)
        # diode_sizes = np.logspace(min_log, max_log, options.num_diode_sizes)
        diode_sizes = np.linspace(options.min_diode_size, options.max_diode_size,
                                  options.num_diode_sizes)
        return diode_sizes

    def test_max_frequency(self):
        inverter_pex, inverter = self.create_inverter()
        transmission_line = self.create_transmission_line(inverter)

        frequencies = []
        diode_sizes = self.get_diode_sizes()
        for diode_size in diode_sizes:
            self.debug.info(1, "Characterizing diode size: %.4g", diode_size)
            diode = self.create_class_from_opts("diode", width=diode_size, length=diode_size)
            diode_pex = self.run_pex(diode)
            rise_time, fall_time = self.run_sim(inverter_pex, diode_pex, inverter.name,
                                                diode.name, transmission_line)
            frequency = 1 / max(rise_time, fall_time)
            frequencies.append(frequency * 1e-6)
            self.debug.info(0, "Size = %4.4g Frequency = %4.4g", diode_size, frequency)

        inv_str = f"{options.driver_size:.4g}"
        cap_str = f"{options.pad_capacitance * 1e15:.4g}"
        res_str = f"{options.series_resistance:.4g}"
        file_name = f"driver_{inv_str}-pad_cap_{cap_str}-res_{res_str}"

        np.savetxt(os.path.join(data_dir, file_name + ".txt"),
                   np.array((diode_sizes, frequencies)).transpose())

        import matplotlib.pylab as plt
        plt.plot(diode_sizes, frequencies, "-o")
        plt.grid()
        plt.xlabel("Diode Width and Length (um)")
        plt.ylabel("Max frequency (MHz)")

        plt.title(f"Inverter = {inv_str} Pad cap = {cap_str} fF ESD Res = {res_str}")
        plt.tight_layout()
        plt.savefig(os.path.join(data_dir, file_name + ".png"))
        plt.show()



spice_template = """
Vvdd vdd 0 {vdd_value}
Vvin vin 0 pulse 0 {vdd_value} 0  20ps 20ps '0.5*{sim_length}' '{sim_length}'
Xinverter vin vin_bar vdd gnd {inverter_name}
Xbuffer vin_bar driver_out vdd gnd {inverter_name}
{transmission_line}
Resd tline_out pad {series_resistance}
Cpad pad 0 {pad_capacitance}
Xvdd_diode pad vdd {diode_name}
Xgnd_diode 0 pad {diode_name}

.tran 1p {sim_length}
.measure tran rise_time TRIG v(vin_bar) VAL={high_vdd} FALL=1 TARG v(pad) VAL={low_vdd} RISE=1
.measure tran fall_time TRIG v(vin_bar) VAL={low_vdd} RISE=1 TARG v(pad) VAL={high_vdd} FALL=1
"""

if __name__ == "__main__":
    first_arg = sys.argv[0]
    options, other_args = parser.parse_known_args()
    sys.argv = [first_arg] + other_args
    EsdCharacterization.run_tests(__name__)
