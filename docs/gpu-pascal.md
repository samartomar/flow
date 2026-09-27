# GPU acceleration on pre-Turing NVIDIA cards — what a CUDA major version costs

Written 2026-09-19 from a live investigation on the GTX 1070 development machine.
**Nothing in Flow was changed.** This is the record of what the hardware actually does,
what Flow already gets right, and the one place that will age badly — with the check
that tells you when it has.

Status of every claim below, same grading as [analysis.md](analysis.md):
`CONFIRMED` = verified on this machine · `PLAUSIBLE` = mechanism known, not yet run ·
`SPECULATIVE` = pattern-match only.

---

## 1. Why this came up

FluidVoice — the closest thing to a reference product for the dictation half of Flow —
ships two local engines, and on this machine only one of them can use the GPU. Tracing
why turned up a trap that any local-inference product can fall into, so it is worth
writing down even though Flow does not currently have it.

FluidVoice installs its llama.cpp runtime from `llama-b9870-bin-win-cuda-13.3-x64.zip`.
CUDA 13 dropped Pascal: it requires compute capability **7.5 or newer**. The GTX 1070 is
**CC 6.1**, so `ggml-cuda.dll` never loads and inference silently falls back to
`ggml-cpu-haswell.dll` — all-core AVX2 on the CPU. Meanwhile its *speech* engine
(parakeet) ships CUDA 12 and accelerates on the same card perfectly well. Two engines in
one product, disagreeing about which CUDA generation to target, with no user-visible
explanation for why one is fast and the other pins twelve cores.

`CONFIRMED` — upstream publishes `llama-b9870-bin-win-cuda-12.4-x64.zip` at the *same
build number*, and it does include `sm_61`:

```
Device 0: NVIDIA GeForce GTX 1070, compute capability 6.1, VMM: yes, VRAM: 8191 MiB
load_backend: loaded CUDA backend from ...\cu124\ggml-cuda.dll
```

Filed upstream as altic-dev/FluidVoice
[discussion #987](https://github.com/altic-dev/FluidVoice/discussions/987) and
[issue #988](https://github.com/altic-dev/FluidVoice/issues/988).

**The transferable lesson is not about llama.cpp.** It is that pinning a CUDA major
version silently strands a whole GPU generation, and the failure presents as "the app is
slow" rather than as an error.

## 2. What Flow's stack actually does on this card

Flow does not use llama.cpp or ggml. It is **faster-whisper → CTranslate2**, a different
compiler, a different kernel set, and a different set of constraints. So none of the
above applies directly. What matters is what CTranslate2 reports for itself.

`CONFIRMED`, probed in `.venv` against CTranslate2 4.8.1 / faster-whisper 1.2.1:

```
cuda device count: 1
supported compute types (cuda): {'float32', 'int8', 'int8_float32'}
supported compute types (cpu):  {'float32', 'int8', 'int8_float32'}
```

**`float16` is absent, and that absence is the whole story.** GP104 runs FP16 at 1/64
rate — Pascal's half-precision units were deliberately crippled on consumer parts — so
CTranslate2 correctly refuses to offer it. A Turing or newer card reports `float16` and
`int8_float16`; Ampere adds `bfloat16`. The set above is a Pascal fingerprint.

What Pascal *does* have is **DP4A**: a 4×-rate INT8 dot-product instruction added in
`sm_61` specifically for inference. So on this card `int8` is not a degraded fallback —
it is the only fast path the silicon offers, and it is a genuinely fast one.

`flow/asr.py:473` already defaults to `compute_type="int8"`, and the comment at
`flow/asr.py:49` records it as measured on this machine. That is the correct choice, and
it is correct for a sharper reason than "int8 is small".

## 3. What Flow already gets right

Worth stating explicitly, because these are the things FluidVoice's issue #585 asked for
and Flow shipped first:

| Behaviour | Where | Why it matters |
|---|---|---|
| Probes DLL *loadability*, not device count | `_cuda_probe`, `flow/asr.py:307` | `get_cuda_device_count()` succeeds on machines where the first encode then dies with `Library cublas64_12.dll is not found`. Checking here turns a broken session into a fallback. |
| Degrades to CPU instead of aborting | `except` in `_cuda_probe` | ggml aborts the process on kernel-launch failure. CPU is a working configuration, not a crash. |
| Names *which* check failed | `_cuda_why` / `cuda_reason()` | "no NVIDIA device" and "CUDA runtime not installed" want different actions from the reader. One message for both is what made a 1070 owner conclude the message was simply wrong. |
| Picks `int8` on a card with no usable FP16 | `flow/asr.py:473` | See §2 — DP4A. |

There is no work to do here. The reason this section exists is so that a future reader
does not "fix" one of them.

## 4. The one thing that will age badly

`flow/asr.py:262`:

```python
_CUDA_LIBS = ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn_ops64_9.dll")
```

The CUDA major version is baked into the filenames. This is **coherent today** —
`pyproject.toml` pins `nvidia-cublas-cu12>=12` and `nvidia-cudnn-cu12>=9`, the package
names are themselves CUDA-12-specific, and the DLL names match what those wheels install.
Nothing is broken and nothing needs changing now.

`PLAUSIBLE` — the failure arrives when CTranslate2 ships cu13 wheels and a user installs
them, or arrives on a machine where a cu13 stack is already on `PATH`. All three `CDLL`
calls fail, `_cuda_ok` goes false, and the user is told:

```
GPU found, CUDA runtime not installed: uv pip install -e ".[cuda]"
```

— which is wrong, and sends them to install something they already have. The card is
fine, the runtime is fine, only the *version in the filename* disagrees. That is the same
class of bug as FluidVoice's, arriving from the opposite direction: FluidVoice pinned too
new and stranded old GPUs; Flow would be pinned too old and strand new runtimes.

**Reopen bar.** Change this when either is true:

1. `ctranslate2` publishes a release built against CUDA 13, **or**
2. `nvidia-cublas-cu13` / `nvidia-cudnn-cu13` become the wheels `pip` resolves for a
   supported Python.

**The shape of the fix, when it is time** — not now:

- Glob `cublas64_*.dll` / `cublasLt64_*.dll` / `cudnn_ops64_*.dll` rather than matching
  exact names, and load whichever is found.
- Distinguish *absent* from *version-mismatched* in `_cuda_why`. "Found cublas64_13.dll
  but this build needs 12" is actionable; "not installed" is not.
- Keep the probe. It is the part that makes any of this recoverable.

## 5. Validating a GPU, when you need to

The check that answers "can this machine's card actually do work" in one command, with
no model load and nothing written:

```bash
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count()); print(ctranslate2.get_supported_compute_types('cuda'))"
```

Read it as:

| Output | Means |
|---|---|
| count `0` | No device, or the driver is not loaded. Nothing to configure. |
| count ≥ 1, raises on `get_supported_compute_types` | Device seen, runtime unusable — the case `_cuda_probe` exists to catch. |
| `{'float32', 'int8', 'int8_float32'}` | **Pascal or older.** `int8` is the fast path (DP4A); FP16 is crippled, do not reach for it. |
| set contains `float16` | Turing or newer. `int8_float16` is usually the best default. |
| set contains `bfloat16` | Ampere or newer. |

For the card itself, `nvidia-smi --query-gpu=name,compute_cap,memory.total --format=csv`
gives the compute capability directly — **7.5 is the line** CUDA 13 draws, and the number
that explains most "why is the GPU idle" reports on older hardware.

`nvidia-smi` reporting `CUDA Version: 13.0` is the **driver's ceiling**, not what any
bundled library uses. Reading it as the latter is the single easiest way to misdiagnose
this whole class of problem.

## 6. Reference: this machine

| | |
|---|---|
| GPU | NVIDIA GeForce GTX 1070, 8 GB, Pascal, **CC 6.1** |
| Driver | 582.66 (reports a CUDA 13.0 ceiling) |
| CPU | AMD Ryzen 9 3900X, 12C/24T |
| RAM | 96 GB DDR4-3200 |
| OS | Windows 11 Pro 26200 |
| CTranslate2 | 4.8.1 |
| faster-whisper | 1.2.1 |
| Usable compute types | `float32`, `int8`, `int8_float32` |

One aside that is not a software finding but is worth the sentence: sustained all-core
AVX2 — what a CPU fallback *is* — was tripping this machine's ageing PSU into hard
power-offs, with no bugcheck and no minidump. An ATX 3.0 supply fixed it. On old
hardware the CPU fallback path is not purely a speed ceiling, and "the app crashes my
computer" is a report that can mean this.
