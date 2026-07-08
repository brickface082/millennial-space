"""Download Kokoro ONNX model files for local TTS (quotes + user soundboard)."""
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "static", "models", "kokoro")
FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, url in FILES.items():
        dest = os.path.join(OUT, name)
        if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
            print(f"  [skip] {name}")
            continue
        print(f"  Downloading {name}...")
        urllib.request.urlretrieve(url, dest)
        print(f"  [OK] {name} ({os.path.getsize(dest)} bytes)")
    print(f"Models ready in {OUT}")


if __name__ == "__main__":
    main()