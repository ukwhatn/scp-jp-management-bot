from datetime import datetime

from sqlalchemy import BigInteger, Integer, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class PrivilegeRemoveQueue(BaseModel):
    __tablename__ = "privilege_remove_queue"

    # discord
    dc_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # wikidot
    wd_site_id: Mapped[int] = mapped_column(Integer, nullable=False)
    wd_user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # notify_guild_id
    notify_guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notify_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notify_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # permission
    permission_level: Mapped[str] = mapped_column(String(50), nullable=False)

    # expired_at
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
