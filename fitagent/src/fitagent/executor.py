"""Executes approved upload actions against YouTube.

This is the only code path that publishes anything — and it only runs on
approvals whose status is 'approved' (set by a human via `fitagent approve`,
or automatically when publishing.auto_upload is on). Metadata is resolved
from the video row at execute time, so edits made between approval and
upload are picked up.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .store import Approval, Store


class Executor:
    def __init__(self, store: Store, cfg: AppConfig, youtube):
        self.store = store
        self.cfg = cfg
        self.youtube = youtube
        self._dispatch = {
            "youtube.upload_video": self._upload,
            "youtube.upload_short": self._upload,
        }

    def execute(self, approval_id: int) -> Approval:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no approval with id {approval_id}")
        if approval.status != "approved":
            raise ValueError(
                f"approval #{approval_id} is {approval.status}; only approved "
                "actions can be executed")
        handler = self._dispatch[approval.action_type]
        try:
            result = handler(approval)
        except Exception as exc:
            self.store.mark_failed(approval_id, str(exc)[:1000])
            video_id = approval.payload.get("video_row_id")
            if video_id:
                self.store.update_video(video_id, status="upload_failed",
                                        notes=str(exc)[:500])
            return self.store.get_approval(approval_id)
        self.store.mark_executed(approval_id, json.dumps(result, default=str))
        return self.store.get_approval(approval_id)

    # ------------------------------------------------------------- handlers

    def _upload(self, approval: Approval) -> dict:
        row_id = approval.payload["video_row_id"]
        video = self.store.get_video(row_id)
        if video is None:
            raise ValueError(f"no video row {row_id}")
        if video["status"] not in ("approved", "upload_failed"):
            raise ValueError(f"video #{row_id} is {video['status']}, not approved")
        file_path = Path(video["file_path"])
        if not file_path.exists():
            raise FileNotFoundError(f"rendered file missing: {file_path}")

        meta = json.loads(video["metadata_json"] or "{}")
        privacy = (approval.payload.get("privacy")
                   or video["privacy"] or self.cfg.publishing.default_privacy)
        result = self.youtube.upload(
            file_path=file_path,
            title=meta.get("title") or video["title"] or file_path.stem,
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            category_id=meta.get("category_id", self.cfg.publishing.category_id),
            privacy=privacy,
        )
        self.store.update_video(
            row_id, status="uploaded", youtube_video_id=result["video_id"],
            privacy=privacy,
            published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return result
