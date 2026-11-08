from __future__ import annotations
import json,os,sqlite3,threading,time,uuid
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from auto_fault_agent.context import ContextBudgetController,ContextBuilder,ContextCompactor
from auto_fault_agent.environment.task_env import TaskEnvironment,TaskSpec
from auto_fault_agent.harness.completion_verifier import CompletionVerifier,CompletionVerifierConfig

ROOT=Path(__file__).resolve().parents[2]
STATE_ROOT=Path(os.environ.get('MVP2_STATE_DIR',ROOT/'outputs/runtime_v2/mvp2_1/demo_state'))
STORE=STATE_ROOT/'tasks';STORE.mkdir(parents=True,exist_ok=True)
app=FastAPI(title='AutoFault-Agent 2.0 MVP-2.1',docs_url='/docs')
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5173','http://localhost:5173','http://127.0.0.1:35174','http://localhost:35174'],allow_methods=['GET','POST'],allow_headers=['Content-Type'])
TASKS={};SESSIONS={}  # compatibility alias; SQLite registry is authoritative
DEMO_MODES={'normal':{'label':'正常诊断','scenario':'normal'},'timeout':{'label':'工具超时与核对','scenario':'normal'},'repeated_final':{'label':'重复 Final','scenario':'normal'},'long_context':{'label':'上下文压缩','scenario':'normal'}}
FAULTS={'F001':{'label':'F001 门窗系统（公开合成）','dtc':'SIM_DTC_001'},'F323':{'label':'F323 供电监测（独立公开合成）','dtc':'SYN_DTC_323'}}

class SessionRegistry:
 def __init__(self,path):self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self._init()
 def _db(self):return sqlite3.connect(self.path,timeout=10)
 def _init(self):
  with self._db() as db:
   db.execute('CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,name TEXT,created_at REAL,updated_at REAL,status TEXT)')
   db.execute('CREATE TABLE IF NOT EXISTS session_tasks(task_id TEXT PRIMARY KEY,session_id TEXT,status TEXT,checkpoint_valid INTEGER,updated_at REAL)')
 def create(self,name):
  now=time.time();sid='s_'+uuid.uuid4().hex[:12]
  with self._db() as db:db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(sid,name,now,now,'ACTIVE'))
  return self.get(sid)
 def get(self,sid):
  with self._db() as db:
   row=db.execute('SELECT * FROM sessions WHERE session_id=?',(sid,)).fetchone()
   if not row:return None
   tasks=[{'task_id':r[0],'status':r[1],'checkpoint_valid':bool(r[2])} for r in db.execute('SELECT task_id,status,checkpoint_valid FROM session_tasks WHERE session_id=? ORDER BY updated_at',(sid,))]
  return {'session_id':row[0],'name':row[1],'created_at':row[2],'updated_at':row[3],'status':row[4],'tasks':tasks}
 def link(self,sid,tid,status,checkpoint=False):
  now=time.time()
  with self._db() as db:db.execute('INSERT OR REPLACE INTO session_tasks VALUES(?,?,?,?,?)',(tid,sid,status,int(checkpoint),now));db.execute('UPDATE sessions SET updated_at=? WHERE session_id=?',(now,sid))
 def update(self,tid,status,checkpoint=False):
  with self._db() as db:db.execute('UPDATE session_tasks SET status=?,checkpoint_valid=?,updated_at=? WHERE task_id=?',(status,int(checkpoint),time.time(),tid))
 def list_tasks(self):
  with self._db() as db:
   rows=db.execute('SELECT task_id,session_id,status,checkpoint_valid,updated_at FROM session_tasks ORDER BY updated_at').fetchall()
  return [{'task_id':r[0],'session_id':r[1],'status':r[2],'checkpoint_valid':bool(r[3]),'updated_at':r[4]} for r in rows]
 def count(self):
  with self._db() as db:return db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]

REGISTRY=SessionRegistry(STATE_ROOT/'sessions.sqlite3')

class SessionRequest(BaseModel):name:str=Field(min_length=1,max_length=80)
class TaskRequest(BaseModel):
 session_id:str;goal:str=Field(min_length=3,max_length=500)
 scenario:str=Field(default='normal',pattern='^(normal|timeout|repeated_final|long_context)$')
 scenario_id:str=Field(default='F001',pattern='^(F001|F323)$')

def persist(task):(STORE/f"{task['task_id']}.json").write_text(json.dumps(task,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def emit(task,event_type,**values):task['events'].append({'event_id':uuid.uuid4().hex,'task_id':task['task_id'],'timestamp':time.time(),'event_type':event_type,'status':values.pop('status','ok'),'duration_ms':values.pop('duration_ms',0),**values})

def reconcile_startup_tasks(registry,task_store,tasks_cache):
 rows={row['task_id']:row for row in registry.list_tasks()};stored={}
 for path in task_store.glob('task_*.json'):
  try:
   task=json.loads(path.read_text(encoding='utf-8'));stored[task['task_id']]=task
  except Exception:
   continue
 for task_id in sorted(set(rows)|set(stored)):
  row=rows.get(task_id);task=stored.get(task_id);reason=None;checkpoint_files=sorted((task_store/task_id/'checkpoints').glob('*.json'))
  if task is None:
   reason='sqlite_task_missing_json';task={'task_id':task_id,'session_id':row['session_id'],'goal':'','scenario':'unknown','scenario_id':'unknown','status':'NEEDS_RECONCILIATION','events':[],'created_at':row['updated_at'],'runtime_mode':'deterministic_scripted_runtime','runtime_version':'2.0-mvp2.1','recovery_reason':reason}
  elif task.get('status')=='RUNNING':
   reason='unexpected_restart_while_running';task['status']='NEEDS_RECONCILIATION';task['recovery_reason']=reason
  elif row and row['status']=='RUNNING' and task.get('status') not in {'COMPLETED','NEEDS_RECONCILIATION','BUDGET_EXHAUSTED'}:
   reason='registry_running_without_terminal_evidence';task['status']='NEEDS_RECONCILIATION';task['recovery_reason']=reason
  task['startup_recovery_evidence']={'task_json_present':task_id in stored,'registry_status':row['status'] if row else None,'checkpoint_file_count':len(checkpoint_files),'latest_checkpoint_name':checkpoint_files[-1].name if checkpoint_files else None}
  if reason and not any(event.get('event_type')=='startup_recovery' for event in task.get('events',[])):
   task.setdefault('events',[]).append({'event_id':uuid.uuid4().hex,'task_id':task_id,'timestamp':time.time(),'event_type':'startup_recovery','status':'needs_reconciliation','duration_ms':0,'recovery_reason':reason,'sanitized_summary':'服务重启后执行结果不确定；未自动重试或恢复为 ACTIVE'})
  path=task_store/f'{task_id}.json';path.write_text(json.dumps(task,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
  checkpoint=bool((row and row['checkpoint_valid']) or checkpoint_files)
  if row:registry.update(task_id,task['status'],checkpoint)
  else:registry.link(task['session_id'],task_id,task['status'],False)
  tasks_cache[task_id]=task
 return tasks_cache

reconcile_startup_tasks(REGISTRY,STORE,TASKS)
def install_f323(env):
 data={'test_case_id':'SYN_TC_323','fault_id':'F323','title':'Synthetic F323 Scenario','steps':['公开合成诊断','恢复'],'expected_dtc':'SYN_DTC_323','expected_result':'PASS','data_source':'synthetic_public_demo'}
 case=SimpleNamespace(fault_id='F323',failure_mode='open_circuit',expected_dtc='SYN_DTC_323',model_dump=lambda:data)
 env.dispatcher.dut.cases['F323']=case;env.dispatcher.cases['F323']=case
def load_tokenizer():
 source=os.environ.get('MVP2_TOKENIZER_PATH','')
 if not source:return None,None
 try:
  from transformers import AutoTokenizer
  return AutoTokenizer.from_pretrained(source,local_files_only=True,trust_remote_code=True),source
 except Exception:return None,source
def progress_snapshot(env,assessment):
 from auto_fault_agent.harness.progress import ProgressSnapshot
 rows=env.harness.ledger.list_actions(env.context.session_id,env.context.task_id)
 return ProgressSnapshot(task_id=env.context.task_id,session_id=env.context.session_id,lifecycle_state=env.lifecycle.state.value,contract_status=assessment.status.value,missing_requirements=assessment.missing,dut_state=env.dispatcher.dut.state.value,dut_version=env.dispatcher.dut.version,succeeded_action_ids=tuple(r['logical_action_id'] for r in rows if r['action_status']=='SUCCEEDED'),failed_action_ids=tuple(r['logical_action_id'] for r in rows if r['action_status']=='FAILED'),operation_ids=tuple(r['operation_id'] for r in rows if r['action_status']=='OUTCOME_UNKNOWN'))

def execute(task):
 fid=task['scenario_id'];dtc=FAULTS[fid]['dtc'];mode=task['scenario']
 spec=TaskSpec(task_id=task['task_id'],task_type='full_fault_test',instruction=task['goal'],fault_id=fid,scenario='normal',initial_state='NORMAL',expected_tools=['search_fault_knowledge','get_test_case','inject_fault','read_dtc','judge_test_result','recover_fault'],ground_truth={'fault_id':fid,'expected_dtc':dtc,'observed_dtc':dtc,'expected_judge':'PASS','expected_outcome':'complete'},difficulty='medium',metadata={'data_source':'synthetic_public_demo','constraints':['必须恢复故障']})
 env=TaskEnvironment(spec,'harness',str(STORE/task['task_id']));env.reset(42)
 if fid=='F323':install_f323(env)
 verifier=CompletionVerifier(CompletionVerifierConfig(enabled=True,max_corrections=3,max_no_progress=2),session_id=task['session_id'],task_id=task['task_id'])
 messages=[{'role':'system','content':'Synthetic Mock Environment；不得声称连接真实 ECU。'},{'role':'user','content':task['goal']}]
 task['status']='RUNNING';emit(task,'user_task',sanitized_summary=task['goal']);persist(task);REGISTRY.update(task['task_id'],'RUNNING')
 if mode=='repeated_final':
  assessment=verifier.assess(env.actions,spec,env.dispatcher.dut.snapshot());snap=progress_snapshot(env,assessment)
  for raw in ('诊断已经完成。','所有诊断步骤均已结束。'):
   decision=verifier.handle_premature_final(assessment,raw,snap)
   emit(task,'verifier_feedback',status='incomplete',source='CompletionVerifier.handle_premature_final',repeated_final=bool(decision.get('repeated_final')),sanitized_summary=json.dumps(decision.get('feedback'),ensure_ascii=False))
  emit(task,'verifier_intervention',status='running',sanitized_summary='Verifier 拒绝提前 Final；后续由确定性演示序列继续执行')
 if mode=='long_context':
  for i in range(18):messages.extend([{'role':'assistant','content':'','tool_calls':[{'type':'function','function':{'name':'search_fault_knowledge','arguments':{'query':fid}}}]},{'role':'tool','name':'search_fault_knowledge','content':json.dumps({'success':True,'result':{'documents':['duplicate'],'sequence':i%2}})}])
 sequence=[('search_fault_knowledge',{'query':fid}),('get_test_case',{'fault_id':fid}),('inject_fault',{'fault_id':fid}),('read_dtc',{}),('judge_test_result',{'fault_id':fid,'dtc':dtc}),('recover_fault',{'fault_id':fid})]
 for name,args in sequence:
  started=time.perf_counter();emit(task,'tool_attempt',tool_name=name,status='running',sanitized_summary=f'{name} 参数已验证')
  if mode=='timeout' and name=='inject_fault':
   original=env.dispatcher.dut.inject_fault;counter={'value':0};completed=threading.Event()
   def slow(value):
    counter['value']+=1
    try:time.sleep(.08);return original(value)
    finally:completed.set()
   env.dispatcher.dut.inject_fault=slow;env.harness.config.timeout_seconds=.02;env.harness.config.max_retries=0
   obs=env.step({'tool_name':name,'arguments':args});action=env.harness.ledger.list_actions(env.context.session_id,env.context.task_id)[-1]
   emit(task,'outcome_unknown',tool_name=name,status=action['action_status'].lower(),action_id=action['logical_action_id'],operation_id=action['operation_id'],side_effect_count=counter['value'],duration_ms=round((time.perf_counter()-started)*1000,3),sanitized_summary=str(obs.get('error')))
   completed.wait(timeout=2);result=env.harness.reconcile(action['logical_action_id'],env.context);obs=result.model_dump();env.actions[-1]['observation']=obs
   emit(task,'outcome_reconciliation',tool_name=name,status='success' if result.success else 'outcome_unknown',action_id=action['logical_action_id'],operation_id=action['operation_id'],side_effect_count=counter['value'],dut_snapshot=env.dispatcher.dut.snapshot(),sanitized_summary='查询 operation/DUT 后核对；未盲目重试')
  else:obs=env.step({'tool_name':name,'arguments':args})
  emit(task,'tool_result',tool_name=name,status='success' if obs['success'] else 'failed',duration_ms=round((time.perf_counter()-started)*1000,3),sanitized_summary=str(obs.get('result') or obs.get('error'))[:240]);persist(task)
  messages.extend([{'role':'assistant','content':'','tool_calls':[{'type':'function','function':{'name':name,'arguments':args}}]},{'role':'tool','name':name,'content':json.dumps(obs,ensure_ascii=False,default=str)}])
  if not obs['success']:break
 assessment=verifier.assess(env.actions,spec,env.dispatcher.dut.snapshot(),cannot_continue=not all(x['observation']['success'] for x in env.actions))
 tokenizer,source=load_tokenizer();budget=ContextBudgetController(40960,4096,tokenizer=tokenizer);original=budget.count_text(messages)
 result=ContextBuilder(budget,ContextCompactor()).build(task=spec,context=env.context,dut_snapshot=env.dispatcher.dut.snapshot(),ledger=env.harness.ledger,progress_state=verifier.progress_guard.state,assessment=assessment,messages=messages,system_prompt=messages[0]['content'])
 context=result.model_dump();compressed=context['token_budget']['current_context_tokens'];context['token_statistics']={'token_count_mode':'exact' if tokenizer else 'estimated','token_count_scope':'serialized_payload_without_chat_template','tokenizer_name':getattr(tokenizer,'name_or_path',None) if tokenizer else None,'tokenizer_source':source or 'heuristic_utf8','original_tokens':original,'original_token_scope':'serialized_messages','compressed_tokens':compressed,'compressed_token_scope':'serialized_context_parts_total','compression_ratio':None,'compression_ratio_basis':'unavailable_mixed_scope','reserved_output_tokens':context['token_budget']['reserved_output_tokens'],'available_context_budget':context['token_budget']['available_context_tokens']}
 task.update(context=context,actions=env.harness.ledger.list_actions(env.context.session_id,env.context.task_id),progress=verifier.progress_guard.state.__dict__,verifier_events=verifier.state.events,final_state=env.dispatcher.dut.snapshot(),status='COMPLETED' if assessment.status.value=='complete' else 'NEEDS_RECONCILIATION')
 emit(task,'final_completion',status=task['status'].lower(),sanitized_summary=f'Completion Contract: {assessment.status.value}');persist(task);REGISTRY.update(task['task_id'],task['status'],bool(env.harness.last_checkpoint))

@app.get('/api/health')
def health():return {'status':'ok','environment':'Synthetic Mock Environment','runtime_mode':'deterministic_scripted_runtime','runtime_version':'2.0-mvp2.1','live_model':False,'session_store':'sqlite'}
@app.get('/api/scenarios')
def scenarios():return {'demo_modes':[{'id':k,**v} for k,v in DEMO_MODES.items()],'fault_scenarios':[{'id':k,**v} for k,v in FAULTS.items()]}
@app.post('/api/sessions')
def create_session(req:SessionRequest):
 value=REGISTRY.create(req.name);SESSIONS[value['session_id']]=value;return value
@app.get('/api/sessions/{session_id}')
def get_session(session_id):
 value=REGISTRY.get(session_id)
 if not value:raise HTTPException(404,'session not found')
 return value
@app.post('/api/tasks')
def create_task(req:TaskRequest):
 if not REGISTRY.get(req.session_id):raise HTTPException(404,'session not found')
 tid='task_'+uuid.uuid4().hex[:12];task={'task_id':tid,'session_id':req.session_id,'goal':req.goal,'scenario':req.scenario,'scenario_id':req.scenario_id,'status':'CREATED','events':[],'created_at':time.time(),'runtime_mode':'deterministic_scripted_runtime','runtime_version':'2.0-mvp2.1'};TASKS[tid]=task;persist(task);REGISTRY.link(req.session_id,tid,'CREATED');execute(task);return {'task_id':tid,'status':task['status']}
def get_task_value(task_id):
 if task_id in TASKS:return TASKS[task_id]
 path=STORE/f'{task_id}.json'
 if path.exists():TASKS[task_id]=json.loads(path.read_text(encoding='utf-8'));return TASKS[task_id]
 raise HTTPException(404,'task not found')
@app.get('/api/tasks/{task_id}')
def get_task(task_id):return get_task_value(task_id)
@app.get('/api/tasks/{task_id}/events')
def events(task_id):return get_task_value(task_id)['events']
@app.get('/api/tasks/{task_id}/context')
def context(task_id):return get_task_value(task_id).get('context',{})
@app.get('/api/tasks/{task_id}/actions')
def actions(task_id):return get_task_value(task_id).get('actions',[])
@app.get('/api/tasks/{task_id}/progress')
def progress(task_id):return get_task_value(task_id).get('progress',{})
@app.post('/api/tasks/{task_id}/resume')
def resume(task_id):
 task=get_task_value(task_id)
 if task['status'] not in {'NEEDS_RECONCILIATION','BUDGET_EXHAUSTED'}:raise HTTPException(409,'task is not resumable')
 emit(task,'resume_rejected',status='safe_stop',sanitized_summary='无有效 checkpoint，未伪装 ACTIVE');persist(task);return {'task_id':task_id,'status':task['status']}
@app.get('/api/tasks/{task_id}/stream')
def stream(task_id):
 task=get_task_value(task_id)
 def generate():
  for event in task['events']:yield f"data: {json.dumps(event,ensure_ascii=False)}\n\n"
 return StreamingResponse(generate(),media_type='text/event-stream')
@app.get('/api/dashboard')
def dashboard():
 values=list(TASKS.values());return {'running':sum(x['status']=='RUNNING' for x in values),'completed':sum(x['status']=='COMPLETED' for x in values),'failed':sum(x['status'] not in {'RUNNING','COMPLETED','CREATED'} for x in values),'tool_calls':sum(sum(e['event_type']=='tool_attempt' for e in x['events']) for x in values),'sessions':REGISTRY.count()}
