"""Lab 3 Part 1 — iperf3 TCP/UDP through the handout's tc step sequence on the client egress
(raw/part1/<step>_{tcp,udp}.json from code/part1_tc_steps.sh), plus the two-shaper scp baseline
(raw/sweep_lab2shaper/baseline.txt vs raw/sweep/baseline.txt).
Run from assignments/lab3/data:  uv run --with matplotlib --with numpy plot_part1_tcsteps_v1.py"""
import json, re, glob, numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; GRID="#e8e7e3"; BLUE="#2a78d6"; AQUA="#1baf7a"; AMB="#e0a30f"; RED="#c0392b"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK,"axes.edgecolor":MUT,
 "axes.labelcolor":INK2,"xtick.color":INK2,"ytick.color":INK2})
STEPS=[("0_clean","no qdisc"),("1_delay100","netem\ndelay 100 ms"),("2_loss10","netem\nloss 10 %"),("3_tbf100","tbf 100 Mbit\nburst 9015"),("4_tbf100_mtu9001","tbf 100 Mbit\nMTU 9001")]
tcp=[];udp=[];loss=[];retr=[]
for k,_ in STEPS:
    t=json.load(open(f"raw/part1/{k}_tcp.json")); u=json.load(open(f"raw/part1/{k}_udp.json"))
    tcp.append(t["end"]["sum_sent"]["bits_per_second"]/1e6); retr.append(t["end"]["sum_sent"].get("retransmits",0))
    lp=u["end"]["sum"]["lost_percent"]; loss.append(lp); udp.append(u["end"]["sum"]["bits_per_second"]/1e6*(1-lp/100))
fig,(ax,ax2)=plt.subplots(1,2,figsize=(11.4,4.3),dpi=150,constrained_layout=True,gridspec_kw={"width_ratios":[3,1.4]}); fig.patch.set_facecolor(SURF)
for a in (ax,ax2):
    a.set_facecolor(SURF); a.yaxis.grid(True,color=GRID,lw=0.8); a.set_axisbelow(True)
    for s in("top","right"): a.spines[s].set_visible(False)
x=np.arange(len(STEPS)); w=0.36
ax.bar(x-w/2,tcp,w,color=BLUE,label="iperf3 TCP (sent)"); ax.bar(x+w/2,udp,w,color=AQUA,label="iperf3 UDP delivered (offered 200 Mbit)")
for xi,v,r in zip(x-w/2,tcp,retr): ax.text(xi,v*1.15,f"{v:.0f}\n{r} retx",ha="center",fontsize=7,color=INK2)
for xi,v,l in zip(x+w/2,udp,loss): ax.text(xi,v*1.15,f"{v:.0f}\n{l:.0f}% lost",ha="center",fontsize=7,color=INK2)
ax.set_yscale("log"); ax.set_ylim(0.5,20000); ax.set_xticks(x); ax.set_xticklabels([s for _,s in STEPS],fontsize=8.5,linespacing=1.3)
ax.set_ylabel("throughput (Mbps, log)"); ax.legend(fontsize=8,frameon=False,loc="upper right")
ax.set_title("Handout tc steps on the client egress: TCP vs UDP readings",fontsize=10.5,loc="left")
def base(p):
    s=open(p).read(); return float(re.search(r"mbps=([0-9.]+)",s).group(1)), float(re.search(r"full_1GiB_s=([0-9.]+)",s).group(1))
b2=base("raw/sweep_lab2shaper/baseline.txt"); b3=base("raw/sweep/baseline.txt")
ax2.bar([0,1],[b2[0],b3[0]],0.55,color=[AMB,BLUE])
for i,(m,t) in enumerate([b2,b3]): ax2.text(i,m+1.5,f"{m:.1f} Mbps\n{t:.0f} s",ha="center",fontsize=8,color=INK2)
ax2.set_xticks([0,1]); ax2.set_xticklabels(["Lab 2 shaper\nburst 9015,\nendpoints + router","Lab 3 shaper\nburst 901555,\nrouter only"],fontsize=8,linespacing=1.3)
ax2.set_ylabel("scp goodput, full 1 GiB (Mbps)"); ax2.set_ylim(0,110)
ax2.set_title("Baseline: 10 ms RTT, 0 % loss",fontsize=10.5,loc="left")
fig.savefig("lab3_part1_tcsteps_v1.png",facecolor=SURF); print("ok")
