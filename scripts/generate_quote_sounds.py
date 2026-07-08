"""Generate movie-quote alert audio via Kokoro TTS (not Microsoft edge-tts).

Setup:
  pip install kokoro-onnx soundfile numpy
  python scripts/download_kokoro_models.py
  python scripts/generate_quote_sounds.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import MOVIE_QUOTE_PACK
from kokoro_tts import synthesize_wav, models_available

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "sounds", "quotes")


def main():
    if not models_available():
        print("Kokoro models missing. Run: python scripts/download_kokoro_models.py")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Generating {len(MOVIE_QUOTE_PACK)} Kokoro quote sounds -> {OUT_DIR}")

    for key, meta in MOVIE_QUOTE_PACK.items():
        dest = os.path.join(OUT_DIR, f"{key}.wav")
        voice = meta.get("voice", "am_adam")
        text = meta["text"]
        wav = synthesize_wav(text, voice=voice, speed=1.0)
        with open(dest, "wb") as f:
            f.write(wav)
        size = os.path.getsize(dest)
        print(f"  [OK] {key}.wav ({size} bytes) — {meta['label']} [{voice}]")

    print("Done. Quote pack uses Kokoro WAV (alert-sounds.js falls back to .mp3 if present).")


if __name__ == "__main__":
    main()