import json
from functools import lru_cache
from importlib.resources import files
from .models import Scenario

@lru_cache
def scenarios() -> list[Scenario]:
    path=files("autofault_agent").joinpath("public_data/scenarios.json")
    return [Scenario.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]

def get_scenario(scenario_id: str) -> Scenario:
    for item in scenarios():
        if item.id == scenario_id:return item
    raise KeyError("Unknown public scenario")
