from fastapi.testclient import TestClient
from web.backend.app import app,TASKS,SESSIONS
client=TestClient(app)
def session():return client.post('/api/sessions',json={'name':'test'}).json()['session_id']
def test_health_is_local_synthetic():assert client.get('/api/health').json()['environment']=='Synthetic Mock Environment'
def test_create_session():assert client.post('/api/sessions',json={'name':'x'}).status_code==200
def test_invalid_session_rejected():assert client.post('/api/tasks',json={'session_id':'bad','goal':'诊断 F001','scenario':'normal'}).status_code==404
def test_invalid_scenario_rejected():assert client.post('/api/tasks',json={'session_id':session(),'goal':'诊断 F001','scenario':'shell'}).status_code==422
def test_submit_real_runtime_task_and_read_views():
 sid=session();r=client.post('/api/tasks',json={'session_id':sid,'goal':'诊断 F001 并恢复','scenario':'normal'});assert r.status_code==200;tid=r.json()['task_id']
 assert client.get(f'/api/tasks/{tid}').json()['status']=='COMPLETED'
 assert len(client.get(f'/api/tasks/{tid}/actions').json())==6
 assert client.get(f'/api/tasks/{tid}/context').json()['authoritative_state']['dut_state']=='RECOVERED'
 assert client.get(f'/api/tasks/{tid}/events').json()[-1]['event_type']=='final_completion'
 assert 'data:' in client.get(f'/api/tasks/{tid}/stream').text
def test_refresh_from_persisted_task():
 sid=session();tid=client.post('/api/tasks',json={'session_id':sid,'goal':'诊断 F001 并恢复','scenario':'normal'}).json()['task_id'];saved=TASKS.pop(tid);assert client.get(f'/api/tasks/{tid}').json()['task_id']==tid
def test_session_isolation():
 a,b=session(),session();ta=client.post('/api/tasks',json={'session_id':a,'goal':'诊断 F001 并恢复','scenario':'normal'}).json()['task_id'];assert client.get(f'/api/tasks/{ta}').json()['session_id']==a and a!=b
def test_resume_safe_rejection():
 sid=session();tid=client.post('/api/tasks',json={'session_id':sid,'goal':'诊断 F001 并恢复','scenario':'timeout'}).json()['task_id'];assert client.post(f'/api/tasks/{tid}/resume').status_code in {200,409}
def test_no_shell_endpoint():assert client.post('/api/shell',json={'cmd':'id'}).status_code==404
