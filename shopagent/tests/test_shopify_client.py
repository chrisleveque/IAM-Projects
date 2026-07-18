import json

import httpx
import pytest

from shopagent.integrations.shopify_client import (MockShopifyClient, ShopifyClient,
                                                   ShopifyError)


# -------------------------------------------------------------- mock Shopify

def test_mock_seeds_orders_and_products():
    shop = MockShopifyClient()
    assert len(shop.list_open_orders()) == 2
    assert shop.list_products()[0]["title"].startswith("LED")


def test_mock_create_product_is_readable_back():
    shop = MockShopifyClient()
    created = shop.create_product("Travel Bowl", "<p>Folds flat</p>",
                                  ["pets"], "9.99", vendor="shopagent")
    titles = [p["title"] for p in shop.list_products()]
    assert "Travel Bowl" in titles
    updated = shop.update_product(created["id"], {"title": "Travel Bowl 2-Pack"})
    assert updated["title"] == "Travel Bowl 2-Pack"


def test_mock_update_unknown_product_raises():
    shop = MockShopifyClient()
    with pytest.raises(ShopifyError):
        shop.update_product("gid://shopify/Product/404", {"title": "x"})


# -------------------------------------------------------------- live Shopify (stubbed)

def _gql_client(handler) -> ShopifyClient:
    return ShopifyClient("test.myshopify.com", "shpat_test",
                         transport=httpx.MockTransport(handler))


def test_create_product_two_step(tmp_path):
    queries = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        queries.append(body["query"])
        if "productCreate" in body["query"]:
            return httpx.Response(200, json={"data": {"productCreate": {
                "product": {"id": "gid://shopify/Product/1", "title": "T",
                            "variants": {"nodes": [{"id": "gid://shopify/ProductVariant/11"}]}},
                "userErrors": []}}})
        return httpx.Response(200, json={"data": {"productVariantsBulkUpdate":
                                                  {"userErrors": []}}})

    client = _gql_client(handler)
    result = client.create_product("T", "<p>d</p>", ["a"], "19.99")
    assert result == {"id": "gid://shopify/Product/1", "title": "T", "price": "19.99"}
    assert len(queries) == 2
    assert "productVariantsBulkUpdate" in queries[1]


def test_user_errors_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"productCreate": {
            "product": None,
            "userErrors": [{"field": ["title"], "message": "can't be blank"}]}}})

    client = _gql_client(handler)
    with pytest.raises(ShopifyError, match="can't be blank"):
        client.create_product("", "", [], "1.00")


def test_graphql_errors_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Throttled"}]})

    client = _gql_client(handler)
    with pytest.raises(ShopifyError, match="Throttled"):
        client.get_shop()


# ------------------------------------------- client credentials (Dev Dashboard)

SHOP_RESPONSE = {"data": {"shop": {"name": "FurrFlow",
                                   "myshopifyDomain": "test.myshopify.com",
                                   "currencyCode": "USD"}}}


def _cc_client(handler, tmp_path) -> ShopifyClient:
    return ShopifyClient.for_client_credentials(
        "test.myshopify.com", "cid_123", "csecret_456",
        token_cache=tmp_path / ".shopify_token.json",
        transport=httpx.MockTransport(handler))


def test_client_credentials_token_fetch_and_cache(tmp_path):
    state = {"auth": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/oauth/access_token":
            state["auth"] += 1
            # Shopify requires form-urlencoded, not JSON
            assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
            body = request.content.decode()
            assert "grant_type=client_credentials" in body
            assert "client_id=cid_123" in body
            assert "client_secret=csecret_456" in body
            return httpx.Response(200, json={"access_token": "cc_tok_1",
                                             "expires_in": 86399, "scope": "read_products"})
        assert request.headers["X-Shopify-Access-Token"] == "cc_tok_1"
        return httpx.Response(200, json=SHOP_RESPONSE)

    client = _cc_client(handler, tmp_path)
    assert client.get_shop()["name"] == "FurrFlow"
    assert state["auth"] == 1
    assert json.loads((tmp_path / ".shopify_token.json").read_text())["token"] == "cc_tok_1"

    # a fresh client reuses the cached token without a new token request
    client2 = _cc_client(handler, tmp_path)
    client2.get_shop()
    assert state["auth"] == 1


def test_client_credentials_401_refreshes_once(tmp_path):
    state = {"auth": 0, "gql": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/oauth/access_token":
            state["auth"] += 1
            return httpx.Response(200, json={"access_token": f"cc_tok_{state['auth']}",
                                             "expires_in": 86399})
        state["gql"] += 1
        if state["gql"] == 1:
            return httpx.Response(401)
        assert request.headers["X-Shopify-Access-Token"] == "cc_tok_2"
        return httpx.Response(200, json=SHOP_RESPONSE)

    client = _cc_client(handler, tmp_path)
    assert client.get_shop()["name"] == "FurrFlow"
    assert state["auth"] == 2  # initial + refresh after 401
    assert state["gql"] == 2


def test_client_credentials_bad_secret_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/oauth/access_token":
            return httpx.Response(401, text="invalid client")
        raise AssertionError("should not reach GraphQL")

    client = _cc_client(handler, tmp_path)
    with pytest.raises(ShopifyError, match="installed on this store"):
        client.get_shop()


def test_exactly_one_auth_source_required():
    with pytest.raises(ValueError):
        ShopifyClient("test.myshopify.com")  # neither token nor auth
