"""EE542 Lab 9 Part 1: FastAPI backend for the group chat + LLM bot.

The instructor's zip ships the frontend, SQL schema and Android wrapper but no
backend/ directory, so this file implements the API that frontend/app.js
calls:

  POST /api/signup   {username, password} -> {token, username}
  POST /api/login    {username, password} -> {token, username}
  GET  /api/messages (Bearer token)       -> {messages: [...]}
  POST /api/messages (Bearer token) {content}
  WS   /ws           server -> client {"type": "message", "message": {...}}

A message that contains "?" also triggers the LLM bot: the backend sends the
recent conversation to an OpenAI-compatible /chat/completions endpoint
(llama.cpp's llama-server or vLLM, see .env) and posts the answer as a bot
message. Static files in ../frontend are served at /.

Run from this directory:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import httpx
import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+asyncmy://chatuser:chatpass@localhost:3306/groupchat")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "43200"))
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://localhost:8001/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3-8b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
BOT_NAME = os.getenv("BOT_NAME", "LLM Bot")
# Part 4: when set, "?" questions go to the knowledge-base service instead of the bare LLM.
RAG_API_BASE = os.getenv("RAG_API_BASE", "").rstrip("/")
RAG_COLLECTION = os.getenv("RAG_COLLECTION", "f1")
RAG_EMBEDDER = os.getenv("RAG_EMBEDDER", "openai")
CONTEXT_MESSAGES = int(os.getenv("LLM_CONTEXT_MESSAGES", "10"))
SYSTEM_PROMPT = os.getenv(
    "LLM_SYSTEM_PROMPT",
    f"You are {BOT_NAME}, a helpful assistant in a group chat. "
    "Each user message is prefixed with the sender's username, like 'alice: ...'. "
    "Answer the latest question concisely and accurately. "
    "Reply with the answer text only: never start your reply with a name and a colon.")

if len(JWT_SECRET) < 32 or JWT_SECRET.startswith("please_change_me"):
    raise SystemExit("Set JWT_SECRET in .env to a long random string (>= 32 chars).")


# ---------------------------------------------------------------- database
class Base(DeclarativeBase):
    pass


def utcnow():
    # Stored as naive UTC; serialized with a trailing "Z" so browsers convert it.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user: Mapped[User | None] = relationship(lazy="joined")


engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with Session() as s:
        yield s


def serialize(m: Message) -> dict:
    return {
        "id": m.id,
        "username": BOT_NAME if m.is_bot else (m.user.username if m.user else "deleted user"),
        "content": m.content,
        "is_bot": m.is_bot,
        "created_at": m.created_at.isoformat() + "Z",
    }


# ---------------------------------------------------------------- auth
class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=4, max_length=128)


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user.id), "name": user.username, "exp": exp}, JWT_SECRET, algorithm="HS256")


async def current_user(authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not logged in")
    try:
        claims = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = await db.get(User, int(claims["sub"]))
    if user is None:
        raise HTTPException(401, "User no longer exists")
    return user


# ---------------------------------------------------------------- websocket fan-out
class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, payload: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


# ---------------------------------------------------------------- LLM bot
async def ask_llm(history: list[Message]) -> str:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        if m.is_bot:
            msgs.append({"role": "assistant", "content": m.content})
        else:
            who = m.user.username if m.user else "someone"
            msgs.append({"role": "user", "content": f"{who}: {m.content}"})
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        r = await client.post(f"{LLM_API_BASE}/chat/completions", headers=headers,
                              json={"model": LLM_MODEL, "messages": msgs, "temperature": 0.7, "max_tokens": 512})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
    # Small models still copy the "name: ..." pattern now and then; drop a
    # leading speaker tag, but only for names actually in play so that an
    # answer starting with e.g. "Note:" is left alone.
    names = {BOT_NAME, "assistant"} | {m.user.username for m in history if m.user}
    tag = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.sub(rf"^(?:{tag}):\s+", "", text, count=1, flags=re.IGNORECASE)


async def ask_rag(history: list[Message], question: Message) -> str:
    """Part 4: answer from the curated knowledge base (../rag/rag_api.py) and
    append the source links, so readers can check the official page."""
    def turn(m):
        return ("assistant", m.content.split("\n\nSources:")[0]) if m.is_bot else \
               ("user", f"{m.user.username if m.user else 'someone'}: {m.content}")
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        r = await client.post(f"{RAG_API_BASE}/ask", json={
            "question": question.content, "history": [turn(m) for m in history],
            "collection": RAG_COLLECTION, "embedder": RAG_EMBEDDER})
        r.raise_for_status()
        out = r.json()
    lines = [f"- {s['agency']}: {s['title']} {s['url']}".rstrip() for s in out["sources"]]
    return out["answer"].strip() + ("\n\nSources:\n" + "\n".join(lines) if lines else "")


async def bot_reply(question_id: int):
    """Answer in the background so the asker's message shows up immediately."""
    async with Session() as db:
        rows = (await db.execute(select(Message).where(Message.id <= question_id)
                                 .order_by(Message.id.desc()).limit(CONTEXT_MESSAGES))).scalars().all()
        rows = list(reversed(rows))
        try:
            text = await (ask_rag(rows[:-1], rows[-1]) if RAG_API_BASE else ask_llm(rows))
        except Exception as e:  # surface the failure in the chat instead of failing silently
            text = f"(Bot unavailable: {type(e).__name__}: {e})"
        bot = Message(user_id=None, content=text or "(empty reply)", is_bot=True)
        db.add(bot)
        await db.commit()
        await db.refresh(bot)
        await hub.broadcast({"type": "message", "message": serialize(bot)})


# ---------------------------------------------------------------- app
app = FastAPI(title="Group Chat + LLM Bot")
_tasks: set[asyncio.Task] = set()


@app.middleware("http")
async def revalidate_static(request, call_next):
    # Make browsers (and the Android TWA) revalidate the frontend files on every
    # load, so a redeployed app.js / styles.css is picked up immediately.
    resp = await call_next(request)
    if not request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.post("/api/signup")
async def signup(c: Credentials, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(User).where(User.username == c.username))).scalar_one_or_none():
        raise HTTPException(400, "Username already taken")
    user = User(username=c.username, password_hash=bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode())
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"token": make_token(user), "username": user.username}


@app.post("/api/login")
async def login(c: Credentials, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == c.username))).scalar_one_or_none()
    if user is None or not bcrypt.checkpw(c.password.encode(), user.password_hash.encode()):
        raise HTTPException(401, "Wrong username or password")
    return {"token": make_token(user), "username": user.username}


@app.get("/api/messages")
async def list_messages(limit: int = 200, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Message).order_by(Message.id.desc()).limit(min(limit, 1000)))).scalars().all()
    return {"messages": [serialize(m) for m in reversed(rows)]}


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@app.post("/api/messages")
async def post_message(body: NewMessage, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    m = Message(user_id=user.id, content=body.content.strip(), is_bot=False)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    out = serialize(m)
    await hub.broadcast({"type": "message", "message": out})
    if "?" in m.content:
        t = asyncio.create_task(bot_reply(m.id))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return {"message": out}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()   # clients only listen; keep the socket open
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


@app.get("/api/health")
async def health():
    return {"ok": True, "llm": LLM_API_BASE, "model": LLM_MODEL, "bot": BOT_NAME,
            "rag": RAG_API_BASE or None, "collection": RAG_COLLECTION if RAG_API_BASE else None}


FRONTEND = ROOT / "frontend"


@app.get("/.well-known/assetlinks.json")
async def assetlinks():
    # Android TWA verification (Part 2) needs this exact path with a JSON type.
    return FileResponse(FRONTEND / ".well-known" / "assetlinks.json", media_type="application/json")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
