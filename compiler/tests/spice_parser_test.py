#!/usr/bin/env python3
import os

from testutils import OpenRamTest

simple_mod = """
.SUBCKT tri_gate in out en en_bar vdd gnd
M_1 net_2 in_inv gnd gnd NMOS_VTG W=180.000000n L=50.000000n
M_2 out en net_2 gnd NMOS_VTG W=180.000000n L=50.000000n
M_3 net_3 in_inv vdd vdd PMOS_VTG W=360.000000n L=50.000000n
M_4 out en_bar net_3 vdd PMOS_VTG W=360.000000n L=50.000000n
M_5 in_inv in vdd vdd PMOS_VTG W=180.000000n L=50.000000n
M_6 in_inv in gnd gnd NMOS_VTG W=90.000000n L=50.000000n
.ENDS
"""
simple_mod_pins = "in out en en_bar vdd gnd".split()

split_lines_mod = """
.SUBCKT tri_gate in out en
+ en_bar vdd gnd
.ENDS
"""

no_ends_mods = """
.SUBCKT tri_gate in out en en_bar vdd gnd
M_1 net_2 in_inv gnd gnd NMOS_VTG W=180.000000n L=50.000000n
.SUBCKT tri_gate2 in out en en_bar vdd gnd
M_1 net_2 in_inv gnd gnd NMOS_VTG W=180.000000n L=50.000000n
"""

hierarchical = """
*master-slave flip-flop with both output and inverted ouput

.SUBCKT dlatch din dout dout_bar clk clk_bar vdd gnd
*clk inverter
mPff1 clk_bar clk vdd vdd PMOS_VTG W=180.0n L=50n m=1
mNff1 clk_bar clk gnd gnd NMOS_VTG W=90n L=50n m=1

*transmission gate 1
mtmP1 din clk int1 vdd PMOS_VTG W=180.0n L=50n m=1
mtmN1 din clk_bar int1 gnd NMOS_VTG W=90n L=50n m=1

*foward inverter
mPff3 dout_bar int1 vdd vdd PMOS_VTG W=180.0n L=50n m=1
mNff3 dout_bar int1 gnd gnd NMOS_VTG W=90n L=50n m=1

*backward inverter
mPff4 dout dout_bar vdd vdd PMOS_VTG W=180.0n L=50n m=1
mNf4 dout dout_bar gnd gnd NMOS_VTG W=90n L=50n m=1

*transmission gate 2
mtmP2 int1 clk_bar dout vdd PMOS_VTG W=180.0n L=50n m=1
mtmN2 int1 clk dout gnd NMOS_VTG W=90n L=50n m=1
.ENDS dlatch

.SUBCKT ms_flop din dout dout_bar clk vdd gnd 
xmaster din mout mout_bar clk clk_bar vdd gnd dlatch
xslave mout_bar dout_bar dout clk_bar clk_nn vdd gnd dlatch
.ENDS flop
"""


class SpiceParserTest(OpenRamTest):

    def test_load_file(self):
        from globals import OPTS
        from base.spice_parser import SpiceParser
        temp_file = os.path.join(OPTS.openram_temp, "sample_spice.sp")
        with open(temp_file, "w") as f:
            f.write(simple_mod)

        self.assertEqual(len(SpiceParser(temp_file).mods), 1, "There should be two modules")

        with open(temp_file, "r") as f:
            self.assertEqual(len(SpiceParser(f).mods), 1, "There should be two modules")

    def test_empty_mod(self):
        from base.spice_parser import SpiceParser
        self.assertEqual(len(SpiceParser("\n").mods), 0, "There should be no module")

    def test_simple_mod(self):
        from base.spice_parser import SpiceParser
        mods = SpiceParser(simple_mod).mods
        self.assertEqual(len(mods), 1, "There should be 1 module")
        mod = mods[0]
        self.assertEqual(mod.name, "tri_gate", "Module name")
        self.assertEqual(mod.pins, simple_mod_pins, "Module pins")
        self.assertTrue(mod.contents[0].startswith("m_1 net_2"))

    def test_no_ends(self):
        from base.spice_parser import SpiceParser
        mods = SpiceParser(no_ends_mods).mods
        self.assertEqual(len(mods), 2, "There should be two modules")
        self.assertEqual(mods[0].name, "tri_gate", "Module name")
        self.assertEqual(mods[1].name, "tri_gate2", "Module name")

    def test_split_lines(self):
        from base.spice_parser import SpiceParser
        mods = SpiceParser(split_lines_mod).mods
        self.assertEqual(len(mods), 1, "There should be one modules")
        self.assertEqual(mods[0].name, "tri_gate")
        self.assertEqual(mods[0].pins, simple_mod_pins)

    def test_module_pins(self):
        from base.spice_parser import SpiceParser
        self.assertEqual(SpiceParser(simple_mod).get_pins("tri_gate"),
                         simple_mod_pins)

    def test_comment_at_end(self):
        from base.spice_parser import SpiceParser
        input_text = ".SUBCKT tri_gate in out en en_bar vdd gnd \n  a b c '3*4' *comment with *"
        mod = SpiceParser(input_text).mods[0]
        self.assertEqual("a b c '3*4'", mod.contents[0])

    def test_single_mod_hierarchy(self):
        from base.spice_parser import SpiceParser
        spice_deck = SpiceParser(simple_mod)
        self.assertEqual(next(spice_deck.deduce_hierarchy_for_pin("en_bar", "tri_gate")),
                         [("g", "M_4 out en_bar net_3 vdd PMOS_VTG W=360.000000n L=50.000000n".lower())])

    def test_module_hierarchy(self):
        from base.spice_parser import SpiceParser
        spice_deck = SpiceParser(hierarchical)
        self.assertEqual(next(spice_deck.deduce_hierarchy_for_pin("dout_bar", "ms_flop")),
                         ["xslave",
                          ("d", "mPff4 dout dout_bar vdd vdd PMOS_VTG W=180.0n L=50n m=1".lower())
                          ])
        self.assertEqual(next(spice_deck.deduce_hierarchy_for_pin("dout", "ms_flop")),
                         ["xslave",
                          ("d", "mPff3 dout_bar int1 vdd vdd PMOS_VTG W=180.0n L=50n m=1".lower())
                          ])

    def test_module_node_hierarchy(self):
        from base.spice_parser import SpiceParser
        # first level
        spice_deck = SpiceParser(simple_mod)
        hierarchy = spice_deck.deduce_hierarchy_for_node("net_2", "tri_gate")
        self.assertEqual(hierarchy[1],
                         [("s", "M_2 out en net_2 gnd NMOS_VTG W=180.000000n L=50.000000n".lower())
                          ])
        # deeper level
        spice_deck = SpiceParser(hierarchical)
        hierarchy = spice_deck.deduce_hierarchy_for_node("xmaster.int1", "ms_flop")
        self.assertEqual(hierarchy[0],
                         ["xmaster",
                          ("s", "mtmP1 din clk int1 vdd PMOS_VTG W=180.0n L=50n m=1".lower())
                          ])

    def test_module_caps(self):
        from base.spice_parser import SpiceParser
        spice_deck = SpiceParser(simple_mod)
        gate_caps = spice_deck.extract_caps_for_pin("in", "tri_gate")
        self.assertAlmostEqual(gate_caps["n"]["g"][0], 90e-9)
        self.assertAlmostEqual(gate_caps["p"]["g"][0], 180e-9)

        drain_caps = spice_deck.extract_caps_for_pin("out", "tri_gate")
        print(drain_caps)
        self.assertAlmostEqual(drain_caps["n"]["d"][0], 180e-9)
        self.assertAlmostEqual(drain_caps["p"]["d"][0], 360e-9)


OpenRamTest.run_tests(__name__)
