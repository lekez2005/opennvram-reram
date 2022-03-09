#!/usr/bin/env python3
"Run a regression test the library cells for DRC"

import os
import re

from testutils import OpenRamTest
import debug
import globals
from globals import OPTS

basic_rules = {
    "metal1_to_metal1": 0.06,
    "metal2_to_metal2": 0.06,
    "metal3_to_metal3": 0.06,
    "metal4_to_metal4": 0.09,
    "parallel_line_space": 0.07,
    "parallel_length_threshold": 0.4,
    "parallel_width_threshold": 0.2,
    "wide_line_space": 0.13,
    "wide_length_threshold": 0.4,
    "wide_width_threshold": 0.4
}

drc = {}


class library_drc_test(OpenRamTest):

    def setUp(self):
        super()
        drc.clear()
        drc.update(basic_rules)

    def reset_drc(self):
        pass

    def test_regular_space(self):
        from base import design
        from base.design import design as cl
        from base.design import METAL1, METAL2, METAL4
        design.drc = drc

        self.assertEqual(cl.get_space_by_width_and_length(METAL1),
                         basic_rules["metal1_to_metal1"], "metal1 no width space specified")

        self.assertEqual(cl.get_space_by_width_and_length(METAL1, 0.2, 0.2, 0.1),
                         basic_rules["metal1_to_metal1"], "metal1 regular width space width")

        self.assertEqual(cl.get_space_by_width_and_length(METAL2),
                         basic_rules["metal2_to_metal2"], "metal2 no width space specified")

        self.assertEqual(cl.get_space_by_width_and_length(METAL4),
                         basic_rules["metal4_to_metal4"], "metal4 no width space specified")

    def test_no_wide_or_parallel_specified(self):
        from base import design
        from base.design import design as cl
        from base.design import METAL1, METAL2, METAL3
        design.drc = drc

        drc.clear()
        drc["metal1_to_metal1"] = 0.1
        drc["metal2_to_metal2"] = 0.1
        drc["metal3_to_metal3"] = 0.3

        # with no dimensions specified
        self.assertEqual(cl.get_space_by_width_and_length(METAL1), 0.1, "metal1 no spec")
        self.assertEqual(cl.get_space_by_width_and_length(METAL2), 0.1, "metal2 no spec")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3), 0.3, "metal3 no spec")

        # with max_width
        self.assertEqual(cl.get_space_by_width_and_length(METAL1, 0.2), 0.1, "metal1 max_width")
        self.assertEqual(cl.get_space_by_width_and_length(METAL2, 0.2), 0.1, "metal2 max_width")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, 0.2), 0.3, "metal3 max_width")

        # with max_width and length
        self.assertEqual(cl.get_space_by_width_and_length(METAL1, 0.2, 0.2, 0.5), 0.1,
                         "metal1 max_width and length")
        self.assertEqual(cl.get_space_by_width_and_length(METAL2, 0.2, 0.2, 0.5), 0.1,
                         "metal2 max_width and length")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, 0.2, 0.2, 0.5), 0.3,
                         "metal3 max_width and length")

    def test_parallel_space(self):
        from base import design
        from base.design import design as cl
        from base.design import METAL1, METAL2, METAL3, METAL4
        design.drc = drc

        self.assertEqual(cl.get_space_by_width_and_length(METAL1, max_width=0.22),
                         basic_rules["parallel_line_space"], "metal1 parallel width space width")

        self.assertEqual(cl.get_space_by_width_and_length(METAL2, max_width=0.22),
                         basic_rules["parallel_line_space"], "metal2 parallel width space width")

        self.assertEqual(cl.get_space_by_width_and_length(METAL3, max_width=0.22),
                         basic_rules["parallel_line_space"], "metal3 parallel width space width")

        self.assertEqual(cl.get_space_by_width_and_length(METAL4, max_width=0.22),
                         basic_rules["metal4_to_metal4"], "metal4 should use its own space since higher")

        # test individual layer space specification
        drc["parallel_line_space_metal3"] = 0.1
        self.assertEqual(cl.get_space_by_width_and_length(METAL2, max_width=0.22),
                         basic_rules["parallel_line_space"], "metal2 should be unchanged")

        self.assertEqual(cl.get_space_by_width_and_length(METAL3, max_width=0.22),
                         0.1, "metal3 should use the specified value")
        self.assertEqual(cl.get_space_by_width_and_length(METAL4, max_width=0.22),
                         0.1, "metal4 should follow metal3 since now higher than 0.09")

        # test individual layer width specification
        drc["parallel_width_threshold_metal3"] = 0.25
        self.assertEqual(cl.get_space_by_width_and_length(METAL2, max_width=0.22),
                         basic_rules["parallel_line_space"], "metal2 should be unchanged")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, max_width=0.22),
                         basic_rules["metal3_to_metal3"], "metal3 use regular space")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, max_width=0.26),
                         drc["parallel_line_space_metal3"], "metal3 use now parallel space")

        # test min length requirement
        self.assertEqual(cl.get_space_by_width_and_length(METAL1, max_width=0.22, run_length=0.5),
                         basic_rules["parallel_line_space"], "metal1 parallel width space width")

        self.assertEqual(cl.get_space_by_width_and_length(METAL1, max_width=0.22, run_length=0.2),
                         basic_rules["metal1_to_metal1"], "metal1 length is below threshold")

    def test_wide_space(self):
        from base import design
        from base.design import design as cl
        from base.design import METAL1, METAL2, METAL3
        design.drc = drc

        self.assertEqual(cl.get_space_by_width_and_length(METAL1, max_width=0.5),
                         basic_rules["wide_line_space"], "metal1 wide width space width")
        drc["wide_width_threshold_metal3"] = 0.6
        drc["wide_line_space_metal3"] = 0.2
        self.assertEqual(cl.get_space_by_width_and_length(METAL2, max_width=0.5),
                         basic_rules["wide_line_space"], "metal2 should be unchanged")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, max_width=0.5),
                         basic_rules["parallel_line_space"], "metal3 use parallel space")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, max_width=0.7),
                         drc["wide_line_space_metal3"], "metal3 use wide space")

    def test_line_end_space(self):
        from base import design
        from base.design import design as cl
        from base.design import METAL1, METAL2, METAL3
        design.drc = drc

        drc["line_end_threshold"] = 0.06
        drc["line_end_space"] = 0.013

        self.assertEqual(cl.get_space_by_width_and_length(METAL1, heights=(0.05, 0.1)),
                         drc["line_end_space"], "metal1 should use line end space")

        self.assertEqual(cl.get_space_by_width_and_length(METAL2, heights=(0.05, 0.04)),
                         drc["line_end_space"], "metal2 should use line end space")

        drc["line_end_threshold_metal2"] = 0.08
        self.assertEqual(cl.get_space_by_width_and_length(METAL1, heights=(0.07, 0.1)),
                         drc["metal1_to_metal1"], "metal1 should use regular space")
        self.assertEqual(cl.get_space_by_width_and_length(METAL2, heights=(0.07, 0.1)),
                         drc["line_end_space"], "metal2 should use line end space")
        self.assertEqual(cl.get_space_by_width_and_length(METAL3, heights=(0.07, 0.1)),
                         drc["line_end_space"], "metal3 should also use line end space")

        self.assertRaises(ValueError, cl.get_space_by_width_and_length, METAL1, heights=0.1)


OpenRamTest.run_tests(__name__)
