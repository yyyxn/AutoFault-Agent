import importlib.util,json
from pathlib import Path
from fastapi.testclient import TestClient
from web.backend import app as module

client=TestClient(module.app)
def session():return client.post('/api/sessions',json={'name':'mvp21'}).json()['session_id']
def task(mode='normal',fault='F001'):
 r=client.post('/api/tasks',json={'session_id':session(),'goal':f'诊断 {fault} 并恢复','scenario':mode,'scenario_id':fault});assert r.status_code==200
 return client.get('/api/tasks/'+r.json()['task_id']).json()

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
 stats=task('long_context')['context']['token_statistics'];assert {'token_count_mode','tokenizer_source','original_tokens','compressed_tokens','compression_ratio','reserved_output_tokens','available_context_budget'}<=set(stats)
def test_estimated_never_claims_exact(monkeypatch):
 monkeypatch.setattr(module,'load_tokenizer',lambda:(None,'missing'));assert task()['context']['token_statistics']['token_count_mode']=='estimated'
def test_exact_mode_with_tokenizer(monkeypatch):
 class Fake:
  name_or_path='fake-qwen-tokenizer'
  def __call__(self,text,add_special_tokens=False):return {'input_ids':list(range(max(1,len(str(text))//4)))}
 monkeypatch.setattr(module,'load_tokenizer',lambda:(Fake(),'local-test'));stats=task()['context']['token_statistics'];assert stats['token_count_mode']=='exact' and stats['tokenizer_name']=='fake-qwen-tokenizer'
def test_frontend_validates_stale_session():
 text=(Path(__file__).parents[2]/'web/frontend/src/App.vue').read_text(encoding='utf-8');assert "request('/api/sessions/'+session.value)" in text and "localStorage.removeItem('mvp2_session_id')" in text
def test_sse_and_refresh_task():
 value=task();tid=value['task_id'];assert 'data:' in client.get(f'/api/tasks/{tid}/stream').text and client.get(f'/api/tasks/{tid}').json()['task_id']==tid
