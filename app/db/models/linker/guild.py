from typing import TYPE_CHECKING

from sqlalchemy import Integer, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .registered_role import RegisteredRole


class Guild(BaseModel):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True)

    # Relationships
    registered_roles: Mapped[list["RegisteredRole"]] = relationship(
        back_populates="guild"
    )
