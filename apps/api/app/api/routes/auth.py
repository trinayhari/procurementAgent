"""Authentication routes: register, login (JWT), and the current-user lookup."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.ratelimit import rate_limit
from app.core.security import create_access_token, get_current_user, verify_password
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.schemas.auth import (
    EmailConfig,
    LoginRequest,
    RegisterRequest,
    TestEmailResult,
    TokenResponse,
    UpdateMeRequest,
)
from app.schemas.auth import User as UserSchema
from app.services.rfq import sender as rfq_sender

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Blunt credential stuffing: 10 login attempts / 5 registrations per IP per minute.
_login_limit = rate_limit("login", limit=10, window_s=60)
_register_limit = rate_limit("register", limit=5, window_s=60)
# Test emails go through the real Gmail quota when configured — keep it slow.
_test_email_limit = rate_limit("test-email", limit=3, window_s=60)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_register_limit)],
)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if users_repo.get_by_email(db, body.email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = users_repo.create_user(
        db, email=body.email, password=body.password, name=body.name, company=body.company
    )
    audit_repo.log(db, user, "auth.registered", "user", user.id)
    token = create_access_token(user.id)
    return {"accessToken": token, "tokenType": "bearer", "user": user.to_dict()}


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_login_limit)])
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = users_repo.get_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    audit_repo.log(db, user, "auth.logged_in", "user", user.id)
    token = create_access_token(user.id)
    return {"accessToken": token, "tokenType": "bearer", "user": user.to_dict()}


@router.get("/me", response_model=UserSchema)
def me(current_user: User = Depends(get_current_user)):
    return current_user.to_dict()


@router.patch("/me", response_model=UserSchema)
def update_me(
    body: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = users_repo.set_cc_email(db, current_user, body.ccEmail)
    return user.to_dict()


@router.get("/email-config", response_model=EmailConfig)
def email_config(current_user: User = Depends(get_current_user)):
    """The effective outbound-email setup: which mailbox mail leaves from,
    whether Gmail is actually connected, and your Cc address.

    Every field derives from the PROCUREAI_GMAIL_* environment variables (see
    docs/email-setup.md) — nothing here is per-user except `ccEmail` and the
    display name baked into `fromHeader`.
    """
    cfg = rfq_sender.email_config()
    cfg["fromHeader"] = rfq_sender.from_display(current_user)
    cfg["ccEmail"] = current_user.cc_email
    return cfg


@router.post(
    "/test-email",
    response_model=TestEmailResult,
    dependencies=[Depends(_test_email_limit)],
)
def send_test_email(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify the email configuration by sending a test message to yourself.

    Uses exactly the same path as an RFQ send: the configured provider (Gmail
    or the logging mock) and the workspace From address carrying your display
    name. See docs/email-setup.md.
    """
    sender = rfq_sender.get_sender()
    from_addr = rfq_sender.from_header(current_user)
    shown_from = rfq_sender.from_display(current_user)  # same identity, readable
    cc = rfq_sender.resolve_cc(current_user.cc_email, current_user.email, from_addr)
    body = (
        f"This is a test email from Proq.\n\n"
        f"From: {shown_from}\n"
        f"Requested by: {current_user.email}\n"
        + (f"Copied to: {cc}\n" if cc else "")
        + "\nAll Proq email is sent from the workspace's connected Gmail account; "
        "your own address is only ever copied (Cc) so you keep a record. Supplier "
        "replies come back to the workspace mailbox, which is what feeds quote "
        "ingest — see docs/email-setup.md in the repo.\n\n— Proq"
    )
    try:
        sent = sender.send(
            current_user.email, "Proq test email", body, from_addr=from_addr, cc=cc
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Test send failed: {exc}")
    audit_repo.log(
        db, current_user, "email.test_sent", "user", current_user.id,
        detail={"from": shown_from, "to": current_user.email, "cc": cc,
                "mocked": sender.mocked},
    )
    return {
        "mocked": sender.mocked,
        "messageId": sent.message_id,
        "fromAddr": shown_from,
        "to": current_user.email,
        "cc": cc,
    }
