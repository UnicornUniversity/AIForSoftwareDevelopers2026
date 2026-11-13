"""Generate a Czech speech sample with a Microsoft neural voice.

This is the Czech counterpart of ``make_sample.ps1``: the same Prague passage,
translated, synthesised into a clip Whisper Lab can transcribe and
language-detect. ``make_sample.ps1`` uses the Windows SAPI voice, which on this
machine only speaks English, so the Czech clip comes from edge-tts instead --
Microsoft's online neural voices, still synthetic and copyright-clear, but they
need a network connection at generation time.

    .venv/Scripts/python.exe samples/make_sample_cs.py

Writes ``demo2-cs.wav`` and ``demo2-cs.reference.txt`` next to this script.
The reference ``<stem>.reference.txt`` is what ``transcribe.py`` pairs with the
audio for its ``.diff.html`` comparison.

edge-tts is installed for generating samples only and is deliberately absent
from ``requirements.txt`` -- the lab itself does not need it:

    uv pip install --python .venv/Scripts/python.exe edge-tts

PyAV, used here to convert edge-tts's MP3 into a WAV, is already a lab
dependency. The bracketed citation markers from the Wikipedia source are left
out; a synthesiser reads "[20]" aloud as gibberish.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import wave
from pathlib import Path

import av
import edge_tts

SAMPLE_RATE = 24000
DEFAULT_VOICE = "cs-CZ-AntoninNeural"  # the other cs-CZ voice is VlastaNeural

SCRIPT = """
Praha vyrostla z osady, která se táhla od Pražského hradu na severu až k pevnosti
Vyšehrad na jihu, a stala se hlavním městem moderní evropské země. Díky
archeologickým vrstvám hlubokým přes deset metrů slouží město jako vzor pro
zavádění ucelených předpisů na ochranu archeologického dědictví v celé České
republice. Mytická kněžna Libuše prorokuje slávu Prahy. Tato oblast byla osídlena
už v paleolitu. Židovský kronikář David Solomon Ganz s odvoláním na Cyriaka
Spangenberga tvrdil, že město založil roku 1306 před naším letopočtem dávný král
Boyya pod jménem Boihaem. Kolem pátého a čtvrtého století před naším letopočtem se
v oblasti objevil keltský kmen a později zde založil osady, mimo jiné největší
keltské oppidum v Čechách, Závist, na území dnešních Dolních Břežan jižně od Prahy,
a dal kraji jméno Bohemia, což znamená „domov kmene Bojů“. V posledním století před
naším letopočtem Kelty postupně vytlačily germánské kmeny – Markomani, Kvádové,
Langobardi a možná i Svébové – a někteří proto kladou sídlo markomanského krále
Marobuda do Závisti. V okolí dnešní Prahy uvádí mapa římského geografa Ptolemaia ze
druhého století germánské město zvané Casurgis.
"""


async def synthesize(text: str, voice: str, rate: str) -> bytes:
    """Return the MP3 bytes edge-tts streams back for ``text``."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError(f"edge-tts returned no audio for voice {voice!r}")
    return bytes(audio)


def write_wav(mp3: bytes, path: Path) -> float:
    """Decode ``mp3`` and write 24 kHz mono 16-bit PCM; return the duration."""
    frames = 0
    with av.open(io.BytesIO(mp3), mode="r") as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            for frame in container.decode(stream):
                for resampled in resampler.resample(frame):
                    out.writeframes(resampled.to_ndarray().tobytes())
                    frames += resampled.samples
            for resampled in resampler.resample(None):
                out.writeframes(resampled.to_ndarray().tobytes())
                frames += resampled.samples
    return frames / SAMPLE_RATE


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the Czech demo sample.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("demo2-cs.wav"),
        help="WAV to write (default: samples/demo2-cs.wav)",
    )
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="edge-tts voice name")
    parser.add_argument(
        "--rate", default="+0%", help="speaking rate, e.g. -10%% (default: +0%%)"
    )
    args = parser.parse_args()

    text = " ".join(SCRIPT.split())

    try:
        mp3 = asyncio.run(synthesize(text, args.voice, args.rate))
    except Exception as error:  # network, unknown voice, throttling
        print(f"error: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    duration = write_wav(mp3, args.output)

    reference = args.output.with_suffix(".reference.txt")
    reference.write_text(text, encoding="utf-8")

    print(f"Voice: {args.voice} ({args.rate})")
    print(f"Wrote {args.output} ({duration:.1f} s)")
    print(f"Wrote {reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
