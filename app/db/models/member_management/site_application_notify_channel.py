from sqlalchemy import BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class SiteApplicationNotifyChannel(BaseModel):
    __tablename__ = "site_application_notify_channels"

    site_id: Mapped[int] = mapped_column(Integer)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)

    # 3カラムでunique
    __table_args__ = (UniqueConstraint("site_id", "guild_id", "channel_id"),)
