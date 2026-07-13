"""A fake PbsClient.get() keyed by (path, frozenset(params))."""


class FakePbs:
    def __init__(self, routes: dict):
        # routes: path -> value, OR path -> callable(params)->value
        self.routes = routes
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        v = self.routes[path]
        return v(params or {}) if callable(v) else v


DAY = 86400


def sample_routes(now):
    return {
        "/nodes": [{"node": "pbs01"}],
        "/version": {"version": "3.2.7"},
        "/admin/datastore": [{"store": "main", "comment": "primary"}],
        "/admin/datastore/main/status": {
            "total": 1000, "used": 250, "avail": 750,
            "gc-status": {"index-data-bytes": 4000, "disk-bytes": 1000,
                          "upid": "UPID:pbs01:GC"},
        },
        "/admin/datastore/main/namespace": [{"ns": ""}],
        "/admin/datastore/main/groups": [
            {"backup-type": "vm", "backup-id": "100", "last-backup": now - 100,
             "backup-count": 7, "comment": "web01"},
        ],
        "/config/sync": [{"id": "s1", "store": "main", "remote": "r1",
                          "remote-store": "rs", "ns": "", "schedule": "daily"}],
        "/config/verify": [{"id": "v1", "store": "main", "schedule": "weekly"}],
        "/config/prune": [{"id": "p1", "store": "main", "schedule": "daily"}],
        "/nodes/localhost/tasks": [
            {"worker_type": "garbage_collection", "worker_id": "main",
             "starttime": now - 3600, "endtime": now - 3500, "status": "OK"},
            {"worker_type": "syncjob", "worker_id": "r1:rs:main::s1",
             "starttime": now - 200, "endtime": now - 100, "status": "OK"},
            {"worker_type": "verificationjob", "worker_id": "main:v1",
             "starttime": now - 400, "endtime": now - 300, "status": "OK"},
            {"worker_type": "prunejob", "worker_id": "main",
             "starttime": now - 500, "endtime": now - 450, "status": "OK"},
        ],
        "/admin/datastore/main/snapshots": [
            {"backup-type": "vm", "backup-id": "100", "backup-time": now - 100 - DAY,
             "size": 40_000_000_000},
            {"backup-type": "vm", "backup-id": "100", "backup-time": now - 100,
             "size": 41_000_000_000, "verification": {"state": "ok", "upid": "x"}},
        ],
    }
