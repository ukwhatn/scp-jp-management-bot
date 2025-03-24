from typing import TYPE_CHECKING, List

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .staff_approval_user import StaffApprovalUser


class StaffApproval(BaseModel):
    __tablename__ = "staff_approvals"

    # 元チャンネルのサマリメッセージID
    summary_message_guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 稟議概要
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=True)

    # リレーション
    users: Mapped[List["StaffApprovalUser"]] = relationship(
        back_populates="staff_approval"
    )

    # 制約
    __table_args__ = (
        UniqueConstraint("summary_message_guild_id", "summary_message_id"),
    )
