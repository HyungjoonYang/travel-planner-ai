from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TravelPlan(Base):
    __tablename__ = "travel_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    budget: Mapped[float] = mapped_column(Float, nullable=False)
    interests: Mapped[str] = mapped_column(Text, default="")  # comma-separated
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | confirmed
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")  # comma-separated tags
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    share_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    itineraries: Mapped[list["DayItinerary"]] = relationship(
        "DayItinerary", back_populates="travel_plan", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        "Expense", back_populates="travel_plan", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["PlanSnapshot"]] = relationship(
        "PlanSnapshot", back_populates="travel_plan", cascade="all, delete-orphan"
    )


class DayItinerary(Base):
    __tablename__ = "day_itineraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    travel_plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("travel_plans.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    transport: Mapped[str] = mapped_column(String(100), default="")

    travel_plan: Mapped["TravelPlan"] = relationship(
        "TravelPlan", back_populates="itineraries"
    )
    places: Mapped[list["Place"]] = relationship(
        "Place", back_populates="day_itinerary", cascade="all, delete-orphan",
        order_by="Place.order"
    )


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    day_itinerary_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("day_itineraries.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="")  # sightseeing|food|cafe|hotel|etc
    address: Mapped[str] = mapped_column(Text, default="")
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    order: Mapped[int] = mapped_column(Integer, default=0)

    day_itinerary: Mapped["DayItinerary"] = relationship(
        "DayItinerary", back_populates="places"
    )


class PlanSnapshot(Base):
    __tablename__ = "plan_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    travel_plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("travel_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    snapshot_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    travel_plan: Mapped["TravelPlan"] = relationship("TravelPlan", back_populates="snapshots")


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    travel_plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("travel_plans.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="")  # food|transport|lodging|activity|other
    date: Mapped[date] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    travel_plan: Mapped["TravelPlan"] = relationship(
        "TravelPlan", back_populates="expenses"
    )
