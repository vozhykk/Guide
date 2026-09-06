#!/usr/bin/env python3
"""
Озвучивает stories.json в mp3 и складывает файлы туда, откуда их берут
оба приложения.

    pip install requests
    export TTS_KEY="ваш-ключ"
    python3 tools/make_audio.py --engine elevenlabs --voice <voice_id>

Раскладка на выходе:

    app/src/main/assets/audio/manifest.json
    app/src/main/assets/audio/<id>/000.mp3   ← название + завязка
    app/src/main/assets/audio/<id>/001.mp3   ← первая глава
    ...
    web/audio/…                              ← та же папка, копия

Файл, который уже озвучен и не менялся, второй раз не генерируется:
рядом лежит .cache с хешами текста. Правите одну главу — платите за одну главу.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Нужен requests:  pip install requests")

ROOT = Path(__file__).resolve().parent.parent
STORIES = ROOT / "app/src/main/assets/stories.json"
OUT = ROOT / "app/src/main/assets/audio"
WEB_OUT = ROOT / "web/audio"
CACHE = OUT / ".cache.json"

# ── та же нормализация, что в приложении: римские цифры и сокращения ──
ORD_GEN = ("", "первого", "второго", "третьего", "четвёртого", "пятого", "шестого",
           "седьмого", "восьмого", "девятого", "десятого", "одиннадцатого",
           "двенадцатого", "тринадцатого", "четырнадцатого", "пятнадцатого",
           "шестнадцатого", "семнадцатого", "восемнадцатого", "девятнадцатого",
           "двадцатого", "двадцать первого")
ORD_PRE = ("", "первом", "втором", "третьем", "четвёртом", "пятом", "шестом",
           "седьмом", "восьмом", "девятом", "десятом", "одиннадцатом",
           "двенадцатом", "тринадцатом", "четырнадцатом", "пятнадцатом",
           "шестнадцатом", "семнадцатом", "восемнадцатом", "девятнадцатом",
           "двадцатом", "двадцать первом")
ORD_NOM = ("", "первый", "второй", "третий", "четвёртый", "пятый", "шестой",
           "седьмой", "восьмой", "девятый", "десятый", "одиннадцатый",
           "двенадцатый", "тринадцатый", "четырнадцатый", "пятнадцатый",
           "шестнадцатый", "семнадцатый", "восемнадцатый", "девятнадцатый",
           "двадцатый", "двадцать первый")

RZYM = re.compile(r"\b([IVXLC]{1,6})\b(\s*[–—-]\s*([IVXLC]{1,6})\b)?(\s*(вв\.|в\.|век[а-яё]*))?")


def _roman(s):
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    n = 0
    for i, ch in enumerate(s):
        a = v.get(ch)
        if a is None:
            return 0
        b = v.get(s[i + 1], 0) if i + 1 < len(s) else 0
        n += -a if a < b else a
    return n


def normalize(text):
    def sub(m):
        a, b, tail = _roman(m.group(1)), m.group(3), (m.group(5) or "")
        if not 1 <= a <= 21 or not tail:
            return m.group(0)
        form = ORD_PRE if tail in ("веке", "веках") else ORD_NOM if tail == "век" else ORD_GEN
        word = "века" if tail == "в." else "веков" if tail == "вв." else tail
        b = _roman(b) if b else 0
        nums = f"{form[a]} и {form[b]}" if 1 <= b <= 21 else form[a]
        return f"{nums} {word}"

    t = RZYM.sub(sub, text)
    for a, b in (("т. н.", "так называемый"), ("ок. ", "около "),
                 ("«", ""), ("»", ""), ("—", ","), (" – ", ", "), ("…", ".")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


# ── движки ───────────────────────────────────────────────────────────
def elevenlabs(text, key, voice, **_):
    """Самый живой результат. voice — id голоса из вашего кабинета."""
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                               "style": 0.30, "use_speaker_boost": True},
        }, timeout=180)
    r.raise_for_status()
    return r.content


def openai(text, key, voice, **_):
    """voice: onyx / ash / echo — мужские."""
    r = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gpt-4o-mini-tts", "voice": voice or "onyx",
              "input": text, "response_format": "mp3",
              "instructions": "Спокойный мужской голос экскурсовода. "
                              "Неторопливо, с паузами, без пафоса."},
        timeout=180)
    r.raise_for_status()
    return r.content


def yandex(text, key, voice, **_):
    """voice: filipp / ermil — мужские. Ключ — API-key сервисного аккаунта."""
    r = requests.post(
        "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
        headers={"Authorization": f"Api-Key {key}"},
        data={"text": text, "lang": "ru-RU", "voice": voice or "filipp",
              "emotion": "neutral", "speed": "0.95", "format": "mp3"},
        timeout=180)
    r.raise_for_status()
    return r.content


def google(text, key, voice, **_):
    """voice: ru-RU-Wavenet-D — мужской."""
    r = requests.post(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
        json={"input": {"text": text},
              "voice": {"languageCode": "ru-RU", "name": voice or "ru-RU-Wavenet-D"},
              "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.95,
                              "pitch": -1.0}},
        timeout=180)
    r.raise_for_status()
    return base64.b64decode(r.json()["audioContent"])


ENGINES = {"elevenlabs": elevenlabs, "openai": openai,
           "yandex": yandex, "google": google}


# ── сборка ───────────────────────────────────────────────────────────
def pieces(place):
    """Что именно озвучиваем: вступление, потом каждая глава целиком."""
    yield f"{place['title']}. {place['hook']}"
    for c in place["chapters"]:
        yield f"{c['h']}. {c['t']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=ENGINES, default="elevenlabs")
    ap.add_argument("--voice", default="", help="id или имя голоса")
    ap.add_argument("--key", default=os.environ.get("TTS_KEY", ""))
    ap.add_argument("--only", default="", help="озвучить одну точку по id")
    ap.add_argument("--dry-run", action="store_true",
                    help="ничего не запрашивать, только показать план и объём")
    a = ap.parse_args()

    data = json.loads(STORIES.read_text(encoding="utf-8"))
    places = [p for p in data["places"] if not a.only or p["id"] == a.only]

    total_chars = sum(len(normalize(t)) for p in places for t in pieces(p))
    print(f"{len(places)} точек, "
          f"{sum(len(p['chapters']) + 1 for p in places)} файлов, "
          f"{total_chars} знаков к синтезу")
    if a.dry_run:
        print("Пробный прогон — запросы не отправлялись.")
        return
    if not a.key:
        sys.exit("Нет ключа. Задайте --key или переменную TTS_KEY.")

    OUT.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    engine = ENGINES[a.engine]
    made = skipped = 0

    for p in places:
        d = OUT / p["id"]
        d.mkdir(exist_ok=True)
        for i, raw in enumerate(pieces(p)):
            text = normalize(raw)
            name = f"{p['id']}/{i:03d}.mp3"
            digest = hashlib.sha1(
                f"{a.engine}|{a.voice}|{text}".encode()).hexdigest()
            if cache.get(name) == digest and (OUT / name).exists():
                skipped += 1
                continue
            print(f"  {name}  {len(text)} зн.", flush=True)
            for attempt in range(3):
                try:
                    (OUT / name).write_bytes(engine(text, a.key, a.voice))
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"    повтор после ошибки: {e}", flush=True)
                    time.sleep(3 * (attempt + 1))
            cache[name] = digest
            made += 1
            CACHE.write_text(json.dumps(cache, ensure_ascii=False))

    manifest = {p["id"]: len(p["chapters"]) + 1 for p in data["places"]
                if (OUT / p["id"]).exists()}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    if WEB_OUT.exists():
        shutil.rmtree(WEB_OUT)
    shutil.copytree(OUT, WEB_OUT, ignore=shutil.ignore_patterns(".cache.json"))

    size = sum(f.stat().st_size for f in OUT.rglob("*.mp3")) / 1_048_576
    print(f"\nГотово: создано {made}, пропущено без изменений {skipped}.")
    print(f"Всего звука {size:.1f} МБ в {OUT} и {WEB_OUT}")


if __name__ == "__main__":
    main()
