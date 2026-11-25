"""Build the Windows release's third-party source archive from pinned inputs."""

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
from urllib.request import urlopen
import zipfile

PACKAGING = Path(__file__).resolve().parent
LOCKED_PACKAGES = {
    "av": "18.0.0",
    "edge-tts": "7.3.1",
    "piper-tts": "1.8.0",
    "pyinstaller": "6.22.3",
}


def download(source, directory, source_dir):
    target = directory / source["filename"]
    cached = source_dir / target.name if source_dir else None
    if cached is not None and cached.is_file():
        shutil.copyfile(cached, target)
    else:
        with urlopen(source["url"], timeout=90) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
    with target.open("rb") as downloaded:
        actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
    if actual != source["sha256"]:
        raise ValueError(f"SHA-256 mismatch for {source['url']}: {actual}")
    return target


def build(output, source_dir=None):
    manifest_path = PACKAGING / "windows-sources.json"
    sources = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock_path = PACKAGING.parent / "uv.lock"
    with lock_path.open("rb") as file:
        packages = {
            package["name"]: package
            for package in tomllib.load(file)["package"]
            if package["name"] in LOCKED_PACKAGES
        }
    for name, version in LOCKED_PACKAGES.items():
        package = packages[name]
        if package["version"] != version:
            raise ValueError(f"Update Windows source provenance for {name} {package['version']}")
        sdist = package["sdist"]
        sources.append({
            "filename": sdist["url"].rsplit("/", 1)[1],
            "url": sdist["url"],
            "sha256": sdist["hash"].removeprefix("sha256:"),
        })
    with tempfile.TemporaryDirectory(dir=output.absolute().parent) as temp:
        directory = Path(temp)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            downloads = list(pool.map(lambda source: download(source, directory, source_dir), sources))
        archive_path = directory / output.name
        with zipfile.ZipFile(archive_path, "w") as archive:
            for path in (PACKAGING / "THIRD-PARTY-SOURCES.md", manifest_path, lock_path, *downloads):
                archive.write(path, path.name)
        archive_path.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-dir", type=Path, help="reuse local archives with matching hashes")
    args = parser.parse_args()
    build(args.output, args.source_dir)
