"""Lab 3 Part 3 section 4 — the same RTT x loss grid under stock cubic and under the
ee542c module (loss is not congestion, window pinned at the BDP by cong_control).
Reads raw/sweep/sweep.csv (cubic) and raw/sweep_ee542c/sweep.csv. Outputs:
  lab3_cc_compare_v1.png   two heatmaps on one log colour scale + the speedup grid
  lab3_cc_lines_v1.png     goodput vs loss at three RTTs, both stacks, 10 Mbps target marked
Run from assignments/lab3/data:  uv run --with pandas --with matplotlib --with numpy plot_cc_compare_v1.py"""
import pandas as pd, numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
from matplotlib.colors import LogNorm
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; GRID="#e8e7e3"
BLUE="#2a78d6"; AQUA="#1baf7a"; RED="#c0392b"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK,"axes.edgecolor":MUT,
 "axes.labelcolor":INK2,"xtick.color":INK2,"ytick.color":INK2})
FLOOR=0.01

def grid(path):
    d=pd.read_csv(path).sort_values(["loss_pct","rtt_ms"]).drop_duplicates(["rtt_ms","loss_pct"],keep="last")
    return d
A=grid("raw/sweep/sweep.csv"); B=grid("raw/sweep_ee542c/sweep.csv")
rtts=sorted(set(A.rtt_ms)&set(B.rtt_ms)); losses=sorted(set(A.loss_pct)&set(B.loss_pct))
def piv(d): return d.pivot(index="loss_pct",columns="rtt_ms",values="mbps").reindex(index=losses,columns=rtts).values.astype(float)
MA,MB=piv(A),piv(B)

def style(a):
    a.set_facecolor(SURF)
    for s in ("top","right"): a.spines[s].set_visible(False)

def heat(ax,M,title,cmap="viridis",norm=None,fmt=True,prefix=None):
    im=ax.imshow(np.maximum(M,FLOOR),origin="lower",aspect="auto",cmap=cmap,norm=norm)
    ax.set_xticks(range(len(rtts))); ax.set_xticklabels(rtts,fontsize=8)
    ax.set_yticks(range(len(losses))); ax.set_yticklabels(losses,fontsize=8)
    if fmt:
        for i in range(len(losses)):
            for j in range(len(rtts)):
                v=M[i,j]
                if np.isnan(v): continue
                s=f"{v:.0f}" if v>=10 else (f"{v:.1f}" if v>=1 else f"{v:.2f}")
                if prefix is not None and prefix[i,j]: s=">"+s
                ax.text(j,i,s,ha="center",va="center",fontsize=8.5,color="white" if v<8 else INK)
    ax.set_title(title,fontsize=10.5,loc="left")
    ax.set_ylabel("loss each way (%)",fontsize=9)
    return im

# 1. side-by-side heatmaps + speedup --------------------------------------
fig,axes=plt.subplots(3,1,figsize=(9.0,8.4),dpi=150,constrained_layout=True)
fig.patch.set_facecolor(SURF)
for a in axes: style(a)
norm=LogNorm(vmin=FLOOR,vmax=100)
im=heat(axes[0],MA,"stock cubic",norm=norm)
heat(axes[1],MB,"ee542c: loss is not congestion",norm=norm)
cb=fig.colorbar(im,ax=axes[:2],pad=0.012,fraction=0.05)
cb.set_label("scp goodput, 60 s window (Mbps, log)",fontsize=9)
S=MB/np.maximum(MA,FLOOR)
LOWER=~(MA>FLOOR)          # cubic moved no measurable data: ratio is a lower bound
im2=heat(axes[2],S,"speedup, ee542c / cubic   (> marks a lower bound: cubic moved 0 bytes)",cmap="magma",
         norm=LogNorm(vmin=1,vmax=max(10,np.nanmax(S))),prefix=LOWER)
fig.colorbar(im2,ax=axes[2],pad=0.012,fraction=0.05).set_label("speedup (x, log)",fontsize=9)
axes[2].set_xlabel("RTT (ms)",fontsize=9.5)
fig.savefig("lab3_cc_compare_v1.png",facecolor=SURF)

# 2. goodput vs loss at three RTTs ----------------------------------------
pick=[r for r in (0,100,200) if r in rtts]
fig,axes=plt.subplots(1,len(pick),figsize=(3.2*len(pick),3.2),dpi=150,constrained_layout=True,sharey=True)
fig.patch.set_facecolor(SURF)
if len(pick)==1: axes=[axes]
for ax,r in zip(axes,pick):
    style(ax); ax.yaxis.grid(True,color=GRID,lw=0.8); ax.set_axisbelow(True)
    j=rtts.index(r)
    ya=np.maximum(MA[:,j],FLOOR); clamp=~(MA[:,j]>FLOOR)
    ax.plot(losses,ya,"-",color=BLUE,lw=1.6,label="cubic")
    ax.plot(np.array(losses)[~clamp],ya[~clamp],"o",color=BLUE,ms=4)
    ax.plot(np.array(losses)[clamp],ya[clamp],"o",mfc="none",mec=BLUE,ms=5,mew=1.2)
    ax.plot(losses,np.maximum(MB[:,j],FLOOR),"o-",color=AQUA,lw=1.6,ms=4,label="ee542c")
    ax.axhline(10,color=RED,lw=1,ls="--")
    ax.set_yscale("log"); ax.set_ylim(FLOOR*0.6,220)   # headroom so floored points clear the axis
    ax.set_xlabel("packet loss, each direction (%)",fontsize=8.5)
    ax.tick_params(labelsize=8)
    ax.set_title(f"RTT {r} ms",fontsize=10,loc="left")
axes[0].set_ylabel("scp goodput (Mbps, log)",fontsize=8.5)
axes[0].legend(fontsize=8.5,frameon=False,loc="lower left")
axes[-1].text(0.98,10*1.25,"full-credit target 10 Mbps",fontsize=7.5,color=RED,ha="right",
              transform=axes[-1].get_yaxis_transform())
# note goes in the middle panel's empty lower-left, not on top of the legend
axes[min(1,len(pick)-1)].text(0.02,0.045,"hollow marker: 0 bytes landed in the 60 s window,\nplotted at the 0.01 Mbps floor",
             fontsize=7,color=INK2,transform=axes[min(1,len(pick)-1)].transAxes)
fig.savefig("lab3_cc_lines_v1.png",facecolor=SURF)
print("ok: lab3_cc_compare_v1.png lab3_cc_lines_v1.png")
