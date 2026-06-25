from test_reach_app import main
from test_reach_app import case_00, case_08, case_09


def test_main_returns_positive_value():
    assert main() > 0


def test_module_projection_is_stable():
    assert case_00.case_projection_00({"value": 3}) == 33


def test_only_projection_reference_is_not_a_production_root():
    assert case_08.case_projection_08({"value": 2}) == 38


def test_only_class_reference_is_not_a_production_root():
    notebook = case_09.ScenarioNotebook09(4)
    assert notebook.render() == 16
