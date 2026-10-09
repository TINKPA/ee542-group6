/*
 * EE542 Lab 6, Part 6.1: matrix multiply through cuBLAS.
 *
 * The call is the handout's cublasSgemm with the operands in the order it
 * prints, (d_B, d_A): cuBLAS is column-major, so computing B^T * A^T in its
 * terms yields the row-major product A * B. Host side identical to part2 /
 * part4 (same seed and fill order, split H2D / kernel / D2H timing with
 * cudaEvents, untimed warm-up). cublasCreate is folded into init_ms, since
 * it loads the library's kernels and is paid once per process, not per call.
 *
 * Build: nvcc matrix_cublas.cu -o matrix_cublas -lcublas    (see Makefile)
 * Run:   ./matrix_cublas 1024
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <cuda_runtime.h>
#include <cublas_v2.h>

#define CK(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); \
    exit(1); } } while (0)
#define CB(call) do { cublasStatus_t st = (call); if (st != CUBLAS_STATUS_SUCCESS) { \
    fprintf(stderr, "cuBLAS error %d at %s:%d\n", (int)st, __FILE__, __LINE__); \
    exit(1); } } while (0)

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
    cublasHandle_t handle;
    CB(cublasCreate(&handle));
    double init_ms = (now_sec() - t0) * 1e3;

    float *d_A, *d_B, *d_C;
    CK(cudaMalloc((void **)&d_A, size));
    CK(cudaMalloc((void **)&d_B, size));
    CK(cudaMalloc((void **)&d_C, size));

    const float alpha = 1.0f, beta = 0.0f;

    // Warm-up: cuBLAS picks and loads its kernel on the first call.
    CK(cudaMemcpy(d_A, A, size, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_B, B, size, cudaMemcpyHostToDevice));
    CB(cublasSgemm(handle, CUBLAS_OP_N, CUBLAS_OP_N, N, N, N,
                   &alpha, d_B, N, d_A, N, &beta, d_C, N));
    CK(cudaDeviceSynchronize());

    cudaEvent_t e0, e1, e2, e3;
    CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
    CK(cudaEventCreate(&e2)); CK(cudaEventCreate(&e3));

    double wall0 = now_sec();
    CK(cudaEventRecord(e0));
    CK(cudaMemcpy(d_A, A, size, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_B, B, size, cudaMemcpyHostToDevice));
    CK(cudaEventRecord(e1));
    CB(cublasSgemm(handle,
                   CUBLAS_OP_N, CUBLAS_OP_N,
                   N, N, N,
                   &alpha,
                   d_B, N,
                   d_A, N,
                   &beta,
                   d_C, N));
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
           "checksum=%.6e gflops=%.3f block=cublas\n",
           wall1 - wall0, kernel_ms, h2d_ms, d2h_ms, init_ms, checksum,
           2.0 * N * N * N / (kernel_ms * 1e-3) / 1e9);

    CB(cublasDestroy(handle));
    CK(cudaFree(d_A)); CK(cudaFree(d_B)); CK(cudaFree(d_C));
    free(A); free(B); free(C);
    return 0;
}
