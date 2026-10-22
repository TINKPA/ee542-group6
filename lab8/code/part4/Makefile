CFLAGS ?= -O2 -Wall -Wextra
dpdk_rx: dpdk_rx.c
	gcc $(CFLAGS) $$(pkg-config --cflags libdpdk) $< -o $@ $$(pkg-config --libs libdpdk)
clean:
	rm -f dpdk_rx
