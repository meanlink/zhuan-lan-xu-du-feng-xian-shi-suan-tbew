from sqlalchemy import String, Double, ForeignKey, Boolean, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    interval_seconds: Mapped[int] = mapped_column(Integer)
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
class Delivery(Base):
    # 一期一档：(report_id, scheduled_for) 唯一，重试与多进程领取都不会新增归档
    __tablename__ = 'deliveries'
    __table_args__ = (UniqueConstraint('report_id', 'scheduled_for', name='uq_deliveries_report_issue'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    scheduled_for: Mapped[float] = mapped_column(Double, default=0.0)  # 本期应发时刻
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/claimed/completed/repair/failed
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 首次领取时固定的试验结果
    created_at: Mapped[float] = mapped_column(Double)
    claimed_by: Mapped[str] = mapped_column(String(120), default='')
    claimed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    recoveries: Mapped[int] = mapped_column(Integer, default=0)
    recovered_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), default='')
    filename: Mapped[str] = mapped_column(String(160), default='')
    destination: Mapped[str] = mapped_column(String(120))
    error: Mapped[str] = mapped_column(String(1000), default='')
