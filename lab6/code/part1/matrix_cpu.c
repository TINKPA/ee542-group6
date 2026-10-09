/*
 * EE542 Lab 6, Part 1: N x N single-precision matrix multiplication on the CPU.
 *
 * Follows the handout's example (triple loop, row-major, clock() timing,
 * N from argv[1]) with three additions that do not change what is measured:
 *   1. srand(1) so every run multiplies the same A and B.
 *   2. A checksum of C is printed, so the compiler cannot discard the
 *      product as dead code and so the GPU versions can be checked
 *      against this result later.
 *   3. clock_gettime(CLOCK_MONOTONIC) wall time is printed next to the
 *      handout's clock() CPU time. For a single-threaded loop the two
 *      agree; they are both kept so the handout's number is still there.
 *
 * Build: gcc matrix_cpu.c -o matrix_cpu -O2     (see Makefile)
 * Run:   ./matrix_cpu 1024
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

void matrixMultiplyCPU(float *A, float *B, float *C, int N) {
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            float sum = 0.0f;
            for (int k = 0; k < N; k++) {
                sum += A[i * N + k] * B[k * N + j];
            }
            C[i * N + j] = sum;
        }
    }
}

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    int N = (argc > 1) ? atoi(argv[1]) : 1024; // allow matrix size as input
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

    double wall0 = now_sec();
    clock_t start = clock();
    matrixMultiplyCPU(A, B, C, N);
    clock_t end = clock();
    double wall1 = now_sec();

    double elapsed = (double)(end - start) / CLOCKS_PER_SEC;
    double checksum = 0.0;
    for (size_t i = 0; i < (size_t)N * N; i++) checksum += C[i];

    printf("CPU execution time (N=%d): %f seconds\n", N, elapsed);
    printf("wall=%.6f cpu=%.6f checksum=%.6e gflops=%.3f\n",
           wall1 - wall0, elapsed, checksum,
           2.0 * N * N * N / (wall1 - wall0) / 1e9);

    free(A); free(B); free(C);
    return 0;
}
