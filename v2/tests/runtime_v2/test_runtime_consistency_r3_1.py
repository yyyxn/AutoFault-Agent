from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from auto_fault_agent.harness.checkpoint import CheckpointStore
from auto_fault_agent.harness.context import ExecutionContext
from auto_fault_agent.harness.progress import (
    ProgressConflictError,
    ProgressState,
    ProgressStore,
    RecoveryStatus,
)


class Dut:
    def __init__(self):
        self.value = {"state": "NORMAL", "active": None, "version": 0}

    def snapshot(self):
        return dict(self.value)

    def restore(self, value):
        self.value = dict(value)


def state(session="s", task="t", count=0):
    return ProgressState(
        session_id=session,
        task_id=task,
        consecutive_no_progress_count=count,
    )


def _cas_worker(db_path, ready, start, queue):
    store = ProgressStore(db_path)
    current = store.load("s", "t")
    ready.put(current.version)
    start.wait()
    current.consecutive_no_progress_count += 1
    try:
        committed = store.save(current, expected_version=current.version)
        queue.put(("ok", committed.version))
    except ProgressConflictError as exc:
        queue.put(("conflict", exc.actual_version))


def test_progress_store_rejects_stale_update(tmp_path):
    store = ProgressStore(tmp_path / "progress.sqlite3")
    first = store.save(state(), expected_version=0)
    stale = store.load("s", "t")
    fresh = store.load("s", "t")
    fresh.consecutive_no_progress_count = 1
    store.save(fresh, expected_version=fresh.version)
    stale.consecutive_no_progress_count = 99
    with pytest.raises(ProgressConflictError):
        store.save(stale, expected_version=stale.version)
    assert store.load("s", "t").consecutive_no_progress_count == 1


def test_two_workers_cannot_commit_same_version(tmp_path):
    db = tmp_path / "progress.sqlite3"
    ProgressStore(db).save(state(), expected_version=0)
    ctx = mp.get_context("spawn")
    ready, queue, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    workers = [ctx.Process(target=_cas_worker, args=(db, ready, start, queue)) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert [ready.get(timeout=10) for _ in workers] == [1, 1]
    start.set()
    results = [queue.get(timeout=10) for _ in workers]
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    assert sorted(kind for kind, _ in results) == ["conflict", "ok"]
    assert ProgressStore(db).load("s", "t").version == 2


def test_sessions_remain_isolated_under_cas(tmp_path):
    store = ProgressStore(tmp_path / "progress.sqlite3")
    a = store.save(state("a", "t", 1), expected_version=0)
    b = store.save(state("b", "t", 7), expected_version=0)
    a.consecutive_no_progress_count = 2
    store.save(a, expected_version=a.version)
    assert store.load("b", "t").consecutive_no_progress_count == 7


def test_checkpoint_records_progress_commit_metadata(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    ctx = ExecutionContext(session_id="s", task_id="t")
    path = store.save(
        ctx,
        Dut(),
        progress_version=3,
        last_committed_sequence=3,
        recovery_status=RecoveryStatus.CONSISTENT.value,
    )
    payload = store.read(path)
    assert payload["consistency"]["checkpoint_version"] == 1
    assert payload["consistency"]["progress_version"] == 3
    assert payload["consistency"]["last_committed_sequence"] == 3


def test_progress_newer_than_checkpoint_is_recovered_without_overwrite(tmp_path):
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    cstore = CheckpointStore(tmp_path / "checkpoints")
    committed = pstore.save(state(count=2), expected_version=0)
    ctx = ExecutionContext(session_id="s", task_id="t")
    cp = cstore.save(ctx, Dut(), progress_version=0, last_committed_sequence=0)
    result = cstore.arbitrate(cp, pstore)
    assert result.status == RecoveryStatus.PROGRESS_AHEAD
    assert result.progress_state.version == committed.version
    assert pstore.load("s", "t").consecutive_no_progress_count == 2


def test_checkpoint_newer_than_progress_is_diagnostic_not_overwrite(tmp_path):
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    cstore = CheckpointStore(tmp_path / "checkpoints")
    pstore.save(state(), expected_version=0)
    ctx = ExecutionContext(session_id="s", task_id="t")
    cp = cstore.save(ctx, Dut(), progress_version=4, last_committed_sequence=4)
    result = cstore.arbitrate(cp, pstore)
    assert result.status == RecoveryStatus.CHECKPOINT_AHEAD
    assert not result.safe_to_resume
    assert pstore.load("s", "t").version == 1


def test_equal_versions_with_conflicting_fingerprint_are_corrupt(tmp_path):
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    cstore = CheckpointStore(tmp_path / "checkpoints")
    current = state()
    current.progress_fingerprint = "store"
    committed = pstore.save(current, expected_version=0)
    ctx = ExecutionContext(session_id="s", task_id="t", progress_fingerprint="checkpoint")
    cp = cstore.save(ctx, Dut(), progress_version=committed.version, last_committed_sequence=committed.version)
    result = cstore.arbitrate(cp, pstore)
    assert result.status == RecoveryStatus.CONFLICT
    assert not result.safe_to_resume


def test_both_missing_and_corrupt_progress_are_explicit(tmp_path):
    cstore = CheckpointStore(tmp_path / "checkpoints")
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    missing = cstore.arbitrate(None, pstore, session_id="s", task_id="t")
    assert missing.status == RecoveryStatus.BOTH_MISSING
    ctx = ExecutionContext(session_id="s", task_id="t")
    cp = cstore.save(ctx, Dut(), progress_version=1, last_committed_sequence=1)
    with sqlite3.connect(pstore.path) as db:
        db.execute(
            "INSERT OR REPLACE INTO progress_state(session_id,task_id,payload,updated_at,version) VALUES(?,?,?,?,?)",
            ("s", "t", "{broken", "x", 1),
        )
    corrupt = cstore.arbitrate(cp, pstore)
    assert corrupt.status == RecoveryStatus.PROGRESS_CORRUPT
    assert not corrupt.safe_to_resume


@pytest.mark.parametrize("crash_point", ["before_progress", "after_progress", "after_checkpoint"])
def test_real_subprocess_crash_windows_are_deterministic(tmp_path, crash_point):
    script = tmp_path / "crash_worker.py"
    script.write_text(
        """
import os,sys
from auto_fault_agent.harness.progress import ProgressStore,ProgressState
from auto_fault_agent.harness.checkpoint import CheckpointStore
from auto_fault_agent.harness.context import ExecutionContext
class D:
 def snapshot(self): return {'state':'NORMAL','active':None,'version':0}
root=sys.argv[1];point=sys.argv[2]
p=ProgressStore(os.path.join(root,'progress.sqlite3'));c=CheckpointStore(os.path.join(root,'checkpoints'))
if point=='before_progress': os._exit(71)
s=p.save(ProgressState('s','t',consecutive_no_progress_count=1),expected_version=0)
if point=='after_progress': os._exit(72)
c.save(ExecutionContext(session_id='s',task_id='t'),D(),progress_version=s.version,last_committed_sequence=s.version)
os._exit(73)
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, str(script), str(tmp_path), crash_point], check=False, env=env)
    assert proc.returncode in {71, 72, 73}
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    cstore = CheckpointStore(tmp_path / "checkpoints")
    cp = cstore.latest("s")
    result = cstore.arbitrate(cp, pstore, session_id="s", task_id="t")
    expected = {
        "before_progress": RecoveryStatus.BOTH_MISSING,
        "after_progress": RecoveryStatus.PROGRESS_AHEAD,
        "after_checkpoint": RecoveryStatus.CONSISTENT,
    }
    assert result.status == expected[crash_point]
    if result.progress_state:
        assert result.progress_state.consecutive_no_progress_count == 1


def test_repeated_recovery_is_idempotent(tmp_path):
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    cstore = CheckpointStore(tmp_path / "checkpoints")
    committed = pstore.save(state(count=1), expected_version=0)
    ctx = ExecutionContext(session_id="s", task_id="t", consecutive_no_progress_count=1)
    cp = cstore.save(ctx, Dut(), progress_version=committed.version, last_committed_sequence=committed.version)
    first = cstore.arbitrate(cp, pstore)
    second = cstore.arbitrate(cp, pstore)
    assert first.status == second.status == RecoveryStatus.CONSISTENT
    assert pstore.load("s", "t").version == committed.version
    assert pstore.load("s", "t").consecutive_no_progress_count == 1


def test_process_killed_during_recovery_can_recover_again(tmp_path):
    pstore = ProgressStore(tmp_path / "progress.sqlite3")
    cstore = CheckpointStore(tmp_path / "checkpoints")
    committed = pstore.save(state(count=1), expected_version=0)
    ctx = ExecutionContext(session_id="s", task_id="t", consecutive_no_progress_count=1)
    cp = cstore.save(ctx, Dut(), progress_version=committed.version, last_committed_sequence=committed.version)
    script = tmp_path / "recovery_worker.py"
    script.write_text(
        """
import os,sys
from auto_fault_agent.harness.progress import ProgressStore
from auto_fault_agent.harness.checkpoint import CheckpointStore
root=sys.argv[1];cp=sys.argv[2]
result=CheckpointStore(os.path.join(root,'checkpoints')).arbitrate(cp,ProgressStore(os.path.join(root,'progress.sqlite3')))
assert result.safe_to_resume
os._exit(74)
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, str(script), str(tmp_path), str(cp)], check=False, env=env)
    assert proc.returncode == 74
    again = cstore.arbitrate(cp, pstore)
    assert again.status == RecoveryStatus.CONSISTENT
    assert again.progress_state.version == committed.version
