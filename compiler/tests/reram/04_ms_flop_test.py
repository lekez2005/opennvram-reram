from reram_test_base import ReRamTestBase


class MsFlopTest(ReRamTestBase):
    def test_vertical_flop(self):
        cell = self.create_class_from_opts("ms_flop")
        self.local_check(cell)

    def test_horizontal_flop(self):
        cell = self.create_class_from_opts("ms_flop_horz_pitch")
        self.local_check(cell)


MsFlopTest.run_tests(__name__)
