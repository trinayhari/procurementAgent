from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import RfqStatus, Tone


class Rfq(BaseModel):
    id: str
    sup: str
    pkg: str
    folder: str
    status: RfqStatus
    statusTone: Tone
    preview: str
    time: str
    unread: bool = False
    logo: str
    logoBg: str


class RfqFolder(BaseModel):
    name: str
    count: str


class ThreadMessage(BaseModel):
    dir: str  # "in" | "out"
    who: str
    initials: str
    time: str
    body: str
    subject: Optional[str] = None
    attach: Optional[str] = None
    logoBg: Optional[str] = None


class RfqDetail(Rfq):
    thread: List[ThreadMessage]


class MessageCreate(BaseModel):
    body: str


class FollowupDraft(BaseModel):
    body: str
