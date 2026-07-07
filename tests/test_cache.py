from conftest import load_module
cache = load_module("libexec/oposs_pbs_cache.py", "oposs_pbs_cache")


def test_refresh_rules(tmp_path):
    c = cache.StateCache.load(str(tmp_path / "missing.json"))
    k = cache.group_key("store1", "", "vm", "100")
    assert c.needs_refresh(k, last_backup=10, verify_activity=0) is True  # new
    c.put(k, {"last_backup": 10, "verify_checked_at": 5,
              "interval": 86400, "interval_known": True,
              "verify_state": "ok", "data_size": 42})
    assert c.needs_refresh(k, last_backup=10, verify_activity=5) is False  # unchanged
    assert c.needs_refresh(k, last_backup=20, verify_activity=5) is True   # new backup
    assert c.needs_refresh(k, last_backup=10, verify_activity=9) is True   # verify ran


def test_roundtrip(tmp_path):
    p = str(tmp_path / "sub" / "host.json")
    c = cache.StateCache.load(p)
    c.put("k", {"last_backup": 1})
    c.save(p)
    again = cache.StateCache.load(p)
    assert again.get("k") == {"last_backup": 1}
