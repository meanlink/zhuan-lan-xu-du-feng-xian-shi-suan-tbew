import time, json, logging, os, socket
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset
from src.services.business import analyze
from src.services import reports
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
WORKER_ID=f'{socket.gethostname()}:{os.getpid()}'
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    now=time.time()
    with Session() as db:
        reports.backfill(db,now)            # 按计划应发时刻补齐漏期
        reports.recover_stale(db,WORKER_ID,now)  # 恢复中断的原期（含已暂停计划的已领取期）
        reports.claim_due(db,WORKER_ID,now)      # 原子领取新期，多进程不重复
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
        # 中断时处于处理中的期次立即恢复原期：同一行、同一快照，不新增归档
        reports.recover_stale(db,WORKER_ID,time.time(),grace=0)
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
