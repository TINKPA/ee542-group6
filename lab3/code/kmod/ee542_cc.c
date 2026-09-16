// SPDX-License-Identifier: GPL-2.0
/*
 * ee542_cc -- EE542 Lab 3 Part 3, modification (2): a TCP congestion control
 * that does not read loss as congestion.
 *
 * ssthresh() and undo_cwnd() never reduce the window, and the window is held at
 * the link's bandwidth-delay product, so random link loss is repaired by the
 * SACK/RACK scoreboard at line rate instead of collapsing cwnd.  This is the
 * Lab 2 NAK loop expressed inside TCP.
 *
 * This is the loadable half of the lab: it needs only linux-headers for the
 * running kernel, no kernel rebuild and no reboot.  Modification (1), removing
 * the RTO exponential backoff, lives in net/ipv4/tcp_timer.c (icsk_backoff++ /
 * icsk_rto <<= 1) which is built into vmlinux and still needs a patched kernel.
 *
 * The module registers TWO algorithms so they can be compared without ever
 * reloading it (rmmod proved unreliable: the per-netns default congestion
 * control holds a module reference, and on this testbed one reference survived
 * even with no socket using it):
 *
 *   ee542    pins the window from cong_avoid().  The core keeps its recovery
 *            machinery, so while the flow is in recovery PRR (tcp_cwnd_reduction)
 *            sets cwnd = in_flight + newly_acked and cong_avoid() is never
 *            called.  Under heavy random loss the flow is almost always in
 *            recovery, so the pin barely applies.
 * TODO: cong_avoid() may not be the right hook under heavy loss -- check whether
 *            whole decision to the module and returns, so PRR never runs.  This
 *            is the hook BBR uses.
 *
 * Parameter:
 *   cwnd=<segments>   window to hold, live-writable via
 *                     /sys/module/ee542_cc/parameters/cwnd.
 *                     Default 1730 = 100 Mbps * 200 ms / 1448 B.
 *
 * Build:  make -C /lib/modules/$(uname -r)/build M=$PWD modules
 * Load:   sudo insmod ee542_cc.ko cwnd=1730
 * Select: sudo sysctl -w net.ipv4.tcp_congestion_control=ee542  
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/version.h>
#include <net/tcp.h>

/* tcp_snd_cwnd()/tcp_snd_cwnd_set() replaced direct tp->snd_cwnd access in 5.19
 * (commit 40570375356c).  Keep building on the 4.4/5.4 kernels the handout
 * assumes as well as on the 7.0-aws kernel the testbed actually runs.
 */
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 19, 0)
static inline u32 tcp_snd_cwnd(const struct tcp_sock *tp)
{
	return tp->snd_cwnd;
}

static inline void tcp_snd_cwnd_set(struct tcp_sock *tp, u32 val)
{
	tp->snd_cwnd = val;
}
#endif

static unsigned int ee542_cwnd = 1730;
module_param_named(cwnd, ee542_cwnd, uint, 0644);
MODULE_PARM_DESC(cwnd, "congestion window to hold, in MSS segments");

static void ee542_pin(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);
	u32 target = ee542_cwnd;

	if (target > tp->snd_cwnd_clamp)
		target = tp->snd_cwnd_clamp;
	if (target < TCP_INIT_CWND)
		target = TCP_INIT_CWND;

	tcp_snd_cwnd_set(tp, target);
	tp->snd_ssthresh = target;
}

/* Loss is a property of the link here, not a congestion signal: hold the window. */
static u32 ee542_ssthresh(struct sock *sk)
{
	return tcp_snd_cwnd(tcp_sk(sk));
}

static u32 ee542_undo_cwnd(struct sock *sk)
{
	return tcp_snd_cwnd(tcp_sk(sk));
}

static void ee542_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
	ee542_pin(sk);
}

static struct tcp_congestion_ops ee542_avoid __read_mostly = {
	.flags		= TCP_CONG_NON_RESTRICTED,
	.name		= "ee542",
	.owner		= THIS_MODULE,
	.ssthresh	= ee542_ssthresh,
	.undo_cwnd	= ee542_undo_cwnd,
	.cong_avoid	= ee542_cong_avoid,
};

static int __init ee542_cc_init(void)
{
	int ret;

	ret = tcp_register_congestion_control(&ee542_avoid);
	if (ret)
		return ret;


	pr_info("ee542_cc: registered ee542 (cong_avoid), cwnd=%u\n",
		ee542_cwnd);
	return 0;
}

static void __exit ee542_cc_exit(void)
{
	tcp_unregister_congestion_control(&ee542_avoid);
}

module_init(ee542_cc_init);
module_exit(ee542_cc_exit);

MODULE_AUTHOR("EE542 Group 6");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("TCP congestion control that does not treat loss as congestion");
