from cmk.rulesets.v1 import Help
from cmk.rulesets.v1.form_specs import DefaultValue, Dictionary, List, RegularExpression
from cmk.rulesets.v1.rule_specs import CheckParameters, SpecialAgent
from conftest import load_module

rs = load_module("rulesets/oposs_pbs.py", "oposs_pbs_rulesets")


def _text(localizable):
    return localizable.localize(lambda s: s)


def test_specs_exist_with_matching_names():
    assert isinstance(rs.rule_spec_special_agent_oposs_pbs, SpecialAgent)
    assert rs.rule_spec_special_agent_oposs_pbs.name == "oposs_pbs"
    assert rs.rule_spec_oposs_pbs_datastore.name == "oposs_pbs_datastore"
    # Sync keeps the legacy name so pre-existing rules keep applying to it.
    assert rs.rule_spec_oposs_pbs_sync_job.name == "oposs_pbs_job"
    assert rs.rule_spec_oposs_pbs_verify_job.name == "oposs_pbs_verify_job"
    assert rs.rule_spec_oposs_pbs_prune_job.name == "oposs_pbs_prune_job"
    assert rs.rule_spec_oposs_pbs_backup.name == "oposs_pbs_backup"
    assert rs.rule_spec_oposs_pbs_server.name == "oposs_pbs_server"
    assert rs.rule_spec_oposs_pbs_backups.name == "oposs_pbs_backups"


def test_every_parameter_form_builds_a_dictionary():
    """The GUI calls parameter_form() when it opens the rule; a form that
    raises there shows an error page instead of the rule editor."""
    for name in dir(rs):
        if name.startswith("rule_spec_"):
            form = getattr(rs, name).parameter_form()
            assert isinstance(form, Dictionary), name
            assert form.elements, name


def test_each_job_kind_has_its_own_age_levels():
    # Sync/verify/prune differ in urgency, so their levels must be separately
    # configurable -- three distinct rulesets, each carrying age_levels.
    for form in (rs._sync_job_form(), rs._verify_job_form(), rs._prune_job_form()):
        assert "age_levels" in form.elements
    helps = {_text(f.elements["age_levels"].parameter_form.help_text)
             for f in (rs._sync_job_form(), rs._verify_job_form(), rs._prune_job_form())}
    assert len(helps) == 3


def test_piggyback_template_defaults_to_guest():
    piggy = rs._agent_form().elements["piggyback_template"]
    prefill = piggy.parameter_form.prefill
    assert isinstance(prefill, DefaultValue)
    assert prefill.value == "{guest}"


def test_agent_form_has_required_elements():
    elements = rs._agent_form().elements
    for key in ("token_id", "token_secret", "verify_tls", "piggyback_template"):
        assert key in elements
    assert elements["token_id"].required and elements["token_secret"].required


def test_agent_form_has_backup_ignore_list_of_regexes():
    elements = rs._agent_form().elements
    assert "backup_ignore" in elements
    lst = elements["backup_ignore"].parameter_form
    assert isinstance(lst, List)
    assert isinstance(lst.element_template, RegularExpression)
    # The match target must be documented in the GUI, including the empty-
    # namespace double-slash form operators will otherwise get wrong.
    assert isinstance(lst.help_text, Help)
    assert "store1//vm/105" in _text(lst.help_text)


def test_check_rulesets_use_the_condition_their_service_needs():
    """A ruleset with the wrong condition type silently never applies."""
    from cmk.rulesets.v1.rule_specs import HostAndItemCondition, HostCondition
    itemless = {"oposs_pbs_server", "oposs_pbs_backups"}
    for name in dir(rs):
        spec = getattr(rs, name)
        if isinstance(spec, CheckParameters):
            want = HostCondition if spec.name in itemless else HostAndItemCondition
            assert isinstance(spec.condition, want), spec.name


def test_every_check_plugin_names_a_ruleset_that_fits_its_defaults():
    """A check_ruleset_name without a rule spec leaves the rule without effect;
    a default the form does not offer cannot be changed in the GUI."""
    from cmk.agent_based.v2 import CheckPlugin
    checks = load_module("agent_based/oposs_pbs.py", "oposs_pbs_checks_rs")
    specs = {spec.name: spec for name, spec in vars(rs).items()
             if isinstance(spec, CheckParameters)}
    plugins = [p for p in vars(checks).values() if isinstance(p, CheckPlugin)]
    assert len(plugins) == 7
    for plugin in plugins:
        spec = specs[plugin.check_ruleset_name]
        assert set(plugin.check_default_parameters) <= set(spec.parameter_form().elements), \
            plugin.name
