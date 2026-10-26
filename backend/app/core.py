import os
import hmac
import hashlib
import secrets
import base64
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import jwt
from fastapi import HTTPException, Request, Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./demo.db")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
APP_SECRET = os.getenv("APP_SECRET", "")
SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
try:
    LEADERBOARD_LIMIT = int(os.getenv("LEADERBOARD_LIMIT", "100"))
    if LEADERBOARD_LIMIT < 1:
        raise ValueError
except ValueError:
    raise RuntimeError("LEADERBOARD_LIMIT 必须是正整数")

if not DEMO_MODE and (len(APP_SECRET) < 32 or len(SUPERADMIN_PASSWORD) < 8 or "CHANGE_TO_" in APP_SECRET or "CHANGE_TO_" in SUPERADMIN_PASSWORD):
    raise RuntimeError("生产模式必须配置至少 32 位 APP_SECRET 和 8 位 SUPERADMIN_PASSWORD")
if not APP_SECRET:
    APP_SECRET = secrets.token_urlsafe(40)  # demo runtime only, restart invalidates tokens

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, autoflush=False, expire_on_commit=False)
COOKIE = "bq_session"
STAFF_COOKIE = "bq_staff"
PENDING_COOKIE = "bq_pending"
STATE_COOKIE = "bq_oauth_state"


def sign(payload: dict, minutes: int = 3 * 24 * 60) -> str:
    return jwt.encode({**payload, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}, APP_SECRET, algorithm="HS256")


def verify(token: str, expected: str):
    try:
        data = jwt.decode(token, APP_SECRET, algorithms=["HS256"])
        if data.get("kind") != expected:
            raise ValueError("wrong token type")
        return data
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "登录状态已失效")


def digest_code(value: str) -> str:
    return hmac.new(APP_SECRET.encode(), value.upper().strip().encode(), hashlib.sha256).hexdigest()


def hash_staff_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 390000)
    return "pbkdf2_sha256$390000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_staff_password(password: str, stored: str) -> bool:
    try:
        algorithm, count, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(count))
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def set_cookie(response, name: str, value: str, max_age: int):
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/")


def clear_cookie(response, name: str):
    response.delete_cookie(name, path="/", secure=COOKIE_SECURE, samesite="lax")


def read_actor(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "请先登录")
    return verify(token, "session")


def require_player(request: Request) -> int:
    actor = read_actor(request)
    if actor.get("role") != "player":
        raise HTTPException(403, "仅参与者可访问")
    from .models import Participant
    try:
        participant_id = int(actor["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "登录状态已失效")
    with SessionLocal() as db:
        p = db.get(Participant, participant_id)
        if not p or not p.active:
            raise HTTPException(401, "参与者账号已停用")
    return participant_id


def require_admin(request: Request):
    from .models import StaffUser
    token = request.cookies.get(STAFF_COOKIE)
    if not token:
        raise HTTPException(401, "请先登录工作人员账号")
    actor = verify(token, "staff")
    try:
        staff_id = int(actor["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "登录状态已失效")
    with SessionLocal() as db:
        staff = db.get(StaffUser, staff_id)
        if not staff or not staff.active or staff.auth_version != actor.get("version"):
            raise HTTPException(401, "工作人员账号已停用或权限发生变化，请重新登录")
        return staff


def db_session():
    with SessionLocal() as db:
        yield db
