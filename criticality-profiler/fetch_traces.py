"""Fetch only a decompressed prefix, never the full multi-GB trace."""
import argparse
import concurrent.futures
import hashlib
import json
import lzma
from pathlib import Path
import urllib.request

FILES = ["605.mcf_s-1554B.champsimtrace.xz",
         "619.lbm_s-2676B.champsimtrace.xz",
         "623.xalancbmk_s-165B.champsimtrace.xz"]

def fetch(name, records, root):
    url = "https://zenodo.org/records/10960004/files/" + name + "?download=1"
    target = root / name.replace(".xz", ".bin")
    manifest = target.with_suffix(".json")
    if target.exists() and manifest.exists() and target.stat().st_size == records * 64:
        expected = json.loads(manifest.read_text())["prefix_sha256"]
        if hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            return f"Verified existing {target.name}"
    remaining = records * 64
    digest = hashlib.sha256()
    decompressor = lzma.LZMADecompressor()
    compressed = 0
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as out:
        while remaining:
            if decompressor.needs_input:
                chunk = response.read(256 * 1024)
                compressed += len(chunk)
                if not chunk:
                    raise RuntimeError("Trace ended before requested prefix")
            else:
                chunk = b""
            data = decompressor.decompress(chunk, max_length=min(remaining, 1024 * 1024))
            out.write(data)
            digest.update(data)
            remaining -= len(data)
            if decompressor.eof and remaining:
                raise RuntimeError("Trace ended before requested prefix")
    manifest.write_text(json.dumps({"source_url": url, "source_record": 10960004,
        "records": records, "record_bytes": 64, "decompressed_bytes": records * 64,
        "compressed_bytes_fetched": compressed, "prefix_sha256": digest.hexdigest(),
        "note": "Prefix only; full archive checksum is not verified."}, indent=2) + "\n")
    return f"Fetched {target.name}: {records} instructions"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=1_200_000)
    parser.add_argument("--trace-name", choices=FILES)
    parser.add_argument("--output-dir", default="traces")
    args = parser.parse_args()
    if args.records <= 0:
        parser.error("records must be positive")
    root = Path(__file__).resolve().parent / args.output_dir
    root.mkdir(exist_ok=True, parents=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch, name, args.records, root)
                   for name in ([args.trace_name] if args.trace_name else FILES)]
        for future in concurrent.futures.as_completed(futures):
            print(future.result(), flush=True)
