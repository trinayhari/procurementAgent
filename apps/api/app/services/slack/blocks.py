"""Block Kit rendering for notices and confirmations.

A notice becomes: a header (title), one section with the lines as a bulleted
mrkdwn list, an actions block with one button per Action, and, for the
milestone kinds, a "Proq" context line. The approve button carries the
approval URL in `value` so the click can be executed server-side (the
interactions handler pulls the token out of it); every other button just
opens its url.
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.services.notify import Action, Notice

APPROVE_ACTION_ID = "approve_award"
OPEN_URL_ACTION_ID = "open_url"
# Kinds that get the "Proq" context footer.
_FOOTER_KINDS = {"award.ready", "po.issued"}
# Slack limits: header plain_text 150 chars, button text 75, value 2000.
_HEADER_MAX = 150
_BUTTON_MAX = 75

_TOKEN_RE = re.compile(r"/approve/([A-Za-z0-9_\-]+)")


def _plain(text: str, limit: int) -> dict:
    text = text.strip() or " "
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return {"type": "plain_text", "text": text, "emoji": True}


def approval_token_from(value: str) -> Optional[str]:
    """The approval token inside an action url like <base>/#/approve/<token>."""
    m = _TOKEN_RE.search(value or "")
    return m.group(1) if m else None


def button(action: Action, url_index: int = 0) -> dict:
    """`url_index` numbers the url buttons: action_ids must be unique within
    the block, so the second open-url button becomes `open_url_1`."""
    is_approve = action.label.strip().lower().startswith("approve")
    if is_approve:
        action_id = APPROVE_ACTION_ID
    else:
        action_id = OPEN_URL_ACTION_ID if url_index == 0 else f"{OPEN_URL_ACTION_ID}_{url_index}"
    el = {"type": "button", "text": _plain(action.label, _BUTTON_MAX), "action_id": action_id}
    if is_approve:
        el["value"] = action.url[:2000]
    else:
        el["url"] = action.url
    if action.style == "primary":
        el["style"] = "primary"
    return el


def render_notice(notice: Notice) -> List[dict]:
    blocks: List[dict] = [{"type": "header", "text": _plain(notice.title, _HEADER_MAX)}]
    if notice.lines:
        body = "\n".join(f"• {line}" for line in notice.lines if line)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body[:3000]}})
    if notice.actions:
        elements = []
        url_buttons = 0
        for action in notice.actions:
            el = button(action, url_buttons)
            if el["action_id"] != APPROVE_ACTION_ID:
                url_buttons += 1
            elements.append(el)
        blocks.append({"type": "actions", "elements": elements})
    if notice.kind in _FOOTER_KINDS:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Proq"}]})
    return blocks


def render_confirmation(title: str, lines: List[str]) -> List[dict]:
    """What an award card becomes once the button was clicked."""
    blocks: List[dict] = [{"type": "header", "text": _plain(title, _HEADER_MAX)}]
    if lines:
        body = "\n".join(f"• {line}" for line in lines if line)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body[:3000]}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Proq"}]})
    return blocks


def render_text(text: str) -> List[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}]
