from pydantic import BaseModel, EmailStr


class Lender(BaseModel):
    id: int
    name: str
    institution: str
    email: str
    phone: str


class LenderCreate(BaseModel):
    """Payload for adding a lender to a project."""

    name: str
    email: EmailStr
    institution: str = ""
    phone: str = ""
