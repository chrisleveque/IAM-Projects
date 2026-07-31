"""Read-mostly HTTP API over the pipeline, so an external automation (n8n,
a phone shortcut, a cron) can see what the agents propose and act on it.

Design constraint that matters more than any endpoint here: **the approval
gate lives in this file's shape.** There is deliberately no way to *propose*
an action over HTTP — proposals only come from agents running locally — and
the decision endpoints (approve/reject/retry) are POST-only so they cannot be
triggered by a link preview or a crawler.

If you wire this into an LLM agent, attach only the GET endpoints as tools.
The moment an agent can call POST /approvals/{id}/approve, the human gate is
gone and you are back to trusting a prompt. Decisions should come from a
person tapping a button.

Auth is a single bearer token (SHOPAGENT_API_TOKEN). That is adequate for one
operator behind a tunnel; it is not a multi-user permission system.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from .config import AppConfig, load_config
from .store import APPROVAL_STATUSES, ORDER_STATUSES, PRODUCT_STATUSES, Approval, Store


class RejectBody(BaseModel):
    note: str = ""


def _approval_summary(a: Approval) -> dict:
    """List view: enough to decide whether to look closer, no payload."""
    return {
        "id": a.id,
        "status": a.status,
        "agent": a.agent,
        "action_type": a.action_type,
        "title": a.title,
        "created_at": a.created_at,
    }


def _approval_detail(a: Approval) -> dict:
    """Detail view: the exact payload that would execute, so a human can
    actually judge it rather than approving a title."""
    return {
        **_approval_summary(a),
        "rationale": a.rationale,
        "payload": a.payload,
        "ref_table": a.ref_table,
        "ref_id": a.ref_id,
        "result": json.loads(a.result) if _is_json(a.result) else a.result,
        "error": a.error,
        "decided_at": a.decided_at,
        "executed_at": a.executed_at,
    }


def _is_json(raw: str) -> bool:
    if not raw:
        return False
    try:
        json.loads(raw)
    except (ValueError, TypeError):
        return False
    return True


def create_app(cfg: AppConfig | None = None, token: str = "") -> FastAPI:
    """Build the API. ``token`` is required — an unauthenticated instance of
    this API is a remote-control for someone's live store, so refusing to
    start is the right failure mode."""
    if not token:
        raise ValueError(
            "an API token is required; set SHOPAGENT_API_TOKEN to a long "
            "random string (this API can spend money and email customers)"
        )
    config = cfg or load_config()
    app = FastAPI(
        title="shopagent",
        description="Pipeline visibility and approval decisions for the agent team.",
        version="0.1.0",
    )

    def require_token(authorization: Optional[str] = Header(None)) -> None:
        expected = f"Bearer {token}"
        # compare full strings; a prefix check would accept a truncated token
        if authorization != expected:
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    def open_store() -> Store:
        # SQLite connections are not shareable across threads, so each request
        # opens its own rather than holding one on the app
        return Store(config.db_path)

    auth = [Depends(require_token)]

    # ------------------------------------------------------------- unauthed

    @app.get("/health")
    def health() -> dict:
        """Liveness only — deliberately reveals nothing about the business, so
        it is safe to hit from a tunnel health check."""
        return {"ok": True, "service": "shopagent"}

    # ------------------------------------------------------------ read side

    @app.get("/status", dependencies=auth)
    def status() -> dict:
        store = open_store()
        try:
            pending = store.list_approvals("pending")
            return {
                "mode": config.mode,
                "integrations": {
                    "shopify": config.shopify_mode(),
                    "cj": config.cj_mode(),
                    "amazon": config.amazon_mode(),
                },
                "pending_approvals": len(pending),
                "products": {
                    s: len(store.list_products(s)) for s in PRODUCT_STATUSES
                },
                "orders": {s: len(store.list_orders(s)) for s in ORDER_STATUSES},
                "recent_runs": store.list_runs(5),
            }
        finally:
            store.close()

    @app.get("/approvals", dependencies=auth)
    def list_approvals(
        status: str = Query("pending",
                            description="Approval status, or 'all' for every row"),
    ) -> dict:
        if status != "all" and status not in APPROVAL_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"status must be 'all' or one of {list(APPROVAL_STATUSES)}")
        store = open_store()
        try:
            approvals = store.list_approvals(None if status == "all" else status)
            return {"count": len(approvals),
                    "approvals": [_approval_summary(a) for a in approvals]}
        finally:
            store.close()

    def _detail_or_404(approval_id: int) -> dict:
        store = open_store()
        try:
            approval = store.get_approval(approval_id)
            if approval is None:
                raise HTTPException(status_code=404,
                                    detail=f"no approval #{approval_id}")
            return _approval_detail(approval)
        finally:
            store.close()

    @app.get("/approvals/{approval_id}", dependencies=auth)
    def get_approval(approval_id: int) -> dict:
        return _detail_or_404(approval_id)

    @app.get("/approval", dependencies=auth)
    def get_approval_by_query(id: int = Query(..., description="Approval id")) -> dict:
        """Same as GET /approvals/{id}, with the id as a query parameter.

        n8n's HTTP Request Tool fills query parameters reliably but its URL
        placeholder mechanism has been unstable across versions, so a tool node
        can point here and let the model supply ?id= instead.
        """
        return _detail_or_404(id)

    @app.get("/products", dependencies=auth)
    def list_products(status: Optional[str] = Query(None)) -> dict:
        if status and status not in PRODUCT_STATUSES:
            raise HTTPException(status_code=400,
                                detail=f"status must be one of {list(PRODUCT_STATUSES)}")
        store = open_store()
        try:
            products = store.list_products(status)
            return {"count": len(products), "products": products}
        finally:
            store.close()

    @app.get("/orders", dependencies=auth)
    def list_orders(status: Optional[str] = Query(None),
                    channel: Optional[str] = Query(None)) -> dict:
        if status and status not in ORDER_STATUSES:
            raise HTTPException(status_code=400,
                                detail=f"status must be one of {list(ORDER_STATUSES)}")
        store = open_store()
        try:
            orders = store.list_orders(status)
            if channel:
                orders = [o for o in orders if o.get("channel") == channel]
            return {"count": len(orders), "orders": orders}
        finally:
            store.close()

    @app.get("/videos", dependencies=auth)
    def list_videos() -> dict:
        """Rendered ads and where they sit on disk, so the phone agent can
        report what's ready to post without shell access."""
        store = open_store()
        try:
            videos = [
                {"product_id": p["id"], "name": p["name"],
                 "tiktok_status": p.get("tiktok_status", ""),
                 "video_path": p["video_path"], "price": p["proposed_price"]}
                for p in store.list_products() if p.get("video_path")
            ]
            return {"count": len(videos), "videos": videos,
                    "before_posting": (
                        "Swap in a TikTok Commercial Music Library track before "
                        "running any of these as a paid ad.")}
        finally:
            store.close()

    @app.get("/trends", dependencies=auth)
    def list_trends(kind: Optional[str] = Query(None),
                    limit: int = Query(30, ge=1, le=200)) -> dict:
        store = open_store()
        try:
            trends = store.list_trends(kind=kind, limit=limit)
            return {"count": len(trends), "trends": trends}
        finally:
            store.close()

    # --------------------------------------------------------- decision side

    def _execute(store: Store, approval_id: int) -> Approval:
        from .executor import Executor
        from .integrations.amazon_client import make_amazon_client
        from .integrations.cj_client import make_cj_client
        from .integrations.shopify_client import make_shopify_client
        executor = Executor(store, config, make_shopify_client(config),
                            make_cj_client(config),
                            amazon=make_amazon_client(config))
        return executor.execute(approval_id)

    def _decision_response(approval: Approval) -> dict:
        return {
            "id": approval.id,
            "status": approval.status,
            "result": json.loads(approval.result) if _is_json(approval.result)
            else approval.result,
            "error": approval.error,
        }

    @app.post("/approvals/{approval_id}/approve", dependencies=auth)
    def approve(approval_id: int) -> dict:
        """Approve AND execute, matching `shopagent approvals approve`.

        A failed execution is reported with HTTP 200 and status 'failed' — the
        decision itself succeeded, and the caller needs the error text to know
        what to fix. Check the ``status`` field, not just the HTTP code.
        """
        store = open_store()
        try:
            try:
                store.decide_approval(approval_id, "approved")
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            return _decision_response(_execute(store, approval_id))
        finally:
            store.close()

    @app.post("/approvals/{approval_id}/reject", dependencies=auth)
    def reject(approval_id: int, body: RejectBody | None = None) -> dict:
        store = open_store()
        try:
            try:
                approval = store.decide_approval(approval_id, "rejected",
                                                 (body or RejectBody()).note)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            return _decision_response(approval)
        finally:
            store.close()

    @app.post("/approvals/{approval_id}/retry", dependencies=auth)
    def retry(approval_id: int) -> dict:
        store = open_store()
        try:
            approval = store.get_approval(approval_id)
            if approval is None:
                raise HTTPException(status_code=404,
                                    detail=f"no approval #{approval_id}")
            if approval.status != "failed":
                raise HTTPException(
                    status_code=409,
                    detail=f"approval #{approval_id} is {approval.status}, not failed")
            store.decide_approval(approval_id, "approved")
            return _decision_response(_execute(store, approval_id))
        finally:
            store.close()

    return app
