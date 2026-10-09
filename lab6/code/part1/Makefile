# EE542 Lab 6 Part 1. Same flags as the handout: gcc -O2.
CC      = gcc
CFLAGS  ?= -O2
all: matrix_cpu
matrix_cpu: matrix_cpu.c
	$(CC) $(CFLAGS) $< -o $@
clean:
	rm -f matrix_cpu
.PHONY: all clean
