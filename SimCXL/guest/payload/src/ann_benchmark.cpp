#include <faiss/IndexHNSW.h>
#include <faiss/Index.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

int main() {
    const int dim = 128;
    const faiss::idx_t nb = std::getenv("SIMCXL_ANN_VECTORS") ? std::atoll(std::getenv("SIMCXL_ANN_VECTORS")) : 200000;
    const faiss::idx_t nq = std::getenv("SIMCXL_ANN_QUERIES") ? std::atoll(std::getenv("SIMCXL_ANN_QUERIES")) : 1000;
    if (nb < 10 || nq < 1) return 2;
    const int k = 10;

    std::vector<float> database(static_cast<size_t>(nb) * dim);
    std::vector<float> queries(static_cast<size_t>(nq) * dim);

    for (size_t i = 0; i < database.size(); ++i)
        database[i] = static_cast<float>((i * 17) % 1000) / 1000.0f;

    for (size_t i = 0; i < queries.size(); ++i)
        queries[i] = static_cast<float>((i * 31) % 1000) / 1000.0f;

    faiss::IndexHNSWFlat index(dim, 32);
    index.hnsw.efConstruction = 40;
    index.hnsw.efSearch = 64;

    auto build_start = std::chrono::steady_clock::now();
    index.add(nb, database.data());
    auto build_end = std::chrono::steady_clock::now();

    std::vector<faiss::idx_t> labels(static_cast<size_t>(nq) * k);
    std::vector<float> distances(static_cast<size_t>(nq) * k);

    auto start = std::chrono::steady_clock::now();

    index.search(
        nq,
        queries.data(),
        k,
        distances.data(),
        labels.data()
    );

    auto end = std::chrono::steady_clock::now();

    double build_sec =
        std::chrono::duration<double>(build_end - build_start).count();

    double search_sec =
        std::chrono::duration<double>(end - start).count();

    long long checksum = 0;
    for (auto x : labels)
        checksum += x;

    printf("ANN_DIM=%d\n", dim);
    printf("DATABASE_VECTORS=%lld\n", (long long)nb);
    printf("QUERIES=%lld\n", (long long)nq);
    printf("TOPK=%d\n", k);
    printf("BUILD_TIME_SEC=%.6f\n", build_sec);
    printf("SEARCH_TIME_SEC=%.6f\n", search_sec);
    printf("QPS=%.4f\n", nq / search_sec);
    printf("RESULT_CHECKSUM=%lld\n", checksum);

    return 0;
}
