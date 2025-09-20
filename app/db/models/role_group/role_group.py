from typing import TYPE_CHECKING, List

from sqlalchemy import String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .role_group_role import RoleGroupRole


class RoleGroup(BaseModel):
    """ロールグループのマスターテーブル"""

    __tablename__ = "role_groups"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Relationships
    roles: Mapped[List["RoleGroupRole"]] = relationship(
        back_populates="role_group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RoleGroup(name='{self.name}', description='{self.description}')>"
