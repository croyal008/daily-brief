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

def female_voices(key: str, region: str, skip: set) -> list:
    """Every natural-sounding US English female voice on the account (HD and multilingual ones)."""
    import json
    import urllib.request
    req = urllib.request.Request(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
                                 headers={"Ocp-Apim-Subscription-Key": key})
    voices = json.load(urllib.request.urlopen(req, timeout=30))
    picks = []
    for v in voices:
        short = v.get("ShortName", "")
        if v.get("Locale") != "en-US" or v.get("Gender") != "Female":
            continue
        if not ("DragonHD" in short or "Multilingual" in short):
            continue
        name = short.replace("en-US-", "").replace(":DragonHDLatestNeural", "-hd").replace("MultilingualNeural", "")
        name = name.replace("DragonHDLatestNeural", "-hd").replace("Neural", "").lower()
        if name in skip:
            continue
        picks.append((name, short, ""))
    print("Voices found:", ", ".join(p[0] for p in picks))
    return picks[:16]


out = Path(__file__).resolve().parent.parent / "docs" / "samples"
out.mkdir(parents=True, exist_ok=True)
key, region = os.environ["AZURE_SPEECH_KEY"], os.environ["AZURE_SPEECH_REGION"]
for name, voice, style in female_voices(key, region, skip={"ava", "ava-hd"}):
    try:
        audio, sr = AzureVoice(key, region, voice, style=style).create(TEXT)
        sf.write(out / f"{name}.mp3", audio, sr, format="MP3")
        print(f"ok   {name:14} {voice}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name:14} {voice}: {e}")
