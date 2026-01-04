from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class SiteApplicationNotifyChannel(BaseModel):
    __tablename__ = "site_application_notify_channels"

    site_unix_name: Mapped[str] = mapped_column(String(100))
    guild_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)

    # 3カラムでunique
    __table_args__ = (UniqueConstraint("site_unix_name", "guild_id", "channel_id"),)
