from datetime import date, datetime
from typing import List

from sqlalchemy import BigInteger, String, UniqueConstraint, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import BaseModel

from .staff_request_user import StaffRequestUser, StaffRequestStatus


class StaffRequest(BaseModel):
    __tablename__ = "staff_requests"

    # 元チャンネルのサマリメッセージID
    summary_message_guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary_message_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 作成者id
    created_by_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # 稟議概要
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=True)

    # リレーション
    users: Mapped[List["StaffRequestUser"]] = relationship(
        back_populates="staff_request"
    )

    last_remind_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # 制約
    __table_args__ = (
        UniqueConstraint("summary_message_guild_id", "summary_message_id"),
    )

    # 関数群
    def _get_users_by_status(
        self, status: "StaffRequestStatus"
    ) -> List["StaffRequestUser"]:
        return [user for user in self.users if user.status == status]

    @property
    def pending_users(self) -> List["StaffRequestUser"]:
        return self._get_users_by_status(StaffRequestStatus.PENDING)

    @property
    def done_users(self) -> List["StaffRequestUser"]:
        return self._get_users_by_status(StaffRequestStatus.DONE)

    @property
    def expired_users(self) -> List["StaffRequestUser"]:
        return self._get_users_by_status(StaffRequestStatus.EXPIRED)

    @property
    def canceled_by_requester_users(self) -> List["StaffRequestUser"]:
        return self._get_users_by_status(StaffRequestStatus.CANCELED_BY_REQUESTER)
