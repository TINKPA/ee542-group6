/*
 * EE542 Lab 6, Part 8: CUDA 2-D convolution kernels, shared by conv_gpu.cu
 * (the standalone executable) and matrix_lib.cu (the Python library).
 *
 * Semantics match conv_cpu.c exactly: an M x M image of unsigned 32-bit
 * pixels, an N x N filter of signed 32-bit integers (N odd, N <= MAXN) with a
 * divisor, true convolution (filter flipped), zero padding, output
 * out[y][x] = min(|sum| / div, 2^32 - 1) accumulated in 64-bit. Integer
 * arithmetic means the GPU result must equal the CPU result bit for bit.
 *
 *   convNaive  one thread per output pixel, the filter in constant memory,
 *              every image read from global memory (L1/L2 do the caching).
 *   convTiled  32 x 32 output tile per block; the tile plus its halo of
 *              radius N/2 is staged in shared memory once, then each thread
 *              reads only shared memory in the N*N loop.
 */
#pragma once
#include <stdint.h>
#include <cuda_runtime.h>

#define CONV_MAXN 31
#define CONV_TILE 32

__constant__ int32_t c_filt[CONV_MAXN * CONV_MAXN];

__device__ __forceinline__ uint32_t conv_finish(int64_t acc, int32_t div) {
    if (acc < 0) acc = -acc;
    acc /= div;
    return acc > 4294967295LL ? 4294967295u : (uint32_t)acc;
}

__global__ void convNaive(const uint32_t *__restrict__ in, uint32_t *__restrict__ out,
                          int M, int N, int32_t div) {
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= M || y >= M) return;
    const int r = N / 2;
    int64_t acc = 0;
    for (int i = 0; i < N; ++i) {
        int yy = y - (i - r);                     // flipped: in[y - (i - r)]
        if (yy < 0 || yy >= M) continue;
        for (int j = 0; j < N; ++j) {
            int xx = x - (j - r);
            if (xx < 0 || xx >= M) continue;
            acc += (int64_t)c_filt[i * N + j] * (int64_t)in[(size_t)yy * M + xx];
        }
    }
    out[(size_t)y * M + x] = conv_finish(acc, div);
}

// Dynamic shared memory: (CONV_TILE + 2r)^2 pixels.
__global__ void convTiled(const uint32_t *__restrict__ in, uint32_t *__restrict__ out,
                          int M, int N, int32_t div) {
    extern __shared__ uint32_t tile[];
    const int r = N / 2;
    const int W = CONV_TILE + 2 * r;              // staged square side
    const int x0 = blockIdx.x * CONV_TILE - r;    // image coords of tile[0][0]
    const int y0 = blockIdx.y * CONV_TILE - r;
    const int tid = threadIdx.y * CONV_TILE + threadIdx.x;

    for (int q = tid; q < W * W; q += CONV_TILE * CONV_TILE) {
        int ty = q / W, tx = q % W;
        int yy = y0 + ty, xx = x0 + tx;
        tile[q] = (yy >= 0 && yy < M && xx >= 0 && xx < M) ? in[(size_t)yy * M + xx] : 0u;
    }
    __syncthreads();

    int x = blockIdx.x * CONV_TILE + threadIdx.x;
    int y = blockIdx.y * CONV_TILE + threadIdx.y;
    if (x >= M || y >= M) return;
    // Output pixel (threadIdx) sits at tile[(threadIdx.y + r)][(threadIdx.x + r)];
    // flipped filter tap (i, j) reads tile[threadIdx.y + r - (i - r)][threadIdx.x + r - (j - r)]
    // = tile[threadIdx.y + 2r - i][threadIdx.x + 2r - j].
    int64_t acc = 0;
    for (int i = 0; i < N; ++i) {
        const uint32_t *row = tile + (threadIdx.y + 2 * r - i) * W + threadIdx.x + 2 * r;
        for (int j = 0; j < N; ++j)
            acc += (int64_t)c_filt[i * N + j] * (int64_t)row[-j];
    }
    out[(size_t)y * M + x] = conv_finish(acc, div);
}

// Host-side helpers used by both the executable and the library.
static inline cudaError_t conv_set_filter(const int32_t *filt, int N) {
    return cudaMemcpyToSymbol(c_filt, filt, (size_t)N * N * sizeof(int32_t));
}
static inline void conv_launch(bool tiled, const uint32_t *d_in, uint32_t *d_out, int M, int N, int32_t div) {
    if (tiled) {
        int r = N / 2, W = CONV_TILE + 2 * r;
        dim3 block(CONV_TILE, CONV_TILE);
        dim3 grid((M + CONV_TILE - 1) / CONV_TILE, (M + CONV_TILE - 1) / CONV_TILE);
        convTiled<<<grid, block, (size_t)W * W * sizeof(uint32_t)>>>(d_in, d_out, M, N, div);
    } else {
        dim3 block(32, 8);
        dim3 grid((M + 31) / 32, (M + 7) / 8);
        convNaive<<<grid, block>>>(d_in, d_out, M, N, div);
    }
}
