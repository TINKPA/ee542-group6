/*
 * EE542 Lab 6, Part 6.2: the register-blocked, float4-vectorized kernel from
 * matrix_fast.cu as a standalone program with the SAME host harness as
 * part2/part4/part6 (same seed, same fill order, single timed launch after one
 * warm-up, H2D / kernel / D2H split with cudaEvents), so its row in the Part 5
 * table has the same methodology as the others. The kernel code is copied
 * verbatim from matrix_fast.cu (see that file for the explanation of each
 * optimization); only the tile shape is fixed here, chosen per N from the
 * search run on the L4 (data/raw/fast_b417302b9409.log, 2026-10-02):
 *   N <  3072 : 64x64 tile, BK 16, 8x8 per thread, strided columns, float4 smem
 *   N >= 3072 : 128x128 tile, BK 16, 8x8 per thread, strided columns, float4 smem
 *
 * Build: nvcc -O3 -std=c++11 matrix_best.cu -o matrix_best   (see Makefile)
 * Run:   ./matrix_best 1024
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <cuda_runtime.h>

#define CK(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); \
    exit(1); } } while (0)

// Four consecutive floats of row r starting at column c (c is always a multiple of 4).
// Anything past the edge of the matrix reads as zero, so N can be any size.
// The single 128-bit load needs 16-byte alignment, which holds when N % 4 == 0;
// otherwise fall back to scalar loads.
__device__ __forceinline__ float4 load4(const float *M, int r, int c, int N, bool vec) {
    float4 v = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
    if (r >= N || c >= N) return v;
    const float *p = M + (size_t)r * N + c;
    if (vec) return *reinterpret_cast<const float4 *>(p);
    v.x = p[0];
    if (c + 1 < N) v.y = p[1];
    if (c + 2 < N) v.z = p[2];
    if (c + 3 < N) v.w = p[3];
    return v;
}

// One block computes a BM x BN tile of C, walking k in slabs of BK.
// One thread computes a TM x TN patch of that tile and keeps it in registers.
// Block size is (BM / TM) * (BN / TN) threads, launched as a 1-D block.
template <int BM, int BN, int BK, int TM, int TN, bool STRIDED, bool V4S = false>
__global__ void matmulBlocked(const float *__restrict__ A, const float *__restrict__ B,
                              float *__restrict__ C, int N) {
    static_assert(BM % TM == 0 && BN % TN == 0, "thread patch must divide the tile");
    static_assert(BK % 4 == 0 && BN % 4 == 0, "float4 loads need multiples of 4");

    __shared__ __align__(16) float As[BK * BM];   // transposed: As[k * BM + m]
    __shared__ __align__(16) float Bs[BK * BN];   //             Bs[k * BN + n]

    const int NT = (BM / TM) * (BN / TN);
    const int tid = threadIdx.x;
    const int tRow = tid / (BN / TN);
    const int tCol = tid % (BN / TN);
    const int rowBase = blockIdx.y * BM;
    const int colBase = blockIdx.x * BN;
    const bool vec = (N % 4 == 0);

    // The fixed-size loops below are fully unrolled so that acc, regA and regB
    // live in registers rather than in per-thread local memory.
    float acc[TM * TN];
    #pragma unroll
    for (int i = 0; i < TM * TN; ++i) acc[i] = 0.0f;
    float regA[TM];
    float regB[TN];

    for (int k0 = 0; k0 < N; k0 += BK) {
        // A slab: BM rows x BK columns, stored transposed.
        for (int q = tid; q < BM * BK / 4; q += NT) {
            const int r = q / (BK / 4);
            const int c = (q % (BK / 4)) * 4;
            const float4 v = load4(A, rowBase + r, k0 + c, N, vec);
            As[(c + 0) * BM + r] = v.x;
            As[(c + 1) * BM + r] = v.y;
            As[(c + 2) * BM + r] = v.z;
            As[(c + 3) * BM + r] = v.w;
        }
        // B slab: BK rows x BN columns.
        for (int q = tid; q < BK * BN / 4; q += NT) {
            const int r = q / (BN / 4);
            const int c = (q % (BN / 4)) * 4;
            const float4 v = load4(B, k0 + r, colBase + c, N, vec);
            if (V4S) {
                *reinterpret_cast<float4 *>(&Bs[r * BN + c]) = v;
            } else {
                Bs[r * BN + c + 0] = v.x;
                Bs[r * BN + c + 1] = v.y;
                Bs[r * BN + c + 2] = v.z;
                Bs[r * BN + c + 3] = v.w;
            }
        }
        __syncthreads();

        for (int k = 0; k < BK; ++k) {
            #pragma unroll
            for (int i = 0; i < TM; ++i)
                regA[i] = As[k * BM + tRow * TM + i];
            #pragma unroll
            for (int j = 0; j < TN; ++j)
                regB[j] = Bs[k * BN + (STRIDED ? tCol + j * (BN / TN) : tCol * TN + j)];
            #pragma unroll
            for (int i = 0; i < TM; ++i) {
                #pragma unroll
                for (int j = 0; j < TN; ++j)
                    acc[i * TN + j] += regA[i] * regB[j];
            }
        }
        __syncthreads();
    }

    #pragma unroll
    for (int i = 0; i < TM; ++i) {
        const int r = rowBase + tRow * TM + i;
        #pragma unroll
        for (int j = 0; j < TN; ++j) {
            const int c = colBase + (STRIDED ? tCol + j * (BN / TN) : tCol * TN + j);
            if (r < N && c < N) C[(size_t)r * N + c] = acc[i * TN + j];
        }
    }
}

template <int BM, int BN, int BK, int TM, int TN, bool STRIDED, bool V4S>
static void launchBlocked(float *A, float *B, float *C, int N) {
    dim3 block((BM / TM) * (BN / TN));
    dim3 grid((N + BN - 1) / BN, (N + BM - 1) / BM);
    matmulBlocked<BM, BN, BK, TM, TN, STRIDED, V4S><<<grid, block>>>(A, B, C, N);
}

static const char *bestName(int N) { return N < 3072 ? "64x64k16-8x8" : "128x128k16-8x8"; }

static void launchBest(float *A, float *B, float *C, int N) {
    if (N < 3072) launchBlocked<64, 64, 16, 8, 8, true, true>(A, B, C, N);
    else          launchBlocked<128, 128, 16, 8, 8, true, true>(A, B, C, N);
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

    CK(cudaMemcpy(d_A, A, size, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_B, B, size, cudaMemcpyHostToDevice));
    launchBest(d_A, d_B, d_C, N);
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
    launchBest(d_A, d_B, d_C, N);
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
           "checksum=%.6e gflops=%.3f block=%s\n",
           wall1 - wall0, kernel_ms, h2d_ms, d2h_ms, init_ms, checksum,
           2.0 * N * N * N / (kernel_ms * 1e-3) / 1e9, bestName(N));

    CK(cudaFree(d_A)); CK(cudaFree(d_B)); CK(cudaFree(d_C));
    free(A); free(B); free(C);
    return 0;
}
