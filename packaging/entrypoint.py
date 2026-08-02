"""The three lines PyInstaller starts the bundle from.

It exists because `flow/__main__.py` cannot be one: PyInstaller runs its entry script as
a top-level `__main__`, and that file is full of relative imports (`from .asr import …`)
which need a package around them. Handed `flow/__main__.py` directly, the bundle builds
cleanly and then dies on the first import at launch — the same failure `--help` used to
print an invocation for, recorded in that file's header.

So the console script's shape is reproduced instead: import the package, call `main()`,
and let its return value be the exit code, exactly as `[project.scripts]` does.
"""

from flow.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
