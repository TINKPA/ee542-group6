"""Lab 3 Part 2 — the Lab 2 UDP transfer program on three testbeds: UTM VMs (Lab 2, 08-29),
netns/veth (Lab 2, 08-29) and AWS EC2 (09-04). One-way 1 GiB time, medians; all runs MD5-verified.
Numbers from notes/2026-08-29_log_lab2-experiments.md and notes/2026-09-04_log_lab2-aws-topology.md.
Run from assignments/lab3/data:  uv run --with matplotlib --with numpy plot_part2_compare_v1.py"""
import numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; GRID="#e8e7e3"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK,"axes.edgecolor":MUT,
 "axes.labelcolor":INK2,"xtick.color":INK2,"ytick.color":INK2})
cases=["Case 1\n10 ms / 1 %","Case 2\n200 ms / 20 %","Case 3\n200 ms / 0 % · 80 M"]
F=8589.934592
t1500={"UTM VMs (x86 emulated)":[115.3,134.9,124.5],"netns + veth":[109.5,136.8,125.3],"AWS EC2":[90.0,124.8,111.4]}
t9000={"netns + veth":[161.2,206.6,171.6],"AWS EC2":[88.7,113.3,110.4]}
shannon=[88.9,110.0,110.0]
scp_aws=[548,None,343]
COL={"UTM VMs (x86 emulated)":"#8a897f","netns + veth":"#e0a30f","AWS EC2":"#2a78d6"}
fig,(ax,ax2)=plt.subplots(1,2,figsize=(11.4,4.3),dpi=150,constrained_layout=True); fig.patch.set_facecolor(SURF)
for a in (ax,ax2):
    a.set_facecolor(SURF); a.yaxis.grid(True,color=GRID,lw=0.8); a.set_axisbelow(True)
    for s in("top","right"): a.spines[s].set_visible(False)
    a.set_xticks(np.arange(3)); a.set_xticklabels(cases,fontsize=9,linespacing=1.4)
x=np.arange(3); w=0.26
for i,(k,v) in enumerate(t1500.items()):
    b=ax.bar(x+(i-1)*w,[F/t for t in v],w,color=COL[k],label=k)
    for xi,t in zip(x+(i-1)*w,v): ax.text(xi,F/t+1.2,f"{F/t:.0f}",ha="center",fontsize=7,color=INK2)
ax.plot(x,[F/s for s in shannon],"_",ms=34,color=INK,mew=1.4,label="Shannon erasure bound")
ax.set_ylabel("goodput (Mbps), MTU 1500"); ax.set_ylim(0,128); ax.legend(fontsize=8,frameon=False,loc="upper center",ncol=2)
ax.set_title("Same program, three testbeds: the cloud is the fastest and closest to the bound",fontsize=10,loc="left")
for i,(k,v) in enumerate(t9000.items()):
    ax2.bar(x+(i-0.5)*w,[F/t for t in v],w,color=COL[k],label=k)
    for xi,t in zip(x+(i-0.5)*w,v): ax2.text(xi,F/t+1.2,f"{F/t:.0f}",ha="center",fontsize=7,color=INK2)
ax2.set_ylabel("goodput (Mbps), MTU 9000/9001"); ax2.set_ylim(0,128); ax2.legend(fontsize=8,frameon=False,loc="upper center",ncol=2)
ax2.set_title("Jumbo frames: slower on veth (shaper artifact), faster on EC2",fontsize=10,loc="left")
fig.savefig("lab3_part2_compare_v1.png",facecolor=SURF); print("ok")
