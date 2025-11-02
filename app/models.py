from sqlalchemy import Column, String, DateTime, Float, Boolean, Integer
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
    skill = Column(Float, nullable=True)
    skillUncertainty = Column(Float, nullable=True)
    lastStatsUpdate = Column(DateTime, nullable=True)

class SchedulerConfig(Base):
    __tablename__ = 'LEX_SCHEDULER_CONFIG'
    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BIGINT, nullable=False, unique=True)
    channel_id = Column(BIGINT, nullable=True)
    schedule_hour = Column(Integer, nullable=True)  # Hour in UTC (0-23)
    schedule_minute = Column(Integer, nullable=True)  # Minute (0-59)
    enabled = Column(Boolean, default=False)
