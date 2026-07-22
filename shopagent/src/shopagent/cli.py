"""shopagent CLI — status | doctor | run | research | draft | orders | support |
marketing | approvals | products."""

from __future__ import annotations

import json
import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import AppConfig, load_config
from .store import Store

app = typer.Typer(
    help="AI agent team for a Shopify dropshipping business. Agents research, "
         "draft, and propose — YOU approve every action that touches the store, "
         "the supplier, or a customer.",
    no_args_is_help=True)
approvals_app = typer.Typer(help="Review and execute proposed actions.", no_args_is_help=True)
orders_app = typer.Typer(help="Order pipeline.", no_args_is_help=True)
products_app = typer.Typer(help="Product pipeline.", no_args_is_help=True)
app.add_typer(approvals_app, name="approvals")
app.add_typer(orders_app, name="orders")
app.add_typer(products_app, name="products")

console = Console()


def _cfg() -> AppConfig:
    return load_config()


def _store(cfg: AppConfig) -> Store:
    return Store(cfg.db_path)


def _ai(cfg: AppConfig):
    from .ai.client import AIClient, MissingAPIKeyError
    try:
        return AIClient(cfg.ai.model, cfg.ai.max_tokens)
    except MissingAPIKeyError as exc:
        raise typer.Exit(code=_fail(str(exc)))


def _clients(cfg: AppConfig):
    from .integrations.amazon_client import make_amazon_client
    from .integrations.cj_client import make_cj_client
    from .integrations.shopify_client import make_shopify_client
    return make_shopify_client(cfg), make_cj_client(cfg), make_amazon_client(cfg)


def _orchestrator(cfg: AppConfig, store: Store):
    from .orchestrator import Orchestrator
    shopify, cj, amazon = _clients(cfg)
    return Orchestrator(_ai(cfg), store, cfg, shopify, cj, amazon=amazon)


def _mode_banner(cfg: AppConfig) -> None:
    shop, cj, amz = cfg.shopify_mode(), cfg.cj_mode(), cfg.amazon_mode()
    style = "yellow" if "mock" in (shop, cj, amz) else "green"
    console.print(f"[{style}]mode: {cfg.mode} | shopify: {shop} | cj: {cj} "
                  f"| amazon: {amz}[/{style}]")
    if cfg.mode == "live" and "mock" in (shop, cj, amz):
        console.print("[yellow]warning: live mode but missing credentials — "
                      "the mock backend is used for the integrations above[/yellow]")


def _fail(msg: str) -> int:
    console.print(f"[red]{msg}[/red]")
    return 1


# ------------------------------------------------------------------ commands

@app.command()
def status() -> None:
    """Pipeline overview: products, orders, pending approvals, recent runs."""
    cfg = _cfg()
    store = _store(cfg)
    _mode_banner(cfg)

    table = Table(title="Products")
    table.add_column("status")
    table.add_column("count", justify="right")
    products = store.list_products()
    for st in ("candidate", "shortlisted", "drafted", "listed", "rejected"):
        n = sum(1 for p in products if p["status"] == st)
        if n:
            table.add_row(st, str(n))
    console.print(table)

    table = Table(title="Orders")
    table.add_column("status")
    table.add_column("count", justify="right")
    orders = store.list_orders()
    for st in ("new", "cj_proposed", "cj_placed", "shipped", "delivered", "attention"):
        n = sum(1 for o in orders if o["status"] == st)
        if n:
            table.add_row(st, str(n))
    console.print(table)

    pending = store.list_approvals("pending")
    if pending:
        console.print(Panel(f"[bold]{len(pending)} action(s) awaiting your approval[/bold] — "
                            "run [cyan]shopagent approvals list[/cyan]", style="yellow"))
    runs = store.list_runs(5)
    if runs:
        table = Table(title="Recent agent runs")
        for col in ("agent", "status", "tool calls", "summary"):
            table.add_column(col)
        for r in runs:
            table.add_row(r["agent"], r["status"], str(r["tool_calls"]),
                          (r["summary"] or "").split("\n")[0][:80])
        console.print(table)


@app.command()
def doctor() -> None:
    """Check configuration, credentials, and database health."""
    cfg = _cfg()
    console.print(f"root: {cfg.root}")
    _mode_banner(cfg)
    checks = [
        ("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")),
         "required for agents to reason"),
        ("SHOPIFY_STORE_DOMAIN", bool(cfg.shop_domain), "for live Shopify"),
        ("SHOPIFY_CLIENT_ID", bool(os.environ.get("SHOPIFY_CLIENT_ID")),
         "Dev Dashboard app auth"),
        ("SHOPIFY_CLIENT_SECRET", bool(os.environ.get("SHOPIFY_CLIENT_SECRET")),
         "Dev Dashboard app auth"),
        ("SHOPIFY_ACCESS_TOKEN", bool(os.environ.get("SHOPIFY_ACCESS_TOKEN")),
         "legacy shpat_ token, pre-2026 apps only"),
        ("CJ_EMAIL", bool(os.environ.get("CJ_EMAIL")), "for live CJ Dropshipping"),
        ("CJ_API_KEY", bool(os.environ.get("CJ_API_KEY")), "for live CJ Dropshipping"),
        ("AMZ_CLIENT_ID", bool(os.environ.get("AMZ_CLIENT_ID")), "Amazon SP-API app"),
        ("AMZ_CLIENT_SECRET", bool(os.environ.get("AMZ_CLIENT_SECRET")),
         "Amazon SP-API app"),
        ("AMZ_REFRESH_TOKEN", bool(os.environ.get("AMZ_REFRESH_TOKEN")),
         "Amazon SP-API self-authorization"),
        ("AMZ_SELLER_ID", bool(os.environ.get("AMZ_SELLER_ID")),
         "Seller Central merchant token"),
    ]
    for name, ok, why in checks:
        mark = "[green]set[/green]" if ok else "[yellow]missing[/yellow]"
        console.print(f"  {name}: {mark}  ({why})")
    console.print(f"  shopify auth method: {cfg.shopify_auth_method()}")
    try:
        store = _store(cfg)
        store.conn.execute("SELECT 1")
        console.print(f"  database: [green]ok[/green] ({cfg.db_path})")
    except Exception as exc:
        console.print(f"  database: [red]{exc}[/red]")
    shopify = cj = amazon = None
    if cfg.shopify_mode() == "live" or cfg.amazon_mode() == "live":
        shopify, cj, amazon = _clients(cfg)
    if cfg.shopify_mode() == "live":
        try:
            shop = shopify.get_shop()
            console.print(f"  shopify: [green]connected to {shop['name']}[/green]")
        except Exception as exc:
            console.print(f"  shopify: [red]{exc}[/red]")
    if cfg.amazon_mode() == "live":
        try:
            seller = amazon.get_seller()
            console.print(f"  amazon: [green]connected to {seller['marketplace']} "
                          f"(seller {seller['seller_id']})[/green]")
            console.print("  [dim]note: buyer addresses also need the "
                          "Direct-to-Consumer Shipping role — if orders sync "
                          "returns 403, see README[/dim]")
        except Exception as exc:
            console.print(f"  amazon: [red]{exc}[/red]")


@app.command()
def run(pipeline: str = typer.Argument("daily", help="Pipeline to run (only: daily)")) -> None:
    """Run the daily pipeline: fulfillment -> support -> research -> listings -> marketing."""
    if pipeline != "daily":
        raise typer.Exit(code=_fail(f"unknown pipeline {pipeline!r}; only 'daily' exists"))
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    console.print("[dim]each agent is a multi-step AI conversation — "
                  "expect a minute or two per agent[/dim]")

    def on_event(kind: str, data: dict) -> None:
        if kind == "start":
            console.print(f"  {data['agent']}: [cyan]running…[/cyan]")
        elif kind == "skip":
            console.print(f"  [dim]{data['agent']}: skipped — {data['skipped']}[/dim]")
        elif data.get("ok"):
            first = data["summary"].splitlines()[0] if data.get("summary") else "done"
            console.print(f"  [green]{data['agent']}[/green]: {first}")
        else:
            console.print(f"  [red]{data['agent']}: {data['error']}[/red]")

    summary = _orchestrator(cfg, store).run_daily(on_event=on_event)
    if summary["pending_approvals"]:
        console.print(Panel(f"[bold]{summary['pending_approvals']} action(s) now pending "
                            "approval[/bold] — run [cyan]shopagent approvals list[/cyan]",
                            style="yellow"))


@app.command()
def research(niche: str = typer.Argument(..., help="Niche to research, e.g. 'pet accessories'"),
             max_products: int = typer.Option(None, "--max", help="Max candidates to save")) -> None:
    """Have the research agent find and evaluate supplier products in a niche."""
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    limit = max_products or cfg.business.max_new_products_per_run
    result = _orchestrator(cfg, store).run_task(
        "research", f"Research the '{niche}' niche and save up to {limit} strong candidates.")
    console.print(result.text)


@app.command()
def draft(what: str = typer.Argument(..., help="What to draft (only: listings)")) -> None:
    """Have the listings agent draft and propose listings for shortlisted products."""
    if what != "listings":
        raise typer.Exit(code=_fail(f"unknown draft target {what!r}; only 'listings' exists"))
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    shortlisted = store.list_products("shortlisted")
    if not shortlisted:
        raise typer.Exit(code=_fail("no shortlisted products — run research first"))
    ids = ", ".join(str(p["id"]) for p in shortlisted)
    result = _orchestrator(cfg, store).run_task(
        "listings", f"Draft listings for shortlisted product ids: {ids}, and propose each "
                    "for the store.")
    console.print(result.text)


@app.command()
def support(action: str = typer.Argument("draft", help="Only: draft")) -> None:
    """Have the support agent draft replies for everything in the inbox."""
    if action != "draft":
        raise typer.Exit(code=_fail(f"unknown support action {action!r}; only 'draft' exists"))
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    _seed_mock_inbox(cfg)
    result = _orchestrator(cfg, store).run_task(
        "support", "Handle every message currently in the inbox.")
    console.print(result.text)


@app.command()
def amazon(action: str = typer.Argument("draft", help="Only: draft")) -> None:
    """Have the Amazon agent cross-list store products onto Amazon (FBM)."""
    if action != "draft":
        raise typer.Exit(code=_fail(f"unknown amazon action {action!r}; only 'draft' exists"))
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    eligible = [p for p in store.list_products("listed") if not p.get("amazon_status")]
    eligible += [p for p in store.list_products("drafted") if not p.get("amazon_status")]
    if not eligible:
        raise typer.Exit(code=_fail(
            "no listed/drafted products without an Amazon status — list something "
            "on the store first (research + draft listings)"))
    ids = ", ".join(str(p["id"]) for p in eligible)
    result = _orchestrator(cfg, store).run_task(
        "amazon", f"Cross-list product ids {ids} onto Amazon: validate each "
                  "listing before proposing it.")
    console.print(result.text)


@app.command()
def marketing(action: str = typer.Argument("draft", help="Only: draft"),
              product_id: Optional[int] = typer.Option(None, "--product-id")) -> None:
    """Have the marketing agent draft content for listed products."""
    if action != "draft":
        raise typer.Exit(code=_fail(f"unknown marketing action {action!r}; only 'draft' exists"))
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    task = ("Draft social, email, and ad content for "
            + (f"listed product id {product_id} only." if product_id
               else "the currently listed products."))
    result = _orchestrator(cfg, store).run_task("marketing", task)
    console.print(result.text)


def _seed_mock_inbox(cfg: AppConfig) -> None:
    """In mock mode, populate an empty inbox with fixture messages so the
    support flow is demonstrable without a real mailbox."""
    if cfg.cj_mode() == "live" and cfg.shopify_mode() == "live":
        return
    inbox = cfg.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    if any(p.suffix == ".txt" for p in inbox.iterdir()):
        return
    from .integrations.fixtures import INBOX_MESSAGES
    for name, content in INBOX_MESSAGES.items():
        (inbox / name).write_text(content, encoding="utf-8")


# ------------------------------------------------------------------ approvals

@approvals_app.command("list")
def approvals_list(show_all: bool = typer.Option(False, "--all",
                                                 help="Include decided approvals")) -> None:
    """List actions awaiting approval."""
    cfg = _cfg()
    store = _store(cfg)
    approvals = store.list_approvals(None if show_all else "pending")
    if not approvals:
        console.print("no pending approvals" if not show_all else "no approvals")
        return
    table = Table(title="Approvals")
    for col in ("id", "status", "agent", "action", "title"):
        table.add_column(col)
    for a in approvals:
        table.add_row(str(a.id), a.status, a.agent, a.action_type, a.title[:60])
    console.print(table)
    console.print("[dim]inspect one with: shopagent approvals show <id>[/dim]")


@approvals_app.command("show")
def approvals_show(approval_id: int) -> None:
    """Show one approval in full, including the exact payload that would execute."""
    cfg = _cfg()
    store = _store(cfg)
    a = store.get_approval(approval_id)
    if a is None:
        raise typer.Exit(code=_fail(f"no approval #{approval_id}"))
    console.print(Panel(
        f"[bold]#{a.id} {a.title}[/bold]\n"
        f"status: {a.status}   agent: {a.agent}   action: {a.action_type}\n"
        f"proposed: {a.created_at}\n\n"
        f"[bold]rationale[/bold]\n{a.rationale or '(none)'}\n\n"
        f"[bold]payload[/bold]\n{json.dumps(a.payload, indent=2)}"
        + (f"\n\n[bold]result[/bold]\n{a.result}" if a.result else "")
        + (f"\n\n[red]error[/red]\n{a.error}" if a.error else "")))


@approvals_app.command("approve")
def approvals_approve(approval_id: int) -> None:
    """Approve a pending action AND execute it immediately."""
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    from .executor import Executor
    try:
        store.decide_approval(approval_id, "approved")
    except ValueError as exc:
        raise typer.Exit(code=_fail(str(exc)))
    shopify, cj, amazon_client = _clients(cfg)
    a = Executor(store, cfg, shopify, cj, amazon=amazon_client).execute(approval_id)
    if a.status == "executed":
        console.print(f"[green]#{approval_id} executed[/green]: {a.result}")
    else:
        console.print(f"[red]#{approval_id} failed[/red]: {a.error}")
        console.print("[dim]fix the issue then: shopagent approvals retry "
                      f"{approval_id}[/dim]")


@approvals_app.command("reject")
def approvals_reject(approval_id: int,
                     note: str = typer.Option("", "--note", help="Why it was rejected")) -> None:
    """Reject a pending action; it will never execute."""
    cfg = _cfg()
    store = _store(cfg)
    try:
        store.decide_approval(approval_id, "rejected", note)
    except ValueError as exc:
        raise typer.Exit(code=_fail(str(exc)))
    console.print(f"#{approval_id} rejected")


@approvals_app.command("retry")
def approvals_retry(approval_id: int) -> None:
    """Re-execute a failed approval."""
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    a = store.get_approval(approval_id)
    if a is None:
        raise typer.Exit(code=_fail(f"no approval #{approval_id}"))
    if a.status != "failed":
        raise typer.Exit(code=_fail(f"approval #{approval_id} is {a.status}, not failed"))
    store.decide_approval(approval_id, "approved")
    from .executor import Executor
    shopify, cj, amazon_client = _clients(cfg)
    a = Executor(store, cfg, shopify, cj, amazon=amazon_client).execute(approval_id)
    if a.status == "executed":
        console.print(f"[green]#{approval_id} executed[/green]: {a.result}")
    else:
        console.print(f"[red]#{approval_id} failed again[/red]: {a.error}")


# --------------------------------------------------------------------- lists

@orders_app.command("sync")
def orders_sync() -> None:
    """Pull unfulfilled Shopify + Amazon orders into the local pipeline (no AI)."""
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    shopify, _, amazon_client = _clients(cfg)

    def _sync(orders: list[dict], channel: str) -> int:
        for order in orders:
            store.upsert_order(
                order["id"],
                channel=channel,
                order_number=order.get("name", ""),
                customer_email=order.get("email", ""),
                line_items_json=json.dumps(order.get("lineItems", [])),
                shipping_address_json=json.dumps(order.get("shippingAddress") or {}),
            )
        return len(orders)

    shopify_count = _sync(shopify.list_open_orders(), "shopify")
    try:
        amazon_count = _sync(amazon_client.list_unshipped_orders(), "amazon")
        console.print(f"synced {shopify_count} shopify + {amazon_count} amazon order(s)")
    except Exception as exc:
        console.print(f"synced {shopify_count} shopify order(s); "
                      f"[red]amazon sync failed: {exc}[/red]")


@orders_app.command("list")
def orders_list(status: Optional[str] = typer.Option(None, "--status")) -> None:
    """List orders in the local pipeline."""
    cfg = _cfg()
    store = _store(cfg)
    orders = store.list_orders(status)
    if not orders:
        console.print("no orders" + (f" with status {status}" if status else ""))
        return
    table = Table(title="Orders")
    for col in ("id", "channel", "number", "status", "customer", "cj order", "tracking"):
        table.add_column(col)
    for o in orders:
        table.add_row(str(o["id"]), o.get("channel", "shopify"), o["order_number"],
                      o["status"], o["customer_email"], o["cj_order_id"],
                      o["tracking_number"])
    console.print(table)


@products_app.command("list")
def products_list(status: Optional[str] = typer.Option(None, "--status")) -> None:
    """List products in the local pipeline."""
    cfg = _cfg()
    store = _store(cfg)
    products = store.list_products(status)
    if not products:
        console.print("no products" + (f" with status {status}" if status else ""))
        return
    table = Table(title="Products")
    for col in ("id", "name", "status", "niche", "cost", "price", "shopify id", "amazon"):
        table.add_column(col)
    for p in products:
        amazon_col = p.get("amazon_status") or ""
        if p.get("amazon_sku"):
            amazon_col = f"{amazon_col} ({p['amazon_sku']})".strip()
        table.add_row(str(p["id"]), p["name"][:40], p["status"], p["niche"],
                      f"{p['supplier_price']:.2f}" if p["supplier_price"] else "",
                      f"{p['proposed_price']:.2f}" if p["proposed_price"] else "",
                      p["shopify_product_id"], amazon_col)
    console.print(table)


if __name__ == "__main__":
    app()
