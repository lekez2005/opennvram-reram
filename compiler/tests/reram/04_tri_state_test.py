from reram_test_base import ReRamTestBase


class TriStateTest(ReRamTestBase):
    def test_tri_state_cell(self):
        cell = self.create_class_from_opts("tri_gate", size=2)
        self.local_check(cell)

    def test_large_tri_state_cell(self):
        cell = self.create_class_from_opts("tri_gate", size=6)
        self.local_check(cell)


TriStateTest.run_tests(__name__)
