"""Plain-text helpers for inbound email: HTML to text, reply-chain
stripping and address parsing. Transport-agnostic; the AgentMail webhook and
the quote parser both read through here."""
import html
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import List


def decode_rfc2047(value: str) -> str:
    """`=?utf-8?q?Jane_Doe?=` -> `Jane Doe` (no-op otherwise)."""
    if not value or "=?" not in value:
        return value or ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


_BR_RE = re.compile(r"<\s*br\s*/?>|</\s*(p|div|tr|li|h[1-6]|blockquote)\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_STYLE_RE = re.compile(r"<\s*(style|script|head)[^>]*>.*?</\s*\1\s*>", re.I | re.S)
_BLOCKQUOTE_RE = re.compile(r"<\s*blockquote[^>]*>.*", re.I | re.S)


def html_to_text(markup: str) -> str:
    """A readable plain-text rendering of an HTML-only email body.

    Outlook, Apple Mail and many CRMs send HTML with no text/plain alternative;
    left as-is the conversation view showed raw tags (or only the snippet) and
    the quote parser saw nothing. Block-level closers become newlines, the
    quoted chain in a <blockquote> is dropped, entities are unescaped.
    """
    if not markup:
        return ""
    text = _STYLE_RE.sub("", markup)
    # Gmail wraps the quoted history in <blockquote class="gmail_quote">; Apple
    # Mail uses a plain <blockquote>. Everything from the first one on is the
    # prior conversation, not this message.
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    out: List[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def parse_addr(raw: str) -> str:
    """'Sales <a@b.com>' → 'a@b.com' (lower-cased; '' when there is none)."""
    return parseaddr(decode_rfc2047(raw or ""))[1].strip().lower()


def parse_name(raw: str) -> str:
    """'Sales <a@b.com>' → 'Sales' (falls back to the address)."""
    name, addr = parseaddr(decode_rfc2047(raw or ""))
    name = (name or "").strip().strip('"').strip()
    return name or addr.strip().lower()


# Reply-chain markers, one per client family. Anything from the marker line on
# is the prior conversation, not this message.
_ON_WROTE_RE = re.compile(r"^(On|Le|Am|El|Il)\s.{0,300}?(wrote|a écrit|schrieb|escribió|ha scritto)\s*:\s*$", re.S)
_HEADER_BLOCK_START = re.compile(r"^(\*?\*?)(From|De|Von)\s*:\s*\*?\*?\s*\S", re.I)
_HEADER_BLOCK_NEXT = re.compile(r"^(\*?\*?)(Sent|To|Date|Subject|Cc|Envoyé|À|Gesendet|An)\s*:", re.I)
_SEPARATOR_RE = re.compile(r"^-{2,}\s*(Original Message|Forwarded message|Mensaje original|Message d'origine)\s*-{2,}\s*$", re.I)


def strip_quoted(text: str) -> str:
    """Drop the quoted reply chain so each message shows only its new content.

    Handles the styles seen in practice:
      - Gmail / Apple Mail:  "On Tue, Sep 16, 2026 at 3:00 PM Jane <a@b> wrote:"
        (Gmail wraps the long form over two lines: the "wrote:" lands on the
        next line, so the marker is matched across up to three lines)
      - Outlook:             "-----Original Message-----" or a bare
        "From: … / Sent: … / To: … / Subject: …" header block, often preceded by
        a "________________________________" rule
      - Quoted lines:        "> …"
      - Localised variants of "On … wrote:" (fr/de/es/it).
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    stripped = [ln.strip() for ln in lines]
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        s = stripped[i]
        if s.startswith(">"):
            break
        if s.startswith("________"):
            break
        if _SEPARATOR_RE.match(s):
            break
        # "On … wrote:" possibly wrapped across 2–3 lines.
        if s.startswith(("On ", "Le ", "Am ", "El ", "Il ")) and any(
            _ON_WROTE_RE.match(" ".join(stripped[i:i + k])) for k in (1, 2, 3)
        ):
            break
        # Outlook-style header block: "From:" followed within 3 lines by Sent:/To:/Date:/Subject:.
        if _HEADER_BLOCK_START.match(s) and any(
            _HEADER_BLOCK_NEXT.match(x) for x in stripped[i + 1:i + 4]
        ):
            break
        out.append(lines[i])
        i += 1
    return "\n".join(out).strip()
