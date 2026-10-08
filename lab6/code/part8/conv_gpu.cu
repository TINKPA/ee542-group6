/*
 * EE542 Lab 6, Part 8.2: the convolution of conv_cpu.c on the GPU.
 *
 * Same command line and file formats as conv_cpu (conv_io.h), plus
 *   --kernel naive|tiled        (default tiled)
 * as the first argument. Host harness as in the matrix programs: untimed
 * warm-up, then H2D / kernel / D2H split with cudaEvents; the output buffer
 * is written once before timing so D2H does not include first-touch faults.
 * The checksum must equal conv_cpu's for the same inputs (integer math).
 *
 * Usage: conv_gpu [--kernel naive|tiled] in.bin M filter.txt [out.bin]
 *        conv_gpu [--kernel naive|tiled] --random M N
 */
#include "conv_io.h"
#include "conv_kernels.cuh"

#define CK(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); \
    exit(1); } } while (0)

int main(int argc, char **argv) {
    static const char *usage = "usage: conv_gpu [--kernel naive|tiled] in.bin M filter.txt [out.bin] | --random M N\n";
    bool tiled = true;
    if (argc >= 3 && strcmp(argv[1], "--kernel") == 0) {
        tiled = strcmp(argv[2], "tiled") == 0;
        if (!tiled && strcmp(argv[2], "naive") != 0) { fprintf(stderr, "%s", usage); return 1; }
        argv += 2; argc -= 2;
    }
    uint32_t *img; int32_t *filt; int M, N; int32_t div; const char *outpath;
    parse_args(argc, argv, &img, &M, &filt, &N, &div, &outpath, usage);
    if (N > CONV_MAXN) { fprintf(stderr, "N > %d not supported\n", CONV_MAXN); return 1; }
    size_t bytes = (size_t)M * M * sizeof(uint32_t);
    uint32_t *out = (uint32_t *)malloc(bytes);
    memset(out, 0, bytes);

    double t0 = now_sec();
    CK(cudaFree(0));
    double init_ms = (now_sec() - t0) * 1e3;

    uint32_t *d_in, *d_out;
    CK(cudaMalloc((void **)&d_in, bytes));
    CK(cudaMalloc((void **)&d_out, bytes));
    CK(conv_set_filter(filt, N));

    // warm-up
    CK(cudaMemcpy(d_in, img, bytes, cudaMemcpyHostToDevice));
    conv_launch(tiled, d_in, d_out, M, N, div);
    CK(cudaGetLastError());
    CK(cudaDeviceSynchronize());

    cudaEvent_t e0, e1, e2, e3;
    CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1)); CK(cudaEventCreate(&e2)); CK(cudaEventCreate(&e3));
    double w0 = now_sec();
    CK(cudaEventRecord(e0));
    CK(cudaMemcpy(d_in, img, bytes, cudaMemcpyHostToDevice));
    CK(cudaEventRecord(e1));
    conv_launch(tiled, d_in, d_out, M, N, div);
    CK(cudaGetLastError());
    CK(cudaEventRecord(e2));
    CK(cudaMemcpy(out, d_out, bytes, cudaMemcpyDeviceToHost));
    CK(cudaEventRecord(e3));
    CK(cudaEventSynchronize(e3));
    double w1 = now_sec();

    float h2d, kern, d2h;
    CK(cudaEventElapsedTime(&h2d, e0, e1)); CK(cudaEventElapsedTime(&kern, e1, e2)); CK(cudaEventElapsedTime(&d2h, e2, e3));

    printf("conv time (M=%d N=%d): %f seconds\n", M, N, kern / 1e3);
    printf("wall=%.6f kernel_ms=%.4f h2d_ms=%.4f d2h_ms=%.4f init_ms=%.1f checksum=%llu gmacs=%.3f M=%d N=%d block=%s\n",
           w1 - w0, kern, h2d, d2h, init_ms, checksum_u64(out, M),
           (double)M * M * N * N / (kern * 1e-3) / 1e9, M, N, tiled ? "tiled32" : "naive32x8");
    if (outpath) write_image(outpath, out, M);
    CK(cudaFree(d_in)); CK(cudaFree(d_out));
    free(img); free(filt); free(out);
    return 0;
}
