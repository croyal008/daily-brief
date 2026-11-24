#!/usr/bin/env python3
"""Record the same short sample in several Azure voices, to compare by ear (docs/samples/)."""
import os
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from podcast import AzureVoice  # noqa: E402

TEXT = ("Morning. It's Tuesday, November 24th, and this is your Daily Brief. Grab your coffee, I'll keep it quick. "
        "First up, your teams, and the Spurs went to Sacramento and did not mess around. 123 to 107 over the Kings. "
        "Stephon Castle was everywhere: 28 points, 8 rebounds and 11 assists. One rebound shy of a triple-double, "
        "which is like leaving the bar one drink short of a legendary story. "
        "Next, Thanksgiving dinner. Some people are hosting fewer guests, or bailing on hosting entirely. Which, "
        "if you've ever had to seat your uncle next to your other uncle, might be the real savings.")

VOICES = [
    ("ava", "en-US-AvaMultilingualNeural", ""),
    ("emma", "en-US-EmmaMultilingualNeural", ""),
    ("jenny-chatty", "en-US-JennyNeural", "chat"),
    ("andrew", "en-US-AndrewMultilingualNeural", ""),
    ("brian", "en-US-BrianMultilingualNeural", ""),
    ("ava-hd", "en-US-Ava:DragonHDLatestNeural", ""),
    ("andrew-hd", "en-US-Andrew:DragonHDLatestNeural", ""),
]

out = Path(__file__).resolve().parent.parent / "docs" / "samples"
out.mkdir(parents=True, exist_ok=True)
key, region = os.environ["AZURE_SPEECH_KEY"], os.environ["AZURE_SPEECH_REGION"]
for name, voice, style in VOICES:
    try:
        audio, sr = AzureVoice(key, region, voice, style=style).create(TEXT)
        sf.write(out / f"{name}.mp3", audio, sr, format="MP3")
        print(f"ok   {name:14} {voice}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name:14} {voice}: {e}")
