"""Deterministic fixture data backing the mock Shopify store and CJ catalog.

Everything here is static so tests and dry runs are reproducible.
"""

from __future__ import annotations

# ---------------------------------------------------------------- CJ catalog

CJ_CATALOG: list[dict] = [
    # pet accessories
    {"pid": "CJ-PET-001", "vid": "V-PET-001-A", "name": "Collapsible Silicone Pet Travel Bowl (2-Pack)",
     "niche": "pet accessories", "sell_price": 3.20, "category": "Pet Supplies",
     "description": "Food-grade silicone bowls that fold flat; carabiner clip included."},
    {"pid": "CJ-PET-002", "vid": "V-PET-002-A", "name": "LED Safety Dog Collar, USB Rechargeable",
     "niche": "pet accessories", "sell_price": 4.85, "category": "Pet Supplies",
     "description": "Three glow modes, adjustable strap, one-hour charge lasts 8 nights."},
    {"pid": "CJ-PET-003", "vid": "V-PET-003-A", "name": "Self-Cleaning Slicker Brush for Cats & Dogs",
     "niche": "pet accessories", "sell_price": 5.40, "category": "Pet Supplies",
     "description": "Retractable bristles release collected fur with one click."},
    {"pid": "CJ-PET-004", "vid": "V-PET-004-A", "name": "No-Spill Dog Water Bottle 550ml",
     "niche": "pet accessories", "sell_price": 6.10, "category": "Pet Supplies",
     "description": "Trigger-fed trough bowl; unused water drains back into the bottle."},
    # home organization
    {"pid": "CJ-HOME-001", "vid": "V-HOME-001-A", "name": "Under-Sink Expandable Storage Rack",
     "niche": "home organization", "sell_price": 8.90, "category": "Home & Garden",
     "description": "Two-tier steel rack that telescopes around pipes, 40-70cm."},
    {"pid": "CJ-HOME-002", "vid": "V-HOME-002-A", "name": "Magnetic Spice Jars with Wall Strip (Set of 6)",
     "niche": "home organization", "sell_price": 11.25, "category": "Home & Garden",
     "description": "Glass jars, airtight lids, stainless wall strip mounts with adhesive."},
    {"pid": "CJ-HOME-003", "vid": "V-HOME-003-A", "name": "Vacuum Compression Storage Bags (5-Pack)",
     "niche": "home organization", "sell_price": 7.60, "category": "Home & Garden",
     "description": "Triple-seal valve bags, hand pump included, 80% space saving."},
    {"pid": "CJ-HOME-004", "vid": "V-HOME-004-A", "name": "Rotating Corner Shelf Organizer",
     "niche": "home organization", "sell_price": 9.75, "category": "Home & Garden",
     "description": "360° lazy-susan corner rack for kitchen or bathroom counters."},
    # fitness gear
    {"pid": "CJ-FIT-001", "vid": "V-FIT-001-A", "name": "Adjustable Resistance Bands Set (5 Levels)",
     "niche": "fitness gear", "sell_price": 6.95, "category": "Sports",
     "description": "Latex bands 10-50lb with handles, ankle straps, and door anchor."},
    {"pid": "CJ-FIT-002", "vid": "V-FIT-002-A", "name": "Smart Jump Rope with Calorie Counter",
     "niche": "fitness gear", "sell_price": 8.30, "category": "Sports",
     "description": "LCD handle counts jumps and calories; cordless ball mode included."},
    {"pid": "CJ-FIT-003", "vid": "V-FIT-003-A", "name": "Deep Tissue Massage Ball Roller Set",
     "niche": "fitness gear", "sell_price": 5.15, "category": "Sports",
     "description": "Spiky ball, lacrosse ball, and peanut roller in mesh carry bag."},
    {"pid": "CJ-FIT-004", "vid": "V-FIT-004-A", "name": "Non-Slip Yoga Mat Towel with Corner Pockets",
     "niche": "fitness gear", "sell_price": 9.40, "category": "Sports",
     "description": "Microfiber towel grips when damp; corner pockets hold it to the mat."},
]

# Freight per product id: deterministic pseudo-quote used by the mock client.
CJ_FREIGHT_USD = {p["pid"]: round(2.0 + (i % 4) * 0.75, 2) for i, p in enumerate(CJ_CATALOG)}

# CJ order status progression the mock walks through on repeated polls.
CJ_STATUS_SEQUENCE = ["CREATED", "IN_CART", "UNSHIPPED", "SHIPPED", "DELIVERED"]

MOCK_TRACKING_PREFIX = "CJMOCK"

# -------------------------------------------------------------- mock Shopify

SHOPIFY_SEED_PRODUCTS: list[dict] = [
    {"id": "gid://shopify/Product/9000000001", "title": "LED Safety Dog Collar, USB Rechargeable",
     "status": "ACTIVE", "vendor": "shopagent", "tags": ["pets", "safety"], "price": "14.99"},
]

SHOPIFY_SEED_ORDERS: list[dict] = [
    {
        "id": "gid://shopify/Order/8000000001",
        "name": "#1001",
        "email": "jamie.rivera@example.com",
        "displayFulfillmentStatus": "UNFULFILLED",
        "lineItems": [
            {"title": "LED Safety Dog Collar, USB Rechargeable", "quantity": 1,
             "sku": "V-PET-002-A", "price": "14.99"},
        ],
        "shippingAddress": {
            "name": "Jamie Rivera", "address1": "428 Maple Ave", "city": "Austin",
            "provinceCode": "TX", "zip": "78701", "countryCodeV2": "US",
            "phone": "+1 512 555 0142",
        },
    },
    {
        "id": "gid://shopify/Order/8000000002",
        "name": "#1002",
        "email": "morgan.chen@example.com",
        "displayFulfillmentStatus": "UNFULFILLED",
        "lineItems": [
            {"title": "Collapsible Silicone Pet Travel Bowl (2-Pack)", "quantity": 2,
             "sku": "V-PET-001-A", "price": "9.99"},
        ],
        "shippingAddress": {
            "name": "Morgan Chen", "address1": "77 Birch St Apt 3B", "city": "Portland",
            "provinceCode": "OR", "zip": "97201", "countryCodeV2": "US",
            "phone": "+1 503 555 0197",
        },
    },
]

# -------------------------------------------------------------- mock Amazon

AMAZON_PRODUCT_TYPES = ["PET_SUPPLIES", "PRODUCT"]

AMAZON_SEED_ORDERS: list[dict] = [
    {
        "id": "111-2233445-6677889",
        "name": "111-2233445-6677889",
        "email": "riley.okafor@example.com",
        "lineItems": [
            {"title": "LED Safety Dog Collar, USB Rechargeable", "quantity": 1,
             "sku": "V-PET-002-A", "price": "16.99", "order_item_id": "OI-0001"},
        ],
        "shippingAddress": {
            "name": "Riley Okafor", "address1": "902 Cedar Ln", "address2": "",
            "city": "Denver", "provinceCode": "CO", "zip": "80202",
            "countryCodeV2": "US", "phone": "+1 720 555 0163",
        },
    },
    {
        "id": "112-9988776-5544332",
        "name": "112-9988776-5544332",
        "email": "casey.nguyen@example.com",
        "lineItems": [
            {"title": "Adjustable Resistance Bands Set (5 Levels)", "quantity": 1,
             "sku": "V-FIT-001-A", "price": "18.99", "order_item_id": "OI-0002"},
        ],
        "shippingAddress": {
            "name": "Casey Nguyen", "address1": "15 Willow Ct", "address2": "Apt 2",
            "city": "Raleigh", "provinceCode": "NC", "zip": "27601",
            "countryCodeV2": "US", "phone": "+1 919 555 0128",
        },
    },
]

# ----------------------------------------------------------------- mock inbox

INBOX_MESSAGES: dict[str, str] = {
    "msg_001_where_is_my_order.txt": (
        "From: jamie.rivera@example.com\n"
        "Subject: Where is my order #1001?\n\n"
        "Hi, I ordered an LED dog collar last week (order #1001) and haven't\n"
        "seen any shipping update. Can you tell me when it will arrive?\n"
    ),
    "msg_002_product_question.txt": (
        "From: sam.taylor@example.com\n"
        "Subject: Question about the travel bowls\n\n"
        "Before I buy — are the collapsible travel bowls dishwasher safe, and\n"
        "how big are they when folded?\n"
    ),
}
