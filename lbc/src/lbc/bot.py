"""
Telegram bot for Leboncoin research.

Runs on your machine (where the persistent Chromium profile + Datadome cookie
live), exposes search/info/message functionality via Telegram so you can hunt
deals from your phone.

Commands:
    /start              — welcome + usage
    /search <query>     — search Leboncoin (supports inline filters)
    /s <query>          — alias
    /info <ad_id>       — full ad details
    /msg <ad_url> <txt> — send a message to a seller (dry-run first)
    /cybex              — list saved Cybex Gold Bouncer results
    /help               — show this list

Inline filters for /search:
    max:<price>         — price max
    min:<price>         — price min
    cat:<category>      — category slug
    geo:<lat>,<lng>,<radius_m>  — geo filter
    n:<limit>           — max results (default 10)

Examples:
    /search rtx 4090 max:800 cat:informatique n:15
    /s cybex bouncer
    /info 3140748683

Start with:
    uv run lbc-bot          (reads .env for TELEGRAM_BOT_TOKEN)
    TELEGRAM_BOT_TOKEN=... uv run lbc-bot
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .browser import BrowserSession
from .models import Ad, relative
from .search import CATEGORIES, search_paginated
from .ad import fetch_ad
from .messaging import send_message, is_logged_in

logger = logging.getLogger("lbc.bot")

# Thread pool for synchronous Playwright calls.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pw")


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_inline_filters(tokens: list[str]) -> tuple[str, dict[str, Any]]:
    """Split a token list into (query_text, filter_kwargs)."""
    query_parts: list[str] = []
    kw: dict[str, Any] = {}
    for t in tokens:
        if m := re.match(r"max:(\d+)", t):
            kw["price_max"] = int(m.group(1))
        elif m := re.match(r"min:(\d+)", t):
            kw["price_min"] = int(m.group(1))
        elif m := re.match(r"cat:(\w+)", t):
            kw["category"] = m.group(1)
        elif m := re.match(r"n:(\d+)", t):
            kw["max_results"] = int(m.group(1))
        elif m := re.match(r"geo:([\d.]+),([\d.-]+),(\d+)", t):
            kw["lat"] = float(m.group(1))
            kw["lng"] = float(m.group(2))
            kw["radius_m"] = int(m.group(3))
        elif m := re.match(r"owner:(private|pro)", t):
            kw["owner_type"] = m.group(1)
        else:
            query_parts.append(t)
    return " ".join(query_parts), kw


def _fmt_ad(i: int, ad: Ad) -> str:
    price = f"{ad.price:,} €".replace(",", " ") if ad.price is not None else "prix ?"
    pub = relative(ad.published_at)
    pro = " 🏢" if ad.owner.is_pro else ""
    loc = str(ad.location) if ad.location.city else ""
    loc_str = f"📍 {loc}" if loc else ""
    return (
        f"*{i}.* [{_esc(ad.title)}]({ad.url})\n"
        f"   💰 {_esc(price)}  ·  🕐 {_esc(pub)}{pro}\n"
        f"   {_esc(loc_str)}"
    )


def _esc(text: str) -> str:
    """Escape MarkdownV2 special chars."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)


def _run_sync(fn, *args, **kwargs):
    """Run a sync function in the thread pool, return a coroutine."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, partial(fn, *args, **kwargs))


# ── Playwright wrappers (sync, run via executor) ─────────────────────────────

def _do_search(text: str, max_results: int = 10, **kwargs) -> list[Ad]:
    with BrowserSession(headless=True) as browser:
        return list(search_paginated(
            browser, text=text, max_results=max_results, **kwargs
        ))


def _do_info(ad_id: str) -> Ad:
    with BrowserSession(headless=True) as browser:
        return fetch_ad(browser, ad_id)


def _do_send(ad_url: str, message: str, dry_run: bool = False) -> bool:
    with BrowserSession(headless=True) as browser:
        if not is_logged_in(browser):
            raise RuntimeError("not logged in — run `lbc login` first")
        return send_message(browser, ad_url, message, dry_run=dry_run)


def _do_check_login() -> bool:
    with BrowserSession(headless=True) as browser:
        return is_logged_in(browser)


# ── command handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔍 *Leboncoin Bot*\n\n"
        "Commandes:\n"
        "  /search \\<query\\> — rechercher\n"
        "  /s \\<query\\> — alias\n"
        "  /info \\<ad\\_id\\> — détails annonce\n"
        "  /msg \\<url\\> \\<texte\\> — envoyer message\n"
        "  /cybex — résultats Cybex sauvegardés\n"
        "  /help — aide\n\n"
        "Filtres inline: `max:800 min:50 cat:informatique n:20`\n"
        "Exemple: `/search rtx 4090 max:800 n:15`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: /search <query> [max:N] [cat:slug] [n:N]")
        return

    query, kw = _parse_inline_filters(ctx.args)
    if not query:
        await update.message.reply_text("❌ Requête vide.")
        return

    max_results = kw.pop("max_results", 10)
    msg = await update.message.reply_text(f"🔍 Recherche *{_esc(query)}*…", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        ads = await _run_sync(_do_search, query, max_results=max_results, **kw)
    except Exception as e:
        await msg.edit_text(f"❌ Erreur: {e}")
        return

    if not ads:
        await msg.edit_text("Aucun résultat.")
        return

    # Send in chunks of 5 to avoid Telegram message length limits.
    lines = [f"*{len(ads)} résultats pour* _{_esc(query)}_\n"]
    for i, ad in enumerate(ads, 1):
        lines.append(_fmt_ad(i, ad))
        if i % 5 == 0 or i == len(ads):
            text = "\n".join(lines)
            if i <= 5:
                await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
            else:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
            lines = []


async def cmd_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: /info <ad_id>")
        return

    ad_id = ctx.args[0].strip()
    # Accept full URL too
    m = re.search(r"/ad/[^/]+/(\d+)", ad_id)
    if m:
        ad_id = m.group(1)

    msg = await update.message.reply_text(f"📋 Chargement annonce {ad_id}…")
    try:
        ad = await _run_sync(_do_info, ad_id)
    except Exception as e:
        await msg.edit_text(f"❌ Erreur: {e}")
        return

    price = f"{ad.price:,} €".replace(",", " ") if ad.price is not None else "?"
    pro = "🏢 Pro" if ad.owner.is_pro else "👤 Particulier"
    body = (ad.body or "")[:500]
    if len(ad.body or "") > 500:
        body += "…"

    text = (
        f"*{_esc(ad.title)}*\n\n"
        f"💰 {_esc(price)}  ·  🕐 {_esc(relative(ad.published_at))}\n"
        f"📍 {_esc(str(ad.location))}\n"
        f"{_esc(pro)}  ·  {_esc(ad.owner.name or '?')}\n\n"
        f"{_esc(body)}\n\n"
        f"🔗 [Voir l'annonce]({ad.url})"
    )
    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

    # Send first image as a photo if available
    if ad.images:
        try:
            await update.message.reply_photo(ad.images[0])
        except Exception:
            pass


async def cmd_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(
            "Usage: /msg <ad_url> <message>\n"
            "Exemple: /msg https://www.leboncoin.fr/ad/... Bonjour, toujours dispo ?"
        )
        return

    ad_url = ctx.args[0]
    message_text = " ".join(ctx.args[1:])

    msg = await update.message.reply_text(
        f"📩 Envoi du message…\n\n"
        f"→ {ad_url}\n"
        f"→ _{_esc(message_text)}_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    try:
        ok = await _run_sync(_do_send, ad_url, message_text)
        if ok:
            await msg.edit_text("✅ Message envoyé !")
        else:
            await msg.edit_text("❌ Échec de l'envoi.")
    except Exception as e:
        await msg.edit_text(f"❌ Erreur: {e}")


async def cmd_cybex(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """List saved Cybex research results."""
    # Look for the YAML in several places
    for p in (
        Path("cybex_results.yml"),
        Path(__file__).parent.parent.parent / "cybex_results.yml",
        Path.home() / "conductor" / "workspaces" / "lbc" / "madrid" / "cybex_results.yml",
        Path.home() / "conductor" / "workspaces" / "lbc" / "madrid" / "lbc" / "cybex_results.yml",
    ):
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f)
            break
    else:
        await update.message.reply_text("❌ Fichier cybex_results.yml non trouvé.")
        return

    ads = data.get("ads", [])
    if not ads:
        await update.message.reply_text("Aucune annonce Cybex sauvegardée.")
        return

    lines = [f"🍼 *{len(ads)} annonces Cybex Gold Bouncer*\n"]
    for i, ad in enumerate(ads[:15], 1):
        price = f"{ad['price']} €" if ad.get("price") else "?"
        title = ad.get("title", "?")
        url = ad.get("url", "")
        status = ad.get("status", "")
        icon = "✅" if status == "contacted" else "📋"
        lines.append(f"{icon} *{i}\\.* [{_esc(title)}]({url})  ·  {_esc(price)}")

    if len(ads) > 15:
        lines.append(f"\n_\\.\\.\\. et {len(ads) - 15} de plus_")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, ctx)


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain text → treat as a search query."""
    text = update.message.text.strip()
    if not text:
        return
    # Simulate /search
    ctx.args = text.split()
    await cmd_search(update, ctx)


# ── entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: set TELEGRAM_BOT_TOKEN in .env or environment", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
        level=logging.INFO,
    )
    logger.info("Starting lbc Telegram bot…")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler(["search", "s"], cmd_search))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("msg", cmd_msg))
    app.add_handler(CommandHandler("cybex", cmd_cybex))
    # Plain text messages = implicit search
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot polling — send /start in Telegram to begin.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
