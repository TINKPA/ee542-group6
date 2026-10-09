/* EE542 Lab 6, Part 8: file formats shared by conv_cpu.c and conv_gpu.cu.
 *
 * Image  .bin : M*M little-endian uint32, row-major (M given on the command line).
 * Filter .txt : first line "N div", then N*N signed integers, row-major.
 * Random mode : --random M N makes a deterministic (srand(1)) image with 16-bit
 *               pixels and a random filter with coefficients in [-8, 8], div 1,
 *               so the timing sweep needs no files.
 */
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static uint32_t *read_image(const char *path, int M) {
    size_t n = (size_t)M * M;
    uint32_t *img = (uint32_t *)malloc(n * sizeof(uint32_t));
    FILE *f = fopen(path, "rb");
    if (!f || !img || fread(img, sizeof(uint32_t), n, f) != n) {
        fprintf(stderr, "cannot read %zu pixels from %s\n", n, path); exit(1);
    }
    fclose(f);
    return img;
}

static int32_t *read_filter(const char *path, int *N, int32_t *div) {
    FILE *f = fopen(path, "r");
    if (!f || fscanf(f, "%d %d", N, div) != 2 || *N < 1 || (*N % 2) == 0 || *div == 0) {
        fprintf(stderr, "bad filter file %s (need odd N and nonzero div)\n", path); exit(1);
    }
    int32_t *filt = (int32_t *)malloc((size_t)(*N) * (*N) * sizeof(int32_t));
    for (int i = 0; i < (*N) * (*N); ++i)
        if (fscanf(f, "%d", &filt[i]) != 1) { fprintf(stderr, "short filter %s\n", path); exit(1); }
    fclose(f);
    return filt;
}

static void write_image(const char *path, const uint32_t *img, int M) {
    FILE *f = fopen(path, "wb");
    if (!f || fwrite(img, sizeof(uint32_t), (size_t)M * M, f) != (size_t)M * M) {
        fprintf(stderr, "cannot write %s\n", path); exit(1);
    }
    fclose(f);
}

static uint32_t *random_image(int M) {
    size_t n = (size_t)M * M;
    uint32_t *img = (uint32_t *)malloc(n * sizeof(uint32_t));
    srand(1);
    for (size_t i = 0; i < n; ++i) img[i] = (uint32_t)(rand() % 65536);
    return img;
}

static int32_t *random_filter(int N) {
    int32_t *filt = (int32_t *)malloc((size_t)N * N * sizeof(int32_t));
    for (int i = 0; i < N * N; ++i) filt[i] = rand() % 17 - 8;
    return filt;
}

static unsigned long long checksum_u64(const uint32_t *img, int M) {
    unsigned long long s = 0;
    for (size_t i = 0; i < (size_t)M * M; ++i) s += img[i];
    return s;
}

/* Parses the common command line. Returns 1 on --random. Sets img, M, filt, N, div, out path. */
static int parse_args(int argc, char **argv, uint32_t **img, int *M, int32_t **filt, int *N,
                      int32_t *div, const char **outpath, const char *usage) {
    if (argc >= 4 && strcmp(argv[1], "--random") == 0) {
        *M = atoi(argv[2]); *N = atoi(argv[3]);
        if (*M <= 0 || *N <= 0 || (*N % 2) == 0) { fprintf(stderr, "%s", usage); exit(1); }
        *img = random_image(*M); *filt = random_filter(*N); *div = 1; *outpath = NULL;
        return 1;
    }
    if (argc < 4) { fprintf(stderr, "%s", usage); exit(1); }
    *M = atoi(argv[2]);
    *img = read_image(argv[1], *M);
    *filt = read_filter(argv[3], N, div);
    *outpath = argc >= 5 ? argv[4] : NULL;
    return 0;
}
