# Windows x64 source downloads

Download `flow-windows-x64-sources.zip` from the same GitHub release as
`flow-windows-x64.zip`. The archive contains third-party source distributions,
the FFmpeg vendor build recipe and patches, and the release's pinned input
manifest. Flow's own source and its Windows packaging scripts are available in
the GitHub source archive for the same release tag.

## Speech synthesis

- **Piper 1.8.0** includes a native bridge statically linked to **eSpeak NG**.
  The Piper source distribution contains the bridge and its CMake build
  instructions. CMake pins the included eSpeak NG source to commit
  `724808c5a83f9ef95fdd0db886ba7ba537ff224a`. The eSpeak NG archive includes its
  phoneme and dictionary sources. [Piper build recipe](https://github.com/OHF-Voice/piper1-gpl/blob/v1.8.0/CMakeLists.txt).
- **edge-tts 7.3.1** is included as the original source distribution published
  by its maintainers. [edge-tts release](https://pypi.org/project/edge-tts/7.3.1/).

## Audio decoding

The **PyAV 18.0.0** Windows x64 wheel includes dynamically linked **FFmpeg
8.1.2** and external libraries, including x264 and x265, both licensed under
GPL-2.0-or-later. The vendor patch changes how FFmpeg classifies these
libraries in its build configuration. Flow distributes the combined FFmpeg
and GPL codec binaries under GPL-3.0-or-later. The source
archive includes PyAV, FFmpeg, the codec and header sources, the vendor build
recipe and patches, and the MSYS2 source packages for GCC runtime, libiconv,
winpthreads, and zlib. [PyAV release and source distribution](https://github.com/PyAV-Org/PyAV/releases/tag/v18.0.0).

PyAV's wheel workflow selects the FFmpeg vendor build `8.1.2-1` and uses
`delvewheel` to bundle the DLLs. The vendor archive comes from the build
commit recorded by the successful release workflow. Its workflow and
`scripts/build-ffmpeg.py` describe the Windows MINGW64 build, and
`scripts/pkg.py` lists exact inputs and checksums. [PyAV wheel workflow](https://github.com/PyAV-Org/PyAV/blob/v18.0.0/.github/workflows/tests.yml) · [FFmpeg vendor release run](https://github.com/PyAV-Org/pyav-ffmpeg/actions/runs/28393781929) · [FFmpeg vendor build commit](https://github.com/PyAV-Org/pyav-ffmpeg/tree/a71bf9279f7a4659154b68ba6783e89be460bcd5).

## Executable bootloader

The **PyInstaller 6.22.3** source distribution contains the bootloader C
sources and build instructions. [PyInstaller release](https://pypi.org/project/PyInstaller/6.22.3/).

## Building the source archive

From the root of the Flow checkout at the release tag, run
`uv run --locked python packaging/build_windows_sources.py flow-windows-x64-sources.zip`.
The script reads Python source distribution hashes from `uv.lock` and the
other source archive hashes from `packaging/windows-sources.json`.
