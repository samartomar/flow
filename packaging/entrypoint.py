"""The three lines PyInstaller starts the bundle from.

It exists because `flow/__main__.py` cannot be one: PyInstaller runs its entry script as
a top-level `__main__`, and that file is full of relative imports (`from .asr import …`)
which need a package around them. Handed `flow/__main__.py` directly, the bundle builds
cleanly and then dies on the first import at launch — the same failure `--help` used to
print an invocation for, recorded in that file's header.

So the console script's shape is reproduced instead: import the package, call `main()`,
and let its return value be the exit code, exactly as `[project.scripts]` does.
"""

import sys

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--install-cuda-runtime":
        from pathlib import Path

        from flow.cuda_setup import install

        install(Path(sys.argv[2]), Path(sys.executable).parent)
        raise SystemExit(0)
    from flow.__main__ import main

    raise SystemExit(main())
