from datetime import datetime

from sqlalchemy import Integer, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .connection import Base


class Guilds(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()")
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()")
    )

    # Relationships
    registered_roles: Mapped[list["RegisteredRoles"]] = relationship(
        back_populates="guild"
    )


class RegisteredRoles(Base):
    __tablename__ = "registered_roles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guilds.guild_id"),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()")
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()")
    )

    # Relationships
    guild: Mapped["Guilds"] = relationship(
        back_populates="registered_roles"
    )


