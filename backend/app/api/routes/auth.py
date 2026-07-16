"""Authentication routes: register, login (JWT), and the current-user lookup."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.ratelimit import rate_limit
from app.core.security import create_access_token, get_current_user, verify_password
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UpdateMeRequest
from app.schemas.auth import User as UserSchema

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Blunt credential stuffing: 10 login attempts / 5 registrations per IP per minute.
_login_limit = rate_limit("login", limit=10, window_s=60)
_register_limit = rate_limit("register", limit=5, window_s=60)


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
    user = users_repo.set_sender_email(db, current_user, body.senderEmail)
    return user.to_dict()
