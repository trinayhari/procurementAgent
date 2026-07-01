"""Best-effort supplier email discovery.

Google Places never returns emails, so we fetch a supplier's website (home +
/contact + /about) and pull addresses from mailto: links and page text. When
several candidates exist and OpenAI is configured, gpt-4.1 picks the best
sales/quotes contact. Every fetch is isolated + timeout-bounded — one bad site
must never fail a search.
"""
import re
from typing import List, NamedTuple, Optional
from urllib.parse import urljoin, urlparse

from app.config import settings

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.IGNORECASE)

# Pages to probe beyond the homepage.
_CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us"]

# Local-parts / domains that are almost never a real sales contact.
_NOISE_LOCALPARTS = {"example", "email", "your", "name", "user", "username", "test"}
_NOISE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
# Local-parts we prefer for an RFQ.
_PREFERRED = ("sales", "quotes", "estimating", "bids", "info", "contact")


class EmailDiscovery(NamedTuple):
    email: Optional[str]
    source: str  # "mailto" | "text" | "llm" | "none"
    confidence: float


def _clean_candidates(raw: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for e in raw:
        e = e.strip().strip(".,;:").lower()
        if not e or e in seen:
            continue
        if e.endswith(_NOISE_EXTS):
            continue
        local = e.split("@", 1)[0]
        if local in _NOISE_LOCALPARTS or "@" not in e:
            continue
        seen.add(e)
        out.append(e)
    return out


def _rank(candidates: List[str]) -> Optional[str]:
    """Deterministic pick: prefer sales/quotes-style local-parts, else first."""
    for pref in _PREFERRED:
        for c in candidates:
            if c.split("@", 1)[0].startswith(pref):
                return c
    return candidates[0] if candidates else None


def _fetch_text(client, url: str) -> str:
    try:
        resp = client.get(url, follow_redirects=True)
        if resp.status_code >= 400:
            return ""
        return resp.text or ""
    except Exception:
        return ""


def _harvest(html: str) -> List[str]:
    return MAILTO_RE.findall(html) + EMAIL_RE.findall(html)


def _llm_pick(candidates: List[str], company: str) -> Optional[str]:
    """Ask gpt-4.1 to choose the best sales/quotes contact. Best-effort."""
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        prompt = (
            "You are picking the single best email to send a construction "
            f"Request-for-Quote to at '{company}'. Choose the most likely sales / "
            "quotes / estimating inbox from this list and reply with ONLY that "
            "email address (or NONE if none are appropriate):\n"
            + "\n".join(candidates)
        )
        resp = client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=40,
        )
        answer = (resp.choices[0].message.content or "").strip().lower()
        match = EMAIL_RE.search(answer)
        if match and match.group(0) in candidates:
            return match.group(0)
    except Exception:
        return None
    return None


def fetch_website_pages(website: Optional[str]) -> List[str]:
    """Fetch homepage + contact/about pages. Returns HTML strings. Never raises."""
    if not website:
        return []
    try:
        import httpx
    except ImportError:
        return []

    base = website if urlparse(website).scheme else f"https://{website}"
    headers = {"User-Agent": "Mozilla/5.0 (ProcureAI supplier sourcing)"}
    pages: List[str] = []

    with httpx.Client(
        timeout=settings.search_email_fetch_timeout_s, headers=headers
    ) as client:
        for path in _CONTACT_PATHS:
            html = _fetch_text(client, urljoin(base, path))
            if html:
                pages.append(html)
            if len(pages) >= 3:
                break
    return pages


def discover_email(
    website: Optional[str],
    company: str = "",
    html_pages: Optional[List[str]] = None,
) -> EmailDiscovery:
    """Discover the best RFQ email for a supplier website. Never raises.

    Pass ``html_pages`` when the caller already fetched the site (e.g. for
    relevance scoring) to avoid a second round-trip.
    """
    if not website and not html_pages:
        return EmailDiscovery(None, "none", 0.0)

    candidates: List[str] = []
    had_mailto = False

    if html_pages is not None:
        for html in html_pages:
            mailtos = MAILTO_RE.findall(html)
            if mailtos:
                had_mailto = True
            candidates.extend(_harvest(html))
            if len(_clean_candidates(candidates)) >= 5:
                break
    else:
        for html in fetch_website_pages(website):
            mailtos = MAILTO_RE.findall(html)
            if mailtos:
                had_mailto = True
            candidates.extend(_harvest(html))
            if len(_clean_candidates(candidates)) >= 5:
                break

    candidates = _clean_candidates(candidates)
    if not candidates:
        return EmailDiscovery(None, "none", 0.0)

    if len(candidates) > 1:
        picked = _llm_pick(candidates, company)
        if picked:
            return EmailDiscovery(picked, "llm", 0.8)

    best = _rank(candidates)
    if best is None:
        return EmailDiscovery(None, "none", 0.0)
    source = "mailto" if had_mailto else "text"
    confidence = 0.7 if best.split("@", 1)[0].startswith(_PREFERRED) else 0.5
    return EmailDiscovery(best, source, confidence)
