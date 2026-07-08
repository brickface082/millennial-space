"""Kokoro TTS helper — offline speech synthesis (no Microsoft edge-tts)."""
import base64
import io
import os

BASEDIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASEDIR, "static", "models", "kokoro")
ONNX_PATH = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
VOICES_PATH = os.path.join(MODEL_DIR, "voices-v1.0.bin")

KOKORO_VOICES = [
    ("af_heart", "Heart (female)"),
    ("af_bella", "Bella (female)"),
    ("af_sarah", "Sarah (female)"),
    ("af_nicole", "Nicole (female)"),
    ("am_adam", "Adam (male)"),
    ("am_michael", "Michael (male)"),
    ("bf_emma", "Emma (British female)"),
    ("bm_george", "George (British male)"),
]

_engine = None


def models_available():
    return os.path.isfile(ONNX_PATH) and os.path.isfile(VOICES_PATH)


def get_engine():
    global _engine
    if _engine is None:
        if not models_available():
            raise RuntimeError(
                "Kokoro model files missing. Run: python scripts/download_kokoro_models.py"
            )
        from kokoro_onnx import Kokoro
        _engine = Kokoro(ONNX_PATH, VOICES_PATH)
    return _engine


def synthesize_wav(text, voice="af_heart", speed=1.0):
    import soundfile as sf
    engine = get_engine()
    samples, sample_rate = engine.create(
        text.strip(), voice=voice, speed=float(speed), lang="en-us"
    )
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()


def wav_to_data_uri(wav_bytes):
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    return f"data:audio/wav;base64,{b64}"


def synthesize_data_uri(text, voice="af_heart", speed=1.0):
    return wav_to_data_uri(synthesize_wav(text, voice, speed))