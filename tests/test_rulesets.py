from conftest import load_module
rs = load_module("rulesets/oposs_pbs.py", "oposs_pbs_rulesets")


def test_specs_exist_with_matching_names():
    assert rs.rule_spec_special_agent_oposs_pbs.kwargs["name"] == "oposs_pbs"
    assert rs.rule_spec_oposs_pbs_datastore.kwargs["name"] == "oposs_pbs_datastore"
    assert rs.rule_spec_oposs_pbs_job.kwargs["name"] == "oposs_pbs_job"
    assert rs.rule_spec_oposs_pbs_backup.kwargs["name"] == "oposs_pbs_backup"
    assert rs.rule_spec_oposs_pbs_server.kwargs["name"] == "oposs_pbs_server"


def test_piggyback_template_defaults_to_guest():
    piggy = rs._agent_form().kwargs["elements"]["piggyback_template"]
    # DictElement(parameter_form=String(prefill=DefaultValue("{guest}")))
    prefill = piggy.kwargs["parameter_form"].kwargs["prefill"]
    assert prefill.args[0] == "{guest}"


def test_agent_form_has_required_elements():
    form = rs._agent_form()  # returns Dictionary recorder
    elements = form.kwargs["elements"]
    for key in ("token_id", "token_secret", "verify_tls", "piggyback_template"):
        assert key in elements
