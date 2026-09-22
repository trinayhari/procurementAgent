"""Slack channel for notices: post the card where the customer works.

A notice that started in Slack (ThreadRef.channel == "slack") is answered in
that thread; any other notice with a project goes to the channel linked to
the project. No installation or no linked channel means silence (email and
the activity feed still carry it). Rendering lives in services/slack/blocks.
"""
from __future__ import annotations

import logging

from app.repositories import slack as slack_repo
from app.services.notify import Notice, register
from app.services.slack import blocks as slack_blocks
from app.services.slack import client as slack_client

logger = logging.getLogger("procureai.notify.slack")


class SlackNotifier:
    name = "slack"

    def notify(self, db, notice: Notice) -> None:
        installation = slack_repo.installation_for_org(db, notice.org_id)
        if installation is None:
            return
        channel = ""
        thread_ts = None
        if notice.thread is not None and notice.thread.channel == "slack" and notice.thread.slack_channel_id:
            channel = notice.thread.slack_channel_id
            thread_ts = notice.thread.slack_thread_ts or None
        elif notice.project_id:
            link = slack_repo.link_for_project(db, notice.org_id, notice.project_id)
            if link is not None:
                channel = link.channel_id
        if not channel:
            return
        blocks = slack_blocks.render_notice(notice)
        slack_client.post_message(installation.bot_token, channel, blocks, notice.title, thread_ts=thread_ts)


register(SlackNotifier())
