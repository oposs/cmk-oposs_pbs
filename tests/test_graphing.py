from cmk.graphing.v1.graphs import Graph
from cmk.graphing.v1.metrics import Metric
from cmk.graphing.v1.perfometers import Perfometer
from conftest import load_module

g = load_module("graphing/oposs_pbs.py", "oposs_pbs_graphing")

METRICS = {v.name for k, v in vars(g).items() if k.startswith("metric_")}


def test_key_metrics_defined():
    for var in ("metric_oposs_pbs_datastore_used", "metric_oposs_pbs_dedup_factor",
                "metric_oposs_pbs_backup_age", "metric_oposs_pbs_backup_size",
                "metric_oposs_pbs_backup_count"):
        assert isinstance(getattr(g, var), Metric)


def test_every_metric_name_carries_the_plugin_prefix():
    """Metric names share one site-wide registry with Checkmk's own."""
    for name, obj in vars(g).items():
        if name.startswith(("metric_", "graph_", "perfometer_")):
            assert obj.name.startswith("oposs_pbs_"), name


def test_variable_names_match_metric_names():
    for name, obj in vars(g).items():
        if name.startswith("metric_"):
            assert name == f"metric_{obj.name}"


def test_graphs_and_perfometers_only_use_defined_metrics():
    for name, obj in vars(g).items():
        if isinstance(obj, Graph):
            used = set(obj.simple_lines) | set(obj.optional)
            assert used <= METRICS, name
        elif isinstance(obj, Perfometer):
            assert set(obj.segments) <= METRICS, name
