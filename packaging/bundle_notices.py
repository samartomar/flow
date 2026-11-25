"""Copy the installed wheels' legal notices beside the Windows executable."""
from importlib.metadata import distributions
from pathlib import Path
from shutil import copyfile
import sys


def bundle(destination):
    packaging = Path(__file__).resolve().parent
    for name in ("THIRD-PARTY-NOTICES.md", "THIRD-PARTY-SOURCES.md"):
        copyfile(packaging / name, destination / name)
    copyfile(packaging.parent / "LICENSE", destination / "LICENSE")
    found = set()
    for dist in distributions():
        name = dist.metadata["Name"]
        for item in dist.files or ():
            filename = item.name.upper()
            if not any(filename.startswith(prefix) for prefix in
                       ("LICENSE", "LICENCE", "COPYING", "NOTICE", "THIRDPARTYNOTICES")):
                continue
            if ".." in item.parts or item.is_absolute():
                continue
            source = Path(dist.locate_file(item))
            if source.is_file():
                target = destination / "licenses" / name / item
                target.parent.mkdir(parents=True, exist_ok=True)
                copyfile(source, target)
                found.add(name.lower().replace("_", "-"))
    missing = {"piper-tts", "edge-tts", "av"} - found
    if missing:
        raise RuntimeError(f"Missing bundled license texts for {sorted(missing)}")


if __name__ == "__main__":
    bundle(Path(sys.argv[1]))
