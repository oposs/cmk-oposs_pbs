from conftest import load_module
u = load_module("libexec/oposs_pbs_util.py", "oposs_pbs_util")


def test_median_interval_daily():
    day = 86400
    assert u.median_interval([0, day, 2 * day, 3 * day]) == day
    assert u.median_interval([100]) is None
    assert u.median_interval([]) is None


def test_dedup_factor():
    assert u.dedup_factor(1000.0, 250.0) == 4.0
    assert u.dedup_factor(1000.0, 0) is None
    assert u.dedup_factor(None, 10.0) is None


def test_piggyback_host_template_and_regex():
    grp = {"backup-type": "vm", "backup-id": "100", "comment": "web01"}
    assert u.piggyback_host("{id}", grp, None) == "100"
    assert u.piggyback_host("{type}-{id}", grp, None) == "vm-100"
    assert u.piggyback_host("{comment}", grp, None) == "web01"
    assert u.piggyback_host("{id}", grp, (r"^(\d+)$", r"vm-\1")) == "vm-100"


def test_latest_task_picks_most_recent_finished():
    tasks = [
        {"worker_type": "syncjob", "worker_id": "r:s:d:ns:job1",
         "starttime": 10, "endtime": 20, "status": "OK"},
        {"worker_type": "syncjob", "worker_id": "r:s:d:ns:job1",
         "starttime": 30, "endtime": 40, "status": "some error"},
        {"worker_type": "syncjob", "worker_id": "r:s:d:ns:job1",
         "starttime": 50, "endtime": None, "status": None},  # running, ignored
    ]
    got = u.latest_task(tasks, "syncjob", lambda wid: wid.rsplit(":", 1)[-1] == "job1")
    assert got["starttime"] == 30 and got["status"] == "some error"
    assert u.task_running(tasks, "syncjob", lambda wid: wid.endswith("job1")) is True
