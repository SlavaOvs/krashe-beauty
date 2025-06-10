
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
from sqlalchemy.orm import sessionmaker, declarative_base, Session

PERSISTENT_DIR = os.getenv("PERSISTENT_DIR", "/data")
os.makedirs(PERSISTENT_DIR, exist_ok=True)
engine = create_engine(f"sqlite:///{PERSISTENT_DIR}/db.sqlite3", connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    login = Column(String, unique=True)
    password_hash = Column(String)

class Appointment(Base):
    __tablename__ = 'appointments'
    id = Column(Integer, primary_key=True)
    master_id = Column(Integer)
    client_name = Column(String)
    phone = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)

Base.metadata.create_all(bind=engine)

def seed():
    db=SessionLocal()
    if db.query(User).count()==0:
        for name,l,p in [('Анна','anna','anna123'),('Катя','kate','ovs123'),('Ольга','olga','olga123'),('Мария','maria','maria123')]:
            db.add(User(name=name,login=l,password_hash=bcrypt.hash(p)))
        db.commit();db.close()
seed()

COLORS=['#f87171','#34d399','#60a5fa','#fbbf24']

class Login(BaseModel):
    login:str
    password:str
class Token(BaseModel):
    user_id:int
    name:str
class ApptIn(BaseModel):
    client_name:str
    phone:Optional[str]=''
    start_time:datetime
    duration_minutes:int
class ApptOut(BaseModel):
    id:int
    master_id:int
    client_name:str
    phone:Optional[str]
    start_time:datetime
    end_time:datetime
    color:str
    master_name:str

app=FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

def current(token:str='',db:Session=Depends(get_db))->User:
    if not token: raise HTTPException(401)
    u=db.query(User).get(int(token))
    if not u: raise HTTPException(401)
    return u

@app.post('/login',response_model=Token)
def login(data:Login,db:Session=Depends(get_db)):
    u=db.query(User).filter(User.login==data.login).first()
    if not u or not bcrypt.verify(data.password,u.password_hash):
        raise HTTPException(400,'Неверный логин или пароль')
    return Token(user_id=u.id,name=u.name)

@app.get('/appointments',response_model=List[ApptOut])
def list_apps(db:Session=Depends(get_db)):
    out=[]
    for a in db.query(Appointment).all():
        m=db.query(User).get(a.master_id)
        out.append(ApptOut(id=a.id,master_id=a.master_id,client_name=a.client_name,phone=a.phone,start_time=a.start_time,end_time=a.end_time,color=COLORS[(a.master_id-1)%4],master_name=m.name))
    return out

@app.post('/add',response_model=ApptOut)
def add_app(data:ApptIn,u:User=Depends(current),db:Session=Depends(get_db)):
    end=data.start_time+timedelta(minutes=data.duration_minutes)
    conflict=db.query(Appointment).filter(and_(Appointment.start_time<end,Appointment.end_time>data.start_time)).first()
    if conflict: raise HTTPException(409,'Кушетка занята')
    a=Appointment(master_id=u.id,client_name=data.client_name,phone=data.phone,start_time=data.start_time,end_time=end)
    db.add(a);db.commit();db.refresh(a)
    return ApptOut(id=a.id,master_id=u.id,client_name=a.client_name,phone=a.phone,start_time=a.start_time,end_time=a.end_time,color=COLORS[(u.id-1)%4],master_name=u.name)

@app.delete('/delete/{aid}')
def del_app(aid:int,u:User=Depends(current),db:Session=Depends(get_db)):
    a=db.query(Appointment).get(aid)
    if not a: raise HTTPException(404)
    if a.master_id!=u.id: raise HTTPException(403)
    db.delete(a);db.commit()
    return {'ok':True}

app.mount('/static',StaticFiles(directory='.'),name='static')
@app.get('/')
def root():
    return FileResponse('index.html')
