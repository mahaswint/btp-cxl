import os
import time
import torch
from transformers import AutoTokenizer, AutoModel

MODEL = "google-bert/bert-base-uncased"
MODEL_PATH = "/opt/btp/models/bert"
BATCH_SIZE = int(os.environ.get('SIMCXL_BERT_BATCH', '8'))
SEQ_LEN = int(os.environ.get('SIMCXL_BERT_SEQUENCE', '128'))
WARMUP = int(os.environ.get('SIMCXL_BERT_WARMUP', '10'))
ITERATIONS = int(os.environ.get('SIMCXL_BERT_ITERATIONS', '100'))
THREADS = int(os.environ.get("OMP_NUM_THREADS", "8"))

torch.set_num_threads(THREADS)
torch.set_num_interop_threads(1)

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
model = AutoModel.from_pretrained(
    MODEL_PATH,
    local_files_only=True,
    torch_dtype=torch.float32
)
model.eval()

text = (
    "This is a fixed benchmark sentence used for measuring "
    "CPU memory behavior during BERT inference."
)

inputs = tokenizer(
    [text] * BATCH_SIZE,
    padding="max_length",
    truncation=True,
    max_length=SEQ_LEN,
    return_tensors="pt",
)

with torch.inference_mode():
    for _ in range(WARMUP):
        _ = model(**inputs)

start = time.perf_counter()

with torch.inference_mode():
    for _ in range(ITERATIONS):
        outputs = model(**inputs)

elapsed = time.perf_counter() - start

sequences = BATCH_SIZE * ITERATIONS
print(f"BERT_MODEL={MODEL}")
print(f"BATCH_SIZE={BATCH_SIZE}")
print(f"SEQ_LEN={SEQ_LEN}")
print(f"WARMUP={WARMUP}")
print(f"ITERATIONS={ITERATIONS}")
print(f"TOTAL_TIME_SEC={elapsed:.6f}")
print(f"SEQUENCES={sequences}")
print(f"SEQUENCES_PER_SEC={sequences / elapsed:.4f}")
print(f"AVG_BATCH_TIME_MS={(elapsed / ITERATIONS) * 1000:.4f}")

# Force output use so the computation is not optimized away.
print(f"OUTPUT_CHECKSUM={outputs.last_hidden_state.sum().item():.6f}")
