"""Lab 3 Part 1 — the AWS testbed as built (VPC 10.200.0.0/16, two subnets, Ubuntu router with two ENIs).
Run from assignments/lab3/data:  uv run --with matplotlib plot_topology_v1.py"""
import matplotlib.pyplot as plt, matplotlib as mpl
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
SURF="#fcfcfb"; INK="#0b0b0b"; INK2="#52514e"; MUT="#8a897f"; BLUE="#2a78d6"; AQUA="#1baf7a"; RED="#c0392b"; AMB="#e0a30f"
mpl.rcParams.update({"font.family":"Helvetica Neue","text.color":INK})
fig,ax=plt.subplots(figsize=(11.4,5.2),dpi=150); fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
ax.set_xlim(0,114); ax.set_ylim(0,52); ax.axis("off")
def box(x,y,w,h,fc,ec,lw=1.2,r=1.2,ls="-"):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle=f"round,pad=0,rounding_size={r}",fc=fc,ec=ec,lw=lw,ls=ls))
def txt(x,y,s,**k): ax.text(x,y,s,**{"ha":"center","va":"center","fontsize":8.5,**k})
# VPC + subnets
box(4,4,106,42,"#f4f4f1",MUT,lw=1,ls="--"); txt(14,43.5,"VPC 10.200.0.0/16 · us-west-2a",fontsize=9,color=INK2,ha="left")
box(8,8,44,30,"#eaf1fb",BLUE,lw=1); txt(30,35.5,"subnet A  10.200.1.0/24",fontsize=9,color=BLUE)
box(62,8,44,30,"#e8f7f0",AQUA,lw=1); txt(84,35.5,"subnet B  10.200.2.0/24",fontsize=9,color=AQUA)
# nodes
def node(x,y,name,ip,role,col):
    box(x,y,18,13,"white",col,lw=1.6); txt(x+9,y+9.8,name,fontsize=10,fontweight="bold",color=col)
    txt(x+9,y+6.2,ip,fontsize=8.5,family="Menlo"); txt(x+9,y+2.6,role,fontsize=7.5,color=INK2)
node(11,15,"client","10.200.1.83","c7i-flex.large · sender\n1 GiB data.bin",BLUE)
node(85,15,"server","10.200.2.48","c7i-flex.large · receiver\niperf -s · md5",AQUA)
# router straddling both subnets
box(48,13,18,17,"white",AMB,lw=1.6); txt(57,26.6,"router",fontsize=10,fontweight="bold",color=AMB)
txt(57,23.2,"Ubuntu 24.04 · ip_forward=1",fontsize=7.5,color=INK2)
txt(52.2,18.6,"enp39s0\n10.200.1.10",fontsize=7,family="Menlo"); txt(61.8,18.6,"enp40s0\n10.200.2.10",fontsize=7,family="Menlo")
txt(57,14.6,"tbf 100 Mbit + netem (delay / loss)\non both interfaces",fontsize=7,color=RED)
# links
for (x0,x1) in [(29,48),(66,85)]:
    ax.add_patch(FancyArrowPatch((x0,21.5),(x1,21.5),arrowstyle="<|-|>",mutation_scale=12,lw=1.6,color=INK2))
txt(38.5,23.6,"ttl 64 $\\rightarrow$ 63",fontsize=7.5,color=INK2); txt(75.5,23.6,"MTU 1500 / 9001",fontsize=7.5,color=INK2)
# route tables
box(9,9.2,26,4.6,"#fff9e6",AMB,lw=0.8,r=0.6); txt(22,11.5,"rtA: 10.200.2.0/24 → router ENI A\n0.0.0.0/0 → igw",fontsize=6.6,family="Menlo")
box(79,9.2,26,4.6,"#fff9e6",AMB,lw=0.8,r=0.6); txt(92,11.5,"rtB: 10.200.1.0/24 → router ENI B\n0.0.0.0/0 → igw",fontsize=6.6,family="Menlo")
txt(57,5.9,"source/dest check OFF on both router ENIs",fontsize=7.2,color=AMB)
# internet / mac
box(44,42,26,7,"white",MUT,lw=1); txt(57,45.5,"Internet Gateway",fontsize=9)
txt(57,50.6,"Mac · ssh ubuntu@<public IP>  (client/server: auto public IP · router: Elastic IP)",fontsize=8,color=INK2)
for x in (20,57,94):
    ax.add_patch(FancyArrowPatch((x,42),(x,28 if x!=57 else 30),arrowstyle="-|>",mutation_scale=9,lw=0.9,color=MUT,ls=":"))
txt(24.5,40.2,"ssh only",fontsize=6.8,color=MUT); txt(98.5,40.2,"ssh only",fontsize=6.8,color=MUT)
fig.savefig("lab3_topology_v1.png",facecolor=SURF,bbox_inches="tight"); print("ok")
