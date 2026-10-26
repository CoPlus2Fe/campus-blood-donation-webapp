import hmac
import secrets
import os
import random
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException, Depends, Request, Response, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, inspect, or_, select, func, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import Session

from .core import (engine, SessionLocal, db_session, DEMO_MODE, APP_SECRET,
                   PUBLIC_BASE_URL, WECHAT_APP_ID, WECHAT_APP_SECRET, COOKIE, STAFF_COOKIE, PENDING_COOKIE,
                   STATE_COOKIE, LEADERBOARD_LIMIT, read_actor, require_player, require_admin, sign, verify,
                   digest_code, set_cookie, clear_cookie, hash_staff_password, verify_staff_password)
from .models import (Base, Participant, Task, TaskClaim, Draw, DrawAudit, BoostAudit, Prize, Redemption, Ledger,
                     StaffUser, StaffTaskGrant, ClaimAudit, now)
from .seed import init_seed

COLLEGES = ("计算机科学与工程学院", "机械与能源工程学院", "材料科学与工程学院", "食品科学与工程学院", "商学院")
STAFF_COLLEGES = (*COLLEGES, "其他")
DRAW_PRIZES = (10, 15, 20, 25, 30)
DRAW_WEIGHTS = (25, 30, 25, 15, 5)
LOGIN_WINDOW = timedelta(minutes=5)
LOGIN_LOCK = timedelta(minutes=5)
LOGIN_FAILURE_LIMIT = 5
MAX_PARTICIPANT_NUMBER = 99999
try:
    DRAW_OPENS_AT = datetime.fromisoformat(os.getenv("DRAW_OPENS_AT", "2026-10-28T15:00:00+08:00"))
    if DRAW_OPENS_AT.tzinfo is None:
        raise ValueError
except ValueError:
    raise RuntimeError("DRAW_OPENS_AT 必须是带时区的 ISO 8601 日期时间")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP: create_all for first run; use Alembic before schema changes in production.
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        participant_columns = {column["name"] for column in inspect(connection).get_columns("participants")}
        if "phone" not in participant_columns:
            connection.execute(text("ALTER TABLE participants ADD COLUMN phone VARCHAR(30) NOT NULL DEFAULT ''"))
        if "energy_score_at" not in participant_columns:
            connection.execute(text("ALTER TABLE participants ADD COLUMN energy_score_at TIMESTAMP WITH TIME ZONE"))
        if "energy_boost_used" not in participant_columns:
            connection.execute(text("ALTER TABLE participants ADD COLUMN energy_boost_used BOOLEAN NOT NULL DEFAULT false"))
        if "identity" not in participant_columns:
            connection.execute(text("ALTER TABLE participants ADD COLUMN identity VARCHAR(16) NOT NULL DEFAULT 'student'"))
        if "college" not in participant_columns:
            connection.execute(text("ALTER TABLE participants ADD COLUMN college VARCHAR(80)"))
        if "active" not in participant_columns:
            connection.execute(text("ALTER TABLE participants ADD COLUMN active BOOLEAN NOT NULL DEFAULT true"))
        redemption_columns = {column["name"] for column in inspect(connection).get_columns("redemptions")}
        if "quantity" not in redemption_columns:
            connection.execute(text("ALTER TABLE redemptions ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1"))
        staff_columns = {column["name"] for column in inspect(connection).get_columns("staff_users")}
        if "login_failures" not in staff_columns:
            connection.execute(text("ALTER TABLE staff_users ADD COLUMN login_failures INTEGER NOT NULL DEFAULT 0"))
        if "login_window_started_at" not in staff_columns:
            connection.execute(text("ALTER TABLE staff_users ADD COLUMN login_window_started_at TIMESTAMP WITH TIME ZONE"))
        if "login_locked_until" not in staff_columns:
            connection.execute(text("ALTER TABLE staff_users ADD COLUMN login_locked_until TIMESTAMP WITH TIME ZONE"))
    with SessionLocal() as db:
        last_scores = db.execute(select(Ledger.participant_id, func.max(Ledger.created_at))
                                 .where(Ledger.kind == "energy", Ledger.delta > 0)
                                 .group_by(Ledger.participant_id)).all()
        for player_id, scored_at in last_scores:
            p = db.get(Participant, player_id)
            if p and p.energy_score_at is None:
                p.energy_score_at = scored_at
        init_seed(db)
        existing_audits = set(db.scalars(select(ClaimAudit.claim_id).distinct()))
        checkin_id = db.scalar(select(Task.id).where(Task.code == "checkin"))
        for claim in db.scalars(select(TaskClaim).where(TaskClaim.status.in_(("completed", "rejected")),
                                                      TaskClaim.task_id != checkin_id)):
            if claim.id not in existing_audits:
                db.add(ClaimAudit(claim_id=claim.id, staff_id=None, action="legacy_" + claim.status,
                                  reason="历史任务核验记录", before_status="pending", after_status=claim.status,
                                  after_blood=claim.blood_delta, after_energy=claim.energy_delta,
                                  created_at=claim.completed_at or claim.created_at))
        db.commit()
    yield


app = FastAPI(title="热血青春・与爱同行 API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("X-Requested-With") != "BloodQuest":
            return Response("Missing CSRF header", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != PUBLIC_BASE_URL:
            return Response("Unexpected origin", status_code=403)
    return await call_next(request)


def player_for_update(db: Session, pid: int):
    p = db.scalar(select(Participant).where(Participant.id == pid).with_for_update())
    if not p:
        raise HTTPException(404, "参与者不存在")
    return p


def ensure_participant_number(db: Session, participant: Participant):
    if participant.id is None or not 1 <= participant.id <= MAX_PARTICIPANT_NUMBER:
        db.rollback()
        raise HTTPException(409, "参与者编号已用完（最大 99999），无法新增参与者")


def participant_number_search(q: str) -> int | None:
    value = q.strip()
    if 1 <= len(value) <= 5 and value.isascii() and value.isdecimal():
        return int(value)
    return None


def draw_blood(db: Session, draw: Draw) -> int:
    adjustment = db.scalar(select(DrawAudit).where(DrawAudit.draw_id == draw.id)
                           .order_by(DrawAudit.id.desc()).limit(1))
    return adjustment.after_blood if adjustment else draw.prize_blood


BOOST_SOURCES = ("boost", "boost_v2", "boost_adjust", "boost_reverse", "boost_manual_adjust")


def latest_boost(db: Session, participant_id: int) -> Ledger | None:
    return db.scalar(select(Ledger).where(Ledger.participant_id == participant_id,
                                          Ledger.kind == "energy", Ledger.source.in_(("boost", "boost_v2")))
                     .order_by(Ledger.id.desc()).limit(1))


def effective_boost_bonus(db: Session, boost: Ledger) -> int:
    return db.scalar(select(func.coalesce(func.sum(Ledger.delta), 0)).where(
        Ledger.participant_id == boost.participant_id, Ledger.kind == "energy",
        Ledger.id >= boost.id, Ledger.source.in_(BOOST_SOURCES))) or 0


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def add_ledger(db: Session, p: Participant, kind: str, delta: int, reason: str, source: str, source_id: int,
               allow_debt: bool = False, adjust_earned: bool = False, counts_as_earned: bool = True):
    if delta == 0:
        return
    if kind not in ("blood", "energy"):
        raise ValueError("unsupported resource")
    current = p.blood if kind == "blood" else p.energy
    if current + delta < 0 and not allow_debt:
        raise HTTPException(409, f"{'血值' if kind == 'blood' else '能量'}余额不足")
    if kind == "blood":
        p.blood += delta
    else:
        p.energy += delta
        if delta > 0 and counts_as_earned:
            p.energy_earned += delta
            p.energy_score_at = now()
        elif adjust_earned:
            p.energy_earned = max(0, p.energy_earned + delta)
            p.energy_score_at = now()
    db.add(Ledger(participant_id=p.id, kind=kind, delta=delta,
                  reason=reason, source=source, source_id=source_id))


def rank_of(db: Session, p: Participant):
    scored_at = p.energy_score_at or p.created_at
    other_at = func.coalesce(Participant.energy_score_at, Participant.created_at)
    ahead = or_(Participant.energy_earned > p.energy_earned,
                and_(Participant.energy_earned == p.energy_earned,
                     or_(other_at < scored_at, and_(other_at == scored_at, Participant.id < p.id))))
    return (db.scalar(select(func.count()).select_from(Participant).where(Participant.active == True, ahead)) or 0) + 1


def profile(db: Session, p: Participant):
    donation_completed = db.scalar(select(TaskClaim.id).join(Task, TaskClaim.task_id == Task.id)
                                   .where(TaskClaim.participant_id == p.id, TaskClaim.status == "completed",
                                          Task.code.in_(("donate_blood", "donate_energy"))).limit(1))
    return dict(id=p.id, student_id=p.student_id, identity=p.identity, college=p.college,
                name=p.name, class_name=p.class_name,
                blood=p.blood, energy=p.energy, energy_earned=p.energy_earned,
                rank=rank_of(db, p), energy_boost_available=bool(donation_completed) and not p.energy_boost_used,
                energy_boost_used=p.energy_boost_used)


class BindRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=40)
    code: str = Field(min_length=6, max_length=30)


class ParticipantInput(BaseModel):
    identity: Literal["student", "staff", "faculty"] = "student"
    college: str | None = None
    class_name: str = Field(default="", max_length=80)
    name: str = Field(min_length=1, max_length=80)
    student_id: str = Field(min_length=1, max_length=40)
    phone: str = Field(pattern=r"^[0-9]{11}$")

    @model_validator(mode="after")
    def validate_identity(self):
        if self.identity == "faculty":
            self.identity = "staff"
        if self.identity == "student":
            if not (len(self.student_id) == 12 and self.student_id.isascii() and self.student_id.isdecimal()):
                raise ValueError("学号应为 12 位数字")
            if self.college not in COLLEGES:
                raise ValueError("请选择学院")
            if not self.class_name.strip():
                raise ValueError("请填写班级")
        elif not self.student_id.strip():
            raise ValueError("请填写工号")
        else:
            if self.college not in STAFF_COLLEGES:
                raise ValueError("请选择学院")
        return self


class SignupRequest(ParticipantInput):
    pass


class PlayerLogin(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    student_id: str = Field(min_length=1, max_length=40)


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class CreateParticipant(ParticipantInput):
    pass


class EditParticipant(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    student_id: str | None = Field(default=None, min_length=1, max_length=40)
    phone: str | None = Field(default=None, pattern=r"^[0-9]{11}$")
    class_name: str | None = Field(default=None, max_length=80)
    college: str | None = None
    identity: Literal["student", "staff"] | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def reject_null_updates(self):
        if any(getattr(self, field) is None for field in self.model_fields_set if field != "college"):
            raise ValueError("修改的字段不能为空")
        return self


class StaffCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["super", "project"]
    task_ids: list[int] = Field(default_factory=list)
    active: bool = True


class StaffEdit(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    role: Literal["super", "project"] | None = None
    task_ids: list[int] | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def reject_null_updates(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("修改的字段不能为空")
        return self


class EditTask(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=90)
    description: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=30)
    blood_reward: int | None = Field(default=None, ge=0)
    energy_reward: int | None = Field(default=None, ge=0)
    blood_per_attempt: int | None = Field(default=None, ge=0)
    energy_per_success: int | None = Field(default=None, ge=0)
    min_success: int | None = Field(default=None, ge=0)
    max_claims: int | None = Field(default=None, ge=1)
    exclusive_group: str | None = Field(default=None, max_length=40)
    active: bool | None = None


class CreateTask(EditTask):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=90)
    category: str = Field(min_length=1, max_length=30)


class EditPrize(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=90)
    description: str | None = Field(default=None, max_length=255)
    energy_price: int | None = Field(default=None, ge=1)
    stock: int | None = Field(default=None, ge=0)
    max_per_player: int | None = Field(default=None, ge=1)
    active: bool | None = None


class CreatePrize(EditPrize):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=90)
    energy_price: int = Field(ge=1)


class AdjustClaim(BaseModel):
    blood_delta: int
    energy_delta: int
    reason: str = Field(min_length=1, max_length=255)


class ReverseClaim(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class AdjustDraw(BaseModel):
    blood: Literal[10, 15, 20, 25, 30]
    reason: str = Field(min_length=1, max_length=255)


class AdjustBoost(BaseModel):
    bonus: int = Field(ge=1, le=1_000_000)
    reason: str = Field(min_length=1, max_length=255)


def require_super(staff: StaffUser = Depends(require_admin)) -> StaffUser:
    if staff.role != "super":
        raise HTTPException(403, "需要最高级管理员权限")
    return staff


def staff_task_ids(db: Session, staff: StaffUser) -> list[int]:
    return db.scalars(select(StaffTaskGrant.task_id).where(StaffTaskGrant.staff_id == staff.id)).all()


def check_task_permission(db: Session, staff: StaffUser, task_id: int):
    if staff.role != "super" and task_id not in staff_task_ids(db, staff):
        raise HTTPException(403, "无该项目权限")


def validate_task_ids(db: Session, role: str, task_ids: list[int]):
    if role == "project" and not task_ids:
        raise HTTPException(400, "分项目管理员至少需要一个项目权限")
    if role == "super" and task_ids:
        raise HTTPException(400, "最高级管理员无需分项目授权")
    if len(task_ids) != len(set(task_ids)):
        raise HTTPException(400, "项目权限不能重复")
    actual = set(db.scalars(select(Task.id).where(
        Task.id.in_(task_ids), Task.active == True, Task.category != "checkin")).all())
    if actual != set(task_ids):
        raise HTTPException(400, "项目不存在或已停用")


def staff_public(db: Session, staff: StaffUser) -> dict:
    return {"id": staff.id, "username": staff.username, "role": staff.role,
            "active": staff.active, "task_ids": staff_task_ids(db, staff)}


def apply_edit(target, data: BaseModel):
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(target, field, value)


class CompleteClaim(BaseModel):
    attempts: int = Field(default=0, ge=0, le=200)
    successes: int = Field(default=0, ge=0, le=200)
    rings10: int = Field(default=0, ge=0, le=200)
    rings9: int = Field(default=0, ge=0, le=200)
    rings8: int = Field(default=0, ge=0, le=200)


class RedeemRequest(BaseModel):
    prize_id: int
    request_key: str = Field(min_length=8, max_length=100)
    quantity: int = Field(default=1, ge=1, le=100)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/bootstrap")
def bootstrap():
    return {"demo_mode": DEMO_MODE, "wechat_enabled": bool(WECHAT_APP_ID and WECHAT_APP_SECRET),
            "draw_opens_at": DRAW_OPENS_AT.isoformat(),
            "draw_prizes": [{"blood": 10, "probability": 25}, {"blood": 15, "probability": 30},
                            {"blood": 20, "probability": 25}, {"blood": 25, "probability": 15},
                            {"blood": 30, "probability": 5}], "leaderboard_limit": LEADERBOARD_LIMIT}


@app.post("/api/auth/signup")
def signup_player(payload: SignupRequest, response: Response, db: Session = Depends(db_session)):
    class_name = payload.class_name.strip()
    name = payload.name.strip()
    student_id = payload.student_id.strip()
    phone = payload.phone.strip()
    if not all((name, student_id, phone)) or (payload.identity == "student" and not class_name):
        raise HTTPException(400, "请完整填写注册信息")
    if db.scalar(select(Participant.id).where(Participant.student_id == student_id)):
        raise HTTPException(409, "该学号或工号已注册，请使用姓名和编号登录")
    checkin = db.scalar(select(Task).where(Task.code == "checkin"))
    if not checkin:
        raise HTTPException(503, "签到任务尚未初始化，请稍后重试")
    participant = Participant(student_id=student_id, name=name, class_name=class_name, phone=phone,
                              identity=payload.identity, college=payload.college)
    try:
        db.add(participant)
        db.flush()
        ensure_participant_number(db, participant)
        db.add(TaskClaim(participant_id=participant.id, task_id=checkin.id,
                         status="completed", completed_at=now()))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该学号或工号已注册，请使用姓名和编号登录")
    set_cookie(response, COOKIE, sign({"kind": "session", "role": "player", "sub": str(participant.id)}), 259200)
    return {"ok": True, "first_checkin": True}


@app.post("/api/auth/login")
def login_player(payload: PlayerLogin, response: Response, db: Session = Depends(db_session)):
    name = payload.name.strip()
    student_id = payload.student_id.strip()
    participant = db.scalar(select(Participant).where(
        Participant.name == name, Participant.student_id == student_id))
    if not participant:
        raise HTTPException(401, "姓名或学号/工号不匹配")
    if not participant.active:
        raise HTTPException(403, "账号已停用")
    set_cookie(response, COOKIE, sign({"kind": "session", "role": "player", "sub": str(participant.id)}), 259200)
    return {"ok": True}


@app.get("/api/auth/wechat/start")
def wechat_start():
    if not (WECHAT_APP_ID and WECHAT_APP_SECRET):
        raise HTTPException(503, "未配置公众号网页授权")
    state = secrets.token_urlsafe(20)
    url = "https://open.weixin.qq.com/connect/oauth2/authorize?" + urlencode({
        "appid": WECHAT_APP_ID,
        "redirect_uri": PUBLIC_BASE_URL + "/api/auth/wechat/callback",
        "response_type": "code", "scope": "snsapi_base", "state": state,
    }) + "#wechat_redirect"
    r = RedirectResponse(url, status_code=302)
    set_cookie(r, STATE_COOKIE, state, 600)
    return r


@app.get("/api/auth/wechat/callback")
async def wechat_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(db_session)):
    state_cookie = request.cookies.get(STATE_COOKIE)
    if not state_cookie or not hmac.compare_digest(state_cookie, state) or not code:
        raise HTTPException(400, "微信登录校验失败，请重新进入")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get("https://api.weixin.qq.com/sns/oauth2/access_token", params={
                "appid": WECHAT_APP_ID, "secret": WECHAT_APP_SECRET,
                "code": code, "grant_type": "authorization_code",
            })
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "微信授权接口请求失败")
    openid = data.get("openid")
    if not openid or "errcode" in data:
        raise HTTPException(401, "公众号授权失败，请检查授权权限或重试")
    p = db.scalar(select(Participant).where(Participant.openid == openid))
    r = RedirectResponse(PUBLIC_BASE_URL + ("/" if p else "/?bind=1"), status_code=302)
    clear_cookie(r, STATE_COOKIE)
    if p and p.active:
        set_cookie(r, COOKIE, sign({"kind": "session", "role": "player", "sub": str(p.id)}), 259200)
    else:
        set_cookie(r, PENDING_COOKIE, sign({"kind": "pending", "openid": openid}, 10), 600)
    return r


@app.post("/api/auth/bind")
def bind_player(payload: BindRequest, request: Request, response: Response, db: Session = Depends(db_session)):
    token = request.cookies.get(PENDING_COOKIE)
    if not token:
        raise HTTPException(401, "请先通过微信完成身份验证")
    openid = verify(token, "pending")["openid"]
    p = db.scalar(select(Participant).where(Participant.student_id == payload.student_id.strip()).with_for_update())
    if not p or not p.active or not p.bind_hash or not hmac.compare_digest(p.bind_hash, digest_code(payload.code)):
        raise HTTPException(400, "学号/工号或绑定码错误")
    if p.openid and p.openid != openid:
        raise HTTPException(409, "此学号已绑定其他微信身份，请联系管理员")
    p.openid, p.bind_hash = openid, None
    db.commit()
    set_cookie(response, COOKIE, sign({"kind": "session", "role": "player", "sub": str(p.id)}), 259200)
    clear_cookie(response, PENDING_COOKIE)
    return {"ok": True}


@app.post("/api/auth/demo")
def demo_login(response: Response, db: Session = Depends(db_session), student_id: str = "DEMO001"):
    if not DEMO_MODE:
        raise HTTPException(404, "演示登录已关闭")
    if student_id not in ("DEMO001", "DEMO002"):
        raise HTTPException(400, "未知演示用户")
    p = db.scalar(select(Participant).where(Participant.student_id == student_id))
    set_cookie(response, COOKIE, sign({"kind": "session", "role": "player", "sub": str(p.id)}), 259200)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_cookie(response, COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    p = db.get(Participant, pid)
    if not p:
        raise HTTPException(404, "账号不存在")
    return profile(db, p)


@app.get("/api/leaderboard")
def leaderboard(db: Session = Depends(db_session), pid: int = Depends(require_player)):
    order = (Participant.energy_earned.desc(),
             func.coalesce(Participant.energy_score_at, Participant.created_at).asc(),
             Participant.id.asc())
    rows = db.scalars(select(Participant).where(Participant.active == True).order_by(*order).limit(LEADERBOARD_LIMIT)).all()
    mine = db.get(Participant, pid)
    my_rank = rank_of(db, mine)
    return {"players": [{"rank": index, "name": p.name,
                          "score": p.energy_earned, "me": p.id == pid}
                         for index, p in enumerate(rows, 1)],
            "my_rank": my_rank,
            "my_position": {"rank": my_rank, "name": mine.name, "score": mine.energy_earned},
            "limit": LEADERBOARD_LIMIT}


@app.get("/api/tasks")
def tasks(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    task_rows = db.scalars(select(Task).where(Task.active == True).order_by(Task.id)).all()
    claims = db.scalars(select(TaskClaim).where(TaskClaim.participant_id == pid)).all()
    out = []
    for task in task_rows:
        mine = [c for c in claims if c.task_id == task.id]
        pending = next((c for c in mine if c.status == "pending"), None)
        completed = sum(c.status == "completed" for c in mine)
        sibling_ids = (set(db.scalars(select(Task.id).where(Task.exclusive_group == task.exclusive_group)).all())
                       if task.exclusive_group else set())
        used_group = any(c.task_id in sibling_ids and c.status in ("pending", "completed") for c in claims)
        out.append({"id": task.id, "title": task.title, "description": task.description,
                    "category": task.category, "blood_reward": task.blood_reward,
                    "energy_reward": task.energy_reward, "blood_per_attempt": task.blood_per_attempt,
                    "energy_per_success": task.energy_per_success, "min_success": task.min_success,
                    "max_claims": task.max_claims, "exclusive_group": task.exclusive_group,
                    "completed_count": completed,
                    "status": "pending" if pending else ("done" if task.max_claims and completed >= task.max_claims else ("done" if used_group else "available")),
                    "pending_id": pending.id if pending else None})
    return out


@app.post("/api/tasks/{task_id}/claim")
def claim_task(task_id: int, pid: int = Depends(require_player), db: Session = Depends(db_session)):
    p = player_for_update(db, pid)
    task = db.get(Task, task_id)
    if not task or not task.active:
        raise HTTPException(404, "任务不存在")
    mine = db.scalars(select(TaskClaim).where(TaskClaim.participant_id == p.id)).all()
    if any(c.task_id == task_id and c.status == "pending" for c in mine):
        raise HTTPException(409, "该任务已领取，等待工作人员确认")
    if task.max_claims is not None and sum(c.task_id == task_id and c.status == "completed" for c in mine) >= task.max_claims:
        raise HTTPException(409, "已经达到任务领取次数上限")
    if task.exclusive_group:
        sibling_ids = db.scalars(select(Task.id).where(Task.exclusive_group == task.exclusive_group)).all()
        if any(c.task_id in sibling_ids and c.status in ("pending", "completed") for c in mine):
            raise HTTPException(409, "互斥奖励只能选择一种")
    c = TaskClaim(participant_id=pid, task_id=task_id, status="pending")
    db.add(c)
    db.commit()
    return {"ok": True, "claim_id": c.id, "message": "已领取，请现场工作人员核验"}


@app.get("/api/draw")
def draw_status(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    draw = db.scalar(select(Draw).where(Draw.participant_id == pid))
    checkin = db.scalar(select(Task).where(Task.code == "checkin"))
    unlocked = bool(db.scalar(select(TaskClaim.id).where(TaskClaim.participant_id == pid, TaskClaim.task_id == checkin.id, TaskClaim.status == "completed")))
    result = draw_blood(db, draw) if draw else None
    return {"unlocked": unlocked, "already_drawn": bool(draw),
            "result": result if result else None, "status": "reversed" if draw and result == 0 else ("drawn" if draw else "not_drawn"),
            "available_at": DRAW_OPENS_AT.isoformat(),
            "can_spin": unlocked and not draw and now() >= DRAW_OPENS_AT}


@app.post("/api/draw")
def spin_draw(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    if now() < DRAW_OPENS_AT:
        raise HTTPException(409, "幸运轮尚未开放")
    p = player_for_update(db, pid)
    checkin = db.scalar(select(Task.id).where(Task.code == "checkin"))
    if not db.scalar(select(TaskClaim.id).where(TaskClaim.participant_id == pid,
                                                 TaskClaim.task_id == checkin,
                                                 TaskClaim.status == "completed")):
        raise HTTPException(403, "请先完成注册")
    if db.scalar(select(Draw.id).where(Draw.participant_id == pid)):
        raise HTTPException(409, "已经参加过幸运轮")
    blood = random.SystemRandom().choices(DRAW_PRIZES, weights=DRAW_WEIGHTS, k=1)[0]
    draw = Draw(participant_id=p.id, prize_blood=blood)
    db.add(draw)
    db.flush()
    add_ledger(db, p, "blood", blood, "热血幸运轮奖励", "draw", draw.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "已经参加过幸运轮")
    return {"ok": True, "blood": blood, "result": blood}


@app.post("/api/energy-boost/use")
def use_energy_boost(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    p = player_for_update(db, pid)
    if p.energy_boost_used:
        raise HTTPException(409, "能量加倍道具已经使用")
    donation = db.scalar(select(TaskClaim.id).join(Task, TaskClaim.task_id == Task.id)
                         .where(TaskClaim.participant_id == pid, TaskClaim.status == "completed",
                                Task.code.in_(("donate_blood", "donate_energy"))).limit(1))
    if not donation:
        raise HTTPException(409, "完成献血并由工作人员核验后才可使用")
    if p.energy_earned <= 0:
        raise HTTPException(409, "当前累计能量为 0，请先获得能量")
    bonus = p.energy_earned * 2
    add_ledger(db, p, "energy", bonus, "三倍能量道具", "boost_v2", donation)
    p.energy_boost_used = True
    db.commit()
    return {"ok": True, "bonus": bonus}


@app.get("/api/prizes")
def prizes(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    return [{"id": p.id, "title": p.title, "description": p.description,
             "price": p.energy_price, "stock": p.stock, "max_per_player": p.max_per_player}
            for p in db.scalars(select(Prize).where(Prize.active == True)).all()]


@app.get("/api/me/redemptions")
def my_redemptions(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    rows = db.execute(select(Redemption, Prize.title).join(Prize, Redemption.prize_id == Prize.id)
                      .where(Redemption.participant_id == pid).order_by(Redemption.id.desc()).limit(30)).all()
    return [{"id": r.id, "title": title, "code": r.pickup_code, "price": r.price,
             "quantity": r.quantity, "status": r.status}
            for r, title in rows]


@app.post("/api/redemptions")
def redeem(data: RedeemRequest, pid: int = Depends(require_player), db: Session = Depends(db_session)):
    p = player_for_update(db, pid)
    previous = db.scalar(select(Redemption).where(Redemption.request_key == data.request_key))
    if previous:
        if (previous.participant_id != pid or previous.prize_id != data.prize_id
                or previous.quantity != data.quantity):
            raise HTTPException(409, "请求标识已用于其他兑换")
        return {"code": previous.pickup_code, "id": previous.id,
                "quantity": previous.quantity, "already_processed": True}
    prize = db.scalar(select(Prize).where(Prize.id == data.prize_id).with_for_update())
    if not prize or not prize.active:
        raise HTTPException(404, "奖励已下架")
    if prize.stock < data.quantity:
        raise HTTPException(409, "库存不足")
    if prize.max_per_player is not None:
        count = db.scalar(select(func.coalesce(func.sum(Redemption.quantity), 0)).where(
            Redemption.participant_id == pid, Redemption.prize_id == prize.id,
            Redemption.status != "cancelled"))
        if count + data.quantity > prize.max_per_player:
            raise HTTPException(409, "达到每人兑换次数上限")
    total_price = prize.energy_price * data.quantity
    if p.energy < total_price:
        raise HTTPException(409, "可用能量不足")
    r = Redemption(participant_id=pid, prize_id=prize.id, request_key=data.request_key,
                   pickup_code=secrets.token_hex(5).upper(), price=total_price,
                   quantity=data.quantity)
    db.add(r)
    db.flush()
    add_ledger(db, p, "energy", -total_price, "兑换：" + prize.title + f" ×{data.quantity}", "redeem", r.id)
    prize.stock -= data.quantity
    db.commit()
    return {"id": r.id, "code": r.pickup_code, "quantity": r.quantity,
            "already_processed": False}


@app.get("/api/me/ledger")
def my_ledger(pid: int = Depends(require_player), db: Session = Depends(db_session)):
    rows = db.scalars(select(Ledger).where(Ledger.participant_id == pid).order_by(Ledger.id.desc()).limit(40)).all()
    return [{"id": x.id, "kind": x.kind, "delta": x.delta, "reason": x.reason,
             "created_at": x.created_at.isoformat()} for x in rows]


@app.post("/api/admin/login")
def admin_login(data: AdminLogin, response: Response, db: Session = Depends(db_session)):
    staff = db.scalar(select(StaffUser).where(StaffUser.username == data.username.strip()).with_for_update())
    if not staff or not staff.active:
        raise HTTPException(401, "工作人员账号或密码错误")
    current = now()
    locked_until = as_utc(staff.login_locked_until)
    if locked_until and locked_until > current:
        retry_after = max(1, int((locked_until - current).total_seconds()) + 1)
        raise HTTPException(429, "登录尝试次数过多，请稍后重试", headers={"Retry-After": str(retry_after)})
    if not verify_staff_password(data.password, staff.password_hash):
        started = as_utc(staff.login_window_started_at)
        if not started or current - started >= LOGIN_WINDOW:
            staff.login_window_started_at = current
            staff.login_failures = 0
        staff.login_failures += 1
        if staff.login_failures >= LOGIN_FAILURE_LIMIT:
            staff.login_locked_until = current + LOGIN_LOCK
        else:
            staff.login_locked_until = None
        db.commit()
        if staff.login_locked_until:
            raise HTTPException(429, "登录尝试次数过多，请稍后重试", headers={"Retry-After": str(int(LOGIN_LOCK.total_seconds()))})
        raise HTTPException(401, "工作人员账号或密码错误")
    staff.login_failures = 0
    staff.login_window_started_at = None
    staff.login_locked_until = None
    db.commit()
    set_cookie(response, STAFF_COOKIE, sign({"kind": "staff", "sub": str(staff.id),
                                             "version": staff.auth_version}, 12 * 60), 43200)
    return {"ok": True, **staff_public(db, staff)}


@app.get("/api/admin/me")
def admin_me(staff: StaffUser = Depends(require_admin), db: Session = Depends(db_session)):
    return staff_public(db, staff)


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    clear_cookie(response, STAFF_COOKIE)
    return {"ok": True}


@app.get("/api/admin/summary")
def admin_summary(task_id: int | None = None, staff: StaffUser = Depends(require_admin), db: Session = Depends(db_session)):
    if task_id is not None:
        check_task_permission(db, staff, task_id)
    permitted = [task_id] if task_id is not None else staff_task_ids(db, staff)
    query = select(func.count()).select_from(TaskClaim).where(TaskClaim.status == "pending")
    if staff.role != "super" or task_id is not None:
        query = query.where(TaskClaim.task_id.in_(permitted))
    participants_query = select(func.count()).select_from(Participant).where(Participant.active == True)
    if task_id is not None:
        participants_query = participants_query.where(Participant.id.in_(select(TaskClaim.participant_id).where(TaskClaim.task_id == task_id)))
    return {"participants": db.scalar(participants_query) if staff.role == "super" else 0,
            "pending_claims": db.scalar(query),
            "pending_redemptions": db.scalar(select(func.count()).select_from(Redemption).where(Redemption.status == "pending")) if staff.role == "super" and task_id is None else 0}


@app.get("/api/admin/tasks")
def admin_tasks(staff: StaffUser = Depends(require_admin), db: Session = Depends(db_session)):
    query = select(Task).order_by(Task.id)
    if staff.role != "super":
        query = query.where(Task.id.in_(staff_task_ids(db, staff)), Task.active == True)
    return [{"id": t.id, "code": t.code, "title": t.title, "description": t.description,
             "category": t.category, "blood_reward": t.blood_reward, "energy_reward": t.energy_reward,
             "blood_per_attempt": t.blood_per_attempt, "energy_per_success": t.energy_per_success,
             "min_success": t.min_success, "max_claims": t.max_claims,
             "exclusive_group": t.exclusive_group, "active": t.active} for t in db.scalars(query)]


@app.get("/api/admin/participants")
def admin_participants(q: str = "", _=Depends(require_super), db: Session = Depends(db_session)):
    draws = {d.id: d for d in db.scalars(select(Draw)).all()}
    boost_participant_ids = set(db.scalars(select(Ledger.participant_id).where(
        Ledger.kind == "energy", Ledger.source.in_(("boost", "boost_v2"))).distinct()).all())
    draw_results = {d.participant_id: d.prize_blood for d in draws.values()}
    draw_statuses = {d.participant_id: "drawn" for d in draws.values()}
    for adjustment in db.scalars(select(DrawAudit).order_by(DrawAudit.id)):
        if adjustment.draw_id in draws:
            player_id = draws[adjustment.draw_id].participant_id
            draw_results[player_id] = adjustment.after_blood or None
            draw_statuses[player_id] = "reversed" if adjustment.after_blood == 0 else "drawn"
    query = select(Participant).order_by(Participant.id.desc())
    if q.strip():
        number = participant_number_search(q)
        if number is not None:
            query = query.where(Participant.id == number)
        else:
            term = f"%{q.strip()[:80]}%"
            query = query.where(or_(Participant.name.ilike(term), Participant.student_id.ilike(term),
                                    Participant.phone.ilike(term)))
    return [{"id": p.id, "student_id": p.student_id, "name": p.name,
             "phone": p.phone, "identity": p.identity, "college": p.college, "active": p.active,
             "class_name": p.class_name, "bound": bool(p.openid), "blood": p.blood,
             "energy": p.energy, "energy_earned": p.energy_earned,
             "boost_recorded": p.id in boost_participant_ids,
             "draw_blood": draw_results.get(p.id), "draw_status": draw_statuses.get(p.id, "not_drawn")}
            for p in db.scalars(query.limit(200))]


@app.get("/api/admin/draws/{participant_id}")
def admin_draw_detail(participant_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    draw = db.scalar(select(Draw).where(Draw.participant_id == participant_id))
    if not draw:
        raise HTTPException(404, "参与者尚未参加幸运轮")
    current = draw_blood(db, draw)
    history = db.execute(select(DrawAudit, StaffUser.username)
                         .outerjoin(StaffUser, DrawAudit.staff_id == StaffUser.id)
                         .where(DrawAudit.draw_id == draw.id).order_by(DrawAudit.id.desc())).all()
    return {"participant_id": participant_id, "draw_id": draw.id,
            "original_blood": draw.prize_blood, "blood": current if current else None,
            "status": "reversed" if current == 0 else "drawn",
            "history": [{"id": a.id, "action": a.action, "reason": a.reason,
                         "before_blood": a.before_blood, "after_blood": a.after_blood,
                         "staff_name": username or "历史账号", "created_at": a.created_at.isoformat()}
                        for a, username in history]}


def correct_draw(db: Session, participant_id: int, staff: StaffUser, blood: int, reason: str, action: str):
    reason = reason.strip()
    if not reason:
        raise HTTPException(400, "请填写修正原因")
    p = player_for_update(db, participant_id)
    draw = db.scalar(select(Draw).where(Draw.participant_id == participant_id).with_for_update())
    if not draw:
        raise HTTPException(404, "参与者尚未参加幸运轮")
    previous = draw_blood(db, draw)
    if previous == blood:
        raise HTTPException(409, "幸运轮结果未发生变化")
    audit = DrawAudit(draw_id=draw.id, staff_id=staff.id, action=action,
                      reason=reason, before_blood=previous, after_blood=blood)
    db.add(audit)
    db.flush()
    add_ledger(db, p, "blood", blood - previous, "幸运轮修正：" + reason[:160],
               "draw_adjust", audit.id, allow_debt=True)
    db.commit()
    return {"ok": True, "participant_id": participant_id, "draw_id": draw.id,
            "blood": blood if blood else None, "status": "reversed" if blood == 0 else "drawn",
            "blood_delta": blood - previous, "audit_id": audit.id}


@app.patch("/api/admin/draws/{participant_id}")
def admin_adjust_draw(participant_id: int, data: AdjustDraw, staff: StaffUser = Depends(require_super),
                      db: Session = Depends(db_session)):
    return correct_draw(db, participant_id, staff, data.blood, data.reason, "adjust")


@app.post("/api/admin/draws/{participant_id}/reverse")
def admin_reverse_draw(participant_id: int, data: ReverseClaim, staff: StaffUser = Depends(require_super),
                       db: Session = Depends(db_session)):
    return correct_draw(db, participant_id, staff, 0, data.reason, "reverse")


@app.get("/api/admin/energy-boosts/{participant_id}")
def admin_boost_detail(participant_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    p = db.get(Participant, participant_id)
    boost = latest_boost(db, participant_id)
    if not p or not boost:
        raise HTTPException(404, "参与者尚未使用三倍能量道具")
    bonus = effective_boost_bonus(db, boost)
    history = db.execute(select(BoostAudit, StaffUser.username)
                         .outerjoin(StaffUser, BoostAudit.staff_id == StaffUser.id)
                         .where(BoostAudit.boost_ledger_id == boost.id)
                         .order_by(BoostAudit.id.desc())).all()
    return {"participant_id": participant_id, "boost_ledger_id": boost.id,
            "original_bonus": boost.delta, "bonus": bonus,
            "status": "reversed" if bonus == 0 else "active", "used": p.energy_boost_used,
            "history": [{"id": audit.id, "action": audit.action, "reason": audit.reason,
                         "before_bonus": audit.before_bonus, "after_bonus": audit.after_bonus,
                         "staff_name": username or "历史账号", "created_at": audit.created_at.isoformat()}
                        for audit, username in history]}


def correct_boost(db: Session, participant_id: int, staff: StaffUser, bonus: int, reason: str, action: str):
    reason = reason.strip()
    if not reason:
        raise HTTPException(400, "请填写修正原因")
    p = player_for_update(db, participant_id)
    boost = latest_boost(db, participant_id)
    if not boost:
        raise HTTPException(404, "参与者尚未使用三倍能量道具")
    previous = effective_boost_bonus(db, boost)
    if previous == bonus:
        raise HTTPException(409, "三倍能量奖励未发生变化")
    if bonus > 0:
        donation = db.get(TaskClaim, boost.source_id) if boost.source == "boost_v2" else None
        if donation and donation.status != "completed":
            raise HTTPException(409, "献血任务已撤回，无法恢复三倍能量奖励")
    audit = BoostAudit(boost_ledger_id=boost.id, staff_id=staff.id, action=action,
                       reason=reason, before_bonus=previous, after_bonus=bonus)
    db.add(audit)
    db.flush()
    add_ledger(db, p, "energy", bonus - previous, "三倍能量修正：" + reason[:160],
               "boost_manual_adjust", audit.id, allow_debt=True, adjust_earned=True)
    p.energy_boost_used = True
    db.commit()
    return {"ok": True, "participant_id": participant_id, "boost_ledger_id": boost.id,
            "bonus": bonus, "status": "reversed" if bonus == 0 else "active",
            "used": True, "energy_delta": bonus - previous, "audit_id": audit.id}


@app.patch("/api/admin/energy-boosts/{participant_id}")
def admin_adjust_boost(participant_id: int, data: AdjustBoost, staff: StaffUser = Depends(require_super),
                       db: Session = Depends(db_session)):
    return correct_boost(db, participant_id, staff, data.bonus, data.reason, "adjust")


@app.post("/api/admin/energy-boosts/{participant_id}/reverse")
def admin_reverse_boost(participant_id: int, data: ReverseClaim, staff: StaffUser = Depends(require_super),
                        db: Session = Depends(db_session)):
    return correct_boost(db, participant_id, staff, 0, data.reason, "reverse")


@app.post("/api/admin/participants")
def admin_create_player(data: CreateParticipant, _=Depends(require_super), db: Session = Depends(db_session)):
    if db.scalar(select(Participant.id).where(Participant.student_id == data.student_id.strip())):
        raise HTTPException(409, "学号或工号已存在")
    code = secrets.token_urlsafe(10).replace("-", "").replace("_", "")[:12].upper()
    p = Participant(student_id=data.student_id, name=data.name.strip(), class_name=data.class_name.strip(),
                    phone=data.phone, identity=data.identity, college=data.college,
                    bind_hash=digest_code(code))
    try:
        db.add(p)
        db.flush()
        ensure_participant_number(db, p)
        checkin_id = db.scalar(select(Task.id).where(Task.code == "checkin"))
        if checkin_id is not None:
            db.add(TaskClaim(participant_id=p.id, task_id=checkin_id,
                             status="completed", completed_at=now()))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "学号或工号已存在")
    # Binding code is returned once and never stored as plaintext.
    return {"id": p.id, "student_id": p.student_id, "bind_code": code}


@app.patch("/api/admin/participants/{participant_id}")
def admin_edit_player(participant_id: int, data: EditParticipant, _=Depends(require_super),
                      db: Session = Depends(db_session)):
    p = player_for_update(db, participant_id)
    changes = data.model_dump(exclude_unset=True)
    identity = changes.get("identity", p.identity)
    identifier = changes.get("student_id", p.student_id)
    college = changes.get("college", p.college)
    if identity != p.identity and "college" not in changes:
        raise HTTPException(400, "切换身份时请重新选择学院")
    if identity == "student":
        if ("identity" in changes or "student_id" in changes) and not (
                len(identifier) == 12 and identifier.isascii() and identifier.isdecimal()):
            raise HTTPException(400, "学号应为 12 位数字")
        if ("identity" in changes or "college" in changes) and college not in COLLEGES:
            raise HTTPException(400, "请选择学院")
        if p.identity != "student" and "identity" in changes and "class_name" not in changes:
            raise HTTPException(400, "切换为学生时请填写班级")
        if "class_name" in changes and not changes["class_name"].strip():
            raise HTTPException(400, "请填写班级")
    else:
        if not identifier.strip():
            raise HTTPException(400, "请填写工号")
        if ("identity" in changes or "college" in changes) and college not in STAFF_COLLEGES:
            raise HTTPException(400, "请选择学院")
        if p.identity != "staff" and changes.get("identity") == "staff":
            changes["class_name"] = ""
    for key in ("name", "student_id"):
        if key in changes and not changes[key].strip():
            raise HTTPException(400, "资料不能留空")
    if "class_name" in changes:
        changes["class_name"] = changes["class_name"].strip()
    for field, value in changes.items():
        setattr(p, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "学号或工号已存在")
    return {"ok": True}


@app.delete("/api/admin/participants/{participant_id}")
def admin_delete_player(participant_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    p = player_for_update(db, participant_id)
    p.active = False
    db.commit()
    return {"ok": True}


@app.get("/api/admin/staff")
def admin_staff(_=Depends(require_super), db: Session = Depends(db_session)):
    return [staff_public(db, s) for s in db.scalars(select(StaffUser).order_by(StaffUser.id))]


@app.post("/api/admin/staff")
def admin_create_staff(data: StaffCreate, _=Depends(require_super), db: Session = Depends(db_session)):
    username = data.username.strip()
    if not username:
        raise HTTPException(400, "请填写账号名")
    validate_task_ids(db, data.role, data.task_ids)
    s = StaffUser(username=username, password_hash=hash_staff_password(data.password), role=data.role,
                  active=data.active)
    db.add(s)
    try:
        db.flush()
        db.add_all(StaffTaskGrant(staff_id=s.id, task_id=task_id) for task_id in data.task_ids)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "工作人员账号名已存在")
    return staff_public(db, s)


@app.patch("/api/admin/staff/{staff_id}")
def admin_edit_staff(staff_id: int, data: StaffEdit, actor: StaffUser = Depends(require_super),
                     db: Session = Depends(db_session)):
    s = db.scalar(select(StaffUser).where(StaffUser.id == staff_id).with_for_update())
    if not s:
        raise HTTPException(404, "工作人员账号不存在")
    changes = data.model_dump(exclude_unset=True)
    if s.username == "管理员" and (changes.get("role", "super") != "super" or changes.get("active") is False or
                                   ("username" in changes and changes["username"] != "管理员")):
        raise HTTPException(409, "初始最高级管理员账号必须保留")
    role = changes.get("role", s.role)
    grants = changes.get("task_ids", staff_task_ids(db, s) if role == s.role else [])
    validate_task_ids(db, role, grants)
    if "username" in changes:
        if not changes["username"].strip():
            raise HTTPException(400, "请填写账号名")
        s.username = changes["username"].strip()
    if "password" in changes:
        s.password_hash = hash_staff_password(changes["password"])
    if "active" in changes:
        s.active = changes["active"]
    s.role = role
    if actor.id == s.id and not s.active:
        raise HTTPException(409, "无法停用当前账号")
    if changes:
        s.auth_version += 1
    if "task_ids" in changes or "role" in changes:
        db.execute(delete(StaffTaskGrant).where(StaffTaskGrant.staff_id == s.id))
        db.add_all(StaffTaskGrant(staff_id=s.id, task_id=task_id) for task_id in grants)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "工作人员账号名已存在")
    return staff_public(db, s)


@app.delete("/api/admin/staff/{staff_id}")
def admin_delete_staff(staff_id: int, actor: StaffUser = Depends(require_super), db: Session = Depends(db_session)):
    s = db.scalar(select(StaffUser).where(StaffUser.id == staff_id).with_for_update())
    if not s:
        raise HTTPException(404, "工作人员账号不存在")
    if actor.id == s.id or s.username == "管理员":
        raise HTTPException(409, "不能停用当前账号或初始最高级管理员")
    s.active = False
    s.auth_version += 1
    db.commit()
    return {"ok": True}


@app.post("/api/admin/tasks")
def admin_create_task(data: CreateTask, _=Depends(require_super), db: Session = Depends(db_session)):
    t = Task(**data.model_dump(exclude_unset=True))
    db.add(t)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "项目代码已存在")
    return {"id": t.id}


@app.patch("/api/admin/tasks/{task_id}")
def admin_edit_task(task_id: int, data: EditTask, _=Depends(require_super), db: Session = Depends(db_session)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "项目不存在")
    apply_edit(t, data)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "项目代码已存在")
    return {"ok": True}


@app.delete("/api/admin/tasks/{task_id}")
def admin_delete_task(task_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "项目不存在")
    t.active = False
    db.commit()
    return {"ok": True}


@app.get("/api/admin/prizes")
def admin_prizes(_=Depends(require_super), db: Session = Depends(db_session)):
    return [{"id": p.id, "code": p.code, "title": p.title, "description": p.description,
             "energy_price": p.energy_price, "price": p.energy_price, "stock": p.stock,
             "max_per_player": p.max_per_player, "active": p.active}
            for p in db.scalars(select(Prize).order_by(Prize.id))]


@app.post("/api/admin/prizes")
def admin_create_prize(data: CreatePrize, _=Depends(require_super), db: Session = Depends(db_session)):
    p = Prize(**data.model_dump(exclude_unset=True))
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "奖品代码已存在")
    return {"id": p.id}


@app.patch("/api/admin/prizes/{prize_id}")
def admin_edit_prize(prize_id: int, data: EditPrize, _=Depends(require_super), db: Session = Depends(db_session)):
    p = db.get(Prize, prize_id)
    if not p:
        raise HTTPException(404, "奖品不存在")
    apply_edit(p, data)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "奖品代码已存在")
    return {"ok": True}


@app.delete("/api/admin/prizes/{prize_id}")
def admin_delete_prize(prize_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    p = db.get(Prize, prize_id)
    if not p:
        raise HTTPException(404, "奖品不存在")
    p.active = False
    db.commit()
    return {"ok": True}


@app.get("/api/admin/claims")
def admin_claims(status: str = "pending", q: str = "", task_id: int | None = None,
                 staff: StaffUser = Depends(require_admin), db: Session = Depends(db_session)):
    if status not in {"pending", "completed", "rejected", "reversed"}:
        raise HTTPException(400, "任务状态无效")
    query = (select(TaskClaim, Task, Participant).join(Task, TaskClaim.task_id == Task.id)
             .join(Participant, TaskClaim.participant_id == Participant.id)
             .where(TaskClaim.status == status, Task.category != "checkin"))
    if task_id is not None:
        check_task_permission(db, staff, task_id)
        query = query.where(Task.id == task_id)
    elif staff.role != "super":
        query = query.where(Task.id.in_(staff_task_ids(db, staff)))
    if q.strip():
        number = participant_number_search(q)
        if number is not None:
            query = query.where(Participant.id == number)
        else:
            term = f"%{q.strip()[:80]}%"
            query = query.where(or_(Participant.name.ilike(term), Participant.student_id.ilike(term),
                                    Task.title.ilike(term)))
    rows = db.execute(query.order_by(TaskClaim.id.asc() if status == "pending" else TaskClaim.id.desc())
                      .limit(100)).all()
    return [{"id": c.id, "participant_id": p.id, "student_id": p.student_id, "name": p.name, "title": t.title,
             "description": t.description, "category": t.category, "task_id": t.id,
             "status": c.status, "created_at": c.created_at.isoformat(),
             "completed_at": c.completed_at.isoformat() if c.completed_at else None,
             "attempts": c.attempts, "successes": c.successes,
             "blood_delta": c.blood_delta, "energy_delta": c.energy_delta,
             "blood_reward": t.blood_reward, "energy_reward": t.energy_reward,
             "blood_per_attempt": t.blood_per_attempt,
             "energy_per_success": t.energy_per_success, "min_success": t.min_success}
            for c, t, p in rows]


@app.post("/api/admin/claims/{claim_id}/complete")
def complete_claim(claim_id: int, data: CompleteClaim, staff: StaffUser = Depends(require_admin), db: Session = Depends(db_session)):
    lookup = db.get(TaskClaim, claim_id)
    if not lookup:
        raise HTTPException(404, "任务登记不存在")
    check_task_permission(db, staff, lookup.task_id)
    p = player_for_update(db, lookup.participant_id)
    c = db.scalar(select(TaskClaim).where(TaskClaim.id == claim_id).with_for_update().execution_options(populate_existing=True))
    if c.status != "pending":
        raise HTTPException(409, "此任务已被其他工作人员处理")
    task = db.get(Task, c.task_id)
    if task.category in ("game", "dart"):
        if data.attempts <= 0 or data.successes > data.attempts:
            raise HTTPException(400, "游戏尝试次数必须大于0，成功数不可大于尝试数")
        blood_change = -(data.attempts * task.blood_per_attempt)
        if task.category == "dart":
            hits = data.rings10 + data.rings9 + data.rings8
            if hits > data.attempts or data.successes:
                raise HTTPException(400, "飞镖命中次数不能超过尝试次数，且无需填写普通成功次数")
            energy_change = (data.rings10 * 3 + data.rings9 * 2 + data.rings8) if hits >= task.min_success else 0
        else:
            if data.rings10 or data.rings9 or data.rings8:
                raise HTTPException(400, "普通游戏无需填写飞镖环数")
            energy_change = data.successes * task.energy_per_success if data.successes >= task.min_success else 0
    else:
        if data.attempts or data.successes or data.rings10 or data.rings9 or data.rings8:
            raise HTTPException(400, "此项目无需填写游戏次数")
        blood_change, energy_change = task.blood_reward, task.energy_reward
        if task.code == "donate_energy":
            blood_change, energy_change = 50, 35
    # Recheck game balance while holding participant lock.
    if p.blood + blood_change < 0:
        raise HTTPException(409, "参与者血值不足，无法确认本轮游戏")
    add_ledger(db, p, "blood", blood_change, "任务：" + task.title, "claim", c.id)
    add_ledger(db, p, "energy", energy_change, "任务：" + task.title, "claim", c.id)
    c.attempts, c.successes = data.attempts, (data.rings10+data.rings9+data.rings8 if task.category=="dart" else data.successes)
    c.blood_delta, c.energy_delta = blood_change, energy_change
    c.status, c.completed_at = "completed", now()
    db.add(ClaimAudit(claim_id=c.id, staff_id=staff.id, action="complete", reason="任务核验",
                      before_status="pending", after_status="completed", after_blood=blood_change,
                      after_energy=energy_change))
    db.commit()
    return {"ok": True, "blood_delta": blood_change, "energy_delta": energy_change}


@app.post("/api/admin/claims/{claim_id}/reject")
def reject_claim(claim_id: int, staff: StaffUser = Depends(require_admin), db: Session = Depends(db_session)):
    lookup = db.get(TaskClaim, claim_id)
    if not lookup:
        raise HTTPException(404, "任务登记不存在")
    check_task_permission(db, staff, lookup.task_id)
    player_for_update(db, lookup.participant_id)
    claim = db.scalar(select(TaskClaim).where(TaskClaim.id == claim_id).with_for_update().execution_options(populate_existing=True))
    if claim.status != "pending":
        raise HTTPException(409, "只能拒绝等待审核的任务")
    claim.status = "rejected"
    db.add(ClaimAudit(claim_id=claim.id, staff_id=staff.id, action="reject", reason="任务核验",
                      before_status="pending", after_status="rejected"))
    db.commit()
    return {"ok": True, "status": "rejected", "blood_delta": 0, "energy_delta": 0}


@app.get("/api/admin/audit")
@app.get("/api/admin/claim-audit")
def admin_claim_audit(task_id: int | None = None, q: str = "",
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
                      _=Depends(require_super),
                      db: Session = Depends(db_session)):
    query = (select(ClaimAudit, TaskClaim, Task, Participant, StaffUser.username)
             .join(TaskClaim, ClaimAudit.claim_id == TaskClaim.id)
             .join(Task, TaskClaim.task_id == Task.id)
             .join(Participant, TaskClaim.participant_id == Participant.id)
             .outerjoin(StaffUser, ClaimAudit.staff_id == StaffUser.id))
    if task_id is not None:
        query = query.where(Task.id == task_id)
    if q.strip():
        number = participant_number_search(q)
        if number is not None:
            query = query.where(Participant.id == number)
        else:
            term = f"%{q.strip()[:80]}%"
            query = query.where(or_(Participant.name.ilike(term), Participant.student_id.ilike(term),
                                    Task.title.ilike(term), StaffUser.username.ilike(term)))
    rows = db.execute(query.order_by(ClaimAudit.id.desc()).offset(offset).limit(limit + 1)).all()
    items = [{"id": audit.id, "claim_id": claim.id, "task_id": task.id, "task": task.title,
             "task_title": task.title, "participant_name": player.name,
             "participant_id": player.id, "name": player.name, "student_id": player.student_id,
             "staff_id": audit.staff_id, "staff_name": staff_name or "历史记录",
             "actor": staff_name or "历史记录",
             "action": audit.action, "reason": audit.reason,
             "detail": (f"{audit.reason} · 血值 {audit.before_blood} → {audit.after_blood}，"
                        f"能量 {audit.before_energy} → {audit.after_energy}"),
             "before_status": audit.before_status, "after_status": audit.after_status,
             "before_blood": audit.before_blood, "after_blood": audit.after_blood,
             "before_energy": audit.before_energy, "after_energy": audit.after_energy,
             "created_at": audit.created_at.isoformat()}
             for audit, claim, task, player, staff_name in rows[:limit]]
    return {"items": items, "next_offset": offset + limit if len(rows) > limit else None}


def correct_claim(db: Session, claim_id: int, staff: StaffUser, reason: str,
                  new_blood: int, new_energy: int, action: str, next_status: str):
    lookup = db.get(TaskClaim, claim_id)
    if not lookup:
        raise HTTPException(404, "任务登记不存在")
    p = player_for_update(db, lookup.participant_id)
    claim = db.scalar(select(TaskClaim).where(TaskClaim.id == claim_id).with_for_update().execution_options(populate_existing=True))
    if claim.status != "completed":
        raise HTTPException(409, "只能修正或撤回已核验的任务")
    task = db.get(Task, claim.task_id)
    if task.category == "checkin":
        raise HTTPException(409, "注册记录不能修改为积分任务")
    old_blood, old_energy = claim.blood_delta, claim.energy_delta
    change_blood, change_energy = new_blood - old_blood, new_energy - old_energy
    if not (change_blood or change_energy or next_status != claim.status):
        raise HTTPException(409, "奖励和状态均未变化")
    audit = ClaimAudit(claim_id=claim.id, staff_id=staff.id, action=action, reason=reason.strip(),
                       before_status=claim.status, after_status=next_status,
                       before_blood=old_blood, after_blood=new_blood,
                       before_energy=old_energy, after_energy=new_energy)
    db.add(audit)
    db.flush()
    add_ledger(db, p, "blood", change_blood, "任务修正：" + reason.strip()[:160], "claim_adjust", audit.id,
               allow_debt=True)
    add_ledger(db, p, "energy", change_energy, "任务修正：" + reason.strip()[:160], "claim_adjust", audit.id,
               allow_debt=True, adjust_earned=True)
    if task.code in ("donate_blood", "donate_energy") and p.energy_boost_used:
        boost = latest_boost(db, p.id)
        if action == "reverse":
            boost_total = effective_boost_bonus(db, boost) if boost else 0
            add_ledger(db, p, "energy", -boost_total, "撤回三倍能量道具：" + reason.strip()[:150],
                       "boost_reverse", audit.id, allow_debt=True, adjust_earned=True)
            p.energy_boost_used = False
        elif change_energy and not (boost and db.scalar(select(BoostAudit.id).where(
                BoostAudit.boost_ledger_id == boost.id).limit(1))):
            add_ledger(db, p, "energy", 2 * change_energy, "三倍能量道具连带修正：" + reason.strip()[:150],
                       "boost_adjust", audit.id, allow_debt=True, adjust_earned=True)
    claim.blood_delta, claim.energy_delta, claim.status = new_blood, new_energy, next_status
    db.commit()
    return {"ok": True, "claim_id": claim.id, "status": claim.status,
            "blood_delta": new_blood, "energy_delta": new_energy, "audit_id": audit.id}


@app.post("/api/admin/claims/{claim_id}/adjust")
def admin_adjust_claim(claim_id: int, data: AdjustClaim, staff: StaffUser = Depends(require_super),
                       db: Session = Depends(db_session)):
    return correct_claim(db, claim_id, staff, data.reason, data.blood_delta, data.energy_delta,
                         "adjust", "completed")


@app.post("/api/admin/claims/{claim_id}/reverse")
def admin_reverse_claim(claim_id: int, data: ReverseClaim, staff: StaffUser = Depends(require_super),
                        db: Session = Depends(db_session)):
    return correct_claim(db, claim_id, staff, data.reason, 0, 0, "reverse", "reversed")


@app.get("/api/admin/redemptions")
def admin_redemptions(q: str = "", status: str = "pending", _=Depends(require_super), db: Session = Depends(db_session)):
    if status not in {"pending", "fulfilled", "cancelled"}:
        raise HTTPException(400, "兑换状态无效")
    query = (select(Redemption, Participant.id, Participant.name, Participant.student_id, Prize.title)
             .join(Participant, Redemption.participant_id == Participant.id)
             .join(Prize, Redemption.prize_id == Prize.id)
             .where(Redemption.status == status))
    if q.strip():
        number = participant_number_search(q)
        if number is not None:
            query = query.where(Participant.id == number)
        else:
            term = f"%{q.strip()[:80]}%"
            query = query.where(or_(Participant.name.ilike(term), Participant.student_id.ilike(term),
                                    Prize.title.ilike(term), Redemption.pickup_code.ilike(term)))
    rows = db.execute(query.order_by(Redemption.id.desc()).limit(100)).all()
    return [{"id": r.id, "participant_id": participant_id, "name": name, "student_id": sid, "title": title,
             "code": r.pickup_code, "price": r.price, "quantity": r.quantity,
             "status": r.status, "created_at": r.created_at.isoformat()}
            for r, participant_id, name, sid, title in rows]


@app.post("/api/admin/redemptions/{redemption_id}/fulfill")
def fulfill(redemption_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    r = db.scalar(select(Redemption).where(Redemption.id == redemption_id).with_for_update())
    if not r or r.status != "pending":
        raise HTTPException(409, "凭证不存在或已核销")
    r.status, r.fulfilled_at = "fulfilled", now()
    db.commit()
    return {"ok": True}


@app.post("/api/admin/redemptions/{redemption_id}/cancel")
def cancel_redemption(redemption_id: int, _=Depends(require_super), db: Session = Depends(db_session)):
    lookup = db.get(Redemption, redemption_id)
    if not lookup:
        raise HTTPException(404, "兑换记录不存在")
    p = player_for_update(db, lookup.participant_id)
    r = db.scalar(select(Redemption).where(Redemption.id == redemption_id).with_for_update().execution_options(populate_existing=True))
    if r.status != "pending":
        raise HTTPException(409, "只能取消未核销的兑换")
    prize = db.scalar(select(Prize).where(Prize.id == r.prize_id).with_for_update())
    add_ledger(db, p, "energy", r.price, "取消兑换：" + prize.title, "redeem_cancel", r.id,
               counts_as_earned=False)
    prize.stock += r.quantity
    r.status = "cancelled"
    db.commit()
    return {"ok": True}
