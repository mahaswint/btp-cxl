#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>

int main(int argc, char **argv) {
    size_t mb = (argc > 1) ? strtoull(argv[1], NULL, 10) : 512;
    size_t n = (mb * 1024ULL * 1024ULL) / sizeof(uint64_t);
    uint64_t *a = aligned_alloc(64, n * sizeof(uint64_t));
    if (!a) { perror("aligned_alloc"); return 1; }

    for (size_t i = 0; i < n; ++i) a[i] = (uint64_t)i;

    volatile uint64_t sum = 0;
    for (int pass = 0; pass < 8; ++pass) {
        for (size_t i = 0; i < n; i += 8) {
            sum += a[i];
            a[i] += 1;
        }
    }

    printf("pilot_sum=%llu\n", (unsigned long long)sum);
    free(a);
    return 0;
}
