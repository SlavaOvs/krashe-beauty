
import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.hash import bcrypt
from sqlalchemy import create_engine, Column, Integer, String, DateTime, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --------------- CONFIG -----------------
PERSISTENT_DIR = os.getenv("PERSISTENT_DIR", "/persistent")  # override in Railway to /data
os.makedirs(PERSISTENT_DIR, exist_ok=True)
DB_PATH = os.path.join(PERSISTENT_DIR, "db.sqlite3")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# --------------- DATABASE ---------------
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    login = Column(String, unique=True, index=True, nullable=False)
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

INITIAL_MASTERS = [
    {"name": "Анна", "login": "anna", "password": "anna123"},
    {"name": "Вика", "login": "vika", "password": "vika123"},
    {"name": "Ольга", "login": "olga", "password": "olga123"},
    {"name": "Мария", "login": "maria", "password": "maria123"},
]

def init_db():
    db: Session = SessionLocal()
    try:
        if db.query(User).count() == 0:
            for m in INITIAL_MASTERS:
                db.add(
                    User(
                        name=m["name"],
                        login=m["login"],
                        password_hash=bcrypt.hash(m["password"]),
                    )
                )
            db.commit()
    finally:
        db.close()

init_db()

# --------------- FASTAPI MODELS ---------
class Token(BaseModel):
    user_id: int
    name: str

class LoginRequest(BaseModel):
    login: str
    password: str

class AppointmentIn(BaseModel):
    client_name: str
    phone: Optional[str] = ""
    start_time: datetime
    duration_minutes: int

class AppointmentOut(BaseModel):
    id: int
    master_id: int
    client_name: str
    phone: Optional[str]
    start_time: datetime
    end_time: datetime
    color: str
    master_name: str

MASTER_COLORS = ["#f87171", "#34d399", "#60a5fa", "#fbbf24"]

# --------------- APP --------------------
app = FastAPI(title="Beauty Booking")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = "", db: Session = Depends(get_db)) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token")
    try:
        user_id = int(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Bad token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@app.post("/login", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.login == data.login).first()
    if not user or not bcrypt.verify(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")
    return Token(user_id=user.id, name=user.name)

@app.get("/appointments", response_model=List[AppointmentOut])
def get_appointments(db: Session = Depends(get_db)):
    res = []
    for a in db.query(Appointment).all():
        master = db.query(User).filter(User.id == a.master_id).first()
        color = MASTER_COLORS[(a.master_id - 1) % len(MASTER_COLORS)]
        res.append(
            AppointmentOut(
                id=a.id,
                master_id=a.master_id,
                client_name=a.client_name,
                phone=a.phone,
                start_time=a.start_time,
                end_time=a.end_time,
                color=color,
                master_name=master.name if master else "?",
            )
        )
    return res

@app.get("/my-appointments", response_model=List[AppointmentOut])
def get_my_appointments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = []
    for a in db.query(Appointment).filter(Appointment.master_id == user.id).all():
        color = MASTER_COLORS[(user.id - 1) % len(MASTER_COLORS)]
        res.append(
            AppointmentOut(
                id=a.id,
                master_id=a.master_id,
                client_name=a.client_name,
                phone=a.phone,
                start_time=a.start_time,
                end_time=a.end_time,
                color=color,
                master_name=user.name,
            )
        )
    return res

@app.post("/add", response_model=AppointmentOut)
def add_appointment(data: AppointmentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = data.start_time
    end = start + timedelta(minutes=data.duration_minutes)

    conflict = db.query(Appointment).filter(
        and_(
            Appointment.start_time < end,
            Appointment.end_time > start,
        )
    ).first()
    if conflict:
        raise HTTPException(409, "Кушетка уже занята в это время")

    a = Appointment(
        master_id=user.id,
        client_name=data.client_name,
        phone=data.phone,
        start_time=start,
        end_time=end,
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    color = MASTER_COLORS[(user.id - 1) % len(MASTER_COLORS)]
    return AppointmentOut(
        id=a.id,
        master_id=user.id,
        client_name=a.client_name,
        phone=a.phone,
        start_time=a.start_time,
        end_time=a.end_time,
        color=color,
        master_name=user.name,
    )

@app.delete("/delete/{appointment_id}")
def delete_appointment(appointment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not a:
        raise HTTPException(404, "Запись не найдена")
    if a.master_id != user.id:
        raise HTTPException(403, "Можно удалять только свои записи")
    db.delete(a)
    db.commit()
    return {"ok": True}

# --------------- STATIC FRONTEND --------
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def root():
    return FileResponse("index.html")
