import {jobs,reports} from '../api/entities.js';
import {download} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {DeliveryStatus} from '../constants/enums.js';
const badge=s=>'<span class="status '+esc(s)+'">'+esc(DeliveryStatus[s]||s)+'</span>';
function trace(d){
 const parts=['领取 '+d.attempts+' 次'];
 if(d.recoveries)parts.push('恢复 '+d.recoveries+' 次 · '+(d.recovered_at?date(d.recovered_at):'—'));
 if(d.finished_at)parts.push('归档于 '+date(d.finished_at));
 if(d.error)parts.push(esc(d.error));
 return parts.join(' · ');
}
function issueRow(d){
 const admin=session.user.role==='admin',ops=[];
 if(d.status==='completed')ops.push('<button class="text-button" data-download="'+d.id+'" data-format="csv">CSV ↓</button><button class="text-button" data-download="'+d.id+'" data-format="json">JSON ↓</button>');
 if(d.status==='repair'&&admin)ops.push('<button class="text-button" data-repair="'+d.id+'">从快照修复</button>');
 if(d.status==='failed'&&admin)ops.push('<button class="text-button" data-retry="'+d.id+'">重试本期</button>');
 return '<tr><td>#'+d.id+'</td><td>'+esc(d.report_name)+'</td><td>'+date(d.scheduled_for)+'</td><td>'+badge(d.status)+'</td><td><small>'+trace(d)+'</small></td><td><small>'+(d.checksum?esc(d.checksum.slice(0,16))+'…':'—')+'</small></td><td class="issue-ops">'+ops.join('')+'</td></tr>';
}
export async function reportPage(){
 const [list,deliveries,allJobs]=await Promise.all([reports.list(),reports.deliveries(),jobs.list()]);workspace.reports=list;
 const approved=allJobs.filter(j=>j.approved&&j.status==='completed');
 return heading('05 / DISTRIBUTION','定时分发与归档','把批准后的结果交付到本地业务收件箱。每期按应发时刻建档，缺期自动补齐；文件与校验值齐全才可下载，缺档可从该期快照修复。','<button class="button" id="refresh-reports">刷新收件箱 ↻</button>')+'<div class="report-grid"><section class="panel"><div class="section-title"><h2>创建分发计划</h2></div><form id="report-form"><label>简报名称<input name="name" required minlength="2" value="日间业务复核简报"></label><label>已批准分析<select name="job_id" required>'+approved.map(j=>'<option value="'+j.id+'">'+esc(j.name)+'</option>').join('')+'</select></label><label>业务接收组<input name="destination" value="业务复核组 · 本地收件箱" required></label><div class="parameter-grid"><label>分发周期<select name="interval_seconds"><option value="86400">每日</option><option value="604800">每周</option><option value="60">每分钟（验收）</option></select></label><label>首次执行<select name="delay_seconds"><option value="0">立即</option><option value="60">1 分钟后</option><option value="3600">1 小时后</option></select></label></div><button type="submit" class="primary" '+(session.user.role!=='admin'||!approved.length?'disabled':'')+'>保存分发计划</button></form><p class="hint">由后台 worker 按应发时刻逐期归档；重启后自动补齐漏期，同一期重试不新增归档。暂停后不再领取新期，已领取的期次仍会恢复完成。仅负责人可创建、暂停、修复或重试。</p></section><section><div class="section-title"><h2>运行中的计划</h2><span>'+list.filter(r=>r.enabled).length+' 条已启用</span></div><div class="schedule-list">'+list.map(r=>'<article><div><strong>'+esc(r.name)+'</strong><p>'+esc(r.destination)+'</p><small>下次应发 '+date(r.next_run)+' · 周期 '+r.interval_seconds+' 秒</small></div><button class="button small" data-toggle="'+r.id+'" '+(session.user.role!=='admin'?'disabled':'')+'>'+(r.enabled?'暂停':'启用')+'</button></article>').join('')+'</div><section class="panel inbox"><div class="section-title"><h2>期次台账 · 本地收件箱</h2><span>'+deliveries.length+' 期归档</span></div>'+(deliveries.length?'<div class="table-wrap"><table><thead><tr><th>期次</th><th>简报</th><th>应发时间</th><th>状态</th><th>处理与恢复</th><th>SHA256</th><th>操作</th></tr></thead><tbody>'+deliveries.map(issueRow).join('')+'</tbody></table></div>':'<p class="empty">计划执行后，各期归档会出现在此处。等待片刻后刷新。</p>')+'</section></section></div>';
}
export function bindReports(refresh){document.querySelector('#refresh-reports').onclick=refresh;submit(document.querySelector('#report-form'),async f=>{await reports.create({name:f.get('name'),job_id:Number(f.get('job_id')),destination:f.get('destination'),interval_seconds:Number(f.get('interval_seconds')),delay_seconds:Number(f.get('delay_seconds'))});notify('计划已保存，后台将按应发时刻逐期归档');await refresh();});document.querySelectorAll('[data-toggle]').forEach(b=>b.onclick=async()=>{try{await reports.toggle(b.dataset.toggle);await refresh();}catch(e){notify(e.message,true);}});document.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>download(b.dataset.download,b.dataset.format).catch(e=>notify(e.message,true)));document.querySelectorAll('[data-repair]').forEach(b=>b.onclick=async()=>{try{await reports.repair(b.dataset.repair);notify('已从该期快照修复归档');await refresh();}catch(e){notify(e.message,true);}});document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{try{await reports.retry(b.dataset.retry);notify('本期已重新排队，不新增归档');await refresh();}catch(e){notify(e.message,true);}});}
