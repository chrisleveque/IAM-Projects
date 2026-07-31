"""Executes approved actions against the real integrations.

This is the only code path that mutates the store, the supplier, or produces
customer-facing output — and it only runs on approvals whose status is
'approved' (set by a human via `shopagent approvals approve`). On success it
writes results back onto the linked pipeline rows; on failure the approval is
marked failed and can be retried.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .store import Approval, Store


class Executor:
    def __init__(self, store: Store, cfg: AppConfig, shopify, cj, amazon=None,
                 music=None, tiktok=None, json2video=None, ai=None):
        self.store = store
        self.cfg = cfg
        self.shopify = shopify
        self.cj = cj
        self.amazon = amazon
        self.music = music
        self.tiktok = tiktok
        self.json2video = json2video
        # optional LLM, used ONLY to repair rejected render specs — the
        # executor never lets a model decide WHAT to execute, that stays with
        # the approvals queue
        self.ai = ai
        self._dispatch = {
            "shopify.create_product": self._shopify_create_product,
            "shopify.update_product": self._shopify_update_product,
            "shopify.fulfill_order": self._shopify_fulfill_order,
            "amazon.create_listing": self._amazon_create_listing,
            "amazon.update_price": self._amazon_update_price,
            "amazon.confirm_shipment": self._amazon_confirm_shipment,
            "cj.create_order": self._cj_create_order,
            "tiktok.render_video": self._tiktok_render_video,
            "tiktok.upload_draft": self._tiktok_upload_draft,
            "support.send_reply": self._support_send_reply,
            "marketing.publish": self._marketing_publish,
        }

    def execute(self, approval_id: int) -> Approval:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no approval with id {approval_id}")
        if approval.status != "approved":
            raise ValueError(
                f"approval #{approval_id} is {approval.status}; only approved "
                "actions can be executed"
            )
        handler = self._dispatch[approval.action_type]
        try:
            result = handler(approval)
        except Exception as exc:
            self.store.mark_failed(approval_id, str(exc)[:1000])
            return self.store.get_approval(approval_id)
        self.store.mark_executed(approval_id, json.dumps(result, default=str))
        return self.store.get_approval(approval_id)

    # ------------------------------------------------------------- handlers

    def _shopify_create_product(self, approval: Approval) -> dict:
        p = approval.payload
        # attach supplier photos saved on the linked pipeline product, so the
        # store listing never goes up imageless (payload may override)
        image_urls = p.get("image_urls")
        if not image_urls and approval.ref_table == "products" and approval.ref_id:
            product = self.store.get_product(approval.ref_id)
            if product and product.get("images_json"):
                image_urls = json.loads(product["images_json"])
        result = self.shopify.create_product(
            title=p["title"], description_html=p["description_html"],
            tags=p["tags"], price=str(p["price"]), vendor=p.get("vendor", ""),
            image_urls=image_urls or [],
        )
        result["images_attached"] = len(image_urls or [])
        if approval.ref_table == "products" and approval.ref_id:
            self.store.update_product(approval.ref_id,
                                      shopify_product_id=result["id"], status="listed")
        return result

    def _shopify_update_product(self, approval: Approval) -> dict:
        p = approval.payload
        return self.shopify.update_product(p["shopify_product_id"], p["fields"])

    def _shopify_fulfill_order(self, approval: Approval) -> dict:
        p = approval.payload
        result = self.shopify.fulfill_order(
            p["shopify_order_id"], p["tracking_number"],
            tracking_company=p.get("tracking_company", "CJPacket"),
            notify_customer=p.get("notify_customer", True),
        )
        if approval.ref_table == "orders" and approval.ref_id:
            self.store.update_order(approval.ref_id, status="shipped",
                                    tracking_number=p["tracking_number"])
        return result

    def _require_amazon(self):
        if self.amazon is None:
            raise RuntimeError("Amazon client not configured for this executor")
        return self.amazon

    def _amazon_create_listing(self, approval: Approval) -> dict:
        p = approval.payload
        result = self._require_amazon().put_listing(
            p["sku"], p["product_type"], p["attributes"])
        if approval.ref_table == "products" and approval.ref_id:
            self.store.update_product(
                approval.ref_id, amazon_sku=p["sku"],
                amazon_submission_id=result.get("submission_id", ""),
                amazon_status="submitted")
        return result

    def _amazon_update_price(self, approval: Approval) -> dict:
        p = approval.payload
        return self._require_amazon().update_price(
            p["sku"], p["product_type"], float(p["price"]))

    def _amazon_confirm_shipment(self, approval: Approval) -> dict:
        p = approval.payload
        result = self._require_amazon().confirm_shipment(
            p["amazon_order_id"], p["tracking_number"],
            carrier_code=p.get("carrier_code", self.cfg.amazon.carrier_default),
            carrier_name=p.get("carrier_name", self.cfg.amazon.carrier_name_default),
            order_items=p["order_items"],
        )
        if approval.ref_table == "orders" and approval.ref_id:
            self.store.update_order(approval.ref_id, status="shipped",
                                    tracking_number=p["tracking_number"])
        return result

    def _cj_create_order(self, approval: Approval) -> dict:
        p = approval.payload
        result = self.cj.create_order(
            order_ref=p["order_ref"], cj_items=p["cj_items"],
            shipping_address=p["shipping_address"], logistic_name=p["logistic_name"],
        )
        if approval.ref_table == "orders" and approval.ref_id:
            self.store.update_order(approval.ref_id,
                                    cj_order_id=result["cj_order_id"], status="cj_placed")
        return result

    # ------------------------------------------------------------- tiktok

    REPAIR_SYSTEM = (
        "You fix rejected JSON2Video movie specifications. You are given the "
        "API's error message and the movie JSON that produced it. Return ONLY "
        "the corrected movie JSON object — same structure, minimal changes, "
        "no commentary. Typical fixes: remove or rename an unsupported "
        "property, shorten text that overflows an element, replace an invalid "
        "enum value with a documented one, drop a broken element entirely. "
        "Never invent new media URLs and never change which product photos "
        "are shown."
    )

    def _tiktok_render_video(self, approval: Approval) -> dict:
        """Render a vertical ad from the product's supplier photos.

        Engine comes from cfg.render_engine(): the JSON2Video cloud editor
        when a key is configured (with a bounded LLM repair loop and an
        ffmpeg fallback), else the local ffmpeg renderer. Rendering is
        deliberately not gated on any TikTok credential — the mp4 lands in
        output/video/ and can be uploaded by hand. Uploading to drafts is a
        separate, optional action.
        """
        p = approval.payload
        product = self.store.get_product(int(p["product_id"]))
        if product is None:
            raise ValueError(f"no product with id {p['product_id']}")
        image_urls = p.get("image_urls") or json.loads(product["images_json"] or "[]")
        if not image_urls:
            raise ValueError(
                f"product {product['name']!r} has no saved photos to build a video "
                "from; run `shopagent products import` to attach supplier images")

        slug = re.sub(r"[^a-z0-9]+", "-", product["name"].lower()).strip("-")[:50]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_dir = self.cfg.output_dir / "video"
        out_path = out_dir / f"{stamp}_{slug}.mp4"

        result: dict | None = None
        if self.cfg.render_engine() == "json2video" and self.json2video is not None:
            result = self._render_json2video(p, image_urls, out_path)
        if result is None:
            fallback_note = None if self.cfg.render_engine() == "ffmpeg" else (
                "json2video failed after repair attempts; rendered with the "
                "local ffmpeg engine instead — see repair_errors")
            ffmpeg_result = self._render_ffmpeg(p, image_urls, out_dir, out_path,
                                                stamp, slug)
            if fallback_note and hasattr(self, "_last_repair_errors"):
                ffmpeg_result["fallback"] = fallback_note
                ffmpeg_result["repair_errors"] = self._last_repair_errors
            result = ffmpeg_result

        self.store.update_product(int(p["product_id"]),
                                  tiktok_status="rendered",
                                  video_path=result["video_path"])
        # the bed is safe to render; it is not what makes a paid ad safe
        result["before_posting"] = (
            "Swap in a track from TikTok's Commercial Music Library before "
            "running this as an ad or posting from a Business account.")
        return result

    def _render_json2video(self, p: dict, image_urls: list[str],
                           out_path) -> dict | None:
        """Cloud render with up to 2 LLM repair attempts. Returns None when it
        cannot produce a video, so the caller falls back to ffmpeg."""
        from .integrations.json2video_client import (JSON2VideoError,
                                                     build_movie)

        video_cfg = self.cfg.video
        music_url = ""
        track = None
        query = p.get("music_query", "")
        if query and self.music is not None:
            results = self.music.search(query, limit=5)
            # the cloud renderer fetches media itself, so only a public URL
            # helps it; a mock:// placeholder would fail the whole render
            for candidate in results:
                if str(candidate.get("url", "")).startswith("http"):
                    track = candidate
                    music_url = candidate["url"]
                    break

        movie = build_movie(
            p["script"], image_urls,
            width=video_cfg.width, height=video_cfg.height,
            seconds_per_shot=video_cfg.seconds_per_shot,
            max_seconds=video_cfg.max_seconds,
            brand_name=video_cfg.brand_name,
            accent_color=video_cfg.accent_color,
            music_url=music_url, voiceover=video_cfg.voiceover)

        errors: list[str] = []
        for attempt in range(3):  # first try + 2 repairs
            try:
                rendered = self.json2video.render(movie, out_path)
                result = {"engine": "json2video", "shots": len(image_urls),
                          "video_path": rendered["video_path"],
                          "credits": rendered.get("credits")}
                if errors:
                    result["repaired_after"] = errors
                if track:
                    result["music"] = {"title": track["title"],
                                       "artist": track["artist"],
                                       "license": track["license"]}
                if video_cfg.voiceover:
                    result["voiceover"] = "narrated by json2video TTS"
                return result
            except JSON2VideoError as exc:
                errors.append(str(exc)[:500])
                if attempt >= 2 or self.ai is None:
                    break
                repaired = self.ai.complete_json(
                    self.REPAIR_SYSTEM,
                    json.dumps({"error": str(exc), "movie": movie}))
                if not isinstance(repaired, dict) or not repaired.get("scenes"):
                    break  # the model gave nothing usable; stop burning credits
                movie = repaired
        self._last_repair_errors = errors
        return None

    def _render_ffmpeg(self, p: dict, image_urls: list[str], out_dir,
                       out_path, stamp: str, slug: str) -> dict:
        from .video.render import Script, fetch_images, render_slideshow

        video_cfg = self.cfg.video
        work = out_dir / f".{stamp}_{slug}_work"
        images = fetch_images(image_urls, work / "img")
        if not images:
            raise ValueError("every product image failed to download")

        music_path = None
        track = None
        query = p.get("music_query", "")
        if query and self.music is not None:
            results = self.music.search(query, limit=5)
            if results:
                track = results[0]
                music_path = self.music.download(track, work / "bed.mp3")

        voice_path = None
        voice_note = ""
        if video_cfg.voiceover:
            from .video.voice import VoiceError, script_to_speech_text, synthesize
            try:
                voice_path = synthesize(script_to_speech_text(p["script"]),
                                        work / "voice.mp3")
            except VoiceError as exc:
                # a broken voice must not cost the render; note it and move on
                voice_note = f"voiceover skipped: {exc}"

        out_path = render_slideshow(
            images, Script.from_dict(p["script"]), out_path,
            music_path=music_path, voice_path=voice_path,
            width=video_cfg.width, height=video_cfg.height, fps=video_cfg.fps,
            seconds_per_shot=video_cfg.seconds_per_shot,
            max_seconds=video_cfg.max_seconds, music_volume=video_cfg.music_volume,
            font_size_hook=video_cfg.font_size_hook,
            font_size_caption=video_cfg.font_size_caption,
            brand_name=video_cfg.brand_name, accent_color=video_cfg.accent_color,
            transition_seconds=video_cfg.transition_seconds,
            end_card_seconds=video_cfg.end_card_seconds,
            work_dir=work)

        result = {"engine": "ffmpeg", "video_path": str(out_path),
                  "shots": len(images)}
        if voice_note:
            result["voiceover"] = voice_note
        elif voice_path:
            result["voiceover"] = "synthesized (experimental edge-tts)"
        if track:
            result["music"] = {"title": track["title"], "artist": track["artist"],
                               "license": track["license"]}
            if "placeholder" in track["license"]:
                result["music"]["note"] = (
                    "placeholder tone, not real music — set JAMENDO_CLIENT_ID "
                    "(free at devportal.jamendo.com) for licensed tracks")
        return result

    def _tiktok_upload_draft(self, approval: Approval) -> dict:
        if self.tiktok is None:
            raise RuntimeError(
                "TikTok client not configured; the rendered video is still in "
                "output/video/ and can be uploaded from the app by hand")
        p = approval.payload
        path = Path(p["video_path"])
        if not path.exists():
            raise ValueError(f"video not found: {path}")
        result = self.tiktok.upload_draft(path, p["caption"])
        if approval.ref_table == "products" and approval.ref_id:
            self.store.update_product(approval.ref_id, tiktok_status="uploaded")
        return result

    def _support_send_reply(self, approval: Approval) -> dict:
        p = approval.payload
        path = self._write_output("replies", p["subject"],
                                  f"To: {p['customer_email']}\n"
                                  f"Subject: {p['subject']}\n\n{p['body']}\n")
        return {"written_to": str(path),
                "note": "copy-ready reply file; sending email is manual in v1"}

    def _marketing_publish(self, approval: Approval) -> dict:
        p = approval.payload
        path = self._write_output(f"marketing/{p['channel']}", p["title"],
                                  f"# {p['title']}\n\n{p['body']}\n")
        return {"written_to": str(path),
                "note": "copy-ready content file; posting is manual in v1"}

    def _write_output(self, subdir: str, name: str, content: str):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "untitled"
        out_dir = self.cfg.output_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{stamp}_{slug}.md"
        # explicit utf-8: Windows defaults to cp1252, which chokes on emoji
        path.write_text(content, encoding="utf-8")
        return path
