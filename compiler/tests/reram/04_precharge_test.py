from reram_test_base import ReRamTestBase


class PrechargeTest(ReRamTestBase):
    def test_precharge_cell(self):
        from globals import OPTS
        cell = self.create_class_from_opts("precharge", size=OPTS.precharge_size)
        self.local_check(cell)

    def test_precharge_array(self):
        from globals import OPTS
        cell = self.create_class_from_opts("precharge_array", columns=16,
                                           size=OPTS.precharge_size)
        self.local_check(cell)


PrechargeTest.run_tests(__name__)
