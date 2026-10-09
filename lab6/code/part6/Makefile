# EE542 Lab 6 Part 6.1. nvcc matrix_cublas.cu -o matrix_cublas -lcublas
NVCC    ?= nvcc
NVFLAGS ?=
all: matrix_cublas matrix_fast matrix_best
matrix_cublas: matrix_cublas.cu
	$(NVCC) $(NVFLAGS) $< -o $@ -lcublas
clean:
	rm -f matrix_cublas matrix_fast matrix_best results_6_2.csv
.PHONY: all clean

# Part 6.2 search harness: times naive / tiled / every blocked config / cuBLAS in one
# process, checks each against cuBLAS, writes results_6_2.csv. Build line as in the file.
matrix_fast: matrix_fast.cu
	$(NVCC) -O3 -std=c++11 $(NVFLAGS) $< -o $@ -lcublas

# Part 6.2 row for the table: the winning shapes in the standard harness.
matrix_best: matrix_best.cu
	$(NVCC) -O3 -std=c++11 $(NVFLAGS) $< -o $@
