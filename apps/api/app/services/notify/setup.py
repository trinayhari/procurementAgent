"""Register the built-in channels. Called once from main.py at startup; safe
to call again (register() replaces by name). Slack registers itself from its
own module when installed."""
from app.services import notify
from app.services.notify.activity import ActivityNotifier
from app.services.notify.email import EmailNotifier


def install() -> None:
    notify.register(ActivityNotifier())
    notify.register(EmailNotifier())
