from typing import Optional as Opt, TYPE_CHECKING

from sqlalchemy import Integer, ForeignKey, BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .guild import Guild


class RegisteredRole(BaseModel):
    __tablename__ = "registered_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    role_id: Mapped[int] = mapped_column(BigInteger, unique=True)

    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id"), nullable=False)

    # Noneなら両方、Trueならリンク済み、Falseなら未リンク
    is_linked: Mapped[Opt[bool]] = mapped_column(Boolean, nullable=True)

    # Noneなら両方、TrueならJPメンバー、Falseなら非JPメンバー
    is_jp_member: Mapped[Opt[bool]] = mapped_column(Boolean, nullable=True)

    # Relationships
    guild: Mapped["Guild"] = relationship(back_populates="registered_roles")
