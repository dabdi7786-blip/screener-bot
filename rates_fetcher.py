"""
Rates Screener — фетчеры макро-данных.
Источники: НБРК, KASE, US Treasury (yfinance), Global Bonds (yfinance), FRED.
Паттерн: каждый фетчер возвращает dict, никогда не бросает исключений наружу.
"""
import logging
import re
import os
import json
from datetime import datetime
from pathlib import Path

import requests
import yfinance as yf
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

HISTORY_FILE = Path(__file__).parent / "last_rates.json"


# ── НБРК ─────────────────────────────────────────────────────────────────────

def get_nbrk_rates() -> dict:
    """Базовая ставка НБРК, коридор, инфляция."""
    _URLS = [
        "https://nationalbank.kz/ru/",          # главная — есть ставка
        "https://nationalbank.kz/",
        "https://nationalbank.kz/en/",
    ]
    for url in _URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            result = _parse_nbrk(r.text)
            if result:
                log.info("NBRK OK: %s → %s", url, result)
                return result
        except Exception as e:
            log.warning("NBRK %s: %s", url, e)

    log.error("НБРК: все источники недоступны")
    return {}


def _parse_nbrk(html: str) -> dict:
    """
    Разбирает главную страницу НБРК.
    Базовая ставка — из текста пресс-релиза: 'снижении/сохранении/повышении базовой ставки до/на уровне X%'
    Инфляция — из блока с цифрами рядом со словом 'инфляция'.
    """
    soup = BeautifulSoup(html, "lxml")
    result = {}
    full_text = soup.get_text(" ", strip=True)

    # Базовая ставка: ищем последнее решение НБРК по ставке
    # Паттерн: "базовой ставки до 17,00%" или "базовой ставки на уровне 17,00%"
    base_patterns = [
        r"базовой\s+ставки\s+до\s+(\d+[\.,]\d+)\s*%",
        r"базовой\s+ставки\s+на\s+уровне\s+(\d+[\.,]\d+)\s*%",
        r"базовую\s+ставку\s+до\s+(\d+[\.,]\d+)\s*%",
        r"base\s+rate[^\d]*(\d+[\.,]\d+)\s*%",
    ]
    for pat in base_patterns:
        # Берём первое вхождение (самое свежее решение вверху страницы)
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            try:
                result["base_rate"] = float(m.group(1).replace(",", "."))
                break
            except ValueError:
                pass

    # Инфляция
    infl_m = re.search(r"инфляци[яию][^\d]{0,30}(\d+[\.,]\d+)\s*%", full_text, re.IGNORECASE)
    if infl_m:
        try:
            result["inflation"] = float(infl_m.group(1).replace(",", "."))
        except ValueError:
            pass

    # Коридор: верхняя = base + 1, нижняя = base - 1 (стандартная полоса НБРК)
    if "base_rate" in result:
        result["corridor_upper"] = round(result["base_rate"] + 1.0, 2)
        result["corridor_lower"] = round(result["base_rate"] - 1.0, 2)

    return result


# ── KASE ─────────────────────────────────────────────────────────────────────

def get_kase_rates() -> dict:
    """TONIA, TWINA с KASE."""
    _URLS = [
        "https://kase.kz/ru/money_market/",
        "https://kase.kz/ru/",
    ]
    result = {}
    for url in _URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            parsed = _parse_kase(r.text)
            if parsed:
                result.update(parsed)
                log.info("KASE OK: %s → %s", url, list(parsed.keys()))
                break
        except Exception as e:
            log.warning("KASE %s: %s", url, e)

    if not result:
        log.error("KASE: все источники недоступны")
    return result


def _parse_kase(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    result = {}
    text = soup.get_text(" ", strip=True)

    patterns = {
        "tonia": r"TONIA[^\d]*(\d+[\.,]\d+)",
        "twina": r"TWINA[^\d]*(\d+[\.,]\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result[key] = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
    return result


# ── Валюты (KZT) ───────────────────────────────────────────────────────────────

def get_currency_rates() -> dict:
    """Тенге к USD, EUR, RUB, TRY. Прямые тикеры Yahoo для USD/EUR,
    кросс-курс через USD для RUB/TRY (прямых KZT-пар для них на Yahoo нет)."""
    result = {}

    usd_kzt = None
    try:
        fx = yf.Ticker("USDKZT=X").history(period="5d")
        if fx.empty:
            fx = yf.Ticker("KZTUSD=X").history(period="5d")
            if not fx.empty:
                usd_kzt = round(1 / float(fx["Close"].iloc[-1]), 2)
        else:
            usd_kzt = round(float(fx["Close"].iloc[-1]), 2)
        if usd_kzt is not None:
            result["usd_kzt"] = usd_kzt
    except Exception as e:
        log.warning("Currency USD/KZT: %s", e)

    try:
        fx = yf.Ticker("EURKZT=X").history(period="5d")
        if not fx.empty:
            result["eur_kzt"] = round(float(fx["Close"].iloc[-1]), 2)
    except Exception as e:
        log.warning("Currency EUR/KZT: %s", e)

    if usd_kzt is not None:
        try:
            fx = yf.Ticker("USDRUB=X").history(period="5d")
            if not fx.empty:
                usd_rub = float(fx["Close"].iloc[-1])
                result["rub_kzt"] = round(usd_kzt / usd_rub, 3)
        except Exception as e:
            log.warning("Currency RUB/KZT: %s", e)

        try:
            fx = yf.Ticker("USDTRY=X").history(period="5d")
            if not fx.empty:
                usd_try = float(fx["Close"].iloc[-1])
                result["try_kzt"] = round(usd_kzt / usd_try, 3)
        except Exception as e:
            log.warning("Currency TRY/KZT: %s", e)

    if not result:
        log.error("Currency: все источники недоступны")
    return result


# ── US Rates ─────────────────────────────────────────────────────────────────

def get_us_rates() -> dict:
    """EFFR, SOFR, US Treasury yields 3M/2Y/5Y/10Y/30Y."""
    result = {}

    # Treasury yields через Yahoo Finance (надёжно, без ключа)
    yf_tickers = {
        "t3m":  "^IRX",
        "t5y":  "^FVX",
        "t10y": "^TNX",
        "t30y": "^TYX",
    }
    for key, ticker in yf_tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if not hist.empty:
                result[key] = round(float(hist["Close"].iloc[-1]), 2)
        except Exception as e:
            log.warning("US Treasury %s (%s): %s", key, ticker, e)

    # EFFR через FRED если есть ключ, иначе — federalreserve.gov
    fred_key = os.getenv("FRED_API_KEY", "")
    if fred_key:
        result.update(_get_fed_rates_fred(fred_key))
    else:
        result.update(_get_fed_rates_scrape())

    if not result:
        log.error("US Rates: все источники недоступны")
    return result


def _get_fed_rates_fred(api_key: str) -> dict:
    series = {"effr": "DFF", "sofr": "SOFR"}
    result = {}
    base = "https://api.stlouisfed.org/fred/series/observations"
    for key, sid in series.items():
        try:
            r = requests.get(base, params={
                "series_id": sid, "api_key": api_key,
                "limit": 5, "sort_order": "desc", "file_type": "json"
            }, timeout=15)
            obs = r.json().get("observations", [])
            for o in obs:
                if o.get("value") not in (".", None, ""):
                    result[key] = round(float(o["value"]), 2)
                    break
        except Exception as e:
            log.warning("FRED %s: %s", sid, e)
    return result


def _get_fed_rates_scrape() -> dict:
    """Fallback: scrape federalreserve.gov для EFFR target range."""
    _URLS = [
        "https://www.federalreserve.gov/monetarypolicy/openmarket.htm",
        "https://www.federalreserve.gov/releases/h15/",
    ]
    for url in _URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            text = r.text
            m = re.search(r"(\d+[\./]\d+)\s*(?:to|-)\s*(\d+[\./]\d+)\s*percent", text, re.IGNORECASE)
            if m:
                lo = float(m.group(1).replace("/", "."))
                hi = float(m.group(2).replace("/", "."))
                return {"effr_lo": lo, "effr_hi": hi, "effr": round((lo + hi) / 2, 2)}
        except Exception as e:
            log.warning("Fed scrape %s: %s", url, e)
    return {}


# ── Global Bonds ──────────────────────────────────────────────────────────────

def get_global_bonds() -> dict:
    """10Y гособлигации: DE (ECB), UK (BoE), JP/FR (Yahoo v8 chart API)."""
    result = {}

    # Германия — ECB Yield Curve API (надёжный источник)
    try:
        ecb_url = ("https://data-api.ecb.europa.eu/service/data/"
                   "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
                   "?lastNObservations=5&format=jsondata")
        r = requests.get(ecb_url, timeout=15)
        r.raise_for_status()
        series = r.json()["dataSets"][0]["series"]
        obs = next(iter(series.values()))["observations"]
        last = obs[sorted(obs.keys(), key=int)[-1]][0]
        result["de_10y"] = round(float(last), 2)
        log.info("ECB DE 10Y: %.2f%%", result["de_10y"])
    except Exception as e:
        log.warning("ECB DE 10Y: %s", e)

    # UK — Bank of England статистика
    try:
        boe_url = ("https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
                   "?Travel=NIxRSxSUx&FromSeries=1&ToSeries=50&DAT=RNG"
                   "&FD=1&FM=Jan&FY=2025&TD=30&TM=Jun&TY=2026"
                   "&VFD=Y&html.x=66&html.y=26&C=BNH&UsingCodes=True")
        r = requests.get(boe_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        # BoE возвращает таблицу — берём последнее значение BNH (10Y gilt)
        tds = soup.find_all("td")
        for td in reversed(tds):
            m = re.search(r"(\d+\.\d+)", td.get_text())
            if m:
                val = float(m.group(1))
                if 1 < val < 15:   # разумный диапазон доходности
                    result["uk_10y"] = round(val, 2)
                    log.info("BoE UK 10Y: %.2f%%", val)
                    break
    except Exception as e:
        log.warning("BoE UK 10Y: %s", e)

    # Япония и Франция — Yahoo Finance chart API (прямой HTTP, не через yfinance lib)
    yf_chart_tickers = {
        "jp_10y": "%5ETMBMKJP-10Y",
        "fr_10y": "%5ETMBMKFR-10Y",
    }
    YF_HEADERS = {
        "User-Agent": "Mozilla/5.0 Chrome/124.0",
        "Accept": "application/json",
    }
    for key, t in yf_chart_tickers.items():
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{t}?range=5d&interval=1d"
            r = requests.get(url, headers=YF_HEADERS, timeout=10)
            d = r.json()
            if d.get("chart", {}).get("result"):
                closes = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
                vals = [c for c in closes if c is not None]
                if vals:
                    result[key] = round(float(vals[-1]), 2)
                    log.info("%s: %.2f%%", key, result[key])
        except Exception as e:
            log.warning("%s Yahoo chart: %s", key, e)

    if not result:
        log.error("Global bonds: все источники недоступны")
    return result


# ── History (дельты) ──────────────────────────────────────────────────────────

def load_previous() -> dict:
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text())
    except Exception as e:
        log.warning("load_previous: %s", e)
    return {}


def save_current(data: dict) -> None:
    try:
        HISTORY_FILE.parent.mkdir(exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        log.warning("save_current: %s", e)


def fmt_delta(current, prev: dict, key: str) -> str:
    prev_val = prev.get(key)
    if prev_val is None or current is None:
        return ""
    try:
        diff = float(current) - float(prev_val)
        if abs(diff) < 0.001:
            return ""
        arrow = "↑" if diff > 0 else "↓"
        sign  = "+" if diff > 0 else ""
        return f" {arrow}{sign}{diff:.2f}"
    except (TypeError, ValueError):
        return ""


# ── Formatter ─────────────────────────────────────────────────────────────────

def _v(val, suffix="%") -> str:
    if val is None:
        return "—"
    return f"{val:.2f}{suffix}"


def build_rates_message(rates: dict, prev: dict = None) -> str:
    """rates: {"nbrk", "kase", "us", "bonds", "currency"} — уже полученные данные,
    эта функция ничего сама не фетчит и не сохраняет историю."""
    if prev is None:
        prev = {}

    nbrk     = rates.get("nbrk", {})
    kase     = rates.get("kase", {})
    us       = rates.get("us", {})
    bonds    = rates.get("bonds", {})
    currency = rates.get("currency", {})

    now = datetime.now().strftime("%d.%m.%Y")
    lines = [f"💹 <b>ОБЗОР СТАВОК — {now}</b>\n"]

    # ── НБРК ──────────────────────────────────────────────────────────────────
    lines.append("🇰🇿 <b>НБРК — МОНЕТАРНАЯ ПОЛИТИКА</b>")
    if nbrk:
        base = nbrk.get("base_rate")
        if base is not None:
            dlt = fmt_delta(base, prev.get("nbrk", {}), "base_rate")
            lines.append(f"  Базовая ставка:  <code>{_v(base)}</code>{dlt}")
        cu = nbrk.get("corridor_upper")
        cl = nbrk.get("corridor_lower")
        if cu is not None and cl is not None:
            lines.append(f"  Коридор:         <code>{_v(cl)} — {_v(cu)}</code>")
        infl = nbrk.get("inflation")
        if infl is not None:
            dlt = fmt_delta(infl, prev.get("nbrk", {}), "inflation")
            lines.append(f"  Инфляция:        <code>{_v(infl)}</code>{dlt}")
    else:
        lines.append("  <i>данные недоступны</i>")

    # ── KASE ──────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("🏦 <b>KASE — ДЕНЕЖНЫЙ РЫНОК</b>")
    if kase:
        tonia = kase.get("tonia")
        twina = kase.get("twina")
        if tonia is not None:
            dlt = fmt_delta(tonia, prev.get("kase", {}), "tonia")
            lines.append(f"  TONIA:    <code>{_v(tonia)}</code>{dlt}")
        if twina is not None:
            dlt = fmt_delta(twina, prev.get("kase", {}), "twina")
            lines.append(f"  TWINA:    <code>{_v(twina)}</code>{dlt}")
    else:
        lines.append("  <i>данные недоступны</i>")

    # ── Валюты ────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("💱 <b>ВАЛЮТЫ (ТЕНГЕ)</b>")
    if currency:
        for key, label in [("usd_kzt","USD/KZT"), ("eur_kzt","EUR/KZT"),
                            ("rub_kzt","RUB/KZT"), ("try_kzt","TRY/KZT")]:
            val = currency.get(key)
            if val is not None:
                dlt = fmt_delta(val, prev.get("currency", {}), key)
                lines.append(f"  {label}:  <code>{_v(val, suffix='')}</code>{dlt}")
    else:
        lines.append("  <i>данные недоступны</i>")

    # ── US Rates ───────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("🇺🇸 <b>США — СТАВКИ И ТРЕЖЕРИС</b>")
    if us:
        effr = us.get("effr")
        effr_lo = us.get("effr_lo")
        effr_hi = us.get("effr_hi")
        sofr = us.get("sofr")
        if effr is not None and effr_lo is not None:
            dlt = fmt_delta(effr, prev.get("us", {}), "effr")
            lines.append(f"  Fed Rate: <code>{_v(effr_lo)} — {_v(effr_hi)}</code> (mid {_v(effr)}){dlt}")
        elif effr is not None:
            dlt = fmt_delta(effr, prev.get("us", {}), "effr")
            lines.append(f"  EFFR:     <code>{_v(effr)}</code>{dlt}")
        if sofr is not None:
            dlt = fmt_delta(sofr, prev.get("us", {}), "sofr")
            lines.append(f"  SOFR:     <code>{_v(sofr)}</code>{dlt}")

        treasury_parts = []
        for key, label in [("t3m","3M"), ("t5y","5Y"), ("t10y","10Y"), ("t30y","30Y")]:
            val = us.get(key)
            if val is not None:
                dlt = fmt_delta(val, prev.get("us", {}), key)
                treasury_parts.append(f"{label}: <code>{_v(val)}</code>{dlt}")
        if treasury_parts:
            lines.append("  Трежерис: " + " | ".join(treasury_parts))
    else:
        lines.append("  <i>данные недоступны</i>")

    # ── Global Bonds ──────────────────────────────────────────────────────────
    lines.append("")
    lines.append("🌍 <b>МИРОВЫЕ ОБЛИГАЦИИ (10Y)</b>")
    if bonds:
        bond_parts = []
        for key, label, flag in [
            ("de_10y","DE","🇩🇪"), ("uk_10y","UK","🇬🇧"),
            ("jp_10y","JP","🇯🇵"), ("fr_10y","FR","🇫🇷"),
            ("cn_10y","CN","🇨🇳"),
        ]:
            val = bonds.get(key)
            if val is not None:
                dlt = fmt_delta(val, prev.get("bonds", {}), key)
                bond_parts.append(f"{flag}{label}: <code>{_v(val)}</code>{dlt}")
        if bond_parts:
            lines.append("  " + " | ".join(bond_parts))
    else:
        lines.append("  <i>данные недоступны</i>")

    return "\n".join(lines)
