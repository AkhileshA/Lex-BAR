from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import BIGINT
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Player(Base):
    __tablename__ = 'LEX_PLAYERS'
    discordId = Column(BIGINT, primary_key=True)
    discordUsername = Column(String, nullable=False)
    barUsername = Column(String, nullable=False)
    registeredAt = Column(DateTime, nullable=False)
    registeredBy = Column(BIGINT, nullable=True)
