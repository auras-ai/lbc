"""Write operations — messaging."""
from __future__ import annotations

from ...browser import BrowserSession
from ...messaging import send_message


class MutationService:

    @staticmethod
    def send_message(
        browser: BrowserSession,
        ad_url: str,
        message: str,
        *,
        dry_run: bool = False,
    ) -> bool:
        return send_message(browser, ad_url, message, dry_run=dry_run)
