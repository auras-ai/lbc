"""
lbc — command-line interface.

Usage:
    lbc login                             # sign in once (headful)
    lbc search "imac" -n 50 --lat 43.33 --lng -0.69 --radius 100000
    lbc search "rtx 3090" --category informatique --price-max 800 --json
    lbc info 3140748683
    lbc inbox -n 10
    lbc send <ad-url> "Bonjour, toujours dispo ?"

Cookie jar / profile persists in the OS user-data dir (see `lbc where`).
"""
from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .ad import fetch_ad
from .browser import BrowserSession, profile_dir
from .messaging import (
    interactive_login,
    is_logged_in,
    list_inbox,
    send_message,
)
from .models import Ad, relative
from .search import CATEGORIES, build_url, search_once, search_paginated

app = typer.Typer(
    add_completion=False,
    help="Leboncoin CLI — browser-emulated search + messaging.",
    no_args_is_help=True,
)
console = Console()


class Fmt(str, Enum):
    pretty = "pretty"
    json = "json"
    yaml = "yaml"


def _emit(payload, fmt: Fmt) -> None:
    """Dump structured data in the chosen format."""
    if fmt is Fmt.json:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    elif fmt is Fmt.yaml:
        typer.echo(yaml.safe_dump(
            payload, sort_keys=False, allow_unicode=True, default_flow_style=False
        ))


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"lbc {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_cb, is_eager=True,
        help="Show version and exit."
    ),
) -> None:
    """Leboncoin CLI."""


# ── search ────────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(..., help="Search text"),
    limit: int = typer.Option(35, "--limit", "-n", help="Max results across all pages"),
    page: int = typer.Option(1, "--page", "-p", help="Starting page (1-based)"),
    category: Optional[str] = typer.Option(None, "--category", "-c",
        help=f"One of: {', '.join(sorted(CATEGORIES))}"),
    lat: Optional[float] = typer.Option(None, help="Latitude (with --lng and --radius)"),
    lng: Optional[float] = typer.Option(None, help="Longitude"),
    radius: Optional[int] = typer.Option(None, "--radius", help="Radius in meters"),
    sort: str = typer.Option("time", "--sort",
        help="time | relevance | price"),
    order: str = typer.Option("desc", "--order", help="asc | desc"),
    price_min: Optional[int] = typer.Option(None, "--price-min"),
    price_max: Optional[int] = typer.Option(None, "--price-max"),
    owner: Optional[str] = typer.Option(None, "--owner",
        help="private | pro | all"),
    fmt: Fmt = typer.Option(Fmt.pretty, "--format", "-f",
        case_sensitive=False, help="pretty | json | yaml"),
    as_json: bool = typer.Option(False, "--json", "-j", help="Shortcut for --format json"),
    as_yaml: bool = typer.Option(False, "--yaml", "-y", help="Shortcut for --format yaml"),
    headed: bool = typer.Option(False, "--headed", help="Show the browser (debug)"),
    debug: Optional[Path] = typer.Option(None, "--debug",
        help="Dump raw HTML / scripts from the extractor into this dir for inspection"),
    open_url: bool = typer.Option(False, "--show-url",
        help="Print the resolved Leboncoin URL and exit"),
) -> None:
    """Search Leboncoin listings."""
    if as_json:
        fmt = Fmt.json
    elif as_yaml:
        fmt = Fmt.yaml

    kwargs = dict(
        text=query, category=category, lat=lat, lng=lng, radius_m=radius,
        sort=sort, order=order, price_min=price_min, price_max=price_max,
        owner_type=owner,
    )
    if open_url:
        typer.echo(build_url(page=page, **kwargs))
        raise typer.Exit()

    try:
        with BrowserSession(headless=not headed, debug_dir=debug) as browser:
            ads = list(search_paginated(browser, max_results=limit, page=page, **kwargs))
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}", highlight=False)
        raise typer.Exit(code=2)

    if fmt is Fmt.pretty:
        _render_table(query, ads)
    else:
        _emit([a.to_json() for a in ads], fmt)


def _render_table(query: str, ads: list[Ad]) -> None:
    if not ads:
        console.print("[yellow]No results.[/yellow]")
        return
    t = Table(title=f"{len(ads)} annonces — {query!r}", show_lines=False, expand=True)
    t.add_column("#", style="dim", width=3)
    t.add_column("Titre", overflow="fold")
    t.add_column("Prix", justify="right", style="bold green")
    t.add_column("Publié", no_wrap=True)
    t.add_column("Lieu", overflow="fold")
    t.add_column("Type", width=4)
    for i, ad in enumerate(ads, 1):
        price = f"{ad.price:,} €".replace(",", " ") if ad.price is not None else "—"
        pub = relative(ad.published_at)
        typ = "[magenta]pro[/magenta]" if ad.owner.is_pro else "part."
        t.add_row(str(i), ad.title, price, pub, str(ad.location), typ)
    console.print(t)
    # Print URLs below the table for easy copy-paste.
    for i, ad in enumerate(ads, 1):
        console.print(f"  [dim]{i}.[/dim] {ad.url}")


# ── info ──────────────────────────────────────────────────────────────────────

@app.command()
def info(
    ad_id: str = typer.Argument(..., help="Leboncoin ad id, e.g. 3140748683"),
    fmt: Fmt = typer.Option(Fmt.pretty, "--format", "-f",
        case_sensitive=False, help="pretty | json | yaml"),
    as_json: bool = typer.Option(False, "--json", "-j", help="Shortcut for --format json"),
    as_yaml: bool = typer.Option(False, "--yaml", "-y", help="Shortcut for --format yaml"),
    headed: bool = typer.Option(False, "--headed"),
) -> None:
    """Fetch full details for a single ad."""
    if as_json:
        fmt = Fmt.json
    elif as_yaml:
        fmt = Fmt.yaml
    with BrowserSession(headless=not headed) as browser:
        ad = fetch_ad(browser, ad_id)
    if fmt is not Fmt.pretty:
        _emit(ad.to_json(), fmt)
        return
    console.print(Text(ad.title, style="bold"))
    price = f"{ad.price:,} €".replace(",", " ") if ad.price is not None else "—"
    console.print(f"[green]{price}[/green]  ·  {relative(ad.published_at)}  ·  {ad.location}")
    console.print(f"[dim]{ad.url}[/dim]")
    console.print(f"[dim]vendeur:[/dim] {ad.owner.name or '?'} "
                  f"({'[magenta]pro[/magenta]' if ad.owner.is_pro else 'particulier'})")
    if ad.body:
        console.print()
        console.print(ad.body)
    if ad.attributes:
        console.print()
        console.print("[dim]attributs:[/dim]")
        for k, v in ad.attributes.items():
            console.print(f"  {k} = {v}")
    if ad.images:
        console.print()
        console.print("[dim]images:[/dim]")
        for u in ad.images[:5]:
            console.print(f"  {u}")


# ── auth + messaging ──────────────────────────────────────────────────────────

@app.command()
def login(
    timeout: int = typer.Option(300, "--timeout", help="Seconds to wait for manual sign-in"),
) -> None:
    """Open a browser and let the user sign in. Session is saved to the profile."""
    with BrowserSession(headless=False) as browser:
        if is_logged_in(browser):
            console.print("[green]Already signed in.[/green]")
            return
        ok = interactive_login(browser, timeout_s=timeout)
    console.print("[green]Signed in.[/green]" if ok else "[red]Login timed out.[/red]")
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def whoami() -> None:
    """Check whether the persistent profile is signed in."""
    with BrowserSession(headless=True) as browser:
        yes = is_logged_in(browser)
    console.print("[green]logged in[/green]" if yes else "[yellow]not logged in[/yellow]")


@app.command()
def send(
    ad_url: str = typer.Argument(..., help="Full ad URL, e.g. https://www.leboncoin.fr/ad/..."),
    message: str = typer.Argument(..., help="Message body"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fill the form but don't click Send"),
    headed: bool = typer.Option(True, "--headed/--headless",
        help="Show the browser (default) so you can watch / intervene"),
) -> None:
    """Send a message to a seller on a given ad."""
    with BrowserSession(headless=not headed) as browser:
        if not is_logged_in(browser):
            console.print("[red]Not signed in.[/red] Run `lbc login` first.")
            raise typer.Exit(code=2)
        ok = send_message(browser, ad_url, message, dry_run=dry_run)
    console.print("[green]sent.[/green]" if ok else "[red]send failed.[/red]")


@app.command()
def inbox(
    limit: int = typer.Option(20, "--limit", "-n"),
    fmt: Fmt = typer.Option(Fmt.pretty, "--format", "-f", case_sensitive=False),
    as_json: bool = typer.Option(False, "--json", "-j"),
    as_yaml: bool = typer.Option(False, "--yaml", "-y"),
    headed: bool = typer.Option(False, "--headed"),
) -> None:
    """List recent conversations from your Leboncoin inbox."""
    if as_json:
        fmt = Fmt.json
    elif as_yaml:
        fmt = Fmt.yaml
    with BrowserSession(headless=not headed) as browser:
        if not is_logged_in(browser):
            console.print("[red]Not signed in.[/red] Run `lbc login` first.")
            raise typer.Exit(code=2)
        convs = list(list_inbox(browser, limit=limit))
    if fmt is not Fmt.pretty:
        _emit(convs, fmt)
        return
    if not convs:
        console.print("[yellow]empty inbox (or the inbox schema changed — try --json).[/yellow]")
        return
    t = Table(show_lines=False)
    t.add_column("#", style="dim", width=3)
    t.add_column("Annonce")
    t.add_column("Interlocuteur")
    t.add_column("Dernier message", overflow="fold")
    t.add_column("●", width=1)
    for i, c in enumerate(convs, 1):
        t.add_row(
            str(i),
            (c.get("ad_title") or "—")[:60],
            c.get("peer") or "?",
            (c.get("last_message") or "")[:80],
            "●" if c.get("unread") else "",
        )
    console.print(t)


# ── utility ──────────────────────────────────────────────────────────────────

@app.command()
def where() -> None:
    """Print the path of the persistent browser profile."""
    typer.echo(str(profile_dir()))


@app.command()
def bot() -> None:
    """Start the Telegram bot (reads TELEGRAM_BOT_TOKEN from .env)."""
    from .bot import main as bot_main
    bot_main()


def main() -> None:  # entry point for `python -m lbc`
    app()


if __name__ == "__main__":
    main()
