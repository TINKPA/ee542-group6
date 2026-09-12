"""Lab 3 Part 3 §2 — scp throughput over the RTT x loss grid (AWS 3-node topology).
Reads raw/sweep/sweep.csv (one 60 s capped scp per cell). Outputs:
  lab3_sweep_heatmap_v1.png   RTT x loss heatmap of scp goodput (Mbps, log color)
  lab3_sweep_surface_v1.png   3D surface of the same grid
  lab3_sweep_lines_v1.png     goodput vs RTT, one line per loss rate (+ retrans fraction panel)
Run from assignments/lab3/data:  uv run --with pandas --with matplotlib --with numpy plot_sweep_v1.py"""
import pandas as pd, numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
from matplotlib.colors import LogNorm
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; GRID="#e8e7e3"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK,"axes.edgecolor":MUT,
 "axes.labelcolor":INK2,"xtick.color":INK2,"ytick.color":INK2})
df=pd.read_csv("raw/sweep/sweep.csv")
df=df.sort_values(["loss_pct","rtt_ms"]).drop_duplicates(["rtt_ms","loss_pct"],keep="last")
rtts=sorted(df.rtt_ms.unique()); losses=sorted(df.loss_pct.unique())
M=df.pivot(index="loss_pct",columns="rtt_ms",values="mbps").reindex(index=losses,columns=rtts)
R=(df.assign(rf=lambda d:np.where(d.bytes_sent>0,d.bytes_retrans/d.bytes_sent,np.nan))
     .pivot(index="loss_pct",columns="rtt_ms",values="rf").reindex(index=losses,columns=rtts))
floor=0.01
def style(a):
    a.set_facecolor(SURF)
    for s in("top","right"): a.spines[s].set_visible(False)

# 1. heatmap ---------------------------------------------------------------
fig,ax=plt.subplots(figsize=(8.6,4.4),dpi=150,constrained_layout=True); fig.patch.set_facecolor(SURF)
Z=np.maximum(M.values.astype(float),floor)
im=ax.imshow(Z,origin="lower",aspect="auto",cmap="viridis",norm=LogNorm(vmin=floor,vmax=100))
ax.set_xticks(range(len(rtts))); ax.set_xticklabels(rtts); ax.set_yticks(range(len(losses))); ax.set_yticklabels(losses)
ax.set_xlabel("RTT (ms)"); ax.set_ylabel("packet loss, each direction (%)")
for i,l in enumerate(losses):
    for j,r in enumerate(rtts):
        v=M.values[i,j]
        if np.isnan(v): continue
        ax.text(j,i,f"{v:.0f}" if v>=10 else (f"{v:.1f}" if v>=1 else f"{v:.2f}"),ha="center",va="center",
                fontsize=7,color="white" if v<8 else INK)
cb=fig.colorbar(im,ax=ax,pad=0.02); cb.set_label("scp goodput, 60 s window (Mbps, log)")
ax.set_title("scp over a 100 Mbps link: TCP goodput vs RTT and random loss",fontsize=11,loc="left")
ax.annotate("full-credit target:\n10 Mbps here",xy=(len(rtts)-1,len(losses)-2),xytext=(len(rtts)-3.2,len(losses)-1.15),fontsize=7.5,color="white",ha="center",arrowprops=dict(arrowstyle="->",color="white",lw=0.8))
fig.savefig("lab3_sweep_heatmap_v1.png",facecolor=SURF)

# 2. 3D surface ------------------------------------------------------------
fig=plt.figure(figsize=(8.6,5.4),dpi=150); fig.patch.set_facecolor(SURF)
ax=fig.add_subplot(111,projection="3d"); ax.set_facecolor(SURF)
X,Y=np.meshgrid(rtts,losses)
ax.plot_surface(X,Y,np.log10(Z),cmap="viridis",edgecolor="k",linewidth=0.25,alpha=0.95)
ax.set_xlabel("RTT (ms)",labelpad=8); ax.set_ylabel("loss per direction (%)",labelpad=8); ax.set_zlabel("goodput (Mbps)",labelpad=6)
zt=[-2,-1,0,1,2]; ax.set_zticks(zt); ax.set_zticklabels([f"{10**t:g}" for t in zt])
ax.view_init(elev=24,azim=-130)
ax.set_title("scp goodput surface (log scale)",fontsize=11,loc="left")
fig.savefig("lab3_sweep_surface_v1.png",facecolor=SURF,bbox_inches="tight")

# 3. lines + retransmission fraction --------------------------------------
fig,(ax,ax2)=plt.subplots(1,2,figsize=(11.4,4.2),dpi=150,constrained_layout=True); fig.patch.set_facecolor(SURF)
cmap=plt.get_cmap("viridis"); 
for k,l in enumerate(losses):
    c=cmap(k/max(1,len(losses)-1))
    ax.plot(rtts,np.maximum(M.loc[l].values,floor),"-o",ms=3.5,lw=1.5,color=c,label=f"{l:g} %")
    if l>0:  # Mathis et al. 1997: B = 1.22*MSS/(RTT*sqrt(p)); base RTT of the unshaped path ~1 ms
        rr=np.array(rtts)+1.0; ax.plot(rtts,1.22*1448*8/(rr/1e3*np.sqrt(l/100))/1e6,"--",lw=0.9,color=c,alpha=0.7)
    ax2.plot(rtts,R.loc[l].values*100,"-o",ms=3.5,lw=1.5,color=c,label=f"{l:g} %")
for a in (ax,ax2): style(a); a.yaxis.grid(True,color=GRID,lw=0.8); a.set_axisbelow(True); a.set_xlabel("RTT (ms)")
ax.set_yscale("log"); ax.set_ylabel("scp goodput (Mbps, 60 s window)")
ax.axhline(10,color="#c0392b",lw=1,ls="--"); ax.text(rtts[-1],10.8,"10 Mbps target",ha="right",fontsize=8,color="#c0392b")
ax.axhline(20,color=MUT,lw=0.8,ls=":"); ax.text(rtts[-1],21.5,"Lab 2 20 Mbps line",ha="right",fontsize=7.5,color=MUT)
ax.legend(title="loss / direction",fontsize=8,title_fontsize=8,frameon=False,ncol=2,loc="center right")
ax.plot([],[],"--",color=MUT,lw=0.9,label="Mathis model")
ax.set_title("Goodput collapses with loss, then with RTT (dashed: 1.22·MSS/(RTT·√p))",fontsize=10.5,loc="left")
ax2.set_ylabel("retransmitted bytes / bytes sent (%)")
ax2.set_title("Retransmission fraction tracks the configured loss",fontsize=10.5,loc="left")
fig.savefig("lab3_sweep_lines_v1.png",facecolor=SURF)
print(M.round(2).to_string())
