"""Amazon SP-API client (FBM seller channel) + in-process mock.

Auth is Login-with-Amazon only — SP-API dropped AWS SigV4 signing in 2023.
A self-authorized private app (Seller Central -> Partner Network -> Develop
Apps) yields the LWA client id/secret and a long-lived refresh token; those
are exchanged for ~1h access tokens, cached in gitignored .amazon_token.json.
Every API call carries the token in the ``x-amz-access-token`` header.

Buyer shipping addresses are RESTRICTED data: getOrders redacts them unless
called with a Restricted Data Token (Tokens API). The developer profile must
have the "Direct-to-Consumer Shipping" restricted role approved, or those
calls return 403 / redacted fields — surfaced with a hint.

The method set below is the Amazon channel interface:

    get_seller() -> dict
    search_product_types(keywords) -> list[str]
    validate_listing(sku, product_type, attributes) -> dict   (non-persisting)
    put_listing(sku, product_type, attributes) -> dict
    get_listing(sku) -> dict | None
    update_price(sku, product_type, price) -> dict
    list_unshipped_orders() -> list[dict]     (normalized to the store shape)
    confirm_shipment(amazon_order_id, tracking_number, ...) -> dict

NOTE: exact required listing attributes vary per productType and cannot be
fully verified without a live seller account — validate_listing (Amazon's
VALIDATION_PREVIEW mode) is the guard, and submission issues are surfaced.
"""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import AppConfig
from . import fixtures

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
USER_AGENT = "shopagent/1.0 (Language=Python)"


class AmazonError(RuntimeError):
    pass


class LWAAuth:
    """LWA refresh-token flow with a file cache (mirrors the CJ/Shopify
    token-cache pattern). Access tokens live ~1 hour; refresh 5 min early."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 token_cache: Path, http):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._token_cache = token_cache
        self._http = http
        self._token: str | None = None

    def _load_cached_token(self) -> str | None:
        try:
            data = json.loads(self._token_cache.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(data["expires_at"])
            if expires > datetime.now(timezone.utc) + timedelta(minutes=5):
                return data["token"]
        except (OSError, ValueError, KeyError):
            pass
        return None

    def _fetch_token(self) -> str:
        resp = self._http.post(
            LWA_TOKEN_URL,
            data={"grant_type": "refresh_token",
                  "refresh_token": self._refresh_token,
                  "client_id": self._client_id,
                  "client_secret": self._client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise AmazonError(
                f"LWA token request failed ({resp.status_code}): {resp.text[:300]}. "
                "Check AMZ_CLIENT_ID/AMZ_CLIENT_SECRET/AMZ_REFRESH_TOKEN."
            )
        body = resp.json()
        token = body["access_token"]
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=int(body.get("expires_in", 3600)))
        self._token_cache.write_text(json.dumps(
            {"token": token, "expires_at": expires.isoformat()}), encoding="utf-8")
        return token

    def token(self) -> str:
        if self._token is None:
            self._token = self._load_cached_token() or self._fetch_token()
        return self._token

    def invalidate(self) -> None:
        self._token = None
        self._token_cache.unlink(missing_ok=True)


class AmazonClient:
    def __init__(self, endpoint: str, marketplace_id: str, seller_id: str,
                 auth: LWAAuth | None = None, *, client_id: str = "",
                 client_secret: str = "", refresh_token: str = "",
                 token_cache: Path | None = None, transport=None):
        import httpx  # lazy so tests importing the module need no network stack

        self.endpoint = endpoint.rstrip("/")
        self.marketplace_id = marketplace_id
        self.seller_id = seller_id
        self._http = getattr(auth, "_http", None) or httpx.Client(
            timeout=30.0, transport=transport)
        self._auth = auth or LWAAuth(client_id, client_secret, refresh_token,
                                     token_cache, self._http)
        self._rdt_cache: dict[str, tuple[str, float]] = {}
        self._last_orders_call = 0.0

    # --------------------------------------------------------------- request

    def _rdt(self, path: str, elements: list[str]) -> str:
        """Restricted Data Token for PII fields (buyer address); cached ~55min."""
        key = f"{path}:{','.join(elements)}"
        cached = self._rdt_cache.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        resp = self._http.post(
            f"{self.endpoint}/tokens/2021-03-01/restrictedDataToken",
            json={"restrictedResources": [
                {"method": "GET", "path": path, "dataElements": elements}]},
            headers={"x-amz-access-token": self._auth.token(),
                     "User-Agent": USER_AGENT},
        )
        if resp.status_code == 403:
            raise AmazonError(
                "restricted data token denied (403): the developer profile "
                "needs the 'Direct-to-Consumer Shipping' restricted role "
                "approved before buyer addresses are visible. Check Seller "
                "Central -> Partner Network -> Develop Apps."
            )
        resp.raise_for_status()
        token = resp.json()["restrictedDataToken"]
        self._rdt_cache[key] = (token, time.monotonic() + 55 * 60)
        return token

    def _request(self, method: str, path: str, *, rdt_elements: list[str] | None = None,
                 retry_auth: bool = True, **kwargs):
        token = (self._rdt(path, rdt_elements) if rdt_elements
                 else self._auth.token())
        resp = self._http.request(
            method, f"{self.endpoint}{path}",
            headers={"x-amz-access-token": token, "User-Agent": USER_AGENT},
            **kwargs,
        )
        if resp.status_code == 401 and retry_auth:
            self._auth.invalidate()
            self._rdt_cache.clear()
            return self._request(method, path, rdt_elements=rdt_elements,
                                 retry_auth=False, **kwargs)
        if resp.status_code == 403:
            raise AmazonError(
                f"{path} forbidden (403): the app may be missing a required "
                "role (Direct-to-Consumer Shipping for order addresses) or "
                "the refresh token was made before roles changed — re-authorize "
                f"the app. Body: {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise AmazonError(
                f"{method} {path} failed ({resp.status_code}): {resp.text[:400]}")
        return resp

    # ------------------------------------------------------------------- api

    def get_seller(self) -> dict:
        resp = self._request("GET", "/sellers/v1/marketplaceParticipations")
        payload = resp.json().get("payload", [])
        names = [p["marketplace"]["name"] for p in payload
                 if p.get("marketplace", {}).get("id") == self.marketplace_id]
        return {"seller_id": self.seller_id,
                "marketplace": names[0] if names else "unknown",
                "participations": len(payload)}

    def search_product_types(self, keywords: str) -> list[str]:
        resp = self._request(
            "GET", "/definitions/2020-09-01/productTypes",
            params={"keywords": keywords, "marketplaceIds": self.marketplace_id})
        return [pt["name"] for pt in resp.json().get("productTypes", [])]

    def _put_listing(self, sku: str, product_type: str, attributes: dict,
                     mode: str | None = None) -> dict:
        params = {"marketplaceIds": self.marketplace_id,
                  "includedData": "issues", "issueLocale": "en_US"}
        if mode:
            params["mode"] = mode
        resp = self._request(
            "PUT", f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
            params=params,
            json={"productType": product_type, "requirements": "LISTING",
                  "attributes": attributes},
        )
        body = resp.json()
        return {"sku": sku, "status": body.get("status", ""),
                "submission_id": body.get("submissionId", ""),
                "issues": [
                    {"severity": i.get("severity", ""),
                     "message": i.get("message", ""),
                     "attribute_names": i.get("attributeNames", [])}
                    for i in body.get("issues", [])]}

    def validate_listing(self, sku: str, product_type: str, attributes: dict) -> dict:
        """Amazon-side validation without persisting anything (VALIDATION_PREVIEW)."""
        return self._put_listing(sku, product_type, attributes,
                                 mode="VALIDATION_PREVIEW")

    def put_listing(self, sku: str, product_type: str, attributes: dict) -> dict:
        return self._put_listing(sku, product_type, attributes)

    def get_listing(self, sku: str) -> dict | None:
        resp = self._request(
            "GET", f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
            params={"marketplaceIds": self.marketplace_id,
                    "includedData": "summaries,issues"})
        body = resp.json()
        summaries = body.get("summaries", [])
        return {"sku": sku,
                "status": summaries[0].get("status", []) if summaries else [],
                "issues": body.get("issues", [])}

    def update_price(self, sku: str, product_type: str, price: float) -> dict:
        offer = [{"marketplace_id": self.marketplace_id, "currency": "USD",
                  "our_price": [{"schedule": [{"value_with_tax": price}]}]}]
        resp = self._request(
            "PATCH", f"/listings/2021-08-01/items/{self.seller_id}/{sku}",
            params={"marketplaceIds": self.marketplace_id,
                    "includedData": "issues", "issueLocale": "en_US"},
            json={"productType": product_type,
                  "patches": [{"op": "replace",
                               "path": "/attributes/purchasable_offer",
                               "value": offer}]},
        )
        body = resp.json()
        return {"sku": sku, "status": body.get("status", ""),
                "submission_id": body.get("submissionId", "")}

    def list_unshipped_orders(self, created_after_days: int = 30) -> list[dict]:
        # getOrders is rate-limited to ~1 call/minute: one call per sync, and
        # a guard so accidental rapid re-syncs wait instead of erroring.
        wait = 65.0 - (time.monotonic() - self._last_orders_call)
        if 0 < wait < 65.0:
            time.sleep(wait)
        created_after = (datetime.now(timezone.utc)
                         - timedelta(days=created_after_days)).isoformat(
                             timespec="seconds")
        resp = self._request(
            "GET", "/orders/v0/orders",
            rdt_elements=["shippingAddress", "buyerInfo"],
            params={"MarketplaceIds": self.marketplace_id,
                    "FulfillmentChannels": "MFN",
                    "OrderStatuses": "Unshipped,PartiallyShipped",
                    "CreatedAfter": created_after},
        )
        self._last_orders_call = time.monotonic()
        orders = resp.json().get("payload", {}).get("Orders", [])
        out = []
        for order in orders:
            order_id = order.get("AmazonOrderId", "")
            items_resp = self._request(
                "GET", f"/orders/v0/orders/{order_id}/orderItems")
            items = items_resp.json().get("payload", {}).get("OrderItems", [])
            addr = order.get("ShippingAddress") or {}
            out.append({
                "id": order_id,
                "name": order_id,
                "email": (order.get("BuyerInfo") or {}).get("BuyerEmail", ""),
                "lineItems": [
                    {"title": i.get("Title", ""),
                     "quantity": i.get("QuantityOrdered", 1),
                     "sku": i.get("SellerSKU", ""),
                     "price": (i.get("ItemPrice") or {}).get("Amount", ""),
                     "order_item_id": i.get("OrderItemId", "")}
                    for i in items],
                "shippingAddress": {
                    "name": addr.get("Name", ""),
                    "address1": addr.get("AddressLine1", ""),
                    "address2": addr.get("AddressLine2", ""),
                    "city": addr.get("City", ""),
                    "provinceCode": addr.get("StateOrRegion", ""),
                    "zip": addr.get("PostalCode", ""),
                    "countryCodeV2": addr.get("CountryCode", "US"),
                    "phone": addr.get("Phone", ""),
                },
            })
        return out

    def confirm_shipment(self, amazon_order_id: str, tracking_number: str,
                         carrier_code: str = "Other", carrier_name: str = "CJPacket",
                         ship_date: str | None = None,
                         order_items: list[dict] | None = None) -> dict:
        package: dict = {
            "packageReferenceId": "1",
            "carrierCode": carrier_code,
            "trackingNumber": tracking_number,
            "shipDate": ship_date or datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "orderItems": [{"orderItemId": i["order_item_id"],
                            "quantity": i.get("quantity", 1)}
                           for i in (order_items or [])],
        }
        if carrier_code == "Other":
            package["carrierName"] = carrier_name
        self._request(
            "POST", f"/orders/v0/orders/{amazon_order_id}/shipmentConfirmation",
            json={"marketplaceId": self.marketplace_id, "packageDetail": package},
        )
        return {"amazon_order_id": amazon_order_id,
                "tracking_number": tracking_number, "confirmed": True}


class MockAmazonClient:
    """Deterministic in-memory Amazon seller account seeded from fixtures."""

    def __init__(self):
        self._orders = copy.deepcopy(fixtures.AMAZON_SEED_ORDERS)
        self._shipped: dict[str, str] = {}
        self._listings: dict[str, dict] = {}
        self._next_submission = 1

    def get_seller(self) -> dict:
        return {"seller_id": "MOCKSELLER", "marketplace": "Mock Amazon.com (dry run)",
                "participations": 1}

    def search_product_types(self, keywords: str) -> list[str]:
        return list(fixtures.AMAZON_PRODUCT_TYPES)

    def validate_listing(self, sku: str, product_type: str, attributes: dict) -> dict:
        issues = []
        if "brand" not in attributes:
            issues.append({"severity": "ERROR",
                           "message": "The attribute 'brand' is required.",
                           "attribute_names": ["brand"]})
        return {"sku": sku, "status": "INVALID" if issues else "VALID",
                "submission_id": "", "issues": issues}

    def put_listing(self, sku: str, product_type: str, attributes: dict) -> dict:
        submission_id = f"MOCKSUB{self._next_submission:04d}"
        self._next_submission += 1
        self._listings[sku] = {"product_type": product_type,
                               "attributes": copy.deepcopy(attributes)}
        return {"sku": sku, "status": "ACCEPTED", "submission_id": submission_id,
                "issues": []}

    def get_listing(self, sku: str) -> dict | None:
        if sku not in self._listings:
            return None
        return {"sku": sku, "status": ["BUYABLE"], "issues": []}

    def update_price(self, sku: str, product_type: str, price: float) -> dict:
        if sku not in self._listings:
            raise AmazonError(f"mock: no listing with sku {sku!r}")
        return {"sku": sku, "status": "ACCEPTED", "submission_id": "MOCKSUBPRICE"}

    def list_unshipped_orders(self, created_after_days: int = 30) -> list[dict]:
        return [copy.deepcopy(o) for o in self._orders
                if o["id"] not in self._shipped]

    def confirm_shipment(self, amazon_order_id: str, tracking_number: str,
                         carrier_code: str = "Other", carrier_name: str = "CJPacket",
                         ship_date: str | None = None,
                         order_items: list[dict] | None = None) -> dict:
        if amazon_order_id not in {o["id"] for o in self._orders}:
            raise AmazonError(f"mock: no order {amazon_order_id!r}")
        if amazon_order_id in self._shipped:
            raise AmazonError(f"mock: order {amazon_order_id!r} already shipped")
        self._shipped[amazon_order_id] = tracking_number
        return {"amazon_order_id": amazon_order_id,
                "tracking_number": tracking_number, "confirmed": True}


def make_amazon_client(cfg: AppConfig):
    if cfg.amazon_mode() == "live":
        import os

        return AmazonClient(
            cfg.amazon.endpoint, cfg.amazon.marketplace_id,
            os.environ["AMZ_SELLER_ID"],
            client_id=os.environ["AMZ_CLIENT_ID"],
            client_secret=os.environ["AMZ_CLIENT_SECRET"],
            refresh_token=os.environ["AMZ_REFRESH_TOKEN"],
            token_cache=cfg.resolve(".amazon_token.json"),
        )
    return MockAmazonClient()
