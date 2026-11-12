import asyncio, httpx, time, json, sys
BASE="http://127.0.0.1:8765"
async def main():
    async with httpx.AsyncClient(timeout=120, limits=httpx.Limits(max_connections=300)) as c:
        jid=(await c.post(f"{BASE}/plan", json={"raw_request":"x"})).json()["job_id"]
        while True:
            await asyncio.sleep(0.5); s=(await c.get(f"{BASE}/plan/{jid}")).json()
            if s["status"] not in ("queued","running"): break
        rep=s["report"]; print("report keys:", sorted(rep.keys()))
        spec=rep.get("trip_spec"); itin=rep.get("itinerary")
        day0=itin["days"][0]; poi=day0["items"][0]["poi_id"]
        body={"trip_spec":spec,"itinerary":itin,"edit":{"op":"remove_item","poi_id":poi,"day_index":0}}
        r=await c.post(f"{BASE}/plan/recompute", json=body); print("recompute status", r.status_code, len(r.content), r.text[:200] if r.status_code!=200 else "")
        sbody={"destination":"SIN","query":"museum"}
        r2=await c.post(f"{BASE}/places/search", json=sbody); print("search status", r2.status_code, r2.text[:300] if r2.status_code!=200 else len(r2.content))
        async def load(name, path, body, total, conc):
            sem=asyncio.Semaphore(conc); lat=[]; bad=0
            async def one():
                nonlocal bad
                async with sem:
                    t=time.perf_counter(); r=await c.post(f"{BASE}{path}", json=body); lat.append((time.perf_counter()-t)*1000)
                    if r.status_code!=200: bad+=1
            t0=time.perf_counter(); await asyncio.gather(*[one() for _ in range(total)]); el=time.perf_counter()-t0
            l=sorted(lat); print(f"{name}: conc={conc} {total/el:.0f} req/s  p50={l[len(l)//2]:.0f}ms p95={l[int(len(l)*.95)]:.0f}ms non200={bad}")
        if r.status_code==200:
            for conc in (1,50,200): await load("recompute", "/plan/recompute", body, 300, conc)
        if r2.status_code==200:
            for conc in (1,50,200): await load("places/search", "/places/search", sbody, 300, conc)
asyncio.run(main())
