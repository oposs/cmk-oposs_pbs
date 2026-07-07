def test_stub_imports():
    from cmk.agent_based.v2 import State, Result, check_levels
    results = list(check_levels(95.0, levels_upper=("fixed", (80.0, 90.0)),
                               metric_name="x", label="CPU"))
    assert results[0].state is State.CRIT
    assert results[1].name == "x" and results[1].value == 95.0
