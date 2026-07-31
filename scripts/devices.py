"""List audio input devices. Confirms a usable mic exists before stage 3 builds on one."""

import sounddevice as sd

print("default input index:", sd.default.device[0])
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        print(
            f"{i:3d}  ch={d['max_input_channels']}  "
            f"sr={int(d['default_samplerate'])}  {d['name'][:55]}"
        )
