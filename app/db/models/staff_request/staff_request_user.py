import enum as python_enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

if TYPE_CHECKING:
    from .staff_request import StaffRequest


class StaffRequestStatus(python_enum.Enum):
    PENDING = 0
    DONE = 1
    EXPIRED = 8
    CANCELED_BY_REQUESTER = 9

    @classmethod
    def name_ja(cls, status: "StaffRequestStatus") -> str:
        if status == cls.PENDING:
            return "未対応"
        elif status == cls.DONE:
            return "対応済"
        elif status == cls.EXPIRED:
            return "期限切れ"
        elif status == cls.CANCELED_BY_REQUESTER:
            return "申請者により取り消し"
        else:
            return "不明"


class StaffRequestUser(BaseModel):
    __tablename__ = "staff_request_users"

    # 稟議ID
    staff_request_id: Mapped[int] = mapped_column(
        ForeignKey("staff_requests.id"), nullable=False
    )
    staff_request: Mapped["StaffRequest"] = relationship(back_populates="users")

    # ユーザID
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 通知メッセージID(DM)
    dm_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # ステータス
    status: Mapped[StaffRequestStatus] = mapped_column(
        Enum(StaffRequestStatus), nullable=False
    )

    @property
    def status_name_ja(self) -> str:
        return StaffRequestStatus.name_ja(self.status)
