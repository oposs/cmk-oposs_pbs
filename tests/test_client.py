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
