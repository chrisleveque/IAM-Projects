"""Content agent: writes short-form video ads for listed products.

Like every other agent it renders nothing itself — it proposes
``tiktok.render_video`` actions and the executor does the work on approval.

The prompt carries two constraints that are easy to get wrong and expensive to
get wrong: the music licensing rule (a royalty-free bed is safe to render, but
only a Commercial Music Library track is safe for a Business-account ad), and
the rule that every claim has to come from the product's real listing data.
"""

from __future__ import annotations

import json

from .base import Agent

MUSIC_RULE = (
    "Music: the tracks trending on TikTok are commercial recordings. Using one "
    "on a Business account or in a paid ad is a copyright violation and TikTok "
    "will mute or remove the video. You can only search royalty-free catalogues "
    "(Pixabay, Jamendo), which is what gets rendered into the draft. In every "
    "rationale, tell the owner to swap in a track from TikTok's Commercial "
    "Music Library before posting as an ad — that library is browsable only in "
    "the TikTok app, so it is a manual step by design, not an oversight."
)


class ContentAgent(Agent):
    name = "content"
    description = "Writes TikTok/Reels ad scripts for listed products and proposes renders."

    def system_prompt(self) -> str:
        return (
            "You are the short-form video agent for a pet-niche dropshipping "
            "store. You write vertical ad scripts for products that are already "
            "listed, and propose them for rendering.\n\n"
            "For each product you're asked about, call get_video_candidates, "
            "read the trend notes, then write ONE script and submit it with "
            "propose_action (tiktok.render_video), ref_table='products' and "
            "ref_id set to the product's local id.\n\n"
            "The payload is {product_id, script, music_query}, where script is "
            "{hook, shots, cta}:\n"
            "- hook: the first thing on screen, under 40 characters. It must "
            "name the problem the viewer already has, not the product. "
            "'Your dog eats way too fast' works; 'Introducing our lick mat' "
            "does not.\n"
            "- shots: one short caption per shot, 3 to 6 of them, under 45 "
            "characters each. One idea per shot. Each maps to one product "
            "photo, in order, so write them to match photos of that product.\n"
            "- cta: 4 words or fewer, e.g. 'Link in bio'.\n"
            "- music_query: 2-4 words describing the mood for a royalty-free "
            "search, e.g. 'upbeat playful ukulele'. Not a song title.\n\n"
            "Ground every claim in the product's real listing copy and specs. "
            "Do not invent discounts, reviews, scarcity, health claims, or "
            "capabilities the listing doesn't state. If a shot needs a fact you "
            "don't have, write a different shot.\n\n"
            "Use the trend notes to choose format and angle, but never repeat a "
            "trend's view counts as if they were your product's numbers.\n\n"
            + MUSIC_RULE +
            "\n\nOne propose_action per product. Finish with a short summary of "
            "what you wrote and why that angle."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "get_video_candidates",
                "description": (
                    "Products that are listed and have supplier photos saved, with "
                    "their listing copy, price, and how many photos exist. The photo "
                    "count is the maximum number of shots a script can use."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer",
                                       "description": "Optional: one product only"},
                        "include_done": {
                            "type": "boolean",
                            "description": ("Include products that already have a "
                                            "video (default false)")},
                    },
                },
            },
            {
                "name": "read_trend_notes",
                "description": (
                    "Trend observations imported from TikTok Creative Center or an "
                    "analytics tool. These are captured by hand — no public API "
                    "exposes trending TikTok Shop products — so they may be stale. "
                    "Check captured_at before leaning on a number."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string",
                                 "description": "Optional filter: hashtag, format, product, note"},
                        "limit": {"type": "integer"},
                    },
                },
            },
            {
                "name": "search_music",
                "description": (
                    "Search royalty-free music (Pixabay/Jamendo) for a mood. Returns "
                    "tracks licensed for commercial use. Use this to sanity-check "
                    "that a music_query returns anything before proposing it."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        ]
        return schemas, {
            "get_video_candidates": self._candidates,
            "read_trend_notes": self._trends,
            "search_music": self._search_music,
        }

    def _candidates(self, inp: dict) -> list[dict]:
        products = self.store.list_products("listed")
        if inp.get("product_id"):
            products = [p for p in products if p["id"] == inp["product_id"]]
        if not inp.get("include_done"):
            products = [p for p in products if not p.get("tiktok_status")]
        out = []
        for product in products:
            images = json.loads(product["images_json"] or "[]")
            if not images:
                continue  # nothing to render from
            listing = json.loads(product["listing_json"]) if product["listing_json"] else {}
            out.append({
                "id": product["id"],
                "name": product["name"],
                "niche": product["niche"],
                "price": product["proposed_price"],
                "photo_count": len(images),
                "listing": listing,
                "tiktok_status": product.get("tiktok_status", ""),
            })
        return out

    def _trends(self, inp: dict) -> list[dict]:
        return self.store.list_trends(kind=inp.get("kind"),
                                      limit=int(inp.get("limit") or 25))

    def _search_music(self, inp: dict) -> list[dict]:
        if self.music is None:
            return [{"note": "no music provider configured; the render will have "
                             "no soundtrack until PIXABAY_API_KEY or "
                             "JAMENDO_CLIENT_ID is set"}]
        return self.music.search(inp["query"], limit=int(inp.get("limit") or 5))
