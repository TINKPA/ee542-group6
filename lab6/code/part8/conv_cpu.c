/*
 * EE542 Lab 6, Part 8.1: 2-D convolution on the CPU.
 *
 * out[y][x] = min(|sum_{i,j} f[i][j] * in[y-(i-r)][x-(j-r)]| / div, 2^32-1),
 * r = N/2, zero padding, 64-bit accumulation. The filter is flipped (true
 * convolution); for symmetric filters that is the same as correlation, for
 * Sobel it only changes the sign, which the absolute value removes.
 *
 * Usage: conv_cpu in.bin M filter.txt [out.bin]     timed on a real image
 *        conv_cpu --random M N                      timed on a random image
 * Prints: conv time (M=%d N=%d): %f seconds
 *         wall=.. cpu=.. checksum=.. gmacs=.. M=.. N=..   (one key=value line)
 */
#include "conv_io.h"

void convolveCPU(const uint32_t *in, uint32_t *out, int M, const int32_t *f, int N, int32_t div) {
    const int r = N / 2;
    for (int y = 0; y < M; ++y) {
        for (int x = 0; x < M; ++x) {
            int64_t acc = 0;
            for (int i = 0; i < N; ++i) {
                int yy = y - (i - r);
                if (yy < 0 || yy >= M) continue;
                for (int j = 0; j < N; ++j) {
                    int xx = x - (j - r);
                    if (xx < 0 || xx >= M) continue;
                    acc += (int64_t)f[i * N + j] * (int64_t)in[(size_t)yy * M + xx];
                }
            }
            if (acc < 0) acc = -acc;
            acc /= div;
            out[(size_t)y * M + x] = acc > 4294967295LL ? 4294967295u : (uint32_t)acc;
        }
    }
}

int main(int argc, char **argv) {
    static const char *usage = "usage: conv_cpu in.bin M filter.txt [out.bin] | conv_cpu --random M N\n";
    uint32_t *img; int32_t *filt; int M, N; int32_t div; const char *outpath;
    parse_args(argc, argv, &img, &M, &filt, &N, &div, &outpath, usage);
    uint32_t *out = (uint32_t *)malloc((size_t)M * M * sizeof(uint32_t));
    memset(out, 0, (size_t)M * M * sizeof(uint32_t));   // pages present before timing

    double w0 = now_sec();
    clock_t c0 = clock();
    convolveCPU(img, out, M, filt, N, div);
    clock_t c1 = clock();
    double w1 = now_sec();

    double cpu = (double)(c1 - c0) / CLOCKS_PER_SEC;
    printf("conv time (M=%d N=%d): %f seconds\n", M, N, w1 - w0);
    printf("wall=%.6f cpu=%.6f checksum=%llu gmacs=%.3f M=%d N=%d\n",
           w1 - w0, cpu, checksum_u64(out, M),
           (double)M * M * N * N / (w1 - w0) / 1e9, M, N);
    if (outpath) write_image(outpath, out, M);
    free(img); free(filt); free(out);
    return 0;
}
