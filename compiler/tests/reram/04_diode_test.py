import os
import sys

from reram_test_base import ReRamTestBase


class DiodeTest(ReRamTestBase):
    def test_p_diode(self):
        cell = self.create_class_from_opts("diode", well_type="pwell", width=0.5, length=1)
        self.local_check(cell)

    def test_n_diode(self):
        cell = self.create_class_from_opts("diode", well_type="nwell", width=0.5, length=1)
        self.local_check(cell)

    def test_multiple_diode(self):
        cell = self.create_class_from_opts("diode", well_type="nwell", width=0.5,
                                           length=1, m=6)
        self.local_check(cell)

    def test_esd_diode(self):
        sys.path.append(os.path.join(os.path.dirname(__file__), "caravel"))
        from caravel_esd_mixin import PadEsdDiode
        esd_diode = PadEsdDiode()
        self.local_check(esd_diode)


DiodeTest.run_tests(__name__)
