from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, or_
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
    # 新增字段用于任务状态跟踪
    status = Column(String, default="pending")  # pending, processing, completed, failed
    updated_at = Column(DateTime, default=datetime.utcnow)
    progress = Column(Integer, default=10)  # 0-100
    message = Column(String, default="任务已创建，等待处理")


class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(String, nullable=True)  # NULL 表示全局
    data = Column(Text)  # JSON
    updated_at = Column(DateTime, default=datetime.utcnow)


# 创建所有表
Base.metadata.create_all(bind=engine)

# ------------------ FastAPI ------------------
app = FastAPI(title="ICBC Central API", version="0.1")

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境中应该限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头部
)

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


class TaskUpdateRequest(BaseModel):
    status: str  # pending, processing, completed, failed
    progress: int  # 0-100
    message: Optional[str] = None


# ------------------ 原有路由 ------------------
@app.get("/healthz")
def health_check():
    return {"status": "ok"}


@app.post("/api/enroll")
def enroll(req: EnrollRequest):
    try:
        db = SessionLocal()
        task = Task(
            school_id=req.school_id,
            data=json.dumps(req.dict()),
            status="pending",
            progress=10,
            message="报名信息已接收，等待处理"
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        db.close()
        return {
            "status": "ok", 
            "task_id": task.id,
            "message": "报名成功，您可以使用task_id查询处理进度"
        }
    except Exception as e:
        print(f"Error in enroll: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/tasks")
def get_tasks(school_id: str, since: Optional[str] = None):
    db = SessionLocal()
    q = db.query(Task).filter(Task.school_id == school_id)
    if since:
        q = q.filter(Task.created_at >= since)
    tasks = q.all()
    db.close()
    return {
        "tasks": [
            {
                "task_id": t.id, 
                "status": t.status,
                "progress": t.progress,
                "message": t.message,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
                **json.loads(t.data)
            } for t in tasks
        ]
    }


@app.post("/api/report")
def report(req: ReportRequest):
    # 这里可以加：存数据库 / 发通知
    # 当有报名位置时，更新相关任务状态
    try:
        db = SessionLocal()
        # 更新对应任务的状态
        task = db.query(Task).filter(Task.id == req.task_id).first()
        if task:
            task.status = "completed"
            task.progress = 100
            task.message = f"找到 {len(req.slots_found)} 个可用时间段"
            task.updated_at = datetime.utcnow()
            db.commit()
        db.close()
    except Exception as e:
        print(f"Error updating task status: {e}")
    
    return {"status": "ok", "received": req.dict()}


@app.get("/api/config")
def get_config(school_id: str):
    db = SessionLocal()
    # 优先取该驾校配置
    cfg = db.query(Config).filter(Config.school_id == school_id).first()
    if not cfg:
        cfg = db.query(Config).filter(Config.school_id == None).first()

    if cfg:
        db.close()
        return json.loads(cfg.data)
    else:
        db.close()
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


# ------------------ 新增的监控和查询路由 ------------------

@app.get("/api/tasks/{task_id}")
def get_task_status(task_id: int):
    """查询特定任务的状态"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # 解析原始数据
        task_data = json.loads(task.data)
        
        result = {
            "task_id": task.id,
            "status": task.status,
            "progress": task.progress,
            "message": task.message,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "school_id": task.school_id,
            "student_info": task_data.get("student", {}),
            "preferences": task_data.get("preferences", {})
        }
        return result
    finally:
        db.close()


@app.put("/api/tasks/{task_id}")
def update_task_status(task_id: int, update: TaskUpdateRequest):
    """更新任务状态（供管理员或自动化脚本使用）"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task.status = update.status
        task.progress = update.progress
        if update.message:
            task.message = update.message
        task.updated_at = datetime.utcnow()
        
        db.commit()
        return {"status": "ok", "message": "任务状态已更新"}
    finally:
        db.close()


@app.get("/api/enrollments")
def get_all_enrollments(limit: int = Query(100, le=1000), offset: int = Query(0, ge=0)):
    """查询所有报名记录（分页）"""
    db = SessionLocal()
    try:
        tasks = db.query(Task).order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
        total = db.query(Task).count()
        
        enrollments = []
        for task in tasks:
            task_data = json.loads(task.data)
            enrollment = {
                "enrollment_id": task.id,
                "task_id": task.id,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
                **task_data
            }
            enrollments.append(enrollment)
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "enrollments": enrollments
        }
    finally:
        db.close()


@app.get("/api/enrollments/search")
def search_enrollments(
    email: Optional[str] = Query(None),
    phone: Optional[str] = Query(None),
    school_id: Optional[str] = Query(None)
):
    """根据邮箱、电话或学校ID搜索报名记录"""
    if not email and not phone and not school_id:
        raise HTTPException(status_code=400, detail="请提供至少一个搜索条件：email、phone 或 school_id")
    
    db = SessionLocal()
    try:
        query = db.query(Task)
        
        if school_id:
            query = query.filter(Task.school_id == school_id)
        
        tasks = query.all()
        
        # 在数据中搜索email和phone（因为存储在JSON中）
        results = []
        for task in tasks:
            task_data = json.loads(task.data)
            student = task_data.get("student", {})
            
            match = True
            if email and student.get("email") != email:
                match = False
            if phone and student.get("phone") != phone:
                match = False
                
            if match:
                result = {
                    "enrollment_id": task.id,
                    "task_id": task.id,
                    "status": task.status,
                    "progress": task.progress,
                    "message": task.message,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                    **task_data
                }
                results.append(result)
        
        return {
            "total": len(results),
            "results": results
        }
    finally:
        db.close()


@app.get("/api/stats")
def get_statistics():
    """获取系统统计信息"""
    db = SessionLocal()
    try:
        total_tasks = db.query(Task).count()
        pending_tasks = db.query(Task).filter(Task.status == "pending").count()
        processing_tasks = db.query(Task).filter(Task.status == "processing").count()
        completed_tasks = db.query(Task).filter(Task.status == "completed").count()
        failed_tasks = db.query(Task).filter(Task.status == "failed").count()
        
        return {
            "total_enrollments": total_tasks,
            "pending": pending_tasks,
            "processing": processing_tasks,
            "completed": completed_tasks,
            "failed": failed_tasks,
            "last_updated": datetime.utcnow().isoformat()
        }
    finally:
        db.close()


# ------------------ 启动 ------------------
# 运行命令: uvicorn main:app --reload