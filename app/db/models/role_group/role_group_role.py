from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .role_group import RoleGroup


class RoleGroupRole(BaseModel):
    """グループに属するロールの中間テーブル"""

    __tablename__ = "role_group_roles"

    role_group_id: Mapped[int] = mapped_column(
        ForeignKey("role_groups.id"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Relationships
    role_group: Mapped["RoleGroup"] = relationship(back_populates="roles")

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "role_group_id", "guild_id", "role_id", name="uq_role_group_guild_role"
        ),
    )

    def __repr__(self) -> str:
        return f"<RoleGroupRole(role_group_id={self.role_group_id}, guild_id={self.guild_id}, role_id={self.role_id})>"
