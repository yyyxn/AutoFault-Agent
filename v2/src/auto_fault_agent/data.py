from __future__ import annotations
import json
from pathlib import Path
from .schemas import FaultCase, TestCase, KnowledgeDocument, BenchmarkTask

ROOT = Path(__file__).resolve().parents[2]
def load_jsonl(path: Path, model):
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
def faults(): return load_jsonl(ROOT / "data/faults/synthetic_fault_cases.jsonl", FaultCase)
def tests(): return load_jsonl(ROOT / "data/faults/synthetic_test_cases.jsonl", TestCase)
def knowledge(): return load_jsonl(ROOT / "data/knowledge/synthetic_knowledge.jsonl", KnowledgeDocument)
def benchmark_tasks():
    raw=json.loads((ROOT / "data/benchmark_tasks.json").read_text(encoding="utf-8"))
    return [BenchmarkTask.model_validate(x) for x in raw]
