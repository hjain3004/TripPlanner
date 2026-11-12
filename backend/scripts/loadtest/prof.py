import cProfile, pstats, sys, os, io, time
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["BENCH_LLM_LATENCY"]="0"
import app_bench as ab, api.main as m
from agents.pipeline import run_pipeline
from datetime import date
kb=m.get_kb(); reg=m.get_place_registry()
run_pipeline("x", kb, ab.FakeLLM(), reg, booking_date=date.today())  # warm
t=time.perf_counter(); pr=cProfile.Profile(); pr.enable()
r=run_pipeline("x", kb, ab.FakeLLM(), reg, booking_date=date.today())
pr.disable(); print("warm pipeline CPU (no LLM wait):", round(time.perf_counter()-t,2),"s", r.status)
s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("cumulative").print_stats(28); 
out=s.getvalue().splitlines()
print("\n".join(l[:170] for l in out[4:44]))
