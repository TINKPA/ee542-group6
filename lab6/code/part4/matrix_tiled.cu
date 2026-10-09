/*
 * EE542 Lab 6, Part 4: shared-memory tiled CUDA matrix multiply.
 *
 * The kernel is the handout's matrixMultiplyTiled, unchanged, TILE_WIDTH 16.
 * The host side is identical to part2/matrix_gpu.cu (same seed, same fill
 * order, same split timing of H2D / kernel / D2H with cudaEvents, same untimed
 * warm-up), so the two binaries differ only in the kernel and their rows can
 * sit in one table. TILE_WIDTH can be overridden at compile time
 * (-DTILE_WIDTH=32) for the Part 6 exploration; the output line records it.
 *
 * Build: nvcc matrix_tiled.cu -o matrix_tiled          (see Makefile)
 * Run:   ./matrix_tiled 1024
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <cuda_runtime.h>

#ifndef TILE_WIDTH
#define TILE_WIDTH 16
#endif

#define CK(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); \
    exit(1); } } while (0)

__global__ void matrixMultiplyTiled(float *A, float *B, float *C, int N) {
    __shared__ float ds_A[TILE_WIDTH][TILE_WIDTH];
    __shared__ float ds_B[TILE_WIDTH][TILE_WIDTH];

    int bx = blockIdx.x; int by = blockIdx.y;
    int tx = threadIdx.x; int ty = threadIdx.y;
    int Row = by * TILE_WIDTH + ty;
    int Col = bx * TILE_WIDTH + tx;

    float Pvalue = 0.0;
    for (int m = 0; m < (N + TILE_WIDTH - 1) / TILE_WIDTH; ++m) {
        if (Row < N && (m*TILE_WIDTH+tx) < N)
            ds_A[ty][tx] = A[Row * N + m * TILE_WIDTH + tx];
        else
            ds_A[ty][tx] = 0.0f;

        if (Col < N && (m*TILE_WIDTH+ty) < N)
            ds_B[ty][tx] = B[(m*TILE_WIDTH + ty) * N + Col];
        else
            ds_B[ty][tx] = 0.0f;

        __syncthreads();

        for (int k = 0; k < TILE_WIDTH; ++k)
            Pvalue += ds_A[ty][k] * ds_B[k][tx];
        __syncthreads();
    }

    if (Row < N && Col < N)
        C[Row * N + Col] = Pvalue;
}

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    int N = (argc > 1) ? atoi(argv[1]) : 1024;
    if (N <= 0) { fprintf(stderr, "usage: %s N\n", argv[0]); return 1; }
    size_t size = (size_t)N * N * sizeof(float);

    float *A = (float *)malloc(size);
    float *B = (float *)malloc(size);
    float *C = (float *)malloc(size);
    if (!A || !B || !C) { fprintf(stderr, "malloc failed for N=%d\n", N); return 1; }

    srand(1);
    for (size_t i = 0; i < (size_t)N * N; i++) {
        A[i] = rand() % 100 / 100.0f;
        B[i] = rand() % 100 / 100.0f;
    }

    double t0 = now_sec();
    CK(cudaFree(0));
    double init_ms = (now_sec() - t0) * 1e3;

    float *d_A, *d_B, *d_C;
    CK(cudaMalloc((void **)&d_A, size));
    CK(cudaMalloc((void **)&d_B, size));
    CK(cudaMalloc((void **)&d_C, size));

    dim3 block(TILE_WIDTH, TILE_WIDTH);
    dim3 grid((N + TILE_WIDTH - 1) / TILE_WIDTH, (N + TILE_WIDTH - 1) / TILE_WIDTH);

    CK(cudaMemcpy(d_A, A, size, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_B, B, size, cudaMemcpyHostToDevice));
    matrixMultiplyTiled<<<grid, block>>>(d_A, d_B, d_C, N);
    CK(cudaGetLastError());
    CK(cudaDeviceSynchronize());

    cudaEvent_t e0, e1, e2, e3;
    CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
    CK(cudaEventCreate(&e2)); CK(cudaEventCreate(&e3));

    double wall0 = now_sec();
    CK(cudaEventRecord(e0));
    CK(cudaMemcpy(d_A, A, size, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_B, B, size, cudaMemcpyHostToDevice));
    CK(cudaEventRecord(e1));
    matrixMultiplyTiled<<<grid, block>>>(d_A, d_B, d_C, N);
    CK(cudaGetLastError());
    CK(cudaEventRecord(e2));
    CK(cudaMemcpy(C, d_C, size, cudaMemcpyDeviceToHost));
    CK(cudaEventRecord(e3));
    CK(cudaEventSynchronize(e3));
    double wall1 = now_sec();

    float h2d_ms, kernel_ms, d2h_ms;
    CK(cudaEventElapsedTime(&h2d_ms, e0, e1));
    CK(cudaEventElapsedTime(&kernel_ms, e1, e2));
    CK(cudaEventElapsedTime(&d2h_ms, e2, e3));

    double checksum = 0.0;
    for (size_t i = 0; i < (size_t)N * N; i++) checksum += C[i];

    printf("GPU execution time (N=%d): %f seconds\n", N, kernel_ms / 1e3);
    printf("wall=%.6f kernel_ms=%.4f h2d_ms=%.4f d2h_ms=%.4f init_ms=%.1f "
           "checksum=%.6e gflops=%.3f block=%dx%d\n",
           wall1 - wall0, kernel_ms, h2d_ms, d2h_ms, init_ms, checksum,
           2.0 * N * N * N / (kernel_ms * 1e-3) / 1e9, block.x, block.y);

    CK(cudaFree(d_A)); CK(cudaFree(d_B)); CK(cudaFree(d_C));
    free(A); free(B); free(C);
    return 0;
}
