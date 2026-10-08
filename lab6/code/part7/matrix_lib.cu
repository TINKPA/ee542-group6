/*
 * EE542 Lab 6, Part 7: the matrix multiply as a shared library for Python.
 *
 * gpu_matrix_multiply       the handout's function, verbatim: Part 4 tiled kernel
 *                           (TILE_WIDTH 16), allocate / copy in / launch / sync /
 *                           copy out / free, all inside the call.
 * gpu_matrix_multiply_fast  same interface, Part 6.2 register-blocked kernel
 *                           (tile shape chosen by N as in matrix_best.cu).
 * gpu_last_timing(out[4])   milliseconds spent inside the last call: alloc+free,
 *                           host-to-device, kernel, device-to-host. Lets the
 *                           Python side see where a call's wall time goes.
 *
 * Build: nvcc -Xcompiler -fPIC -shared matrix_lib.cu -o libmatrix.so   (see Makefile)
 */
#include <cuda_runtime.h>
#include <stdio.h>
#include <stdint.h>
#include "../part8/conv_kernels.cuh"   // Part 8.3: the convolution kernels, verbatim

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

// Exposed C function for Python
extern "C" void gpu_matrix_multiply(float *h_A, float *h_B, float *h_C, int N) {
    size_t size = N * N * sizeof(float);
    float *d_A, *d_B, *d_C;

    cudaMalloc((void**)&d_A, size);
    cudaMalloc((void**)&d_B, size);
    cudaMalloc((void**)&d_C, size);

    cudaMemcpy(d_A, h_A, size, cudaMemcpyHostToDevice);
    cudaMemcpy(d_B, h_B, size, cudaMemcpyHostToDevice);

    dim3 dimBlock(TILE_WIDTH, TILE_WIDTH);
    dim3 dimGrid((N + TILE_WIDTH - 1) / TILE_WIDTH, (N + TILE_WIDTH - 1) / TILE_WIDTH);

    matrixMultiplyTiled<<<dimGrid, dimBlock>>>(d_A, d_B, d_C, N);
    cudaDeviceSynchronize();

    cudaMemcpy(h_C, d_C, size, cudaMemcpyDeviceToHost);

    cudaFree(d_A); cudaFree(d_B); cudaFree(d_C);
}

// ---------------------------------------------------------------- Part 6.2 kernel, verbatim from matrix_fast.cu
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

// ---------------------------------------------------------------- timed variants
static float g_last[4] = {0, 0, 0, 0};   // alloc+free, h2d, kernel, d2h (ms)

static void multiply_timed(float *h_A, float *h_B, float *h_C, int N, bool fast) {
    size_t size = (size_t)N * N * sizeof(float);
    float *d_A, *d_B, *d_C;
    cudaEvent_t e[6];
    for (int i = 0; i < 6; ++i) cudaEventCreate(&e[i]);

    cudaEventRecord(e[0]);
    cudaMalloc((void**)&d_A, size);
    cudaMalloc((void**)&d_B, size);
    cudaMalloc((void**)&d_C, size);
    cudaEventRecord(e[1]);
    cudaMemcpy(d_A, h_A, size, cudaMemcpyHostToDevice);
    cudaMemcpy(d_B, h_B, size, cudaMemcpyHostToDevice);
    cudaEventRecord(e[2]);
    if (fast) {
        if (N < 3072) launchBlocked<64, 64, 16, 8, 8, true, true>(d_A, d_B, d_C, N);
        else          launchBlocked<128, 128, 16, 8, 8, true, true>(d_A, d_B, d_C, N);
    } else {
        dim3 dimBlock(TILE_WIDTH, TILE_WIDTH);
        dim3 dimGrid((N + TILE_WIDTH - 1) / TILE_WIDTH, (N + TILE_WIDTH - 1) / TILE_WIDTH);
        matrixMultiplyTiled<<<dimGrid, dimBlock>>>(d_A, d_B, d_C, N);
    }
    cudaEventRecord(e[3]);
    cudaDeviceSynchronize();
    cudaMemcpy(h_C, d_C, size, cudaMemcpyDeviceToHost);
    cudaEventRecord(e[4]);
    cudaFree(d_A); cudaFree(d_B); cudaFree(d_C);
    cudaEventRecord(e[5]);
    cudaEventSynchronize(e[5]);

    float alloc, h2d, kern, d2h, fr;
    cudaEventElapsedTime(&alloc, e[0], e[1]);
    cudaEventElapsedTime(&h2d,   e[1], e[2]);
    cudaEventElapsedTime(&kern,  e[2], e[3]);
    cudaEventElapsedTime(&d2h,   e[3], e[4]);
    cudaEventElapsedTime(&fr,    e[4], e[5]);
    g_last[0] = alloc + fr; g_last[1] = h2d; g_last[2] = kern; g_last[3] = d2h;
    for (int i = 0; i < 6; ++i) cudaEventDestroy(e[i]);
}

extern "C" void gpu_matrix_multiply_timed(float *h_A, float *h_B, float *h_C, int N) {
    multiply_timed(h_A, h_B, h_C, N, false);
}
extern "C" void gpu_matrix_multiply_fast(float *h_A, float *h_B, float *h_C, int N) {
    multiply_timed(h_A, h_B, h_C, N, true);
}
extern "C" void gpu_last_timing(float *out) {
    for (int i = 0; i < 4; ++i) out[i] = g_last[i];
}
extern "C" const char *gpu_device_name(void) {
    static cudaDeviceProp p; cudaGetDeviceProperties(&p, 0); return p.name;
}

// ---------------------------------------------------------------- Part 8.3: convolution exports
#define CK_(call) do { cudaError_t e_ = (call); if (e_ != cudaSuccess) { \
    fprintf(stderr, "libmatrix: CUDA error %s at %s:%d\n", cudaGetErrorString(e_), __FILE__, __LINE__); \
    return -1; } } while (0)

struct ConvImage { uint32_t *d_in; uint32_t *d_out; int M; };
static ConvImage g_imgs[16];
static int g_nimgs = 0;

static int conv_run(ConvImage &im, const int32_t *filt, int N, int32_t div, uint32_t *out,
                    float alloc_ms) {
    if (N < 1 || N > CONV_MAXN || (N % 2) == 0 || div == 0) return -2;
    size_t bytes = (size_t)im.M * im.M * sizeof(uint32_t);
    cudaEvent_t e0, e1, e2;
    CK_(cudaEventCreate(&e0)); CK_(cudaEventCreate(&e1)); CK_(cudaEventCreate(&e2));
    CK_(cudaEventRecord(e0));
    CK_(conv_set_filter(filt, N));
    CK_(cudaEventRecord(e1));
    conv_launch(true, im.d_in, im.d_out, im.M, N, div);
    CK_(cudaGetLastError());
    CK_(cudaEventRecord(e2));
    CK_(cudaDeviceSynchronize());
    double t0_ = 0; (void)t0_;
    cudaEvent_t e3; CK_(cudaEventCreate(&e3));
    CK_(cudaMemcpy(out, im.d_out, bytes, cudaMemcpyDeviceToHost));
    CK_(cudaEventRecord(e3)); CK_(cudaEventSynchronize(e3));
    float f2k, kern, d2h;
    CK_(cudaEventElapsedTime(&f2k, e0, e1)); CK_(cudaEventElapsedTime(&kern, e1, e2)); CK_(cudaEventElapsedTime(&d2h, e2, e3));
    g_last[0] = alloc_ms; g_last[1] += f2k; g_last[2] = kern; g_last[3] = d2h;
    cudaEventDestroy(e0); cudaEventDestroy(e1); cudaEventDestroy(e2); cudaEventDestroy(e3);
    return 0;
}

extern "C" int gpu_conv_upload(const uint32_t *img, int M) {
    if (g_nimgs >= 16 || M <= 0) return -3;
    ConvImage im; im.M = M;
    size_t bytes = (size_t)M * M * sizeof(uint32_t);
    cudaEvent_t e0, e1, e2;
    CK_(cudaEventCreate(&e0)); CK_(cudaEventCreate(&e1)); CK_(cudaEventCreate(&e2));
    CK_(cudaEventRecord(e0));
    CK_(cudaMalloc((void **)&im.d_in, bytes));
    CK_(cudaMalloc((void **)&im.d_out, bytes));
    CK_(cudaEventRecord(e1));
    CK_(cudaMemcpy(im.d_in, img, bytes, cudaMemcpyHostToDevice));
    CK_(cudaEventRecord(e2)); CK_(cudaEventSynchronize(e2));
    float a, h; CK_(cudaEventElapsedTime(&a, e0, e1)); CK_(cudaEventElapsedTime(&h, e1, e2));
    g_last[0] = a; g_last[1] = h; g_last[2] = 0; g_last[3] = 0;
    g_imgs[g_nimgs] = im;
    return g_nimgs++;
}

extern "C" int gpu_conv_apply(int handle, const int32_t *filt, int N, int32_t div, uint32_t *out) {
    if (handle < 0 || handle >= g_nimgs || !g_imgs[handle].d_in) return -3;
    g_last[1] = 0;
    return conv_run(g_imgs[handle], filt, N, div, out, 0.0f);
}

extern "C" int gpu_conv_free(int handle) {
    if (handle < 0 || handle >= g_nimgs || !g_imgs[handle].d_in) return -3;
    CK_(cudaFree(g_imgs[handle].d_in)); CK_(cudaFree(g_imgs[handle].d_out));
    g_imgs[handle].d_in = g_imgs[handle].d_out = NULL;
    return 0;
}

extern "C" int gpu_convolve(const uint32_t *img, int M, const int32_t *filt, int N, int32_t div, uint32_t *out) {
    int h = gpu_conv_upload(img, M);
    if (h < 0) return h;
    float alloc = g_last[0], h2d = g_last[1];
    g_last[1] = h2d;
    int rc = conv_run(g_imgs[h], filt, N, div, out, alloc);
    cudaEvent_t e0, e1; cudaEventCreate(&e0); cudaEventCreate(&e1);
    cudaEventRecord(e0);
    gpu_conv_free(h);
    cudaEventRecord(e1); cudaEventSynchronize(e1);
    float fr; cudaEventElapsedTime(&fr, e0, e1);
    g_last[0] = alloc + fr;
    g_nimgs = h;   // one-shot: hand the slot back
    return rc;
}
