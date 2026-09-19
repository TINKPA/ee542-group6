#!/usr/bin/env python3
"""EE542 Lab3 Part 3, modification (1): remove TCP's exponential RTO backoff.

Run inside the unpacked linux-aws source tree on the build host.

The change is exposed as a sysctl, net.ipv4.tcp_no_rto_backoff, default 0, so a
single kernel can be measured both ways.  That removes the kernel build itself
as a confounding variable: "stock" and "no backoff" are the same binary, the
same config and the same boot, differing only by a sysctl write.

What it does, when the knob is 1 and the socket is ESTABLISHED: instead of
    icsk->icsk_backoff++;
    icsk->icsk_rto = min(icsk->icsk_rto << 1, tcp_rto_max(sk));
it recomputes the timeout from the RTT estimator and leaves the backoff counter
at zero.  This is byte for byte what the kernel's own thin-stream linear-timeout
path already does a few lines above; that path cannot help us because it
requires tcp_stream_is_thin(), and the modified congestion control holds a
window of 1730 segments.

Connection teardown is unaffected: icsk_retransmits is incremented in
tcp_write_timeout(), not here, so tcp_retries1/tcp_retries2 still apply.  Note
that retransmits_timed_out() models an exponentially backing-off sender when it
converts a retry count into a deadline, so with backoff off a dying connection
reaches that deadline after more retries than the model assumes; it is a
time-based bound, so it still fires.

SYN_SENT is deliberately left alone: the paper's argument is about established
flows, and connection-setup backoff is what protects a server under SYN load.
"""
import re, sys, pathlib

def edit(path, old, new, count=1):
    p = pathlib.Path(path)
    s = p.read_text()
    n = s.count(old)
    if n != count:
        sys.exit(f"FAIL {path}: expected {count} occurrence(s) of the anchor, found {n}")
    p.write_text(s.replace(old, new))
    print(f"ok  {path}")

# 1. the per-netns field, next to the knob whose behaviour we are copying
edit("include/net/netns/ipv4.h",
"""	u8 sysctl_tcp_thin_linear_timeouts;
""",
"""	u8 sysctl_tcp_thin_linear_timeouts;
	u8 sysctl_tcp_no_rto_backoff;	/* EE542: TCP*(inf), no exponential RTO backoff */
""")

# 2. the sysctl table entry
edit("net/ipv4/sysctl_net_ipv4.c",
"""		.procname       = "tcp_thin_linear_timeouts",
		.data           = &init_net.ipv4.sysctl_tcp_thin_linear_timeouts,
		.maxlen         = sizeof(u8),
		.mode           = 0644,
		.proc_handler   = proc_dou8vec_minmax,
	},
""",
"""		.procname       = "tcp_thin_linear_timeouts",
		.data           = &init_net.ipv4.sysctl_tcp_thin_linear_timeouts,
		.maxlen         = sizeof(u8),
		.mode           = 0644,
		.proc_handler   = proc_dou8vec_minmax,
	},
	{
		.procname       = "tcp_no_rto_backoff",
		.data           = &init_net.ipv4.sysctl_tcp_no_rto_backoff,
		.maxlen         = sizeof(u8),
		.mode           = 0644,
		.proc_handler   = proc_dou8vec_minmax,
		.extra1         = SYSCTL_ZERO,
		.extra2         = SYSCTL_ONE,
	},
""")

# 3. the behaviour itself, as a new first arm of the existing if/else chain
edit("net/ipv4/tcp_timer.c",
"""	if (sk->sk_state == TCP_ESTABLISHED &&
	    (tp->thin_lto || READ_ONCE(net->ipv4.sysctl_tcp_thin_linear_timeouts)) &&
""",
"""	if (sk->sk_state == TCP_ESTABLISHED &&
	    READ_ONCE(net->ipv4.sysctl_tcp_no_rto_backoff)) {
		/* EE542 Lab 3 / Mondal & Kuzmanovic 2008: on a link that drops
		 * packets at random rather than from congestion, doubling the
		 * retransmission timer adds delay without reducing load.  Keep
		 * the timer at the RTT estimator's value and the backoff
		 * counter at zero; icsk_retransmits still advances in
		 * tcp_write_timeout(), so retries1/retries2 still apply.
		 */
		icsk->icsk_backoff = 0;
		icsk->icsk_rto = clamp(__tcp_set_rto(tp),
				       tcp_rto_min(sk),
				       tcp_rto_max(sk));
	} else if (sk->sk_state == TCP_ESTABLISHED &&
	    (tp->thin_lto || READ_ONCE(net->ipv4.sysctl_tcp_thin_linear_timeouts)) &&
""")
print("all three edits applied")
