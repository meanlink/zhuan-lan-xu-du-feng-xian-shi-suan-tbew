import time, os, csv, io, hashlib, json, logging
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from src.models import Job, Report, Delivery
from src.services.audit import record
from src.config.settings import ARTIFACT_DIR
BACKFILL_LIMIT = 200  # 单次 tick 每个计划最多补齐的期数，剩余下个 tick 继续
CLAIM_LIMIT = 5       # 单次 tick 最多领取/恢复的期数
CLAIM_GRACE = 60      # 领取后超过该秒数未完成，视为执行进程中断，可恢复原期
def create(db, data):
    j=db.get(Job,data.job_id)
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r
def backfill(db, now=None):
    """按计划应发时刻补齐漏期：为启用计划生成截至 now 的全部到期期次。
    (report_id, scheduled_for) 唯一约束保证同一期只建档一次，多进程并发安全。"""
    now=now or time.time()
    for rid in db.scalars(select(Report.id).where(Report.enabled==True)).all():
        r=db.scalar(select(Report).where(Report.id==rid).with_for_update())
        if not r or not r.enabled: continue
        created=0
        while r.next_run<=now and created<BACKFILL_LIMIT:
            issue=r.next_run
            try:
                with db.begin_nested():
                    db.add(Delivery(report_id=r.id, scheduled_for=issue, status='pending', destination=r.destination, created_at=now))
                    db.flush()
            except IntegrityError:
                pass  # 另一执行进程已建档该期
            r.next_run=issue+r.interval_seconds
            created+=1
        db.commit()
def claim_due(db, worker_id, now=None, limit=CLAIM_LIMIT):
    """原子领取待处理期次：条件 UPDATE 只有一个进程能生效，同时领取不重复。
    暂停的计划不再领取新期。"""
    now=now or time.time()
    ids=db.scalars(select(Delivery.id).join(Report,Delivery.report_id==Report.id).where(Delivery.status=='pending',Report.enabled==True).order_by(Delivery.scheduled_for).limit(limit)).all()
    for did in ids:
        res=db.execute(update(Delivery).where(Delivery.id==did,Delivery.status=='pending').values(status='claimed',claimed_by=worker_id,claimed_at=now,attempts=Delivery.attempts+1))
        db.commit()
        if res.rowcount==1: process(db,did)
def recover_stale(db, worker_id, now=None, grace=CLAIM_GRACE, limit=CLAIM_LIMIT):
    """恢复中断期次：领取后超过 grace 秒仍未完成的原期由当前进程接管执行。
    同一行、同一快照，不新增归档；已暂停计划的已领取期次同样允许恢复。"""
    now=now or time.time()
    cutoff=now-grace
    ids=db.scalars(select(Delivery.id).where(Delivery.status=='claimed',Delivery.claimed_at<cutoff).order_by(Delivery.scheduled_for).limit(limit)).all()
    for did in ids:
        res=db.execute(update(Delivery).where(Delivery.id==did,Delivery.status=='claimed',Delivery.claimed_at<cutoff).values(claimed_by=worker_id,claimed_at=now,recoveries=Delivery.recoveries+1,recovered_at=now))
        db.commit()
        if res.rowcount==1:
            record(db,'worker','delivery.recovered',{'id':did})
            db.commit()
            process(db,did)
def process(db, delivery_id):
    """执行已领取的一期：首次领取时固定试验结果快照，之后一律用快照原子落盘。"""
    d=db.get(Delivery,delivery_id)
    if not d or d.status!='claimed': return
    try:
        if not d.snapshot:
            r=db.get(Report,d.report_id)
            j=db.get(Job,r.job_id) if r else None
            if not j or not j.approved: raise RuntimeError('关联分析不存在或未获批准')
            d.snapshot={'job_id':j.id,'job':j.name,'params':j.params,'result':j.result}
            db.commit()
        write_issue_files(d)
        d.status='completed'; d.finished_at=time.time(); d.error=''
        record(db,'worker','report.delivered',{'id':d.report_id,'delivery':d.id})
        db.commit()
    except Exception as e:
        logging.exception('Delivery failed')
        db.rollback()
        d=db.get(Delivery,delivery_id)
        d.status='failed'; d.error=str(e)[:990]
        record(db,'worker','delivery.failed',{'id':d.report_id,'delivery':d.id,'error':d.error})
        db.commit()
def safe(v):
    if isinstance(v,(int,float)) and not isinstance(v,bool): return v
    text=str(v)
    return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
def render_csv(snapshot):
    out=io.StringIO()
    out.write('\ufeff')
    table=(snapshot.get('result') or {}).get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    return out.getvalue().encode('utf-8')
def issue_filename(d):
    return f'report-{d.report_id}-delivery-{d.id}.csv'
def atomic_write(path, data):
    tmp=path+'.tmp'
    with open(tmp,'wb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
def write_issue_files(d):
    """从该期快照生成 CSV 与 JSON；临时文件原子改名，写盘中断不会留下空记录。"""
    payload=render_csv(d.snapshot or {})
    checksum=hashlib.sha256(payload).hexdigest()
    filename=issue_filename(d)
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    base=os.path.join(ARTIFACT_DIR,filename)
    atomic_write(base,payload)
    meta={'job':d.snapshot.get('job'),'params':d.snapshot.get('params'),'result':d.snapshot.get('result'),'checksum':checksum,'scheduled_for':d.scheduled_for}
    atomic_write(base+'.json',json.dumps(meta,ensure_ascii=False,allow_nan=False).encode('utf-8'))
    d.filename=filename
    d.checksum=checksum
def sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(65536),b''): h.update(chunk)
    return h.hexdigest()
def integrity_ok(d):
    """文件和校验值齐全才算完整：CSV 与 JSON 都在，且 SHA256 与记录一致。"""
    if not d.filename or not d.checksum: return False
    base=os.path.join(ARTIFACT_DIR,d.filename)
    if not (os.path.exists(base) and os.path.exists(base+'.json')): return False
    if sha256_file(base)!=d.checksum: return False
    try:
        with open(base+'.json') as f:
            if json.load(f).get('checksum')!=d.checksum: return False
    except Exception: return False
    return True
def verify(db, d):
    """核对已归档期次；缺文件或校验不符时标记为待修复。返回是否有状态变化。"""
    if d.status=='completed' and not integrity_ok(d):
        d.status='repair'
        record(db,'system','delivery.repair_marked',{'id':d.id})
        return True
    return False
def repair(db, d):
    """从该期首次领取时固定的快照修复文件；同一期修复，不新增归档。"""
    if d.status!='repair': raise HTTPException(409,'仅待修复的归档需要修复')
    if not d.snapshot: raise HTTPException(409,'该期缺少首次领取时的快照，无法修复')
    write_issue_files(d)
    d.status='completed'; d.finished_at=time.time(); d.error=''
    db.flush()
    return d
def retry(db, d):
    """重试同一期：回到待领取队列，不新增归档。"""
    if d.status!='failed': raise HTTPException(409,'仅待重试的期次可以重试')
    d.status='pending'; d.error=''; d.claimed_by=''; d.claimed_at=None
    db.flush()
    return d
