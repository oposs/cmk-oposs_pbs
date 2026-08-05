"""GUI configuration: special-agent form and check-parameter forms."""
from cmk.rulesets.v1 import Help, Label, Title
from cmk.rulesets.v1.form_specs import (
    BooleanChoice, DefaultValue, DictElement, Dictionary, Integer, LevelsType, List,
    MatchingScope, Password, Percentage, RegularExpression, SimpleLevels, SingleChoice,
    SingleChoiceElement, String, TimeSpan, TimeMagnitude, LevelDirection, validators,
)
from cmk.rulesets.v1.rule_specs import (
    CheckParameters, HostAndItemCondition, HostCondition, SpecialAgent, Topic,
)


def _agent_form() -> Dictionary:
    return Dictionary(
        title=Title("Proxmox Backup Server (REST API)"),
        help_text=Help("Monitor a Proxmox Backup Server via its REST API using an "
                       "API token. No software is installed on the PBS host."),
        elements={
            "token_id": DictElement(required=True, parameter_form=String(
                title=Title("API token ID"),
                help_text=Help("Form: user@realm!tokenname"),
                custom_validate=[validators.LengthInRange(min_value=3)])),
            "token_secret": DictElement(required=True, parameter_form=Password(
                title=Title("API token secret"))),
            "port": DictElement(parameter_form=Integer(
                title=Title("TCP port"), prefill=DefaultValue(8007),
                custom_validate=[validators.NetworkPort()])),
            "verify_tls": DictElement(parameter_form=BooleanChoice(
                title=Title("Verify TLS certificate"),
                label=Label("Verify the PBS server certificate"),
                prefill=DefaultValue(True))),
            "cacert": DictElement(parameter_form=String(
                title=Title("CA certificate file (path on the Checkmk server)"))),
            "datastore_include": DictElement(parameter_form=List(
                title=Title("Only these datastores (regex)"),
                element_template=RegularExpression(
                    title=Title("Pattern"),
                    predefined_help_text=MatchingScope.PREFIX))),
            "datastore_exclude": DictElement(parameter_form=List(
                title=Title("Exclude these datastores (regex)"),
                element_template=RegularExpression(
                    title=Title("Pattern"),
                    predefined_help_text=MatchingScope.PREFIX))),
            "task_limit": DictElement(parameter_form=Integer(
                title=Title("Task list fetch limit"), prefill=DefaultValue(1000))),
            "timeout": DictElement(parameter_form=Integer(
                title=Title("Per-request HTTP timeout"), unit_symbol="s",
                help_text=Help(
                    "Read timeout for a single PBS API request. Enumerating "
                    "snapshots of a large backup group off slow (e.g. USB) "
                    "storage can be slow on the first, cold read; raise this "
                    "if such groups time out. A group that still times out is "
                    "skipped for that run without failing the whole agent."),
                prefill=DefaultValue(60))),
            "refresh_budget": DictElement(parameter_form=Integer(
                title=Title("Snapshot refresh budget per run"), unit_symbol="s",
                help_text=Help(
                    "Wall-clock ceiling on time spent enumerating snapshots per "
                    "run. Once exceeded, the remaining backup groups report their "
                    "last cached values and are refreshed on a later run, so a "
                    "large datastore warms up gradually instead of exceeding the "
                    "datasource timeout. Set 0 for no limit."),
                prefill=DefaultValue(120))),
            "piggyback_template": DictElement(parameter_form=String(
                title=Title("Piggyback host template"),
                help_text=Help(
                    "Placeholders: {guest} {id} {type} {comment}. {guest} is the "
                    "PVE guest name (from the backup's snapshot comment) -- the "
                    "same host name the built-in Proxmox VE agent piggybacks "
                    "under, so the PBS backup service lands on the same host. "
                    "It falls back to the backup-id (VMID) when no guest name is "
                    "present. {id} is the raw backup-id, {type} vm/ct/host, "
                    "{comment} the datastore group comment."),
                prefill=DefaultValue("{guest}"))),
            "piggyback_regex": DictElement(parameter_form=String(
                title=Title("Piggyback host rewrite (PATTERN=REPLACEMENT)"))),
            "no_piggyback": DictElement(parameter_form=List(
                title=Title("Datastores without per-guest piggyback"),
                element_template=String(title=Title("Datastore")))),
            "backup_ignore": DictElement(parameter_form=List(
                title=Title("Ignore these backup groups (regex)"),
                help_text=Help(
                    "Backup groups matching any of these patterns are excluded "
                    "from all backup monitoring: no piggyback service, no entry "
                    "in the 'PBS Backups' roll-up, no missing-guest-name "
                    "complaint. Use it to keep the backups of a decommissioned "
                    "machine without alerting on their growing age. The pattern "
                    "is searched (not anchored) in "
                    "'<datastore>/<namespace>/<type>/<id>' -- with no namespace "
                    "that reads 'store1//vm/105' (note the double slash), with "
                    "one 'store1/tenantA/ct/210'. The datastore's group and "
                    "backup counts still include ignored groups, because the "
                    "data is still on disk. The 'PBS Server' service reports "
                    "how many groups are being ignored."),
                element_template=RegularExpression(
                    title=Title("Pattern"),
                    predefined_help_text=MatchingScope.INFIX))),
        },
    )


rule_spec_special_agent_oposs_pbs = SpecialAgent(
    name="oposs_pbs", title=Title("Proxmox Backup Server (REST API)"),
    topic=Topic.STORAGE, parameter_form=_agent_form)


def _server_form() -> Dictionary:
    return Dictionary(elements={
        "unmapped_state": DictElement(parameter_form=SingleChoice(
            title=Title("State when VM/CT backups have no guest name"),
            help_text=Help(
                "vm/ct backups whose PBS snapshot comment carries no guest name "
                "land on their numeric VMID instead of the guest host. Set the "
                "PVE backup notes-template to {{guestname}} to fix this at the "
                "source; meanwhile this controls how the PBS Server service "
                "reports the gap."),
            elements=[SingleChoiceElement(name="ok", title=Title("OK")),
                      SingleChoiceElement(name="warn", title=Title("WARN")),
                      SingleChoiceElement(name="crit", title=Title("CRIT"))],
            prefill=DefaultValue("warn"))),
    })


rule_spec_oposs_pbs_server = CheckParameters(
    name="oposs_pbs_server", title=Title("PBS server"),
    topic=Topic.STORAGE, parameter_form=_server_form,
    condition=HostCondition())


def _datastore_form() -> Dictionary:
    return Dictionary(elements={
        "usage_levels": DictElement(parameter_form=SimpleLevels(
            title=Title("Datastore usage levels"), level_direction=LevelDirection.UPPER,
            form_spec_template=Percentage(),
            prefill_fixed_levels=DefaultValue((80.0, 90.0)))),
        "gc_age_levels": DictElement(parameter_form=SimpleLevels(
            title=Title("Maximum age since last garbage collection"),
            level_direction=LevelDirection.UPPER,
            form_spec_template=TimeSpan(displayed_magnitudes=[TimeMagnitude.DAY,
                                                              TimeMagnitude.HOUR]),
            prefill_levels_type=DefaultValue(LevelsType.NONE),
            prefill_fixed_levels=DefaultValue((0.0, 0.0)))),
    })


rule_spec_oposs_pbs_datastore = CheckParameters(
    name="oposs_pbs_datastore", title=Title("PBS datastore"),
    topic=Topic.STORAGE, parameter_form=_datastore_form,
    condition=HostAndItemCondition(item_title=Title("Datastore")))


def _job_form() -> Dictionary:
    return Dictionary(elements={
        "age_levels": DictElement(parameter_form=SimpleLevels(
            title=Title("Maximum age since last successful run"),
            level_direction=LevelDirection.UPPER,
            form_spec_template=TimeSpan(displayed_magnitudes=[TimeMagnitude.DAY,
                                                              TimeMagnitude.HOUR]),
            prefill_levels_type=DefaultValue(LevelsType.NONE),
            prefill_fixed_levels=DefaultValue((0.0, 0.0)))),
    })


rule_spec_oposs_pbs_job = CheckParameters(
    name="oposs_pbs_job", title=Title("PBS job (sync/verify/prune)"),
    topic=Topic.STORAGE, parameter_form=_job_form,
    condition=HostAndItemCondition(item_title=Title("Job")))


def _backup_form() -> Dictionary:
    return Dictionary(elements={
        "warn_missed": DictElement(parameter_form=Integer(
            title=Title("WARN after N missed backups"), prefill=DefaultValue(2))),
        "crit_missed": DictElement(parameter_form=Integer(
            title=Title("CRIT after N missed backups"), prefill=DefaultValue(3))),
        "fallback_interval": DictElement(parameter_form=TimeSpan(
            title=Title("Fallback interval when cadence is unknown"),
            displayed_magnitudes=[TimeMagnitude.DAY, TimeMagnitude.HOUR],
            prefill=DefaultValue(86400.0))),
        "unverified_state": DictElement(parameter_form=SingleChoice(
            title=Title("State when newest snapshot is unverified"),
            elements=[SingleChoiceElement(name="ok", title=Title("OK")),
                      SingleChoiceElement(name="warn", title=Title("WARN"))],
            prefill=DefaultValue("ok"))),
    })


rule_spec_oposs_pbs_backup = CheckParameters(
    name="oposs_pbs_backup", title=Title("PBS backup freshness (piggyback)"),
    topic=Topic.STORAGE, parameter_form=_backup_form,
    condition=HostAndItemCondition(item_title=Title("Backup group")))


rule_spec_oposs_pbs_backups = CheckParameters(
    name="oposs_pbs_backups",
    title=Title("PBS backups roll-up (all backups on the PBS host)"),
    topic=Topic.STORAGE, parameter_form=_backup_form,
    condition=HostCondition())
