from __future__ import annotations

import hashlib,json,sqlite3
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from enum import Enum
from pathlib import Path


def now():return datetime.now(timezone.utc).isoformat()

class ProgressConflictError(RuntimeError):
    def __init__(self,session_id,task_id,expected_version,actual_version):
        self.session_id=session_id;self.task_id=task_id;self.expected_version=expected_version;self.actual_version=actual_version
        super().__init__(f"progress version conflict for {session_id}/{task_id}: expected {expected_version}, actual {actual_version}")

class ProgressCorruptError(RuntimeError):pass

class RecoveryStatus(str,Enum):
    CONSISTENT="CONSISTENT"
    PROGRESS_AHEAD="PROGRESS_AHEAD"
    CHECKPOINT_AHEAD="CHECKPOINT_AHEAD"
    CONFLICT="CONFLICT"
    BOTH_MISSING="BOTH_MISSING"
    CHECKPOINT_MISSING="CHECKPOINT_MISSING"
    PROGRESS_MISSING="PROGRESS_MISSING"
    CHECKPOINT_CORRUPT="CHECKPOINT_CORRUPT"
    PROGRESS_CORRUPT="PROGRESS_CORRUPT"

@dataclass(frozen=True)
class ProgressSnapshot:
    task_id:str;session_id:str;lifecycle_state:str;contract_status:str
    missing_requirements:tuple[str,...]=();dut_state:str="UNKNOWN";dut_version:int=0
    succeeded_action_ids:tuple[str,...]=();operation_ids:tuple[str,...]=();evidence_ids:tuple[str,...]=()
    context_version:int=0;failed_action_ids:tuple[str,...]=();allowed_next_actions:tuple[str,...]=()

@dataclass(frozen=True)
class ProgressFingerprint:
    digest:str;components:dict
    def compare(self,current):
        before=self.components;after=current.components
        if len(after["missing_requirements"])<len(before["missing_requirements"]):return True,"CONTRACT_REQUIREMENTS_REDUCED"
        if (after["dut_state"],after["dut_version"])!=(before["dut_state"],before["dut_version"]):return True,"DUT_STATE_CHANGED"
        if set(after["succeeded_action_ids"])-set(before["succeeded_action_ids"]):return True,"NEW_ACTION_SUCCEEDED"
        if set(after["evidence_ids"])-set(before["evidence_ids"]):return True,"NEW_VERIFIED_EVIDENCE"
        if set(after["operation_ids"])-set(before["operation_ids"]):return True,"OUTCOME_RECONCILED"
        return False,"NO_MEANINGFUL_CHANGE"

def build_fingerprint(snapshot:ProgressSnapshot):
    components={
        "task_id":snapshot.task_id,"lifecycle_state":snapshot.lifecycle_state,"contract_status":snapshot.contract_status,
        "missing_requirements":sorted(set(snapshot.missing_requirements)),"dut_state":snapshot.dut_state,"dut_version":snapshot.dut_version,
        "succeeded_action_ids":sorted(set(snapshot.succeeded_action_ids)),"operation_ids":sorted(set(snapshot.operation_ids)),
        "evidence_ids":sorted(set(snapshot.evidence_ids)),"context_version":snapshot.context_version,
    }
    raw=json.dumps(components,sort_keys=True,separators=(",",":"));return ProgressFingerprint(hashlib.sha256(raw.encode()).hexdigest(),components)

@dataclass
class ProgressState:
    session_id:str;task_id:str;progress_fingerprint:str|None=None;previous_fingerprint:str|None=None
    fingerprint_components:dict=field(default_factory=dict);consecutive_no_progress_count:int=0;repeated_final_count:int=0
    consecutive_invalid_tool_count:int=0;last_verifier_status:str|None=None;last_missing_requirements:list[str]=field(default_factory=list)
    last_progress_reason:str|None=None;updated_at:str=field(default_factory=now)
    version:int=0;last_committed_sequence:int=0;recovery_status:str=RecoveryStatus.CONSISTENT.value

@dataclass(frozen=True)
class ProgressDecision:
    status:str;reason:str;limit_reached:bool=False;terminal_recommendation:str|None=None

class NoProgressGuard:
    def __init__(self,max_no_progress=2,state=None):self.max_no_progress=max_no_progress;self.state=state or ProgressState("local","task")
    def record(self,fingerprint,event_type,blocked_evidence=False):
        previous=None
        if self.state.progress_fingerprint:
            previous=ProgressFingerprint(self.state.progress_fingerprint,self.state.fingerprint_components)
        self.state.previous_fingerprint=self.state.progress_fingerprint;self.state.progress_fingerprint=fingerprint.digest;self.state.fingerprint_components=fingerprint.components
        if previous is None:status,reason="PROGRESS","INITIAL_BASELINE"
        else:
            changed,reason=previous.compare(fingerprint);status="PROGRESS" if changed else ("REPEATED_FINAL" if event_type=="final" else "NO_PROGRESS")
        if status=="PROGRESS":self.state.consecutive_no_progress_count=0;self.state.repeated_final_count=0;self.state.consecutive_invalid_tool_count=0
        else:
            self.state.consecutive_no_progress_count+=1
            if event_type=="final":self.state.repeated_final_count+=1
            else:self.state.consecutive_invalid_tool_count+=1
        self.state.last_progress_reason=reason;self.state.updated_at=now();limit=self.state.consecutive_no_progress_count>=self.max_no_progress
        terminal=("BLOCKED" if blocked_evidence else "BUDGET_EXHAUSTED") if limit else None
        return ProgressDecision(status,reason,limit,terminal)

class ProgressStore:
    def __init__(self,path):self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self._init()
    def _db(self):
        db=sqlite3.connect(self.path,timeout=5);db.execute("PRAGMA busy_timeout=5000");db.execute("PRAGMA journal_mode=WAL");return db
    def _init(self):
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS progress_state(session_id TEXT,task_id TEXT,payload TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(session_id,task_id))")
            columns={row[1] for row in db.execute("PRAGMA table_info(progress_state)")}
            if "version" not in columns:db.execute("ALTER TABLE progress_state ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
    def save(self,state,expected_version=None):
        expected=state.version if expected_version is None else expected_version
        committed=expected+1;state.updated_at=now();state.version=committed;state.last_committed_sequence=committed;state.recovery_status=RecoveryStatus.CONSISTENT.value
        payload=json.dumps(asdict(state),ensure_ascii=False,sort_keys=True)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected==0:
                cursor=db.execute("INSERT OR IGNORE INTO progress_state(session_id,task_id,payload,updated_at,version) VALUES(?,?,?,?,?)",(state.session_id,state.task_id,payload,state.updated_at,committed))
            else:
                cursor=db.execute("UPDATE progress_state SET payload=?,updated_at=?,version=? WHERE session_id=? AND task_id=? AND version=?",(payload,state.updated_at,committed,state.session_id,state.task_id,expected))
            if cursor.rowcount!=1:
                row=db.execute("SELECT version FROM progress_state WHERE session_id=? AND task_id=?",(state.session_id,state.task_id)).fetchone();actual=int(row[0]) if row else 0
                db.rollback();state.version=expected;state.last_committed_sequence=expected
                raise ProgressConflictError(state.session_id,state.task_id,expected,actual)
            db.commit()
        return state
    def load(self,session_id,task_id):
        with self._db() as db:row=db.execute("SELECT payload,version FROM progress_state WHERE session_id=? AND task_id=?",(session_id,task_id)).fetchone()
        if not row:return None
        try:value=json.loads(row[0]);value["version"]=int(row[1]);value["last_committed_sequence"]=max(int(value.get("last_committed_sequence",0)),int(row[1]));return ProgressState(**value)
        except Exception as exc:raise ProgressCorruptError(f"invalid progress state for {session_id}/{task_id}: {exc}") from exc
