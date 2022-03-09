from typing import TYPE_CHECKING
from importlib import reload

import debug

# TODO decoder temporary glitches are triggering false positives in vector checks
period_base = 50e-12
period_32_rows = 20e-12
setup_time = 10e-12
rise_time = 5e-12

if TYPE_CHECKING:
    from testutils import OpenRamTest
else:
    class OpenRamTest:
        pass


class RowDecoderBase(OpenRamTest):
    def test_row_32(self):
        self.run_for_rows(32)

    def test_row_64(self):
        self.run_for_rows(64)

    def test_row_128(self):
        self.run_for_rows(128)

    def test_row_256(self):
        self.run_for_rows(256)

    def test_row_512(self):
        self.run_for_rows(512)

    def run_for_rows(self, num_rows):
        debug.info(1, "Testing {} row sample for hierarchical_decoder".format(num_rows))
        dut, dut_statement = self.instantiate_dut(num_rows)
        self.local_check(dut)
        # self.run_sim(dut, dut_statement)

    @staticmethod
    def instantiate_dut(num_rows):
        import tech
        from modules.hierarchical_decoder import hierarchical_decoder
        drc_excepts = tech.drc_exceptions

        drc_excepts["hierarchical_decoder"] = (drc_excepts.get("latchup", [])
                                               + drc_excepts.get("min_nwell", []))

        dut = hierarchical_decoder(rows=num_rows)
        a_pins = ' '.join(["A[{}]".format(x) for x in range(dut.num_inputs)])
        decode_pins = ' '.join(["decode[{}]".format(x) for x in range(dut.rows)])

        return dut, "Xdut {} {} vdd gnd {}\n".format(a_pins, decode_pins, dut.name)

    def write_vec_file(self, dut, vdd_value, period):
        num_rows = dut.rows
        vec_file_name = self.temp_file("expect.vec")
        with open(vec_file_name, "w") as vec_file:
            vec_file.write("RADIX {}\n".format(' '.join(["1"] * num_rows)))
            vec_file.write("TUNIT ns\n")
            vec_file.write("VOH {}\n".format(0.5 * vdd_value))
            vec_file.write("VOL {}\n".format(0.5 * vdd_value))
            vec_file.write("IO {}\n".format(' '.join(["O"] * num_rows)))
            vec_file.write("CHECK_WINDOW 0 1p 0\n")
            vec_file.write("VNAME {}\n".format(' '.join(["decode[{}]".format(x) for x in range(num_rows)])))
            # Expected output
            for i in range(num_rows):
                t = (setup_time + (i + 1) * period) * 1e9

                output = [0] * num_rows
                output[i] = 1

                vec_file.write("{:.5g} {}\n".format(t, " ".join(map(str, output))))
        return vec_file_name

    def get_sim_length(self, dut, period):
        sim_length = period * (1 + dut.rows)
        return sim_length

    def run_sim(self, dut, dut_statement):
        import characterizer
        reload(characterizer)
        from characterizer import stimuli

        vdd_value = self.corner[1]

        num_rows = dut.rows
        num_address_bits = dut.num_inputs
        period = (num_rows / 32) * period_32_rows + period_base

        control = ""
        control += "Vdd vdd gnd {}\n".format(vdd_value)
        control += "Vclk clk gnd pulse 0 {0} {1} {2} {2} '0.5*{3}' {3}\n".format(vdd_value, -setup_time,
                                                                                 rise_time, period)

        control += dut_statement
        # Address
        for i in range(num_address_bits):
            control += "VA{0} A[{0}] gnd pulse {1} 0 0 {2} {2} '0.5*{3}' {3}\n".format(i, vdd_value,
                                                                                       rise_time,
                                                                                       (2 ** (i + 1)) * period)

        vec_file_name = self.write_vec_file(dut, vdd_value, period)

        control += ".vec '{}'\n".format(vec_file_name)

        self.stim_file_name = self.temp_file("stim.sp")
        dut_file = self.temp_file("dut.sp")
        dut.sp_write(dut_file)

        with open(self.stim_file_name, "w") as stim_file:
            stim = stimuli(stim_file, corner=self.corner)
            stim.write_include(dut_file)
            stim_file.write(control)
            stim.write_control(self.get_sim_length(dut, period) / 1e-9)

        stim.run_sim()
        with open(self.temp_file("stim_tran.vecerr"), "r") as results_f:
            results = results_f.read()
            if results:
                print(results)
                self.fail("Vector check mismatch for rows {}".format(num_rows))
