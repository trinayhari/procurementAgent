"""Request/response shapes for the Slack settings endpoints."""
from typing import List, Optional

from pydantic import BaseModel


class SlackChannelLink(BaseModel):
    """A Slack channel the agent listens in, and the project it feeds."""

    id: str
    teamId: str
    channelId: str
    channelName: str = ""
    projectId: Optional[str] = None
    projectName: Optional[str] = None
    createdAt: Optional[str] = None


class SlackStatus(BaseModel):
    """Whether the Slack app is set up on the server and installed by this org.

    `configured` is server-side (the three PROCUREAI_SLACK_* variables);
    `installed` is per organization (an OAuth install exists)."""

    configured: bool
    missing: List[str] = []  # PROCUREAI_SLACK_* variables still unset
    installed: bool
    teamId: Optional[str] = None
    teamName: Optional[str] = None
    botUserId: Optional[str] = None
    installedAt: Optional[str] = None
    channels: List[SlackChannelLink] = []


class SlackInstallUrl(BaseModel):
    url: str


class SlackChannelLinkRequest(BaseModel):
    projectId: str
    channelName: str = ""
