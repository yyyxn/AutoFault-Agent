import importlib.util,json,os,subprocess,sys
from pathlib import Path
from fastapi.testclient import TestClient
from web.backend import app as module

client=TestClient(module.app)
def session():return client.post('/api/sessions',json={'name':'mvp21'}).json()['session_id']
def task(mode='normal',fault='F001'):
 r=client.post('/api/tasks',json={'session_id':session(),'goal':f'诊断 {fault} 并恢复','scenario':mode,'scenario_id':fault});assert r.status_code==200
 return client.get('/api/tasks/'+r.json()['task_id']).json()

ROOT=Path(__file__).parents[2]
def seed_restart_state(state_dir,status='RUNNING',with_json=True,events=None,task_id='task_restart',session_name='restart'):
 registry=module.SessionRegistry(state_dir/'sessions.sqlite3');sid=registry.create(session_name)['session_id'];registry.link(sid,task_id,status,False)
 if with_json:
  store=state_dir/'tasks';store.mkdir(parents=True,exist_ok=True);(store/f'{task_id}.json').write_text(json.dumps({'task_id':task_id,'session_id':sid,'goal':'restart test','scenario':'normal','scenario_id':'F001','status':status,'events':events or [],'created_at':1,'runtime_mode':'deterministic_scripted_runtime','runtime_version':'2.0-mvp2.1'}),encoding='utf-8')
 return registry,sid
def restart_process(state_dir,task_id='task_restart',api=False):
 expression=("import json;from fastapi.testclient import TestClient;from web.backend.app import app;print(json.dumps(TestClient(app).get('/api/tasks/%s').json()))"%task_id) if api else ("import json;from web.backend.app import TASKS;print(json.dumps(TASKS[%r]))"%task_id)
 env={**os.environ,'MVP2_STATE_DIR':str(state_dir),'PYTHONPATH':os.pathsep.join([str(ROOT),str(ROOT/'src')])}
 result=subprocess.run([sys.executable,'-c',expression],cwd=ROOT,env=env,text=True,capture_output=True,check=True)
 return json.loads(result.stdout.strip().splitlines()[-1])

def test_api_url_standardized():
 text=(Path(__file__).parents[2]/'web/frontend/src/api.ts').read_text(encoding='utf-8');assert 'VITE_API_URL' in text
def test_api_url_legacy_fallback():
 text=(Path(__file__).parents[2]/'web/frontend/src/api.ts').read_text(encoding='utf-8');assert 'VITE_API_BASE_URL' in text
def test_api_url_default():
 text=(Path(__file__).parents[2]/'web/frontend/src/api.ts').read_text(encoding='utf-8');assert 'http://127.0.0.1:38081' in text
def test_runbook_matches_variable():
 text=(Path(__file__).parents[2]/'README.md').read_text(encoding='utf-8');assert 'VITE_API_URL=' in text
def test_session_registry_survives_new_instance(tmp_path):
 a=module.SessionRegistry(tmp_path/'s.db');sid=a.create('x')['session_id'];a.link(sid,'task_x','COMPLETED');b=module.SessionRegistry(tmp_path/'s.db');value=b.get(sid);assert value['session_id']==sid and value['tasks'][0]['task_id']=='task_x'
def test_sessions_isolated(tmp_path):
 r=module.SessionRegistry(tmp_path/'s.db');a=r.create('a')['session_id'];b=r.create('b')['session_id'];r.link(a,'ta','COMPLETED');assert r.get(b)['tasks']==[]
def test_running_history_not_claimed_active(tmp_path,monkeypatch):
 r=module.SessionRegistry(tmp_path/'s.db');sid=r.create('a')['session_id'];r.link(sid,'ta','NEEDS_RECONCILIATION',False);assert r.get(sid)['tasks'][0]['status']=='NEEDS_RECONCILIATION'
def test_f001_selection():assert task('normal','F001')['final_state']['state']=='RECOVERED'
def test_f323_selection_and_trace():
 value=task('normal','F323');assert value['scenario_id']=='F323' and value['final_state']['state']=='RECOVERED' and any('F323' in e.get('sanitized_summary','') for e in value['events'])
def test_invalid_fault_rejected():assert client.post('/api/tasks',json={'session_id':session(),'goal':'bad fault','scenario':'normal','scenario_id':'F999'}).status_code==422
def test_repeated_final_uses_verifier():
 value=task('repeated_final');events=[e for e in value['events'] if e['event_type']=='verifier_feedback'];assert len(events)==2 and all(e['source']=='CompletionVerifier.handle_premature_final' for e in events) and events[1]['repeated_final']
def test_timeout_has_unknown_reconcile_and_one_effect():
 value=task('timeout');unknown=next(e for e in value['events'] if e['event_type']=='outcome_unknown');rec=next(e for e in value['events'] if e['event_type']=='outcome_reconciliation');assert unknown['operation_id']==rec['operation_id'] and rec['side_effect_count']==1 and value['final_state']['state']=='RECOVERED'
def test_long_context_has_inspector_fields():
 stats=task('long_context')['context']['token_statistics'];assert {'token_count_mode','token_count_scope','tokenizer_source','original_tokens','compressed_tokens','compression_ratio','compression_ratio_basis','reserved_output_tokens','available_context_budget'}<=set(stats);assert stats['compression_ratio'] is None
def test_estimated_never_claims_exact(monkeypatch):
 monkeypatch.setattr(module,'load_tokenizer',lambda:(None,'missing'));assert task()['context']['token_statistics']['token_count_mode']=='estimated'
def test_exact_mode_with_tokenizer(monkeypatch):
 class Fake:
  name_or_path='fake-qwen-tokenizer'
  def __call__(self,text,add_special_tokens=False):return {'input_ids':list(range(max(1,len(str(text))//4)))}
 monkeypatch.setattr(module,'load_tokenizer',lambda:(Fake(),'local-test'));stats=task()['context']['token_statistics'];assert stats['token_count_mode']=='exact' and stats['tokenizer_name']=='fake-qwen-tokenizer' and stats['token_count_scope']=='serialized_payload_without_chat_template'
def test_frontend_validates_stale_session():
 text=(Path(__file__).parents[2]/'web/frontend/src/App.vue').read_text(encoding='utf-8');assert 'resolveSession' in text and 'restoreTask' in text
def test_sse_and_refresh_task():
 value=task();tid=value['task_id'];assert 'data:' in client.get(f'/api/tasks/{tid}/stream').text and client.get(f'/api/tasks/{tid}').json()['task_id']==tid

def test_real_restart_running_json_becomes_reconciliation(tmp_path):
 registry,_=seed_restart_state(tmp_path);checkpoints=tmp_path/'tasks/task_restart/checkpoints';checkpoints.mkdir(parents=True);(checkpoints/'checkpoint_001.json').write_text('{}');value=restart_process(tmp_path);assert value['status']=='NEEDS_RECONCILIATION';assert registry.list_tasks()[0]['status']=='NEEDS_RECONCILIATION';assert [e['event_type'] for e in value['events']].count('startup_recovery')==1;assert value['startup_recovery_evidence']['checkpoint_file_count']==1
def test_real_restart_missing_json_creates_minimal_record(tmp_path):
 _,sid=seed_restart_state(tmp_path,with_json=False);value=restart_process(tmp_path);assert value['session_id']==sid and value['status']=='NEEDS_RECONCILIATION' and value['recovery_reason']=='sqlite_task_missing_json'
def test_completed_json_overrides_stale_running_registry(tmp_path):
 registry,_=seed_restart_state(tmp_path,status='RUNNING');path=tmp_path/'tasks/task_restart.json';value=json.loads(path.read_text());value['status']='COMPLETED';path.write_text(json.dumps(value),encoding='utf-8');assert restart_process(tmp_path)['status']=='COMPLETED';assert registry.list_tasks()[0]['status']=='COMPLETED'
def test_restart_is_idempotent_and_does_not_retry_unknown(tmp_path):
 events=[{'event_type':'outcome_unknown','operation_id':'op_existing'}];seed_restart_state(tmp_path,events=events);first=restart_process(tmp_path);second=restart_process(tmp_path);assert [e['event_type'] for e in second['events']].count('startup_recovery')==1;assert [e['event_type'] for e in second['events']].count('outcome_unknown')==1;assert not any(e['event_type'] in {'tool_attempt','outcome_reconciliation'} for e in first['events']+second['events'])
def test_restart_keeps_sessions_isolated(tmp_path):
 registry,sid1=seed_restart_state(tmp_path,task_id='task_one',session_name='one');sid2=registry.create('two')['session_id'];registry.link(sid2,'task_two','COMPLETED');store=tmp_path/'tasks';(store/'task_two.json').write_text(json.dumps({'task_id':'task_two','session_id':sid2,'status':'COMPLETED','events':[]}),encoding='utf-8');restart_process(tmp_path,'task_one');assert registry.get(sid1)['tasks'][0]['status']=='NEEDS_RECONCILIATION';assert registry.get(sid2)['tasks'][0]['status']=='COMPLETED'
def test_recovered_task_is_readable_through_api_after_restart(tmp_path):
 seed_restart_state(tmp_path,with_json=False);value=restart_process(tmp_path,api=True);assert value['task_id']=='task_restart' and value['status']=='NEEDS_RECONCILIATION'
def test_normal_completed_task_stays_completed_after_restart(tmp_path):
 seed_restart_state(tmp_path,status='COMPLETED');assert restart_process(tmp_path)['status']=='COMPLETED'
