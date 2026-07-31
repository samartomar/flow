"""Flow — local English dictation with a talk-to-it refine loop.

Design constraints that shape every module here (see docs/analysis.md):
  R11  the agent CLI is never on the hot path
  R16  three declared dependencies; GUI, hotkeys and injection come from stdlib
  R8   fixed-size buffers, so a long session costs what a short one costs
"""

SAMPLE_RATE = 16_000

# Whisper pads every input to a single 30 s mel window, so decode cost is flat up to
# that boundary and climbs past it (measured: 0.75 s @ 1 s, 0.91 s @ 8 s). Cutting an
# utterance before the boundary is what keeps latency constant in a long session.
MAX_UTTERANCE_SEC = 24.0
