# EE542 Lab 6 Part 2. Same command as the handout: nvcc matrix_gpu.cu -o matrix_gpu.
NVCC    ?= nvcc
NVFLAGS ?=
all: matrix_gpu
matrix_gpu: matrix_gpu.cu
	$(NVCC) $(NVFLAGS) $< -o $@
clean:
	rm -f matrix_gpu
.PHONY: all clean
