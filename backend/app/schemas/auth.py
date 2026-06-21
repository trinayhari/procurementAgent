from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = ""
    company: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class User(BaseModel):
    """Public-safe user shape (never includes the password hash)."""

    id: str
    email: EmailStr
    name: str
    company: str
    createdAt: Optional[str] = None


class TokenResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    user: User
