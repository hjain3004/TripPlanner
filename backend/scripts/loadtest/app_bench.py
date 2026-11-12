"""Bench wrapper: real app, fake LLM with simulated latency. Records prompt sizes."""
import json, os, time, threading
from agents.llm import LLMCallError
from core.trip_models import TripSpec
import api.main as m

LAT = float(os.getenv("BENCH_LLM_LATENCY", "2.0"))
SPEC = {"home_country":"IN","origin_city":"DEL","destination_city":"SIN","start_date":"2027-02-10","end_date":"2027-02-14","travelers":2,"budget_minor":None,"budget_currency":"INR","style":"balanced","interests":["food","culture"],"pace":"moderate","dietary":[],"wallet":{"card_ids":["hdfc-infinia","axis-atlas"],"points_balances":{}},"optimization":{"objective":"max_savings"},"unresolved":[]}
LOG = os.getenv("BENCH_PROMPT_LOG")
_lock = threading.Lock()

class FakeLLM:
    def complete_json(self, *, node, system, user, schema, temperature=0.0, max_tokens=2048, timeout_s=20, tools=None):
        sys_full = system + "\n\n" + json.dumps(schema.model_json_schema())
        if tools:
            sys_full = system + json.dumps(tools, indent=2)
        if LOG:
            with _lock, open(LOG, "a") as f:
                f.write(json.dumps({"node": node, "sys": len(sys_full), "user": len(user), "max_tokens": max_tokens}) + "\n")
        time.sleep(LAT)
        if node == "intake":
            return TripSpec.model_validate(SPEC)
        raise LLMCallError("bench: simulated provider failure -> deterministic fallback")

m.app.dependency_overrides[m.get_llm] = lambda: FakeLLM()
app = m.app
