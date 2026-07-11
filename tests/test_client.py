import pytest
import responses
from conftest import load_module

client = load_module("libexec/oposs_pbs_client.py", "oposs_pbs_client")


@responses.activate
def test_get_sends_token_header_and_unwraps_data():
    responses.add(responses.GET, "https://pbs.example:8007/api2/json/version",
                  json={"data": {"version": "3.2.7"}}, status=200)
    c = client.PbsClient("pbs.example", 8007, "root@pam!mon", "s3cr3t", verify=False)
    assert c.get("/version") == {"version": "3.2.7"}
    sent = responses.calls[0].request.headers["Authorization"]
    assert sent == "PBSAPIToken root@pam!mon:s3cr3t"


@responses.activate
def test_get_raises_pbserror_on_http_500():
    responses.add(responses.GET, "https://pbs.example:8007/api2/json/nodes",
                  status=500)
    c = client.PbsClient("pbs.example", 8007, "root@pam!mon", "x", verify=False)
    with pytest.raises(client.PbsError):
        c.get("/nodes")


def test_resolve_password_ref_passthrough_plain():
    # No colon -> not a reference, returned unchanged (inline/test secret).
    assert client.resolve_password_ref("plainsecret") == "plainsecret"


def test_resolve_password_ref_passthrough_missing_file():
    # Looks like a reference but the store file does not exist -> unchanged.
    val = "someid:/nonexistent/passwords_merged"
    assert client.resolve_password_ref(val) == val


def test_resolve_password_ref_looks_up_real_secret(tmp_path):
    store = tmp_path / "passwords_merged"
    store.write_bytes(b"encrypted-blob")
    seen = {}

    def fake_lookup(path, pw_id):
        seen["path"], seen["id"] = path, pw_id
        return "RESOLVED-SECRET"

    ref = f"uuid-abc-123:{store}"
    assert client.resolve_password_ref(ref, _lookup=fake_lookup) == "RESOLVED-SECRET"
    assert str(seen["path"]) == str(store) and seen["id"] == "uuid-abc-123"
