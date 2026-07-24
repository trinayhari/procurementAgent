"""ORM model for project lenders.

A lender is the financing contact for a project (bank / lending institution).
Lenders are stored per-project so progress emails — driven by the project's
timeline and where it stands — can go to the right people (PRO-16).
"""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Lender(Base):
    __tablename__ = "lenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)  # contact person
    institution: Mapped[str] = mapped_column(String, nullable=False, default="")
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False, default="")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "institution": self.institution,
            "email": self.email,
            "phone": self.phone,
        }
