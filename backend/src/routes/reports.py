import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Report, Delivery
from src.schemas.report import ReportInput
from src.middlewares.auth import current_user, admin_only
from src.services import reports
from src.services.audit import record
from src.utils.serialization import report_dict, delivery_dict
router=APIRouter()
@router.get('/reports')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [report_dict(r) for r in db.scalars(select(Report).order_by(Report.id.desc()))]
@router.post('/reports',status_code=201)
def create(data:ReportInput,db=Depends(get_db),u=Depends(admin_only)):
    r=reports.create(db,data); record(db,u.email,'report.schedule',{'id':r.id,'destination':r.destination}); db.commit()
    return report_dict(r)
@router.post('/reports/{id}/toggle')
def toggle(id:int,db=Depends(get_db),u=Depends(admin_only)):
    r=db.get(Report,id)
    if not r:raise HTTPException(404,'分发计划不存在')
    r.enabled=not r.enabled;record(db,u.email,'report.toggle',{'id':id,'enabled':r.enabled});db.commit()
    return report_dict(r)
@router.get('/deliveries')
def deliveries(db=Depends(get_db),u=Depends(current_user)):
    rows=list(db.scalars(select(Delivery).order_by(Delivery.scheduled_for.desc(),Delivery.id.desc()).limit(100)))
    changed=False
    for d in rows: changed=reports.verify(db,d) or changed
    if changed: db.commit()
    names={r.id:r.name for r in db.scalars(select(Report))}
    return [delivery_dict(d,names.get(d.report_id,'')) for d in rows]
@router.post('/deliveries/{id}/retry')
def retry(id:int,db=Depends(get_db),u=Depends(admin_only)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档期次不存在')
    reports.retry(db,d); record(db,u.email,'delivery.retry',{'id':id}); db.commit()
    return delivery_dict(d)
@router.post('/deliveries/{id}/repair')
def repair(id:int,db=Depends(get_db),u=Depends(admin_only)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档期次不存在')
    reports.repair(db,d); record(db,u.email,'delivery.repaired',{'id':id}); db.commit()
    return delivery_dict(d)
@router.get('/deliveries/{id}/download')
def download(id:int,format:str='csv',db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档不存在')
    if format not in ('csv','json'):raise HTTPException(422,'支持 CSV 或 JSON')
    if d.status=='repair':raise HTTPException(409,'归档文件缺失或校验不符，待修复后可下载')
    if d.status!='completed':raise HTTPException(409,'该期尚未归档完成，暂不可下载')
    if not reports.integrity_ok(d):
        d.status='repair'; record(db,'system','delivery.repair_marked',{'id':d.id}); db.commit()
        raise HTTPException(409,'归档文件缺失或校验不符，已标记为待修复')
    filename=d.filename+('.json' if format=='json' else '')
    return FileResponse(os.path.join(ARTIFACT_DIR,filename),filename=filename,media_type='application/json' if format=='json' else 'text/csv; charset=utf-8')
