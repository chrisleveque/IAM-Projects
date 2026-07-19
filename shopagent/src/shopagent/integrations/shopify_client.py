"""Shopify Admin GraphQL API client + in-process mock.

The REST Admin API is legacy (product endpoints are unavailable to newly
created custom apps), so everything goes through the single GraphQL endpoint.

Both classes expose the same methods — that set is the store interface used
by agents (read-only) and the executor (mutations):

    get_shop() -> dict
    list_products(limit) -> list[dict]
    create_product(title, description_html, tags, price, vendor) -> dict
    update_product(shopify_product_id, fields) -> dict
    list_open_orders(limit) -> list[dict]
    get_order(order_id) -> dict | None
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import AppConfig
from . import fixtures


class ShopifyError(RuntimeError):
    pass


class ClientCredentialsAuth:
    """OAuth client credentials grant for Dev Dashboard apps (the only kind of
    custom app Shopify allows since Jan 2026).

    Exchanges the app's client id + secret for an Admin access token valid
    ~24h. Shopify requires the request body to be form-urlencoded, not JSON.
    Tokens are cached in a gitignored file and refreshed shortly before
    expiry, or immediately when the API answers 401.
    """

    def __init__(self, shop_domain: str, client_id: str, client_secret: str,
                 token_cache: Path, http):
        self._url = f"https://{shop_domain}/admin/oauth/access_token"
        self._client_id = client_id
        self._client_secret = client_secret
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
            self._url,
            data={"grant_type": "client_credentials",
                  "client_id": self._client_id,
                  "client_secret": self._client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("location", "")
            raise ShopifyError(
                "token request was redirected"
                + (f" to {location}" if location else "")
                + " — SHOPIFY_STORE_DOMAIN must be the canonical *.myshopify.com "
                "domain, not a custom storefront domain. Find it in the admin URL: "
                "admin.shopify.com/store/<handle> means <handle>.myshopify.com."
            )
        if resp.status_code != 200:
            raise ShopifyError(
                f"token request failed ({resp.status_code}): {resp.text[:300]}. "
                "Check SHOPIFY_CLIENT_ID/SHOPIFY_CLIENT_SECRET and that the app "
                "is installed on this store."
            )
        body = resp.json()
        token = body["access_token"]
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=int(body.get("expires_in", 86399)))
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


class ShopifyClient:
    def __init__(self, shop_domain: str, access_token: str | None = None,
                 api_version: str = "2025-07", auth: ClientCredentialsAuth | None = None,
                 transport=None):
        """Authenticate with either a static token (legacy shpat_ apps) or a
        ClientCredentialsAuth (Dev Dashboard apps); exactly one must be given.
        Build via ``for_client_credentials`` for the latter so both share the
        underlying HTTP client."""
        import httpx  # lazy so tests importing the module need no network stack

        if (access_token is None) == (auth is None):
            raise ValueError("pass exactly one of access_token or auth")
        self.endpoint = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        self._static_token = access_token
        self._auth = auth
        self._http = getattr(auth, "_http", None) or httpx.Client(
            timeout=30.0, transport=transport)

    @classmethod
    def for_client_credentials(cls, shop_domain: str, client_id: str, client_secret: str,
                               token_cache: Path, api_version: str = "2025-07",
                               transport=None) -> "ShopifyClient":
        import httpx

        http = httpx.Client(timeout=30.0, transport=transport)
        auth = ClientCredentialsAuth(shop_domain, client_id, client_secret,
                                     token_cache, http)
        return cls(shop_domain, api_version=api_version, auth=auth)

    def _post_gql(self, query: str, variables: dict):
        token = self._static_token if self._auth is None else self._auth.token()
        return self._http.post(
            self.endpoint,
            json={"query": query, "variables": variables},
            headers={"X-Shopify-Access-Token": token,
                     "Content-Type": "application/json"},
        )

    def _gql(self, query: str, variables: dict | None = None) -> dict:
        resp = self._post_gql(query, variables or {})
        if resp.status_code == 401 and self._auth is not None:
            # cached client-credentials token expired mid-flight; refresh once
            self._auth.invalidate()
            resp = self._post_gql(query, variables or {})
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise ShopifyError(f"GraphQL errors: {json.dumps(body['errors'])[:500]}")
        return body["data"]

    @staticmethod
    def _check_user_errors(payload: dict, op: str) -> None:
        errs = payload.get("userErrors") or []
        if errs:
            raise ShopifyError(f"{op} userErrors: {json.dumps(errs)[:500]}")

    def get_shop(self) -> dict:
        data = self._gql("{ shop { name myshopifyDomain currencyCode } }")
        return data["shop"]

    def list_products(self, limit: int = 20) -> list[dict]:
        data = self._gql(
            """
            query($n: Int!) {
              products(first: $n, sortKey: UPDATED_AT, reverse: true) {
                nodes {
                  id title status vendor tags
                  variants(first: 1) { nodes { id price } }
                }
              }
            }
            """,
            {"n": limit},
        )
        out = []
        for node in data["products"]["nodes"]:
            variants = node.pop("variants")["nodes"]
            node["price"] = variants[0]["price"] if variants else ""
            out.append(node)
        return out

    def create_product(self, title: str, description_html: str, tags: list[str],
                       price: str, vendor: str = "") -> dict:
        # productCreate cannot set a variant price; Shopify auto-creates a
        # default variant which we then price with a bulk variant update.
        data = self._gql(
            """
            mutation($product: ProductCreateInput!) {
              productCreate(product: $product) {
                product { id title variants(first: 1) { nodes { id } } }
                userErrors { field message }
              }
            }
            """,
            {"product": {"title": title, "descriptionHtml": description_html,
                         "tags": tags, "vendor": vendor}},
        )
        payload = data["productCreate"]
        self._check_user_errors(payload, "productCreate")
        product = payload["product"]
        variant_nodes = product["variants"]["nodes"]
        if variant_nodes:
            data = self._gql(
                """
                mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
                  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                    userErrors { field message }
                  }
                }
                """,
                {"productId": product["id"],
                 "variants": [{"id": variant_nodes[0]["id"], "price": price}]},
            )
            self._check_user_errors(data["productVariantsBulkUpdate"],
                                    "productVariantsBulkUpdate")
        return {"id": product["id"], "title": product["title"], "price": price}

    def update_product(self, shopify_product_id: str, fields: dict) -> dict:
        product_input = {"id": shopify_product_id}
        for key in ("title", "descriptionHtml", "tags", "vendor", "status"):
            if key in fields:
                product_input[key] = fields[key]
        data = self._gql(
            """
            mutation($product: ProductUpdateInput!) {
              productUpdate(product: $product) {
                product { id title }
                userErrors { field message }
              }
            }
            """,
            {"product": product_input},
        )
        payload = data["productUpdate"]
        self._check_user_errors(payload, "productUpdate")
        return payload["product"]

    def list_open_orders(self, limit: int = 20) -> list[dict]:
        data = self._gql(
            """
            query($n: Int!) {
              orders(first: $n, query: "fulfillment_status:unfulfilled status:open") {
                nodes {
                  id name email displayFulfillmentStatus
                  lineItems(first: 20) {
                    nodes { title quantity sku
                            originalUnitPriceSet { shopMoney { amount } } }
                  }
                  shippingAddress { name address1 address2 city provinceCode zip
                                    countryCodeV2 phone }
                }
              }
            }
            """,
            {"n": limit},
        )
        out = []
        for node in data["orders"]["nodes"]:
            items = []
            for li in node.pop("lineItems")["nodes"]:
                price = (li.pop("originalUnitPriceSet") or {}).get("shopMoney", {}).get("amount", "")
                items.append({**li, "price": price})
            node["lineItems"] = items
            out.append(node)
        return out

    def get_order(self, order_id: str) -> dict | None:
        for order in self.list_open_orders(limit=50):
            if order["id"] == order_id or order["name"] == order_id:
                return order
        return None


class MockShopifyClient:
    """Deterministic in-memory Shopify store seeded from fixtures.

    Mutations really mutate the in-memory state, so an approved+executed
    mock action is visible to subsequent reads within the same process.
    """

    def __init__(self):
        self._products = copy.deepcopy(fixtures.SHOPIFY_SEED_PRODUCTS)
        self._orders = copy.deepcopy(fixtures.SHOPIFY_SEED_ORDERS)
        self._next_id = 9000000100

    def get_shop(self) -> dict:
        return {"name": "Mock Store (dry run)", "myshopifyDomain": "mock-store.myshopify.com",
                "currencyCode": "USD"}

    def list_products(self, limit: int = 20) -> list[dict]:
        return copy.deepcopy(self._products[:limit])

    def create_product(self, title: str, description_html: str, tags: list[str],
                       price: str, vendor: str = "") -> dict:
        product = {"id": f"gid://shopify/Product/{self._next_id}", "title": title,
                   "status": "ACTIVE", "vendor": vendor, "tags": list(tags),
                   "price": str(price), "description_html": description_html}
        self._next_id += 1
        self._products.append(product)
        return {"id": product["id"], "title": title, "price": str(price)}

    def update_product(self, shopify_product_id: str, fields: dict) -> dict:
        for product in self._products:
            if product["id"] == shopify_product_id:
                product.update(fields)
                return {"id": product["id"], "title": product["title"]}
        raise ShopifyError(f"mock: no product {shopify_product_id}")

    def list_open_orders(self, limit: int = 20) -> list[dict]:
        return copy.deepcopy(self._orders[:limit])

    def get_order(self, order_id: str) -> dict | None:
        for order in self._orders:
            if order["id"] == order_id or order["name"] == order_id:
                return copy.deepcopy(order)
        return None


def make_shopify_client(cfg: AppConfig):
    if cfg.shopify_mode() != "live":
        return MockShopifyClient()
    if os.environ.get("SHOPIFY_ACCESS_TOKEN"):
        return ShopifyClient(cfg.shop_domain, os.environ["SHOPIFY_ACCESS_TOKEN"],
                             cfg.store.api_version)
    return ShopifyClient.for_client_credentials(
        cfg.shop_domain,
        os.environ["SHOPIFY_CLIENT_ID"],
        os.environ["SHOPIFY_CLIENT_SECRET"],
        token_cache=cfg.resolve(".shopify_token.json"),
        api_version=cfg.store.api_version,
    )
