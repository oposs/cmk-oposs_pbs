from conftest import load_module
rs = load_module("rulesets/oposs_pbs.py", "oposs_pbs_rulesets")


def test_specs_exist_with_matching_names():
    assert rs.rule_spec_special_agent_oposs_pbs.kwargs["name"] == "oposs_pbs"
    assert rs.rule_spec_oposs_pbs_datastore.kwargs["name"] == "oposs_pbs_datastore"
    assert rs.rule_spec_oposs_pbs_job.kwargs["name"] == "oposs_pbs_job"
    assert rs.rule_spec_oposs_pbs_backup.kwargs["name"] == "oposs_pbs_backup"


def test_agent_form_has_required_elements():
    form = rs._agent_form()  # returns Dictionary recorder
    elements = form.kwargs["elements"]
    for key in ("token_id", "token_secret", "verify_tls", "piggyback_template"):
        assert key in elements
