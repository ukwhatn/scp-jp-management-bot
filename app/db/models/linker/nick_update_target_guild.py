from sqlalchemy import Integer, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class NickUpdateTargetGuild(BaseModel):
    __tablename__ = "nick_update_target_guilds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True)
