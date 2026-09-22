"""ORM model for a Slack workspace that installed the Proq app.

One row per (organization, Slack workspace). The bot token minted by the
OAuth install is what every outbound call (chat.postMessage, files download,
users.info) authenticates with, and `team_id` is how an inbound Slack event
(which carries a team id, not an org) finds its tenant. Tokens are stored as
issued; encryption at rest is a follow-up.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SlackInstallation(Base):
    __tablename__ = "slack_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    # Tenant boundary. Scoped reads filter on this; the one unscoped lookup is
    # by team_id (see repositories/slack.installation_for_team).
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )
    # A workspace installs the app once; re-installing replaces the token.
    team_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    team_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    bot_user_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    bot_token: Mapped[str] = mapped_column(String, nullable=False)
    installed_by_user_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        """Public-safe payload for the settings UI: never the token."""
        return {
            "id": self.id,
            "teamId": self.team_id,
            "teamName": self.team_name,
            "botUserId": self.bot_user_id,
            "installedByUserId": self.installed_by_user_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
