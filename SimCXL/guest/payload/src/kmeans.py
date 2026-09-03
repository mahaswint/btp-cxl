import time
import os
import numpy as np
from sklearn.cluster import KMeans

SEED = 42
N_SAMPLES = int(os.environ.get('SIMCXL_KMEANS_SAMPLES', '200000'))
N_FEATURES = int(os.environ.get('SIMCXL_KMEANS_FEATURES', '32'))
N_CLUSTERS = int(os.environ.get('SIMCXL_KMEANS_CLUSTERS', '32'))
N_INIT = 1
MAX_ITER = int(os.environ.get('SIMCXL_KMEANS_ITERATIONS', '20'))

rng = np.random.default_rng(SEED)
X = rng.random((N_SAMPLES, N_FEATURES), dtype=np.float32)

model = KMeans(
    n_clusters=N_CLUSTERS,
    n_init=N_INIT,
    max_iter=MAX_ITER,
    random_state=SEED,
    # sklearn 0.24 in the Python 3.6 guest calls Lloyd's algorithm "full".
    algorithm="full",
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
