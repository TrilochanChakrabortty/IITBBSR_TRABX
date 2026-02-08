from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from database import Base
from datetime import datetime


# ---------- USER TABLE ----------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)


# ---------- ASTEROID TABLE ----------
class Asteroid(Base):
    __tablename__ = "asteroids"

    id = Column(Integer, primary_key=True, index=True)

    # NASA unique asteroid ID
    neo_id = Column(String, unique=True, index=True)

    name = Column(String)
    close_approach_date = Column(String)

    diameter_km = Column(Float)
    velocity_km_s = Column(Float)

    hazardous = Column(Boolean)
    nasa_url = Column(String)

from sqlalchemy import Column, Integer, String, Float, Boolean
from database import Base


class AsteroidRisk(Base):
    __tablename__ = "asteroid_risk"
    id = Column(Integer, primary_key=True, index=True)
    neo_id = Column(String)
    name = Column(String)
    close_approach_date = Column(String)
    diameter_km = Column(Float)
    velocity_km_s = Column(Float)
    hazardous = Column(Boolean)
    risk_score = Column(Float)
    risk_level = Column(String)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)
    message = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
