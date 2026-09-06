# Fountain-code experiment (set aside)

An LT rateless-code variant (`ltr.cpp`) to avoid the per-round RTT on high-RTT
links by sending forward repair instead of waiting for a NAK.

**Result: shelved.** On our links it did not beat round-based NAK. The analysis
(see the report appendix) shows the NAK protocol is already within ~2 s of the
erasure-channel lower bound, so there is no room for FEC to help - the round
overhead it removes is only ~1.9 s, and the repair packets it adds cost more.
We keep the code here as a documented dead-end; the shipped protocol uses no
FEC.
