import json

import httpx
import pytest

from shopagent.integrations.amazon_client import (AmazonClient, AmazonError,
                                                  MockAmazonClient)

MARKETPLACE = "ATVPDKIKX0DER"


# ---------------------------------------------------------------- mock Amazon

def test_mock_orders_and_shipment_lifecycle():
    amz = MockAmazonClient()
    orders = amz.list_unshipped_orders()
    assert len(orders) == 2
    assert orders[0]["lineItems"][0]["sku"] == "V-PET-002-A"

    amz.confirm_shipment("111-2233445-6677889", "CJMOCK111111",
                         order_items=[{"order_item_id": "OI-0001", "quantity": 1}])
    assert len(amz.list_unshipped_orders()) == 1
    with pytest.raises(AmazonError, match="already shipped"):
        amz.confirm_shipment("111-2233445-6677889", "CJMOCK111111")
    with pytest.raises(AmazonError, match="no order"):
        amz.confirm_shipment("999-0000000-0000000", "X")


def test_mock_listing_roundtrip_and_validation():
    amz = MockAmazonClient()
    invalid = amz.validate_listing("SKU1", "PET_SUPPLIES", {"item_name": []})
    assert invalid["status"] == "INVALID"
    assert invalid["issues"][0]["attribute_names"] == ["brand"]

    ok = amz.validate_listing("SKU1", "PET_SUPPLIES", {"brand": [], "item_name": []})
    assert ok["status"] == "VALID"

    result = amz.put_listing("SKU1", "PET_SUPPLIES", {"brand": []})
    assert result["status"] == "ACCEPTED"
    assert result["submission_id"].startswith("MOCKSUB")
    assert amz.get_listing("SKU1")["status"] == ["BUYABLE"]
    with pytest.raises(AmazonError):
        amz.update_price("NOPE", "PET_SUPPLIES", 9.99)


# ------------------------------------------------------- live client (stubbed)

def _client(handler, tmp_path) -> AmazonClient:
    client = AmazonClient(
        "https://sellingpartnerapi-na.amazon.com", MARKETPLACE, "SELLER123",
        client_id="cid", client_secret="csec", refresh_token="rtok",
        token_cache=tmp_path / ".amazon_token.json",
        transport=httpx.MockTransport(handler))
    client._last_orders_call = 0.0
    return client


def _lwa_response():
    return httpx.Response(200, json={"access_token": "Atza|token1",
                                     "token_type": "bearer", "expires_in": 3600})


def test_lwa_token_fetched_cached_and_sent(tmp_path):
    state = {"lwa": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            state["lwa"] += 1
            body = request.content.decode()
            assert "grant_type=refresh_token" in body
            assert "refresh_token=rtok" in body
            return _lwa_response()
        assert request.headers["x-amz-access-token"] == "Atza|token1"
        assert "shopagent" in request.headers["user-agent"]
        return httpx.Response(200, json={"payload": [
            {"marketplace": {"id": MARKETPLACE, "name": "Amazon.com"}}]})

    client = _client(handler, tmp_path)
    seller = client.get_seller()
    assert seller["marketplace"] == "Amazon.com"
    assert state["lwa"] == 1
    assert json.loads(
        (tmp_path / ".amazon_token.json").read_text())["token"] == "Atza|token1"

    client2 = _client(handler, tmp_path)
    client2.get_seller()
    assert state["lwa"] == 1  # cache reused across clients


def test_orders_sync_uses_rdt_and_normalizes(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "api.amazon.com":
            return _lwa_response()
        calls.append(path)
        if path == "/tokens/2021-03-01/restrictedDataToken":
            body = json.loads(request.content)
            assert body["restrictedResources"][0]["dataElements"] == [
                "shippingAddress", "buyerInfo"]
            return httpx.Response(200, json={"restrictedDataToken": "RDT1",
                                             "expiresIn": 3600})
        if path == "/orders/v0/orders":
            assert request.headers["x-amz-access-token"] == "RDT1"
            assert request.url.params["FulfillmentChannels"] == "MFN"
            return httpx.Response(200, json={"payload": {"Orders": [{
                "AmazonOrderId": "111-1111111-1111111",
                "BuyerInfo": {"BuyerEmail": "b@example.com"},
                "ShippingAddress": {
                    "Name": "Riley Okafor", "AddressLine1": "902 Cedar Ln",
                    "City": "Denver", "StateOrRegion": "CO",
                    "PostalCode": "80202", "CountryCode": "US",
                    "Phone": "+1 720 555 0163"},
            }]}})
        if path.endswith("/orderItems"):
            return httpx.Response(200, json={"payload": {"OrderItems": [{
                "OrderItemId": "OI-9", "Title": "LED Collar",
                "SellerSKU": "V-PET-002-A", "QuantityOrdered": 2,
                "ItemPrice": {"Amount": "16.99", "CurrencyCode": "USD"}}]}})
        raise AssertionError(f"unexpected path {path}")

    client = _client(handler, tmp_path)
    orders = client.list_unshipped_orders()
    assert orders == [{
        "id": "111-1111111-1111111", "name": "111-1111111-1111111",
        "email": "b@example.com",
        "lineItems": [{"title": "LED Collar", "quantity": 2,
                       "sku": "V-PET-002-A", "price": "16.99",
                       "order_item_id": "OI-9"}],
        "shippingAddress": {"name": "Riley Okafor", "address1": "902 Cedar Ln",
                            "address2": "", "city": "Denver",
                            "provinceCode": "CO", "zip": "80202",
                            "countryCodeV2": "US", "phone": "+1 720 555 0163"},
    }]
    assert calls[0] == "/tokens/2021-03-01/restrictedDataToken"


def test_rdt_403_names_the_missing_role(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return _lwa_response()
        return httpx.Response(403, text="Access to requested resource is denied.")

    client = _client(handler, tmp_path)
    with pytest.raises(AmazonError, match="Direct-to-Consumer Shipping"):
        client.list_unshipped_orders()


def test_put_listing_shape_and_issues(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return _lwa_response()
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "sku": "V-PET-002-A", "status": "ACCEPTED", "submissionId": "SUB1",
            "issues": [{"severity": "WARNING", "message": "image low res",
                        "attributeNames": ["main_product_image_locator"]}]})

    client = _client(handler, tmp_path)
    result = client.put_listing("V-PET-002-A", "PET_SUPPLIES",
                                {"item_name": [{"value": "LED Collar"}]})
    assert captured["path"] == "/listings/2021-08-01/items/SELLER123/V-PET-002-A"
    assert captured["params"]["marketplaceIds"] == MARKETPLACE
    assert "mode" not in captured["params"]
    assert captured["body"] == {"productType": "PET_SUPPLIES",
                                "requirements": "LISTING",
                                "attributes": {"item_name": [{"value": "LED Collar"}]}}
    assert result["status"] == "ACCEPTED"
    assert result["issues"][0]["severity"] == "WARNING"


def test_validate_listing_uses_preview_mode(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return _lwa_response()
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"sku": "S", "status": "VALID", "issues": []})

    client = _client(handler, tmp_path)
    client.validate_listing("S", "PRODUCT", {})
    assert captured["params"]["mode"] == "VALIDATION_PREVIEW"


def test_update_price_patches_purchasable_offer(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return _lwa_response()
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"sku": "S", "status": "ACCEPTED",
                                         "submissionId": "SUB2"})

    client = _client(handler, tmp_path)
    client.update_price("S", "PET_SUPPLIES", 21.99)
    assert captured["method"] == "PATCH"
    patch = captured["body"]["patches"][0]
    assert patch["op"] == "replace"
    assert patch["path"] == "/attributes/purchasable_offer"
    assert patch["value"][0]["our_price"][0]["schedule"][0]["value_with_tax"] == 21.99


def test_confirm_shipment_posts_package(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return _lwa_response()
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    client = _client(handler, tmp_path)
    result = client.confirm_shipment(
        "111-1111111-1111111", "TRACK9", carrier_code="Other",
        carrier_name="CJPacket",
        order_items=[{"order_item_id": "OI-9", "quantity": 2}])
    assert result["confirmed"] is True
    assert captured["path"].endswith(
        "/orders/v0/orders/111-1111111-1111111/shipmentConfirmation")
    package = captured["body"]["packageDetail"]
    assert package["trackingNumber"] == "TRACK9"
    assert package["carrierName"] == "CJPacket"
    assert package["orderItems"] == [{"orderItemId": "OI-9", "quantity": 2}]


def test_401_refreshes_token_once(tmp_path):
    state = {"lwa": 0, "api": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            state["lwa"] += 1
            return httpx.Response(200, json={"access_token": f"Atza|t{state['lwa']}",
                                             "expires_in": 3600})
        state["api"] += 1
        if state["api"] == 1:
            return httpx.Response(401)
        assert request.headers["x-amz-access-token"] == "Atza|t2"
        return httpx.Response(200, json={"payload": []})

    client = _client(handler, tmp_path)
    client.get_seller()
    assert state["lwa"] == 2
    assert state["api"] == 2
