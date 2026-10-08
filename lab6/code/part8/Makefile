# EE542 Lab 6 Part 8. conv_cpu: gcc -O2 (as Part 1). conv_gpu: nvcc, same flags as Parts 2/4.
CC      = gcc
CFLAGS  ?= -O2
NVCC    ?= nvcc
NVFLAGS ?=
all: conv_cpu conv_gpu
conv_cpu: conv_cpu.c conv_io.h
	$(CC) $(CFLAGS) conv_cpu.c -o $@
conv_gpu: conv_gpu.cu conv_io.h conv_kernels.cuh
	$(NVCC) $(NVFLAGS) conv_gpu.cu -o $@
clean:
	rm -f conv_cpu conv_gpu
.PHONY: all clean
