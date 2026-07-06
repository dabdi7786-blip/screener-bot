"""
Загружает HTML-файл на публичный хостинг и возвращает URL.
Приоритет: gofile.io → transfer.sh → 0x0.st
"""
import logging
import requests
from pathlib import Path

log = logging.getLogger(__name__)
TIMEOUT = 40


def upload(file_path: str) -> str | None:
    """Вернуть публичный URL или None если все хосты недоступны."""
    path = Path(file_path)
    if not path.exists():
        log.error("upload: файл не найден: %s", file_path)
        return None
    content = path.read_bytes()
    fname   = path.name

    for fn in (_try_gofile, _try_transfersh, _try_0x0):
        url = fn(content, fname)
        if url:
            return url

    log.error("upload: все хосты недоступны")
    return None


def _try_gofile(content: bytes, fname: str) -> str | None:
    """gofile.io — бесплатно, без аккаунта, файлы 10 дней без скачивания."""
    try:
        # 1. Получить лучший сервер
        srv_r = requests.get("https://api.gofile.io/servers", timeout=10)
        server = srv_r.json()["data"]["servers"][0]["name"]
        # 2. Загрузить файл
        r = requests.post(
            f"https://{server}.gofile.io/contents/uploadfile",
            files={"file": (fname, content, "text/html")},
            timeout=TIMEOUT,
        )
        d = r.json()
        if d.get("status") == "ok":
            page = d["data"]["downloadPage"]
            # Прямая ссылка на файл
            file_id   = d["data"]["id"]
            direct    = d["data"].get("directLink") or page
            log.info("gofile.io OK: %s", page)
            return page   # страница скачивания — открывается в браузере
        log.warning("gofile.io: %s", d)
    except Exception as e:
        log.warning("gofile.io: %s", e)
    return None


def _try_transfersh(content: bytes, fname: str) -> str | None:
    """transfer.sh — max 10GB, 14 дней."""
    try:
        r = requests.put(
            f"https://transfer.sh/{fname}",
            data=content,
            headers={"Content-Type": "text/html", "Max-Days": "14"},
            timeout=TIMEOUT,
        )
        if r.status_code == 200 and r.text.strip().startswith("http"):
            url = r.text.strip()
            log.info("transfer.sh OK: %s", url)
            return url
        log.warning("transfer.sh: status=%d", r.status_code)
    except Exception as e:
        log.warning("transfer.sh: %s", e)
    return None


def _try_0x0(content: bytes, fname: str) -> str | None:
    """0x0.st — когда доступен."""
    try:
        r = requests.post(
            "https://0x0.st",
            files={"file": (fname, content, "text/html")},
            timeout=TIMEOUT,
        )
        if r.status_code == 200 and r.text.strip().startswith("http"):
            url = r.text.strip()
            log.info("0x0.st OK: %s", url)
            return url
        log.warning("0x0.st: status=%d body=%s", r.status_code, r.text[:80])
    except Exception as e:
        log.warning("0x0.st: %s", e)
    return None
