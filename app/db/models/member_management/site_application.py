from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseModel


class SiteApplication(BaseModel):
    __tablename__ = "site_applications"

    original_id: Mapped[int] = mapped_column(Integer)
    site_id: Mapped[int] = mapped_column(BigInteger)
