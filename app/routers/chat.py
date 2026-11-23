"""Chat pane: STUB ONLY (phase 2 wires up full Hermes integration).

POST /api/chat proxies to HERMES_CHAT_ENDPOINT when configured; otherwise it
answers with a disabled notice. No secrets involved — the endpoint is an
internal LAN URL.
"""
import logging

import httpx
from fastapi import APIRouter

from .. import config
from ..models import ChatIn, ChatOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatOut)
async def chat(body: ChatIn) -> ChatOut:
    if not config.HERMES_CHAT_ENDPOINT:
        return ChatOut(
            enabled=False,
            reply=(
                "Chat is disabled — HERMES_CHAT_ENDPOINT is not set. "
                "Full Hermes wiring is phase 2."
            ),
        )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                config.HERMES_CHAT_ENDPOINT,
                json={"message": body.message},
                headers={"User-Agent": config.USER_AGENT},
            )
            r.raise_for_status()
            try:
                upstream = r.json()
            except ValueError:
                upstream = {"text": r.text[:2000]}
            reply = upstream.get("reply") or upstream.get("text") or str(upstream)[:2000]
            return ChatOut(enabled=True, reply=str(reply), upstream=upstream)
    except Exception as e:  # noqa: BLE001 — stub: report, don't crash
        log.warning("chat proxy failed: %s", e)
        # enabled=True is deliberate: the feature IS configured (endpoint set),
        # so the UI keeps the pane visible and surfaces the failure in `reply`.
        return ChatOut(
            enabled=True,
            reply=f"Chat upstream error: {e.__class__.__name__}. Try again shortly.",
        )
