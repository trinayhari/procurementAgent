"""Slack integration: the agent as a coworker in the customer's channels.

    client.py         thin httpx wrapper over the Web API + request signing
    oauth.py          signed install state and the OAuth code exchange
    intake_bridge.py  hands a Slack message + files to the intake service
    events.py         Events API handling (messages with files, mentions)
    interactions.py   button clicks (approve award) and slash commands
    blocks.py         Block Kit rendering shared by the notifier + handlers

Routes live in api/routes/slack.py (authed settings) and
api/routes/webhooks_slack.py (public, signature-verified). The outbound
channel is services/notify/slack.py.
"""
