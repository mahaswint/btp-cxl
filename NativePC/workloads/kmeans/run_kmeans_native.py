import time
import numpy as np
from sklearn.cluster import KMeans

SEED = 42
N_SAMPLES = 200000
N_FEATURES = 32
N_CLUSTERS = 32
N_INIT = 1
MAX_ITER = 20

rng = np.random.default_rng(SEED)
X = rng.random((N_SAMPLES, N_FEATURES), dtype=np.float32)

model = KMeans(
    n_clusters=N_CLUSTERS,
    n_init=N_INIT,
    max_iter=MAX_ITER,
    random_state=SEED,
    algorithm="lloyd",
)

start = time.perf_counter()
model.fit(X)
elapsed = time.perf_counter() - start

print(f"KMEANS_SAMPLES={N_SAMPLES}")
print(f"KMEANS_FEATURES={N_FEATURES}")
print(f"KMEANS_CLUSTERS={N_CLUSTERS}")
print(f"KMEANS_MAX_ITER={MAX_ITER}")
print(f"TIME_SEC={elapsed:.6f}")
print(f"ITERATIONS={model.n_iter_}")
print(f"INERTIA={model.inertia_:.6f}")
print(f"LABEL_CHECKSUM={int(model.labels_.sum())}")
