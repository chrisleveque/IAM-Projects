"""CJ Dropshipping API v2 client + in-process mock.

The method set below IS the supplier interface: a future second supplier
(AliExpress, Zendrop, ...) implements these same methods and plugs into the
same factory. No abc machinery while there is only one implementation.

    search_products(keyword, page_size) -> list[dict]
    get_product(pid) -> dict | None
    freight_calculate(vid, quantity, country) -> dict
    create_order(order_ref, cj_items, shipping_address, logistic_name) -> dict
    get_order_status(cj_order_id) -> dict
    get_tracking(cj_order_id) -> dict

Auth: POST /authentication/getAccessToken with CJ_EMAIL + CJ_API_KEY returns
a token valid ~15 days. The auth endpoint is severely rate-limited (roughly
once per 5 minutes), so the token is cached in a gitignored .cj_token.json
and only refreshed on expiry or a 401.

NOTE: field names were written against the public docs at
developers.cjdropshipping.com and must be reconfirmed against a live account
before switching mode: live.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import AppConfig
from . import fixtures

BASE_URL = "https://developers.cjdropshipping.com/api2.0/v1"


class CJError(RuntimeError):
    pass


def parse_price_range(value) -> tuple[float, float]:
    """CJ price fields may be a number, a numeric string, or a range across
    variants like '3.39 -- 4.37'. Returns (low, high); (0.0, 0.0) if unparseable."""
    if value is None:
        return (0.0, 0.0)
    if isinstance(value, (int, float)):
        return (float(value), float(value))
    nums = re.findall(r"\d+(?:\.\d+)?", str(value))
    if not nums:
        return (0.0, 0.0)
    vals = [float(n) for n in nums]
    return (min(vals), max(vals))


class CJClient:
    def __init__(self, email: str, api_key: str, token_cache: Path, transport=None):
        import httpx  # lazy so importing the module needs no network stack

        self._email = email
        self._api_key = api_key
        self._token_cache = token_cache
        self._token: str | None = None
        self._last_request = 0.0
        self._http = httpx.Client(base_url=BASE_URL, timeout=30.0, transport=transport)

    # ------------------------------------------------------------------ auth

    def _load_cached_token(self) -> str | None:
        try:
            data = json.loads(self._token_cache.read_text(encoding="utf-8"))
            if datetime.fromisoformat(data["expires_at"]) > datetime.now(timezone.utc):
                return data["token"]
        except (OSError, ValueError, KeyError):
            pass
        return None

    def _fetch_token(self) -> str:
        resp = self._http.post("/authentication/getAccessToken",
                               json={"email": self._email, "password": self._api_key})
        resp.raise_for_status()
        body = resp.json()
        if not body.get("result"):
            raise CJError(f"CJ auth failed: {body.get('message', 'unknown error')}")
        token = body["data"]["accessToken"]
        expires = datetime.now(timezone.utc) + timedelta(days=14)
        self._token_cache.write_text(json.dumps(
            {"token": token, "expires_at": expires.isoformat()}), encoding="utf-8")
        return token

    def _ensure_token(self) -> str:
        if self._token is None:
            self._token = self._load_cached_token() or self._fetch_token()
        return self._token

    # --------------------------------------------------------------- request

    def _request(self, method: str, path: str, *, retry_auth: bool = True, **kwargs) -> dict:
        # CJ enforces roughly 1 request/second per account.
        wait = 1.0 - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        headers = {"CJ-Access-Token": self._ensure_token()}
        resp = self._http.request(method, path, headers=headers, **kwargs)
        self._last_request = time.monotonic()
        if resp.status_code == 401 and retry_auth:
            self._token = None
            self._token_cache.unlink(missing_ok=True)
            return self._request(method, path, retry_auth=False, **kwargs)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("result"):
            raise CJError(f"CJ API error on {path}: {body.get('message', 'unknown error')}")
        return body.get("data") or {}

    # ------------------------------------------------------------------- api

    def search_products(self, keyword: str, page_size: int = 20) -> list[dict]:
        data = self._request("GET", "/product/list",
                             params={"productNameEn": keyword, "pageNum": 1,
                                     "pageSize": page_size})
        out = []
        for item in data.get("list", []):
            low, high = parse_price_range(item.get("sellPrice"))
            out.append({
                "pid": item.get("pid", ""),
                "name": item.get("productNameEn", ""),
                "sell_price": low,
                "sell_price_max": high,
                "category": item.get("categoryName", ""),
                "description": "",
            })
        return out

    def get_product(self, pid: str) -> dict | None:
        data = self._request("GET", "/product/query", params={"pid": pid})
        if not data:
            return None
        variants = data.get("variants") or []
        low, high = parse_price_range(data.get("sellPrice"))
        variant_low, _ = parse_price_range(variants[0].get("variantSellPrice")
                                           if variants else None)
        return {
            "pid": data.get("pid", pid),
            "vid": variants[0].get("vid", "") if variants else "",
            "name": data.get("productNameEn", ""),
            "sell_price": variant_low or low,
            "sell_price_max": high,
            "category": data.get("categoryName", ""),
            "description": data.get("description", ""),
            "variant_count": len(variants),
        }

    def freight_calculate(self, vid: str, quantity: int, country: str = "US") -> dict:
        data = self._request("POST", "/logistic/freightCalculate",
                             json={"startCountryCode": "CN", "endCountryCode": country,
                                   "products": [{"vid": vid, "quantity": quantity}]})
        options = data if isinstance(data, list) else []
        if not options:
            return {"logistic_name": "", "freight_usd": None, "days": ""}

        def price_of(option: dict) -> float:
            low, _ = parse_price_range(option.get("logisticPrice"))
            return low or 1e9

        best = min(options, key=price_of)
        return {"logistic_name": best.get("logisticName", ""),
                "freight_usd": parse_price_range(best.get("logisticPrice"))[0],
                "days": best.get("logisticAging", "")}

    def create_order(self, order_ref: str, cj_items: list[dict],
                     shipping_address: dict, logistic_name: str) -> dict:
        payload = {
            "orderNumber": order_ref,
            "shippingZip": shipping_address.get("zip", ""),
            "shippingCountryCode": shipping_address.get("countryCodeV2", "US"),
            "shippingCounty": "",
            "shippingProvince": shipping_address.get("provinceCode", ""),
            "shippingCity": shipping_address.get("city", ""),
            "shippingAddress": " ".join(filter(None, [shipping_address.get("address1", ""),
                                                      shipping_address.get("address2", "")])),
            "shippingCustomerName": shipping_address.get("name", ""),
            "shippingPhone": shipping_address.get("phone", ""),
            "logisticName": logistic_name,
            "fromCountryCode": "CN",
            "payType": 2,  # balance payment
            "products": [{"vid": i["vid"], "quantity": i["quantity"]} for i in cj_items],
        }
        data = self._request("POST", "/shopping/order/createOrderV2", json=payload)
        cj_order_id = data if isinstance(data, str) else data.get("orderId", "")
        return {"cj_order_id": cj_order_id, "order_ref": order_ref}

    def get_order_status(self, cj_order_id: str) -> dict:
        data = self._request("GET", "/shopping/order/getOrderDetail",
                             params={"orderId": cj_order_id})
        return {"cj_order_id": cj_order_id,
                "status": data.get("orderStatus", ""),
                "tracking_number": data.get("trackNumber", "")}

    def get_tracking(self, cj_order_id: str) -> dict:
        status = self.get_order_status(cj_order_id)
        return {"cj_order_id": cj_order_id,
                "tracking_number": status["tracking_number"],
                "status": status["status"]}


class MockCJClient:
    """Deterministic in-memory CJ supplier seeded from fixtures.

    Order status advances one step per poll (CREATED -> ... -> DELIVERED) so a
    dry run exercises the whole fulfillment lifecycle.
    """

    def __init__(self):
        self._catalog = copy.deepcopy(fixtures.CJ_CATALOG)
        self._orders: dict[str, dict] = {}
        self._next_order = 1

    def search_products(self, keyword: str, page_size: int = 20) -> list[dict]:
        words = keyword.lower().split()
        hits = [p for p in self._catalog
                if any(w in (p["name"] + " " + p["niche"]).lower() for w in words)]
        return copy.deepcopy(hits[:page_size])

    def get_product(self, pid: str) -> dict | None:
        for p in self._catalog:
            if p["pid"] == pid:
                return copy.deepcopy(p)
        return None

    def freight_calculate(self, vid: str, quantity: int, country: str = "US") -> dict:
        pid = next((p["pid"] for p in self._catalog if p["vid"] == vid), None)
        freight = fixtures.CJ_FREIGHT_USD.get(pid, 3.5)
        return {"logistic_name": "CJPacket Ordinary",
                "freight_usd": round(freight * max(1, quantity) ** 0.5, 2),
                "days": "8-12"}

    def create_order(self, order_ref: str, cj_items: list[dict],
                     shipping_address: dict, logistic_name: str) -> dict:
        known_vids = {p["vid"] for p in self._catalog}
        for item in cj_items:
            if item["vid"] not in known_vids:
                raise CJError(f"mock: unknown variant {item['vid']!r}")
        cj_order_id = f"MOCKCJ{self._next_order:06d}"
        self._next_order += 1
        self._orders[cj_order_id] = {"order_ref": order_ref, "status_idx": 0,
                                     "items": copy.deepcopy(cj_items)}
        return {"cj_order_id": cj_order_id, "order_ref": order_ref}

    def get_order_status(self, cj_order_id: str) -> dict:
        order = self._orders.get(cj_order_id)
        if order is None:
            raise CJError(f"mock: no order {cj_order_id!r}")
        idx = order["status_idx"]
        status = fixtures.CJ_STATUS_SEQUENCE[idx]
        order["status_idx"] = min(idx + 1, len(fixtures.CJ_STATUS_SEQUENCE) - 1)
        tracking = ""
        if status in ("SHIPPED", "DELIVERED"):
            tracking = f"{fixtures.MOCK_TRACKING_PREFIX}{cj_order_id[-6:]}"
        return {"cj_order_id": cj_order_id, "status": status,
                "tracking_number": tracking}

    def get_tracking(self, cj_order_id: str) -> dict:
        return self.get_order_status(cj_order_id)


def make_cj_client(cfg: AppConfig):
    if cfg.cj_mode() == "live":
        return CJClient(os.environ["CJ_EMAIL"], os.environ["CJ_API_KEY"],
                        token_cache=cfg.resolve(".cj_token.json"))
    return MockCJClient()
