"""A fake AgentMail SDK client for tests (no network, ever).

Mirrors the surface services/email/agentmail_client.py and the sender use:
inboxes.create / get, pods.inboxes.create, inboxes.messages.send / reply /
get_attachment. Records every call so tests can assert on them. Install it
with `monkeypatch.setattr(agentmail_client, "get_client", lambda: fake)`.
"""
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


class ApiError(Exception):
    """Shape of agentmail.core.api_error.ApiError."""

    def __init__(self, status_code: int, message: str = "boom", fix: Optional[str] = None):
        super().__init__(f"headers: {{}}, status_code: {status_code}, body: {message}")
        self.status_code = status_code
        self.headers = {}
        self.body = SimpleNamespace(name="Error", message=message, fix=fix)


class FakeAgentMail:
    def __init__(self, *, domain: str = "agentmail.to", send_results: Optional[List[Any]] = None,
                 taken: Optional[set] = None, attachments: Optional[Dict[str, bytes]] = None):
        self.domain = domain
        self.created: List[dict] = []
        self.sent: List[dict] = []
        self.replied: List[dict] = []
        self.attachment_reads: List[tuple] = []
        self._send_results = list(send_results or [])
        self._taken = set(taken or ())
        self._attachments = dict(attachments or {})
        self._n = 0
        fake = self

        class _Messages:
            def send(self, inbox_id, **kw):
                return fake._send("send", inbox_id, None, kw)

            def reply(self, inbox_id, message_id, **kw):
                return fake._send("reply", inbox_id, message_id, kw)

            def get_attachment(self, inbox_id, message_id, attachment_id):
                fake.attachment_reads.append((inbox_id, message_id, attachment_id))
                data = fake._attachments.get(attachment_id)
                if data is None:
                    raise ApiError(404, "attachment not found")
                return SimpleNamespace(
                    attachment_id=attachment_id, filename="x", size=len(data),
                    download_url=f"https://files.example/{attachment_id}", expires_at=None,
                )

        class _Inboxes:
            messages = _Messages()

            def create(self, *, request=None, request_options=None):
                return fake._create(vars(request) if request is not None else {})

            def get(self, inbox_id):
                return SimpleNamespace(inbox_id=inbox_id, email=inbox_id, display_name="Proq for X")

        class _PodInboxes:
            def create(self, pod_id, **kw):
                kw["pod_id"] = pod_id
                return fake._create(kw)

        self.inboxes = _Inboxes()
        self.pods = SimpleNamespace(inboxes=_PodInboxes())

    # -- internals
    def _create(self, fields: dict):
        fields = {k: v for k, v in fields.items() if v is not None}
        username = fields.get("username") or f"inbox-{len(self.created) + 1}"
        domain = fields.get("domain") or self.domain
        address = f"{username}@{domain}"
        self.created.append({**fields, "inbox_id": address})
        if address in self._taken:
            raise ApiError(403, f"{address} is taken", fix="Choose another username")
        return SimpleNamespace(inbox_id=address, email=address, pod_id=fields.get("pod_id", "pod_default"),
                               display_name=fields.get("display_name"), client_id=fields.get("client_id"),
                               metadata=fields.get("metadata"))

    def _send(self, kind: str, inbox_id: str, message_id: Optional[str], kw: dict):
        record = {"inbox_id": inbox_id, "in_reply_to": message_id, **kw}
        (self.sent if kind == "send" else self.replied).append(record)
        if self._send_results:
            result = self._send_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        self._n += 1
        return SimpleNamespace(message_id=f"<m{self._n}@agentmail.to>",
                               thread_id=f"thr_{message_id or self._n}" if kind == "send" else f"thr_of_{message_id}")
