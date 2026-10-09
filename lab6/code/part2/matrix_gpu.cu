/*
 * EE542 Lab 6, Part 2: naive CUDA matrix multiply, one thread per output element.
 *
 * The kernel is the handout's, unchanged. The host side mirrors matrix_cpu.c:
 * same srand(1) and the same fill order, so the checksum must equal the CPU's
 * for the same N. Timing is split with cudaEvents into H2D copy, kernel, and
 * D2H copy, because the lab's Part 5 asks about the overhead of the GPU as a
 * peripheral and that question cannot be answered from one total. An untimed
 * warm-up launch absorbs context creation and module load; its cost is
 * reported separately as init_ms.
 *
 * Build: nvcc matrix_gpu.cu -o matrix_gpu           (see Makefile)
 * Run:   ./matrix_gpu 1024
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <cuda_runtime.h>

#define CK(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); \
    exit(1); } } while (0)

__global__ void matrixMultiplyGPU(float *A, float *B, float *C, int N) {
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;

    if (row < N && col < N) {
        float sum = 0.0f;
        for (int k = 0; k < N; k++) {
            sum += A[row * N + k] * B[k * N + col];
        }
        C[row * N + col] = sum;
    }
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

    // Context creation, measured on its own so it does not pollute the copies.
    double t0 = now_sec();
    CK(cudaFree(0));
    double init_ms = (now_sec() - t0) * 1e3;

    float *d_A, *d_B, *d_C;
    CK(cudaMalloc((void **)&d_A, size));
    CK(cudaMalloc((void **)&d_B, size));
    CK(cudaMalloc((void **)&d_C, size));

    dim3 block(16, 16);
    dim3 grid((N + block.x - 1) / block.x, (N + block.y - 1) / block.y);

    // Warm-up: first launch pays module load; not what the handout wants timed.
    CK(cudaMemcpy(d_A, A, size, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_B, B, size, cudaMemcpyHostToDevice));
    matrixMultiplyGPU<<<grid, block>>>(d_A, d_B, d_C, N);
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
    matrixMultiplyGPU<<<grid, block>>>(d_A, d_B, d_C, N);
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
