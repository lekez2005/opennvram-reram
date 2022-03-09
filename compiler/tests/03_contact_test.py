#!/usr/bin/env python3
"Run a regression test for DRC on basic contacts of different array sizes"

from testutils import OpenRamTest
import debug


class contact_test(OpenRamTest):

    def check_stack(self, layer_stack):
        from base import contact
        stack_name = ":".join(map(str, layer_stack))

        # Check single 1 x 1 contact"
        debug.info(2, "1 x 1 {} test".format(stack_name))
        c = contact.contact(layer_stack, (1, 1))
        self.local_drc_check(c)

        # check vertical array with one in the middle and two ends
        debug.info(2, "1 x 3 {} test".format(stack_name))
        c = contact.contact(layer_stack, (1, 3))
        self.local_drc_check(c)

        # check horizontal array with one in the middle and two ends
        debug.info(2, "3 x 1 {} test".format(stack_name))
        c = contact.contact(layer_stack, (3, 1))
        self.local_drc_check(c)

        # check 3x3 array for all possible neighbors
        debug.info(2, "3 x 3 {} test".format(stack_name))
        c = contact.contact(layer_stack, (3, 3))
        self.local_drc_check(c)

    def test_poly_contact(self):
        self.check_stack(("poly", "contact", "metal1"))

    def test_m1m2(self):
        self.check_stack(("metal1", "via1", "metal2"))

    def test_full_stack_m1_mtop(self):
        from base.contact_full_stack import ContactFullStack
        m1mtop = ContactFullStack.m1mtop()
        self.local_drc_check(m1mtop)

    def test_full_stack_m2_mtop(self):
        from base.contact_full_stack import ContactFullStack
        m2mtop = ContactFullStack.m2mtop()
        self.local_drc_check(m2mtop)

    def test_full_stack_m1_m_second_top(self):
        from base.contact_full_stack import ContactFullStack
        m1mtop = ContactFullStack(start_layer=0, stop_layer=-2, centralize=False, dimensions=[1, 2])
        self.local_drc_check(m1mtop)

    def test_full_stack_m1_m2(self):
        from base.contact_full_stack import ContactFullStack
        m1mtop = ContactFullStack(start_layer=0, stop_layer=1, centralize=False, dimensions=[1, 5])
        self.local_drc_check(m1mtop)


OpenRamTest.run_tests(__name__)
