"""
Ежедневная сводка утреннего эфира Business FM Kazakhstan (08:00-09:00 Алматы).
Запускается из .github/workflows/radio_digest.yml по cron (03:00 UTC = 08:00
Алматы) — записывает живой поток, распознаёт речь, суммаризирует и шлёт
сводку в Telegram. Задержка в 1-2 часа после эфира — ожидаемо и нормально
(запись 60 мин + распознавание на CPU может занять почти столько же).

Зависимости — только для этого workflow (requirements-radio.txt), не в
основном requirements.txt: faster-whisper, anthropic.

Суммаризация:
  - Если задан ANTHROPIC_API_KEY — саммари через Claude Haiku (дёшево:
    ~12-16k токенов транскрипта в день, доли цента).
  - Если ключа нет — черновая сводка без LLM: транскрипт режется на
    ~3-минутные окна, из каждого берётся короткий фрагмент с меткой времени.
    Явно помечается как "черновая", чтобы не путать с нормальным саммари.

Только русский язык распознавания — станция преимущественно русскоязычная,
казахоязычные вставки (джинглы, отдельные сегменты) могут распознаваться
с ошибками. Не оптимизировано под это в первой версии.
"""
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from faster_whisper import WhisperModel

REPO_DIR = Path(__file__).parent
load_dotenv(REPO_DIR / ".env")

STREAM_URL       = "https://bfmreg.hostingradio.ru/kz.bfm128.mp3"
RECORD_SECONDS   = int(os.getenv("RADIO_RECORD_SECONDS", "3600"))  # переопределяемо для тестов
WHISPER_MODEL    = "small"
BUCKET_SECONDS   = 180  # окна для черновой сводки без LLM

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

AUDIO_FILE = Path("/tmp/bfm_recording.mp3")


def tg_send(text: str):
    if not TELEGRAM_TOKEN:
        print(f"[TG] {text}")
        return
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            print(f"[TG send error] {e}")


def record_stream() -> Path:
    """Пишет поток как есть (уже MP3) в файл ровно RECORD_SECONDS по настенным
    часам — простой стриминг-докачка, без ffmpeg: источник и так MP3, поэтому
    перекодирование не нужно."""
    print(f"Записываю {RECORD_SECONDS}с из {STREAM_URL}...")
    start = time.time()
    with requests.get(STREAM_URL, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(AUDIO_FILE, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                if time.time() - start > RECORD_SECONDS:
                    break
    print(f"Записано {AUDIO_FILE.stat().st_size} байт за {time.time()-start:.0f}с")
    return AUDIO_FILE


def transcribe(path: Path) -> list:
    print(f"Загружаю модель Whisper ({WHISPER_MODEL})...")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    print("Распознаю речь...")
    segments, info = model.transcribe(str(path), language="ru")
    segments = list(segments)
    print(f"Распознано {len(segments)} сегментов, язык: {info.language} ({info.language_probability:.2f})")
    return segments


def summarize_with_llm(segments: list) -> str:
    import anthropic
    transcript = " ".join(s.text.strip() for s in segments)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Это транскрипт утреннего эфира радио Business FM (Казахстан), "
                "08:00-09:00. Сделай краткую сводку ключевых новостей и бизнес-тем "
                "на русском языке, списком. Игнорируй рекламу, музыкальные вставки "
                "и болтовню ведущих между темами — только содержательные новости.\n\n"
                f"Транскрипт:\n{transcript}"
            ),
        }],
    )
    return resp.content[0].text


def summarize_extractive(segments: list) -> str:
    if not segments:
        return "Нет распознанного текста."
    buckets = {}
    for s in segments:
        bucket_idx = int(s.start // BUCKET_SECONDS)
        buckets.setdefault(bucket_idx, []).append(s.text.strip())

    lines = ["⚠️ <b>Черновая сводка (без LLM)</b> — добавь ANTHROPIC_API_KEY в секреты для нормального саммари.\n"]
    for idx in sorted(buckets):
        offset_min = idx * BUCKET_SECONDS // 60
        snippet = " ".join(buckets[idx])[:200]
        lines.append(f"[{offset_min:02d} мин] {snippet}")
    return "\n".join(lines)


def main():
    audio_path = record_stream()
    try:
        segments = transcribe(audio_path)
        if ANTHROPIC_API_KEY:
            digest = summarize_with_llm(segments)
        else:
            digest = summarize_extractive(segments)

        now = time.strftime("%d.%m.%Y")
        tg_send(f"📻 <b>СВОДКА BUSINESS FM — {now}</b>\n\n{digest}")
    finally:
        if audio_path.exists():
            audio_path.unlink()


if __name__ == "__main__":
    main()
