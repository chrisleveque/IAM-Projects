import json

import httpx
import pytest

from shopagent.integrations.cj_client import CJClient, CJError, MockCJClient


# ------------------------------------------------------------------ mock CJ

def test_mock_search_is_deterministic():
    cj = MockCJClient()
    hits = cj.search_products("pet")
    assert hits and all("PET" in p["pid"] for p in hits)
    assert hits == MockCJClient().search_products("pet")


def test_mock_order_lifecycle_progresses():
    cj = MockCJClient()
    order = cj.create_order("#1001", [{"vid": "V-PET-001-A", "quantity": 1}],
                            {"name": "A", "countryCodeV2": "US"}, "CJPacket Ordinary")
    cj_id = order["cj_order_id"]
    seen = [cj.get_order_status(cj_id)["status"] for _ in range(6)]
    assert seen[0] == "CREATED"
    assert seen[-1] == "DELIVERED"
    final = cj.get_order_status(cj_id)
    assert final["tracking_number"].startswith("CJMOCK")


def test_mock_rejects_unknown_variant():
    cj = MockCJClient()
    with pytest.raises(CJError, match="unknown variant"):
        cj.create_order("#1", [{"vid": "V-NOPE", "quantity": 1}], {}, "x")


# ------------------------------------------------------------------ live CJ (stubbed transport)

def _client_with(handler, tmp_path) -> CJClient:
    client = CJClient("a@b.c", "key", token_cache=tmp_path / ".cj_token.json",
                      transport=httpx.MockTransport(handler))
    client._last_request = 0.0  # skip throttle sleeps in tests
    return client


def test_token_fetched_then_cached(tmp_path):
    auth_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authentication/getAccessToken"):
            auth_calls["n"] += 1
            return httpx.Response(200, json={"result": True,
                                             "data": {"accessToken": "tok123"}})
        assert request.headers["CJ-Access-Token"] == "tok123"
        return httpx.Response(200, json={"result": True, "data": {"list": []}})

    client = _client_with(handler, tmp_path)
    client.search_products("pet")
    assert auth_calls["n"] == 1
    assert json.loads((tmp_path / ".cj_token.json").read_text())["token"] == "tok123"

    # a fresh client reuses the cached token without re-authing
    client2 = _client_with(handler, tmp_path)
    client2.search_products("pet")
    assert auth_calls["n"] == 1


def test_401_triggers_reauth_once(tmp_path):
    state = {"auth": 0, "data": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authentication/getAccessToken"):
            state["auth"] += 1
            return httpx.Response(200, json={"result": True,
                                             "data": {"accessToken": f"tok{state['auth']}"}})
        state["data"] += 1
        if state["data"] == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"result": True, "data": {"list": []}})

    client = _client_with(handler, tmp_path)
    client.search_products("pet")
    assert state["auth"] == 2  # initial token + refresh after 401
    assert state["data"] == 2


def test_api_level_error_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authentication/getAccessToken"):
            return httpx.Response(200, json={"result": True,
                                             "data": {"accessToken": "tok"}})
        return httpx.Response(200, json={"result": False, "message": "quota exceeded"})

    client = _client_with(handler, tmp_path)
    with pytest.raises(CJError, match="quota exceeded"):
        client.search_products("pet")


def test_create_order_payload_shape(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authentication/getAccessToken"):
            return httpx.Response(200, json={"result": True,
                                             "data": {"accessToken": "tok"}})
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"result": True, "data": {"orderId": "CJ42"}})

    client = _client_with(handler, tmp_path)
    result = client.create_order(
        "#1001", [{"vid": "V1", "quantity": 2}],
        {"name": "Jamie Rivera", "address1": "428 Maple Ave", "city": "Austin",
         "provinceCode": "TX", "zip": "78701", "countryCodeV2": "US", "phone": "555"},
        "CJPacket Ordinary")
    assert result["cj_order_id"] == "CJ42"
    assert captured["orderNumber"] == "#1001"
    assert captured["shippingCity"] == "Austin"
    assert captured["products"] == [{"vid": "V1", "quantity": 2}]
