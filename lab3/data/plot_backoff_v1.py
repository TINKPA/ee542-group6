"""Lab 3 Part 3 §6 — the 2x2 modification matrix at 200 ms / 20 %, from raw/matrix/.
Left: RTO over the 120 s window for the four cells (the effect of tcp_no_rto_backoff is
directly visible as the absence of doubling).  Right: bytes acked over the same window.
Run from assignments/lab3/data:  uv run --with matplotlib --with numpy plot_backoff_v1.py"""
import re, glob, numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; GRID="#e8e7e3"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK,"axes.edgecolor":MUT,
 "axes.labelcolor":INK2,"xtick.color":INK2,"ytick.color":INK2})

CELLS=[("cubic",0,"#c0392b","cubic, backoff on"),
       ("cubic",1,"#e0a30f","cubic, backoff off"),
       ("ee542c",0,"#2a78d6","ee542c, backoff on"),
       ("ee542c",1,"#1baf7a","ee542c, backoff off")]

def parse(cc,nb):
    f=f"raw/matrix/ss_{cc}_nb{nb}.log"
    try: txt=open(f).read()
    except FileNotFoundError: return None
    t=[];rto=[];ack=[]
    for blk in txt.split("===")[1:]:
        lines=blk.strip().splitlines()
        if not lines: continue
        try: ts=int(lines[0].strip())
        except ValueError: continue
        body="\n".join(lines[1:])
        r=re.search(r"rto:([0-9]+)",body); a=re.search(r"bytes_acked:([0-9]+)",body)
        if not r: continue
        t.append(ts); rto.append(int(r.group(1))); ack.append(int(a.group(1)) if a else 0)
    if not t: return None
    return np.array(t)-t[0], np.array(rto)/1000.0, np.array(ack)

fig,(a1,a2)=plt.subplots(1,2,figsize=(11.0,4.0),dpi=150,constrained_layout=True)
fig.patch.set_facecolor(SURF)
for a in (a1,a2):
    a.set_facecolor(SURF); a.yaxis.grid(True,color=GRID,lw=0.8); a.set_axisbelow(True)
    for s in ("top","right"): a.spines[s].set_visible(False)

for cc,nb,c,lab in CELLS:
    d=parse(cc,nb)
    if d is None: continue
    t,rto,ack=d
    # the sampler keeps running until the outer ssh returns, which for the cubic
    # cells is ~60 s after `timeout 120` has already killed scp; clip to the
    # measurement window so all four traces cover the same 120 s.
    k=t<=122; t,rto,ack=t[k],rto[k],ack[k]
    ls="-" if nb==0 else "--"
    a1.step(t,rto,where="post",color=c,lw=1.6,ls=ls,label=lab)
    a2.plot(t,ack/1e6,marker="o",ms=2.5,color=c,lw=1.4,ls=ls,label=lab)

a1.set_yscale("log"); a1.set_ylabel("RTO (s)"); a1.set_xlabel("time (s)")
a1.set_title("Retransmission timeout",fontsize=10.5,loc="left")
a2.set_yscale("log"); a2.set_ylabel("bytes acked (MB)"); a2.set_xlabel("time (s)")
a2.set_title("Progress in the 120 s window",fontsize=10.5,loc="left")
a1.legend(fontsize=8,frameon=False,loc="upper left")
fig.savefig("lab3_backoff_v1.png",facecolor=SURF)
print("ok: lab3_backoff_v1.png")
