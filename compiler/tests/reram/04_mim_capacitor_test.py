from reram_test_base import ReRamTestBase


class MimCapacitorTest(ReRamTestBase):
    def test_mim_cap(self):
        from mim_capacitor import MimCapacitor
        cell = MimCapacitor(width=4, height=5)
        self.local_check(cell)


MimCapacitorTest.run_tests(__name__)
