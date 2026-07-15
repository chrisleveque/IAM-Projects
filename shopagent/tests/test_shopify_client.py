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
