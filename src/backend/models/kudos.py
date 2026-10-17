from datetime import datetime

from sqlalchemy import DateTime, Integer, PrimaryKeyConstraint, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Kudos(Base):
    __tablename__ = 'kudos'
    __table_args__ = (PrimaryKeyConstraint('id', name='kudos_pk'),)

    id: Mapped[int] = mapped_column(Integer)
    # Stored without a time zone, as written by the server's clock
    datestamp: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    from_user: Mapped[str | None] = mapped_column(String(21))
    to_user: Mapped[str | None] = mapped_column(String(21))
    from_user_id: Mapped[str] = mapped_column(String(12))
    to_user_id: Mapped[str] = mapped_column(String(12))
    team_id: Mapped[str] = mapped_column(String(64), server_default=text("''"))
    team_name: Mapped[str] = mapped_column(String(64), server_default=text("''"))
    permalink: Mapped[str] = mapped_column(String(128), server_default=text("''"))
    channel_id: Mapped[str] = mapped_column(String(12), server_default=text("''"))
    channel_name: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
