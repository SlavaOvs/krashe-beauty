import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.hash import bcrypt
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    and_,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# ──────────────────────── НАСТРОЙКИ ────────────────────────
PERSISTENT_DIR = os.getenv("PERSISTENT_DIR", "/data")  # для Railway volume
os.makedirs(PERSISTENT_DIR, exist_ok=True)

DB_URL = f"sqlite:///{PERSISTENT_DIR}/db.sqlite3"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ──────────────────────── МОДЕЛИ БД ────────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    login = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    master_id = Column(Integer)
    client_name = Column(String, nullable=False)
    phone = Column(String)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)


Base.metadata.create_all(bind=engine)

# ─────────────────────── ЗАПОЛНЯЕМ МАСТЕРОВ ───────────────────────
MASTERS = [
    ("Анна", "anna", "anna123"),
    ("Вика", "kate", "ovs123"),
    ("Ольга", "olga", "olga123"),
    ("Мария", "maria", "maria123"),
]


def seed():
    db = SessionLocal()
    if db.query(User).count() == 0:
        for name, login, pw in MASTERS:
            db.add(User(name=name, login=login, password_hash=bcrypt.hash(pw)))
        db.commit()
    db.close()


seed()

# ─────────────────────── Pydantic-схемы ───────────────────────
COLORS = ["#f87171", "#34d399", "#60a5fa", "#fbbf24"]


class Token(BaseModel):
    user_id: int
    name: str


class LoginReq(BaseModel):
    login: str
    password: str


class ApptIn(BaseModel):
    client_name: str
    phone: Optional[str] = ""
    start_time: datetime
    duration_minutes: int


class ApptOut(BaseModel):
    id: int
    master_id: int
    client_name: str
    phone: Optional[str]
    start_time: datetime
    end_time: datetime
    color: str
    master_name: str


# ─────────────────────── FastAPI-приложение ───────────────────────
app = FastAPI(title="Beauty Booking")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────── вспомогательные зависимости ────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(
    token: str = Header(default=""), db: Session = Depends(get_db)
) -> User:
    """Авторизация через заголовок `token`."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = db.query(User).get(int(token))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


# ──────────────────────────── ЭНДПОИНТЫ ────────────────────────────
@app.post("/login", response_model=Token)
def login(data: LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.login == data.login).first()
    if not user or not bcrypt.verify(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")
    return Token(user_id=user.id, name=user.name)


@app.get("/appointments", response_model=List[ApptOut])
def list_appointments(db: Session = Depends(get_db)):
    out = []
    for a in db.query(Appointment).all():
        master = db.query(User).get(a.master_id)
        out.append(
            ApptOut(
                id=a.id,
                master_id=a.master_id,
                client_name=a.client_name,
                phone=a.phone,
                start_time=a.start_time,
                end_time=a.end_time,
                color=COLORS[(a.master_id - 1) % 4],
                master_name=master.name,
            )
        )
    return out


@app.post("/add", response_model=ApptOut)
def add_appt(
    data: ApptIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    end = data.start_time + timedelta(minutes=data.duration_minutes)
    conflict = (
        db.query(Appointment)
        .filter(
            and_(
                Appointment.start_time < end,
                Appointment.end_time > data.start_time,
            )
        )
        .first()
    )
    if conflict:
        raise HTTPException(409, "Кушетка занята")

    a = Appointment(
        master_id=user.id,
        client_name=data.client_name,
        phone=data.phone,
        start_time=data.start_time,
        end_time=end,
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    return ApptOut(
        id=a.id,
        master_id=user.id,
        client_name=a.client_name,
        phone=a.phone,
        start_time=a.start_time,
        end_time=a.end_time,
        color=COLORS[(user.id - 1) % 4],
        master_name=user.name,
    )


@app.delete("/delete/{aid}")
def remove_appt(
    aid: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    appt = db.query(Appointment).get(aid)
    if not appt:
        raise HTTPException(404, "Запись не найдена")
    if appt.master_id != user.id:
        raise HTTPException(403, "Можно удалять только свои записи")
    db.delete(appt)
    db.commit()
    return {"ok": True}


# ───────────── статический фронт ─────────────
app.mount("/static", StaticFiles(directory="."), name="static")


@app.get("/")
def root():
    return FileResponse("index.html")
