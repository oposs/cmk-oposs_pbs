"""Metric, graph and perfometer definitions for oposs_pbs."""
from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph, MinimalRange
from cmk.graphing.v1.metrics import (
    Color, DecimalNotation, IECNotation, Metric, TimeNotation, Unit,
)
from cmk.graphing.v1.perfometers import Closed, FocusRange, Perfometer

_BYTES = Unit(IECNotation("B"))
_PCT = Unit(DecimalNotation("%"))
_COUNT = Unit(DecimalNotation(""))
_SECONDS = Unit(TimeNotation())
_FACTOR = Unit(DecimalNotation("x"))

metric_oposs_pbs_datastore_size = Metric(name="oposs_pbs_datastore_size",
    title=Title("Datastore size"), unit=_BYTES, color=Color.GRAY)
metric_oposs_pbs_datastore_used = Metric(name="oposs_pbs_datastore_used",
    title=Title("Datastore used"), unit=_BYTES, color=Color.BLUE)
metric_oposs_pbs_datastore_avail = Metric(name="oposs_pbs_datastore_avail",
    title=Title("Datastore available"), unit=_BYTES, color=Color.GREEN)
metric_oposs_pbs_datastore_used_pct = Metric(name="oposs_pbs_datastore_used_pct",
    title=Title("Datastore usage"), unit=_PCT, color=Color.ORANGE)
metric_oposs_pbs_group_count = Metric(name="oposs_pbs_group_count",
    title=Title("Backup groups"), unit=_COUNT, color=Color.LIGHT_PURPLE)
metric_oposs_pbs_backup_count = Metric(name="oposs_pbs_backup_count",
    title=Title("Backups"), unit=_COUNT, color=Color.LIGHT_BLUE)
metric_oposs_pbs_dedup_factor = Metric(name="oposs_pbs_dedup_factor",
    title=Title("Deduplication factor"), unit=_FACTOR, color=Color.PURPLE)
metric_oposs_pbs_gc_age = Metric(name="oposs_pbs_gc_age",
    title=Title("Time since last GC"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_sync_age = Metric(name="oposs_pbs_sync_age",
    title=Title("Time since last sync"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_verify_age = Metric(name="oposs_pbs_verify_age",
    title=Title("Time since last verification"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_prune_age = Metric(name="oposs_pbs_prune_age",
    title=Title("Time since last prune"), unit=_SECONDS, color=Color.CYAN)
metric_oposs_pbs_backup_age = Metric(name="oposs_pbs_backup_age",
    title=Title("Backup age"), unit=_SECONDS, color=Color.ORANGE)
metric_oposs_pbs_backup_size = Metric(name="oposs_pbs_backup_size",
    title=Title("Protected data size"), unit=_BYTES, color=Color.BLUE)

graph_oposs_pbs_datastore = Graph(
    name="oposs_pbs_datastore", title=Title("Datastore usage"),
    simple_lines=["oposs_pbs_datastore_used", "oposs_pbs_datastore_avail",
                  "oposs_pbs_datastore_size"],
    optional=["oposs_pbs_datastore_avail", "oposs_pbs_datastore_size"])

graph_oposs_pbs_backups = Graph(
    name="oposs_pbs_backups", title=Title("Backups"),
    simple_lines=["oposs_pbs_backup_count", "oposs_pbs_group_count"],
    optional=["oposs_pbs_group_count"])

perfometer_oposs_pbs_usage = Perfometer(
    name="oposs_pbs_datastore_used_pct",
    focus_range=FocusRange(Closed(0), Closed(100)),
    segments=["oposs_pbs_datastore_used_pct"])
