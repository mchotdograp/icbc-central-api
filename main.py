from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json

# ------------------ 数据库配置 ------------------
DATABASE_URL = "sqlite:///./db.sqlite3"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(String, index=True)
    data = Column(Text)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)


class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(String, nullable=True)  # NULL 表示全局
    data = Column(Text)  # JSON
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ------------------ FastAPI ------------------
app = FastAPI(title="ICBC Central API", version="0.1")


# ------------------ 模型 ------------------
class Contact(BaseModel):
    email: Optional[str]
    phone: Optional[str]
    telegram: Optional[str]


class Preferences(BaseModel):
    centre: str
    date_start: str
    date_end: str
    days_of_week: List[str]
    time_of_day: Optional[str]


class EnrollRequest(BaseModel):
    school_id: str
    student: Dict[str, Any]
    preferences: Preferences
    consent_timestamp: str


class ReportRequest(BaseModel):
    task_id: int
    school_id: str
    detected_at: str
    slots_found: List[Dict[str, Any]]
    agent_meta: Dict[str, Any]


# ------------------ 路由 ------------------

@app.post("/api/enroll")
def enroll(req: EnrollRequest):
    db = SessionLocal()
    task = Task(
        school_id=req.school_id,
        data=json.dumps(req.dict()),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {"status": "ok", "task_id": task.id}


@app.get("/api/tasks")
def get_tasks(school_id: str, since: Optional[str] = None):
    db = SessionLocal()
    q = db.query(Task).filter(Task.school_id == school_id)
    if since:
        q = q.filter(Task.created_at >= since)
    tasks = q.all()
    return {
        "tasks": [
            {"task_id": t.id, **json.loads(t.data)} for t in tasks
        ]
    }


@app.post("/api/report")
def report(req: ReportRequest):
    # 这里可以加：存数据库 / 发通知
    return {"status": "ok", "received": req.dict()}


@app.get("/api/config")
def get_config(school_id: str):
    db = SessionLocal()
    # 优先取该驾校配置
    cfg = db.query(Config).filter(Config.school_id == school_id).first()
    if not cfg:
        cfg = db.query(Config).filter(Config.school_id == None).first()

    if cfg:
        return json.loads(cfg.data)
    else:
        # 默认参数
        return {
            "rate_limits": {
                "per_task_interval_min": 15,
                "jitter_percent": 30,
                "max_checks_per_hour": 20,
                "max_checks_per_day": 200,
                "backoff_enabled": True,
                "backoff_factor": 2,
                "max_interval_min": 60
            },
            "notifications": {
                "allow_email": True,
                "allow_sms": True,
                "allow_telegram": True
            },
            "agent": {
                "heartbeat_interval_min": 10,
                "update_required": False,
                "latest_version": "1.0.0"
            }
        }


# ------------------ 启动 ------------------
# 运行命令: uvicorn main:app --reload
