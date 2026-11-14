from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
DELIVERY_COLUMNS=[
    ('scheduled_for','DOUBLE NOT NULL DEFAULT 0'),
    ('status',"VARCHAR(20) NOT NULL DEFAULT 'pending'"),
    ('snapshot','JSON NULL'),
    ('claimed_by',"VARCHAR(120) NOT NULL DEFAULT ''"),
    ('claimed_at','DOUBLE NULL'),
    ('finished_at','DOUBLE NULL'),
    ('recovered_at','DOUBLE NULL'),
    ('attempts','INTEGER NOT NULL DEFAULT 0'),
    ('recoveries','INTEGER NOT NULL DEFAULT 0'),
    ('error',"VARCHAR(1000) NOT NULL DEFAULT ''"),
]
def migrate():
    Base.metadata.create_all(engine)
    ensure_delivery_schema()
def ensure_delivery_schema():
    """为既有库补齐期次字段与唯一约束；新库由 create_all 一步建全。"""
    insp=inspect(engine)
    if 'deliveries' not in insp.get_table_names(): return
    cols={c['name'] for c in insp.get_columns('deliveries')}
    with engine.begin() as conn:
        for name,ddl in DELIVERY_COLUMNS:
            if name not in cols: conn.execute(text(f'ALTER TABLE deliveries ADD COLUMN {name} {ddl}'))
        # 旧版归档记录：应发时刻回填为创建时刻，视为已归档
        conn.execute(text("UPDATE deliveries SET scheduled_for=created_at, status='completed', finished_at=created_at WHERE scheduled_for=0 AND checksum<>''"))
        indexes={i['name'] for i in insp.get_indexes('deliveries')}|{c['name'] for c in insp.get_unique_constraints('deliveries')}
        if 'uq_deliveries_report_issue' not in indexes:
            conn.execute(text('CREATE UNIQUE INDEX uq_deliveries_report_issue ON deliveries (report_id, scheduled_for)'))
if __name__=='__main__':migrate()
