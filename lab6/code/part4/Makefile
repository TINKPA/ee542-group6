# EE542 Lab 6 Part 4. nvcc matrix_tiled.cu -o matrix_tiled; TILE=32 for a wider tile.
NVCC    ?= nvcc
NVFLAGS ?=
TILE    ?= 16
all: matrix_tiled
matrix_tiled: matrix_tiled.cu
	$(NVCC) $(NVFLAGS) -DTILE_WIDTH=$(TILE) $< -o $@
clean:
	rm -f matrix_tiled
.PHONY: all clean
