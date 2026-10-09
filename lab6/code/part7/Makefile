# EE542 Lab 6 Part 7. Handout: nvcc -Xcompiler -fPIC -shared matrix_lib.cu -o libmatrix.so
# (-O3 -std=c++11 added for the Part 6.2 kernel that is also in the library.)
NVCC    ?= nvcc
NVFLAGS ?=
all: libmatrix.so
libmatrix.so: matrix_lib.cu ../part8/conv_kernels.cuh
	$(NVCC) -O3 -std=c++11 $(NVFLAGS) -Xcompiler -fPIC -shared $< -o $@
clean:
	rm -f libmatrix.so
.PHONY: all clean
