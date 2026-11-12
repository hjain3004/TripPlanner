import asyncio, httpx, time, json, os, sys, statistics as st, subprocess
BASE="http://127.0.0.1:8765"
PID=int(sys.argv[1]); N=int(sys.argv[2])
def proc():
    s=open(f"/proc/{PID}/status").read()
    g=lambda k:[l.split()[1] for l in s.splitlines() if l.startswith(k)][0]
    return int(g("Threads:")), int(g("VmRSS:"))//1024
async def one(c, lat, done):
    t0=time.perf_counter()
    r=await c.post(f"{BASE}/plan", json={"raw_request":"4 nights Singapore from Delhi, 2 people, Feb 10-14 2027, Infinia and Atlas"})
    jid=r.json()["job_id"]
    while True:
        await asyncio.sleep(1.5)
        t=time.perf_counter()
        r=await c.get(f"{BASE}/plan/{jid}")
        lat.append((time.perf_counter()-t)*1000)
        s=r.json()
        if s["status"] not in ("queued","running"):
            done.append((time.perf_counter()-t0, s["status"], len(r.content)))
            return s
async def main():
    lim=httpx.Limits(max_connections=N+20)
    async with httpx.AsyncClient(timeout=120, limits=lim) as c:
        lat=[];done=[]
        t0=time.perf_counter()
        peak=[0,0]
        async def watch():
            while True:
                th,rss=proc(); peak[0]=max(peak[0],th); peak[1]=max(peak[1],rss)
                await asyncio.sleep(0.25)
        w=asyncio.create_task(watch())
        res=await asyncio.gather(*[one(c,lat,done) for _ in range(N)], return_exceptions=True)
        w.cancel()
        errs=[r for r in res if isinstance(r,Exception)]
        el=time.perf_counter()-t0
        d=sorted(x[0] for x in done); l=sorted(lat)
        statuses={}
        for x in done: statuses[x[1]]=statuses.get(x[1],0)+1
        print(f"N={N} wall={el:.1f}s statuses={statuses} client_errors={len(errs)} {type(errs[0]).__name__ if errs else ''}")
        if d: print(f"  plan time  p50={d[len(d)//2]:.1f}s p95={d[int(len(d)*.95)-1]:.1f}s max={d[-1]:.1f}s")
        if l: print(f"  poll latency p50={l[len(l)//2]:.0f}ms p95={l[int(len(l)*.95)-1]:.0f}ms max={l[-1]:.0f}ms  polls={len(l)}")
        print(f"  server peak threads={peak[0]} peak RSS={peak[1]}MB; report bytes={done[0][2] if done else 0}")
asyncio.run(main())
