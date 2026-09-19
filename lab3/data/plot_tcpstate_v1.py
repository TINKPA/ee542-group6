"""Lab 3 Part 3 — sender-side TCP state during scp, from `ss -tin` samples (5 s) in raw/sweep/ss_r<RTT>_l<loss>.log.
Left: cwnd over time for four cells; right: RTO over time (exponential backoff visible).
Bottom right: the largest RTO seen in each of the 66 cells vs configured loss (backoff climbs to the 120 s Linux cap).
Run from assignments/lab3/data:  uv run --with matplotlib --with numpy plot_tcpstate_v1.py"""
import re, glob, numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; GRID="#e8e7e3"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK,"axes.edgecolor":MUT,
 "axes.labelcolor":INK2,"xtick.color":INK2,"ytick.color":INK2})
CELLS=[(20,0,"#2a78d6","20 ms / 0 %"),(100,5,"#1baf7a","100 ms / 5 %"),(200,10,"#e0a30f","200 ms / 10 %"),(200,20,"#c0392b","200 ms / 20 %")]
def parse(rtt,loss):
    f=f"raw/sweep/ss_r{rtt}_l{loss}.log"
    try: txt=open(f).read()
    except FileNotFoundError: return None
    t=[];cw=[];rto=[];acked=[]
    for blk in txt.split("===")[1:]:
        lines=blk.strip().splitlines()
        if not lines: continue
        ts=int(lines[0].strip()); body="\n".join(lines[1:])
        m=re.search(r"cwnd:(\d+)",body); r=re.search(r"rto:(\d+)",body); a=re.search(r"bytes_acked:(\d+)",body)
        if not m: continue
        t.append(ts); cw.append(int(m.group(1))); rto.append(int(r.group(1))); acked.append(int(a.group(1)) if a else 0)
    if not t: return None
    t0=t[0]; return np.array(t)-t0,np.array(cw),np.array(rto)/1000,np.array(acked)
fig,ax=plt.subplots(2,2,figsize=(11.4,7.6),dpi=150,constrained_layout=True); fig.patch.set_facecolor(SURF)
(a1,a2),(a3,a4)=ax
for a in ax.flat:
    a.set_facecolor(SURF); a.yaxis.grid(True,color=GRID,lw=0.8); a.set_axisbelow(True)
    for s in("top","right"): a.spines[s].set_visible(False)
for rtt,loss,c,lab in CELLS:
    d=parse(rtt,loss)
    if d is None: continue
    t,cw,rto,ack=d
    a1.step(t,cw,where="post",color=c,lw=1.6,label=lab); a2.step(t,rto,where="post",color=c,lw=1.6,label=lab)
    a3.plot(t,ack/1e6,"-o",ms=3,color=c,lw=1.4,label=lab)
a1.set_ylabel("cwnd (segments)"); a1.set_yscale("log"); a1.set_xlabel("time (s)"); a1.set_title("Congestion window",fontsize=10.5,loc="left")
a2.set_ylabel("RTO (s)"); a2.set_yscale("log"); a2.set_xlabel("time (s)"); a2.set_title("Retransmission timeout: doubling on each loss",fontsize=10.5,loc="left")
a3.set_ylabel("bytes acked (MB)"); a3.set_xlabel("time (s)"); a3.set_title("Progress in the 60 s window",fontsize=10.5,loc="left")
import glob as _g
pts=[]
for f in _g.glob("raw/sweep/ss_r*_l*.log"):
    m=re.search(r"ss_r(\d+)_l(\d+)\.log",f); rtt,loss=int(m.group(1)),int(m.group(2))
    r=[int(x)/1000 for x in re.findall(r"rto:(\d+)",open(f).read())]
    if r: pts.append((loss,max(r),rtt))
pts=np.array(pts); sc=a4.scatter(pts[:,0]+np.random.default_rng(0).uniform(-0.8,0.8,len(pts)),pts[:,1],c=pts[:,2],cmap="viridis",s=22,alpha=0.9)
cb=fig.colorbar(sc,ax=a4,pad=0.02); cb.set_label("RTT (ms)")
a4.axhline(120,color=INK2,lw=0.9,ls=":"); a4.text(0,135,"Linux RTO cap 120 s",fontsize=7.5,color=INK2)
a4.axhline(0.2,color=MUT,lw=0.9,ls="--"); a4.text(0,0.225,"RFC 6298 minimum 200 ms",fontsize=7.5,color=MUT)
a4.set_yscale("log"); a4.set_xlabel("configured loss per direction (%)"); a4.set_ylabel("largest RTO observed in the cell (s)")
a4.set_xticks([0,5,10,15,20,25])
a4.set_title("Exponential backoff: worst RTO per cell, all 66 cells",fontsize=10.5,loc="left")
for a in (a1,a2,a3): a.legend(fontsize=7.5,frameon=False)
fig.savefig("lab3_tcpstate_v1.png",facecolor=SURF); print("ok")
