"""Authentication routes: register, login (JWT), and the current-user lookup."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_current_user, verify_password
from app.db import get_db
from app.models.user import User
from app.repositories import users as users_repo
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UpdateMeRequest
from app.schemas.auth import User as UserSchema

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if users_repo.get_by_email(db, body.email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = users_repo.create_user(
        db, email=body.email, password=body.password, name=body.name, company=body.company
    )
    token = create_access_token(user.id)
    return {"accessToken": token, "tokenType": "bearer", "user": user.to_dict()}


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = users_repo.get_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
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
