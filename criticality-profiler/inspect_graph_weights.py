"""Inspect the authors' region weights without extracting archive paths."""
import io
import json
from pathlib import Path
import tarfile
import urllib.request

url = "https://zenodo.org/records/20043527/files/weights.tar.gz?download=1"
with urllib.request.urlopen(url, timeout=60) as response:
    data = response.read(1024 * 1024)
weights = {}
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    for member in archive:
        if member.isfile():
            if member.size > 1024 * 1024:
                raise RuntimeError("Unexpectedly large weight file")
            content = archive.extractfile(member).read().decode("utf-8")
            weights[member.name] = content
            if any(name in member.name.lower() for name in ("bc", "tc")):
                print(member.name, content[:4000], flush=True)
target = Path(__file__).resolve().parent / "traces" / "graph" / "published_weights.json"
target.write_text(json.dumps({"source_url": url, "files": weights}, indent=2) + "\n")
