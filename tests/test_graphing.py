from conftest import load_module
g = load_module("graphing/oposs_pbs.py", "oposs_pbs_graphing")


def test_key_metrics_defined():
    for var in ("metric_oposs_pbs_datastore_used", "metric_oposs_pbs_dedup_factor",
                "metric_oposs_pbs_backup_age", "metric_oposs_pbs_backup_size",
                "metric_oposs_pbs_backup_count"):
        assert hasattr(g, var)
