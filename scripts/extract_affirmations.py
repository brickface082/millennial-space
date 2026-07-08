"""One-time: extract affirmations from purchased PLR PDF into data/quotes.json."""
import json
import os
import re
import sys

from pypdf import PdfReader

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(
    BASE,
    "data",
    "affirmations-plr",
    "DailyAffirmHandbook_mrr",
    "1 - Ebook",
    "The Daily Affirmation Handbook.pdf",
)
OUT = os.path.join(BASE, "data", "quotes.json")

SPLIT_RE = re.compile(r"\n?\s*(\d{1,3})\.\s+")
SKIP_FRAGMENTS = (
    "table of contents",
    "disclaimer",
    "chapter 1 -",
    "introduction",
    "affirmations for attracting",
    "understanding affirmations",
    "why you should use",
    "how to make affirmations",
)


def clean_segment(text):
    text = re.sub(r"THE DAILY AFFIRMATION HANDBOOK\s*\d+\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(" .")
    return text


def looks_like_affirmation(text):
    lower = text.lower()
    if len(text) < 12 or len(text) > 400:
        return False
    if any(fragment in lower for fragment in SKIP_FRAGMENTS):
        return False
    starters = (
        "i ", "my ", "being ", "the ", "every ", "each ", "today ",
        "living ", "all ", "health ", "wealth ", "happiness ", "success ",
        "abundance ", "money ", "joy ", "love ", "peace ", "confidence ",
        "gratitude ", "positive ", "you ", "we ",
    )
    return lower.startswith(starters)


def main():
    reader = PdfReader(PDF)
    raw = "\n".join((page.extract_text() or "") for page in reader.pages)
    raw = re.sub(r"THE DAILY AFFIRMATION HANDBOOK\s*\n\s*\d+\s*\n", "\n", raw)

    start = raw.find("1. I am full of energy")
    if start < 0:
        start = raw.find("Chapter 1 - Affirmations for Attracting Health")
    end = raw.find("Conclusion", start + 1) if start >= 0 else -1
    if end < 0:
        end = len(raw)
    section = raw[start:end]

    parts = SPLIT_RE.split(section)
    affirmations = []
    for index in range(1, len(parts), 2):
        text = clean_segment(parts[index + 1])
        if looks_like_affirmation(text):
            affirmations.append(text)

    seen = set()
    unique = []
    for item in affirmations:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    quotes = [
        {"text": text, "author": "", "source": "daily-affirmation-handbook-plr"}
        for text in unique
    ]
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(quotes, handle, indent=2, ensure_ascii=False)

    print(f"Extracted {len(quotes)} affirmations -> {OUT}")
    if quotes:
        print(f"Sample: {quotes[0]['text'][:70]}...")


if __name__ == "__main__":
    main()