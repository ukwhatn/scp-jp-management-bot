import enum as python_enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .staff_approval import StaffApproval


class StaffApprovalStatus(python_enum.Enum):
    PENDING = 0
    DONE = 1
    CANCELLED = 9


class StaffApprovalUser(BaseModel):
    __tablename__ = "staff_approval_users"

    # 稟議ID
    staff_approval_id: Mapped[int] = mapped_column(
        ForeignKey("staff_approvals.id"), nullable=False
    )
    staff_approval: Mapped["StaffApproval"] = relationship(back_populates="users")

    # ユーザID
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # ステータス
    status: Mapped[StaffApprovalStatus] = mapped_column(
        Enum(StaffApprovalStatus), nullable=False
    )
