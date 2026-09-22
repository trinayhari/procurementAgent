"""Register the built-in channels. Called once from main.py at startup; safe
to call again (register() replaces by name), which also restores the set
after a test calls notify.reset()."""
from app.services import notify
from app.services.notify.activity import ActivityNotifier
from app.services.notify.email import EmailNotifier
from app.services.notify.slack import SlackNotifier


def install() -> None:
    notify.register(ActivityNotifier())
    notify.register(EmailNotifier())
    notify.register(SlackNotifier())
