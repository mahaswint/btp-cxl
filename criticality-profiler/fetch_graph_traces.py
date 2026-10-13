"""Read ZIP directories remotely and fetch selected trace prefixes only."""
import argparse
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path
import time
import urllib.request
import zipfile

RECORD = 20043527

class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.downloaded = 0
        self.cache_start = -1
        self.cache_data = b""
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
            self.length = int(r.headers["Content-Length"])

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.length + offset
        if self.pos < 0:
            raise ValueError("Negative seek")
        return self.pos

    def tell(self):
        return self.pos

    def read(self, size=-1):
        size = min(self.length - self.pos, size if size >= 0 else self.length - self.pos)
        if size <= 0:
            return b""
        if size > 8 * 1024 * 1024:
            raise ValueError("Refusing a large archive read")
        if self.cache_start <= self.pos and self.pos + size <= self.cache_start + len(self.cache_data):
            offset = self.pos - self.cache_start
            data = self.cache_data[offset:offset + size]
            self.pos += size
            return data
        fetch_size = min(self.length - self.pos, max(size, 1024 * 1024))
        end = self.pos + fetch_size - 1
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    if r.status != 206:
                        raise ValueError("Server did not honor byte ranges; full archive not downloaded")
                    data = r.read(fetch_size)
                    self.downloaded += len(data)
                if len(data) != fetch_size:
                    raise RuntimeError("Short range read")
                break
            except (OSError, RuntimeError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        self.cache_start = self.pos
        self.cache_data = data
        self.pos += size
        return data[:size]

def run(archive, member, records, listing, allow_short=False):
    url = f"https://zenodo.org/records/{RECORD}/files/{archive}?download=1"
    remote = RemoteZip(url)
    with zipfile.ZipFile(remote) as z:
        entries = z.infolist()
        if listing:
            for e in entries:
                if not e.is_dir():
                    print(e.filename, e.file_size, flush=True)
            return
        if not member:
            raise ValueError("--member required; use --list first")
        entry = z.getinfo(member)
        root = Path(__file__).resolve().parent / "traces" / "graph"
        root.mkdir(parents=True, exist_ok=True)
        name = archive.replace("_traces.zip", "") + "_" + Path(member).name
        for suffix in (".xz", ".gz"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
        target = root / (name + (".full.bin" if records is None else ".bin"))
        manifest = target.with_suffix(".json")
        if target.exists() and manifest.exists() and (records is None or target.stat().st_size == records * 64):
            saved = json.loads(manifest.read_text())
            with target.open("rb") as existing:
                existing_hash = hashlib.file_digest(existing, "sha256").hexdigest()
            if existing_hash == saved["prefix_sha256"] and (records is not None or saved.get("full_trace")):
                print("Verified existing", target.name, flush=True)
                return
        digest = hashlib.sha256()
        remaining = records * 64 if records is not None else None
        actual_bytes=0
        eof_reached=False
        temporary = target.with_suffix(".bin.partial")
        with z.open(entry) as raw:
            source = lzma.LZMAFile(raw) if member.endswith(".xz") else gzip.GzipFile(fileobj=raw) if member.endswith(".gz") else raw
            with source, temporary.open("wb") as out:
                while remaining is None or remaining:
                    chunk = source.read(1024 * 1024 if remaining is None else min(remaining, 1024 * 1024))
                    if not chunk:
                        eof_reached=True
                        if allow_short or records is None:
                            break
                        raise RuntimeError("Selected trace is too short")
                    out.write(chunk)
                    digest.update(chunk)
                    actual_bytes+=len(chunk)
                    if remaining is not None:
                        remaining -= len(chunk)
            if records is None and not raw.closed:
                # Consume the ZIP member to verify its CRC as well as XZ integrity.
                while raw.read(1024*1024):
                    pass
        if not actual_bytes or actual_bytes%64:
            raise RuntimeError("Empty or truncated instruction records")
        temporary.replace(target)
        manifest.write_text(json.dumps({"source_url": url, "source_record": RECORD,
            "archive_member": member, "member_uncompressed_bytes": entry.file_size,
            "records": actual_bytes//64, "requested_records": records, "record_bytes": 64, "decompressed_bytes": actual_bytes,
            "prefix_sha256": digest.hexdigest(), "archive_bytes_fetched": remote.downloaded,
            "full_trace": records is None and eof_reached,
            "note": "Full member decoded to EOF; XZ integrity and ZIP member CRC checked." if records is None else
                "Only a trace prefix was fetched; full ZIP/member checksum is not verified."}, indent=2) + "\n")
        print("Fetched", target.name, actual_bytes//64, "instructions", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", choices=[f"{name}_traces.zip" for name in ("bc", "bfs", "sssp", "tc", "pr", "cc")], required=True)
    parser.add_argument("--member")
    parser.add_argument("--records", type=int, default=1_200_000)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--allow-short", action="store_true", help="Keep complete records if the real trace ends early")
    parser.add_argument("--full", action="store_true", help="Decode the complete selected member to EOF into a separate .full.bin")
    args = parser.parse_args()
    if args.records <= 0:
        parser.error("records must be positive")
    run(args.archive, args.member, None if args.full else args.records, args.list, args.allow_short)
