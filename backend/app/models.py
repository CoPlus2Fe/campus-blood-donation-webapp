from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, Integer, DateTime, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    class_name: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(30), default="", server_default="")
    identity: Mapped[str] = mapped_column(String(16), default="student", server_default="student")
    college: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    openid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    bind_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blood: Mapped[int] = mapped_column(Integer, default=0)
    energy: Mapped[int] = mapped_column(Integer, default=0)
    energy_earned: Mapped[int] = mapped_column(Integer, default=0)
    energy_score_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    energy_boost_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(90))
    description: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(30), default="daily")
    blood_reward: Mapped[int] = mapped_column(Integer, default=0)
    energy_reward: Mapped[int] = mapped_column(Integer, default=0)
    blood_per_attempt: Mapped[int] = mapped_column(Integer, default=0)
    energy_per_success: Mapped[int] = mapped_column(Integer, default=0)
    min_success: Mapped[int] = mapped_column(Integer, default=0)
    max_claims: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exclusive_group: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaskClaim(Base):
    __tablename__ = "task_claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    blood_delta: Mapped[int] = mapped_column(Integer, default=0)
    energy_delta: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index("ix_claim_player_task_status", "participant_id", "task_id", "status"),)


class Draw(Base):
    __tablename__ = "draws"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), unique=True)
    prize_blood: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Prize(Base):
    __tablename__ = "prizes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(90))
    description: Mapped[str] = mapped_column(String(255), default="")
    energy_price: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    max_per_player: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Redemption(Base):
    __tablename__ = "redemptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    prize_id: Mapped[int] = mapped_column(ForeignKey("prizes.id"))
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    pickup_code: Mapped[str] = mapped_column(String(30), unique=True)
    price: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Ledger(Base):
    __tablename__ = "resource_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(180))
    source: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("kind", "source", "source_id", name="uq_source_resource"),)


class StaffUser(Base):
    __tablename__ = "staff_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_version: Mapped[int] = mapped_column(Integer, default=0)
    login_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    login_window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    login_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StaffTaskGrant(Base):
    __tablename__ = "staff_task_grants"
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"), primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)


class ClaimAudit(Base):
    __tablename__ = "claim_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("task_claims.id"), index=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_users.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(255), default="")
    before_status: Mapped[str] = mapped_column(String(20))
    after_status: Mapped[str] = mapped_column(String(20))
    before_blood: Mapped[int] = mapped_column(Integer, default=0)
    after_blood: Mapped[int] = mapped_column(Integer, default=0)
    before_energy: Mapped[int] = mapped_column(Integer, default=0)
    after_energy: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DrawAudit(Base):
    __tablename__ = "draw_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    draw_id: Mapped[int] = mapped_column(ForeignKey("draws.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"))
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(255))
    before_blood: Mapped[int] = mapped_column(Integer)
    after_blood: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BoostAudit(Base):
    __tablename__ = "boost_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    boost_ledger_id: Mapped[int] = mapped_column(ForeignKey("resource_ledger.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_users.id"))
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(255))
    before_bonus: Mapped[int] = mapped_column(Integer)
    after_bonus: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
