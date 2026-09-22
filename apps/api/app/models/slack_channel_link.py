"""ORM model tying a Slack channel to a Proq project.

The agent listens in linked channels: a plan set dropped in `#riverside-wtp`
lands on the Riverside project, and every notice for that project posts back
there. A link with no project yet is a channel the agent has seen but not
attributed; the first intake in it fills `project_id` (auto-link).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SlackChannelLink(Base):
    __tablename__ = "slack_channel_links"
    __table_args__ = (UniqueConstraint("team_id", "channel_id", name="uq_slack_channel_links_team_channel"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    # Tenant boundary. Every read/write filters on this explicitly.
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), index=True, nullable=False
    )
    team_id: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    channel_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Null until the channel is attributed to a project (slash command, the
    # settings UI, or the first intake that creates one).
    project_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "teamId": self.team_id,
            "channelId": self.channel_id,
            "channelName": self.channel_name,
            "projectId": self.project_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
