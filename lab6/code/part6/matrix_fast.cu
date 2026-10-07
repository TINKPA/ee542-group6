// EE 542 Lab 6, Step 6.2 - a matmul kernel that goes past the 16x16 shared-memory tiling.
//
// Build:  nvcc -O3 -std=c++11 matrix_fast.cu -o matrix_fast -lcublas
// Run:    ./matrix_fast                 (N = 512 1024 2048 4096)
//         ./matrix_fast 1024 3000       (any list of sizes)
//
// One run times naive CUDA, the Part 4 tiled kernel, the new kernel and cuBLAS on the
// same inputs, checks every result against cuBLAS, and writes results_6_2.csv.
//
// What the new kernel changes relative to the Part 4 tiled kernel:
//   1. Register blocking. Each thread computes a TM x TN patch of C (up to 64 outputs)
//      instead of one. Per step of k it reads TM + TN values from shared memory and does
//      TM * TN multiply-adds, so the ratio of arithmetic to memory traffic goes from
//      1 FMA per 2 loads to 64 FMAs per 16 loads.
//   2. Bigger output tile (up to 128 x 128 per block), so every value fetched from
//      global memory is reused 128 times instead of 16.
//   3. 128-bit global loads (float4): a quarter of the load instructions.
//   4. A is stored transposed in shared memory, so the inner loop walks both tiles
//      with unit stride.
//   5. Optional strided column ownership: thread t owns columns t, t+16, t+32, ...
//      rather than 8 adjacent ones. That removes shared-memory bank conflicts on the
//      B tile and makes the final writes to C coalesced.
//   6. Tile shape is a template parameter and the program times several shapes per N
//      and keeps the best one, because the best shape depends on the GPU and on N
//      (a 512 x 512 product with 128 x 128 tiles is only 16 blocks, fewer than the
//      L4's 58 SMs).
//   8. (added 2026-10-02 for the L4 run) V4S: the B slab is written to shared memory
//      with one 128-bit store per thread instead of four 32-bit stores, which removes
//      the 4-way bank conflict of the scalar version (Boehm's kernel 6 does this).
//      Timed as extra configurations next to the originals, so both are measured.
//   7. Host side: pinned host buffers for the transfers, which are reported
//      separately so the copy overhead is visible next to the kernel time.

#include <cuda_runtime.h>
#include <cublas_v2.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define CHECK(call)                                                              \
    do {                                                                         \
        cudaError_t e_ = (call);                                                 \
        if (e_ != cudaSuccess) {                                                 \
            fprintf(stderr, "CUDA error: %s (%s:%d)\n", cudaGetErrorString(e_),  \
                    __FILE__, __LINE__);                                         \
            exit(1);                                                             \
        }                                                                        \
    } while (0)

// ---------------------------------------------------------------- Part 2: naive kernel
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

// ---------------------------------------------------------------- Part 4: tiled kernel
#define TILE_WIDTH 16

__global__ void matrixMultiplyTiled(float *A, float *B, float *C, int N) {
    __shared__ float ds_A[TILE_WIDTH][TILE_WIDTH];
    __shared__ float ds_B[TILE_WIDTH][TILE_WIDTH];

    int bx = blockIdx.x; int by = blockIdx.y;
    int tx = threadIdx.x; int ty = threadIdx.y;
    int Row = by * TILE_WIDTH + ty;
    int Col = bx * TILE_WIDTH + tx;

    float Pvalue = 0.0;
    for (int m = 0; m < (N + TILE_WIDTH - 1) / TILE_WIDTH; ++m) {
        if (Row < N && (m * TILE_WIDTH + tx) < N)
            ds_A[ty][tx] = A[Row * N + m * TILE_WIDTH + tx];
        else
            ds_A[ty][tx] = 0.0f;

        if (Col < N && (m * TILE_WIDTH + ty) < N)
            ds_B[ty][tx] = B[(m * TILE_WIDTH + ty) * N + Col];
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

// ---------------------------------------------------------------- Step 6.2: new kernel

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

// ---------------------------------------------------------------- launchers
typedef void (*LaunchFn)(float *, float *, float *, int);

static void launchNaive(float *A, float *B, float *C, int N) {
    dim3 block(16, 16);
    dim3 grid((N + 15) / 16, (N + 15) / 16);
    matrixMultiplyGPU<<<grid, block>>>(A, B, C, N);
}

static void launchTiled(float *A, float *B, float *C, int N) {
    dim3 block(TILE_WIDTH, TILE_WIDTH);
    dim3 grid((N + TILE_WIDTH - 1) / TILE_WIDTH, (N + TILE_WIDTH - 1) / TILE_WIDTH);
    matrixMultiplyTiled<<<grid, block>>>(A, B, C, N);
}

template <int BM, int BN, int BK, int TM, int TN, bool STRIDED, bool V4S = false>
static void launchBlocked(float *A, float *B, float *C, int N) {
    dim3 block((BM / TM) * (BN / TN));
    dim3 grid((N + BN - 1) / BN, (N + BM - 1) / BM);
    matmulBlocked<BM, BN, BK, TM, TN, STRIDED, V4S><<<grid, block>>>(A, B, C, N);
}

static cublasHandle_t g_cublas;

// cuBLAS is column-major. Passing (B, A) computes B^T A^T = (A B)^T in its view,
// which is exactly A B in our row-major layout.
static void launchCublas(float *A, float *B, float *C, int N) {
    const float alpha = 1.0f, beta = 0.0f;
    cublasSgemm(g_cublas, CUBLAS_OP_N, CUBLAS_OP_N, N, N, N, &alpha, B, N, A, N, &beta, C, N);
}

struct Config {
    const char *name;   // BMxBN, k-slab, per-thread patch, column ownership
    LaunchFn fn;
};

static const Config kConfigs[] = {
    {"128x128 k8 8x8 adjacent", launchBlocked<128, 128, 8, 8, 8, false>},
    {"128x128 k8 8x8 strided", launchBlocked<128, 128, 8, 8, 8, true>},
    {"128x128 k16 8x8 strided", launchBlocked<128, 128, 16, 8, 8, true>},
    {"64x64 k8 4x4 strided", launchBlocked<64, 64, 8, 4, 4, true>},
    {"64x64 k16 8x8 strided", launchBlocked<64, 64, 16, 8, 8, true>},
    {"64x128 k16 4x8 strided", launchBlocked<64, 128, 16, 4, 8, true>},
    {"128x128 k8 8x8 strided v4s", launchBlocked<128, 128, 8, 8, 8, true, true>},
    {"128x128 k16 8x8 strided v4s", launchBlocked<128, 128, 16, 8, 8, true, true>},
    {"64x64 k16 8x8 strided v4s", launchBlocked<64, 64, 16, 8, 8, true, true>},
    {"64x128 k16 4x8 strided v4s", launchBlocked<64, 128, 16, 4, 8, true, true>},
};
static const int kNumConfigs = sizeof(kConfigs) / sizeof(kConfigs[0]);

// ---------------------------------------------------------------- timing helpers

// Kernel time in ms, GPU-side (cudaEvent), after one warm-up launch.
// Repeats enough times to cover roughly 300 ms, capped at 20 repetitions.
static float timeMs(LaunchFn fn, float *A, float *B, float *C, int N) {
    cudaEvent_t t0, t1;
    CHECK(cudaEventCreate(&t0));
    CHECK(cudaEventCreate(&t1));
    float ms = 0.0f;

    fn(A, B, C, N);
    CHECK(cudaGetLastError());
    CHECK(cudaDeviceSynchronize());

    CHECK(cudaEventRecord(t0));
    fn(A, B, C, N);
    CHECK(cudaEventRecord(t1));
    CHECK(cudaEventSynchronize(t1));
    CHECK(cudaEventElapsedTime(&ms, t0, t1));

    int reps = ms > 0.0f ? (int)(300.0f / ms) : 20;
    if (reps > 20) reps = 20;
    if (reps > 1) {
        CHECK(cudaEventRecord(t0));
        for (int i = 0; i < reps; ++i) fn(A, B, C, N);
        CHECK(cudaEventRecord(t1));
        CHECK(cudaEventSynchronize(t1));
        CHECK(cudaEventElapsedTime(&ms, t0, t1));
        ms /= reps;
    }
    CHECK(cudaEventDestroy(t0));
    CHECK(cudaEventDestroy(t1));
    return ms;
}

// Largest absolute difference from the reference, relative to the largest reference value.
static float relError(const float *x, const float *ref, size_t n) {
    float maxDiff = 0.0f, maxRef = 0.0f;
    for (size_t i = 0; i < n; ++i) {
        maxDiff = fmaxf(maxDiff, fabsf(x[i] - ref[i]));
        maxRef = fmaxf(maxRef, fabsf(ref[i]));
    }
    return maxRef > 0.0f ? maxDiff / maxRef : maxDiff;
}

// Host -> device for A and B plus device -> host for C, in ms, averaged over 5 rounds.
static float transferMs(float *hA, float *hB, float *hC, float *dA, float *dB, float *dC,
                        size_t bytes) {
    const int reps = 5;
    CHECK(cudaDeviceSynchronize());
    const std::chrono::steady_clock::time_point t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < reps; ++i) {
        CHECK(cudaMemcpy(dA, hA, bytes, cudaMemcpyHostToDevice));
        CHECK(cudaMemcpy(dB, hB, bytes, cudaMemcpyHostToDevice));
        CHECK(cudaMemcpy(hC, dC, bytes, cudaMemcpyDeviceToHost));
    }
    const std::chrono::steady_clock::time_point t1 = std::chrono::steady_clock::now();
    return std::chrono::duration<float, std::milli>(t1 - t0).count() / reps;
}

// ---------------------------------------------------------------- main
int main(int argc, char **argv) {
    std::vector<int> sizes;
    for (int i = 1; i < argc; ++i) sizes.push_back(atoi(argv[i]));
    if (sizes.empty()) {
        const int defaults[] = {512, 1024, 2048, 4096};
        sizes.assign(defaults, defaults + 4);
    }

    cudaDeviceProp prop;
    CHECK(cudaGetDeviceProperties(&prop, 0));
    printf("GPU: %s, %d SMs\n", prop.name, prop.multiProcessorCount);

    if (cublasCreate(&g_cublas) != CUBLAS_STATUS_SUCCESS) {
        fprintf(stderr, "cublasCreate failed\n");
        return 1;
    }

    const int S = (int)sizes.size();
    std::vector<float> tNaive(S), tTiled(S), tFast(S), tBlas(S), tPageable(S), tPinned(S);
    std::vector<int> bestCfg(S);
    const float tol = 1e-4f;
    bool allOk = true;

    for (int s = 0; s < S; ++s) {
        const int N = sizes[s];
        const size_t count = (size_t)N * N;
        const size_t bytes = count * sizeof(float);
        printf("\nN = %d\n", N);

        float *hA, *hB, *hC, *hRef;
        CHECK(cudaMallocHost((void **)&hA, bytes));
        CHECK(cudaMallocHost((void **)&hB, bytes));
        CHECK(cudaMallocHost((void **)&hC, bytes));
        hRef = (float *)malloc(bytes);
        for (size_t i = 0; i < count; ++i) {
            hA[i] = rand() % 100 / 100.0f;
            hB[i] = rand() % 100 / 100.0f;
        }

        float *dA, *dB, *dC;
        CHECK(cudaMalloc((void **)&dA, bytes));
        CHECK(cudaMalloc((void **)&dB, bytes));
        CHECK(cudaMalloc((void **)&dC, bytes));
        CHECK(cudaMemcpy(dA, hA, bytes, cudaMemcpyHostToDevice));
        CHECK(cudaMemcpy(dB, hB, bytes, cudaMemcpyHostToDevice));

        tBlas[s] = timeMs(launchCublas, dA, dB, dC, N);
        CHECK(cudaMemcpy(hRef, dC, bytes, cudaMemcpyDeviceToHost));
        printf("  %-28s %10.3f ms\n", "cuBLAS sgemm", tBlas[s]);

        tNaive[s] = timeMs(launchNaive, dA, dB, dC, N);
        CHECK(cudaMemcpy(hC, dC, bytes, cudaMemcpyDeviceToHost));
        float err = relError(hC, hRef, count);
        allOk = allOk && err < tol;
        printf("  %-28s %10.3f ms   err %.1e %s\n", "naive", tNaive[s], err,
               err < tol ? "ok" : "MISMATCH");

        tTiled[s] = timeMs(launchTiled, dA, dB, dC, N);
        CHECK(cudaMemcpy(hC, dC, bytes, cudaMemcpyDeviceToHost));
        err = relError(hC, hRef, count);
        allOk = allOk && err < tol;
        printf("  %-28s %10.3f ms   err %.1e %s\n", "tiled 16x16", tTiled[s], err,
               err < tol ? "ok" : "MISMATCH");

        tFast[s] = 1e30f;
        bestCfg[s] = 0;
        for (int c = 0; c < kNumConfigs; ++c) {
            CHECK(cudaMemset(dC, 0, bytes));
            const float ms = timeMs(kConfigs[c].fn, dA, dB, dC, N);
            CHECK(cudaMemcpy(hC, dC, bytes, cudaMemcpyDeviceToHost));
            err = relError(hC, hRef, count);
            const bool ok = err < tol;
            allOk = allOk && ok;
            printf("  %-28s %10.3f ms   err %.1e %s\n", kConfigs[c].name, ms, err,
                   ok ? "ok" : "MISMATCH");
            if (ok && ms < tFast[s]) {
                tFast[s] = ms;
                bestCfg[s] = c;
            }
        }

        // Copy overhead: same data from ordinary (pageable) and from pinned host memory.
        float *pA = (float *)malloc(bytes), *pB = (float *)malloc(bytes), *pC = (float *)malloc(bytes);
        memcpy(pA, hA, bytes);
        memcpy(pB, hB, bytes);
        memset(pC, 0, bytes);
        tPageable[s] = transferMs(pA, pB, pC, dA, dB, dC, bytes);
        tPinned[s] = transferMs(hA, hB, hC, dA, dB, dC, bytes);
        printf("  %-28s %10.3f ms\n", "copies, pageable host mem", tPageable[s]);
        printf("  %-28s %10.3f ms\n", "copies, pinned host mem", tPinned[s]);

        free(pA); free(pB); free(pC); free(hRef);
        CHECK(cudaFree(dA)); CHECK(cudaFree(dB)); CHECK(cudaFree(dC));
        CHECK(cudaFreeHost(hA)); CHECK(cudaFreeHost(hB)); CHECK(cudaFreeHost(hC));
    }

    struct Row { const char *name; const std::vector<float> *t; };
    const Row rows[] = {
        {"Naive CUDA (ms)", &tNaive},
        {"Tiled 16x16 CUDA (ms)", &tTiled},
        {"Blocked + float4 CUDA (ms)", &tFast},
        {"cuBLAS (ms)", &tBlas},
        {"Copies, pageable (ms)", &tPageable},
        {"Copies, pinned (ms)", &tPinned},
    };
    const int R = sizeof(rows) / sizeof(rows[0]);

    printf("\n%-28s", "Implementation");
    for (int s = 0; s < S; ++s) printf("  N=%-9d", sizes[s]);
    printf("\n");
    for (int r = 0; r < R; ++r) {
        printf("%-28s", rows[r].name);
        for (int s = 0; s < S; ++s) printf("  %-11.3f", (*rows[r].t)[s]);
        printf("\n");
    }
    printf("%-28s", "Speedup over tiled");
    for (int s = 0; s < S; ++s) printf("  %-11.2f", tTiled[s] / tFast[s]);
    printf("\n%-28s", "Fraction of cuBLAS speed");
    for (int s = 0; s < S; ++s) printf("  %-11.2f", tBlas[s] / tFast[s]);
    printf("\n%-28s", "GFLOP/s, new kernel");
    for (int s = 0; s < S; ++s)
        printf("  %-11.1f", 2.0 * sizes[s] * sizes[s] * sizes[s] / (tFast[s] * 1e6));
    printf("\n");
    for (int s = 0; s < S; ++s)
        printf("Best tile shape at N=%d: %s\n", sizes[s], kConfigs[bestCfg[s]].name);

    FILE *f = fopen("results_6_2.csv", "w");
    if (f) {
        fprintf(f, "N,naive_ms,tiled_ms,blocked_ms,cublas_ms,copies_pageable_ms,copies_pinned_ms,best_config\n");
        for (int s = 0; s < S; ++s)
            fprintf(f, "%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%s\n", sizes[s], tNaive[s], tTiled[s],
                    tFast[s], tBlas[s], tPageable[s], tPinned[s], kConfigs[bestCfg[s]].name);
        fclose(f);
    }

    cublasDestroy(g_cublas);
    if (!allOk) {
        fprintf(stderr, "\nAt least one kernel disagreed with cuBLAS.\n");
        return 1;
    }
    return 0;
}
