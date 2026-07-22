"""
Telegram bot server — одноразовый проход по апдейтам (запускается по расписанию,
например из GitHub Actions каждые ~10 минут; не держит постоянное соединение).
Слушает команды и запускает скринеры по запросу.

Команды:
  /start  — справка + кнопки
  /scan   — все 3 скринера
  /scan1  — 💎 Value
  /scan2  — 🚀 Growth
  /scan3  — 🏆 Compounder
  /guide  — инструкция по интерпретации
  /status — время последнего скана
  /users  — (admin) список подписчиков
  /ticker — анализ произвольного тикера (тот же TA, что в карточках скринеров)
"""

import os, re, sys, json, traceback
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)  # flush лог после каждой строки
from datetime import datetime
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent / ".env")

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
API     = f"https://api.telegram.org/bot{TOKEN}"
STATUS_FILE = Path(__file__).parent / "last_scan.json"
USERS_FILE  = Path(__file__).parent / "users.json"

# ── Telegram helpers ───────────────────────────────────────────────────────

def tg_send(text: str, chat_id: str = CHAT_ID):
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        try:
            requests.post(f"{API}/sendMessage", json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
            }, timeout=10)
        except Exception as e:
            print(f"[send error] {e}")

def tg_send_kb(text: str, chat_id: str, keyboard: dict):
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }, timeout=10)
    except Exception as e:
        print(f"[send_kb error] {e}")

def tg_answer_cb(callback_id: str):
    try:
        requests.post(f"{API}/answerCallbackQuery",
                      json={"callback_query_id": callback_id}, timeout=5)
    except Exception:
        pass

def tg_get_updates(offset: int, timeout: int = 30) -> list:
    try:
        r = requests.get(f"{API}/getUpdates", params={
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }, timeout=timeout + 5)
        return r.json().get("result", [])
    except Exception:
        return []

# ── Статус последнего скана ────────────────────────────────────────────────

def save_status(screeners: list[int], count: dict):
    STATUS_FILE.write_text(json.dumps({
        "time": datetime.now().isoformat(timespec="seconds"),
        "screeners": screeners,
        "matches": count,
    }, ensure_ascii=False))

def load_status() -> dict:
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text())
    return {}

# ── Управление пользователями ─────────────────────────────────────────────

def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}

def save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2))

def is_admin(chat_id: str) -> bool:
    return chat_id == CHAT_ID

def is_allowed(chat_id: str) -> bool:
    if is_admin(chat_id):
        return True
    return load_users().get(chat_id, {}).get("status") == "allowed"

def register_user(message: dict) -> bool:
    """Save new user as pending and notify admin. Returns True if first contact."""
    from_info = message.get("from", {})
    chat_id   = str(message["chat"]["id"])
    if is_admin(chat_id):
        return False
    users = load_users()
    if chat_id in users:
        return False
    first_name = from_info.get("first_name", "")
    username   = from_info.get("username", "")
    users[chat_id] = {
        "first_name": first_name,
        "username":   username,
        "status":     "pending",
        "joined":     datetime.now().isoformat(timespec="seconds"),
    }
    save_users(users)
    name_str  = first_name + (f" (@{username})" if username else "")
    admin_kb  = {"inline_keyboard": [[
        {"text": "✅ Разрешить",     "callback_data": f"allow_{chat_id}"},
        {"text": "🚫 Заблокировать", "callback_data": f"block_{chat_id}"},
    ]]}
    tg_send_kb(
        f"👤 <b>Новый пользователь</b>\n"
        f"Имя: {name_str}\n"
        f"ID: <code>{chat_id}</code>\n"
        f"Статус: ⏳ Ожидает разрешения",
        CHAT_ID, admin_kb,
    )
    return True

_STATUS_EMOJI = {"allowed": "✅", "pending": "⏳", "blocked": "🚫"}

def send_users_list(admin_id: str):
    users = load_users()
    if not users:
        tg_send("👥 Подписчиков пока нет.", admin_id)
        return
    lines = ["👥 <b>Подписчики бота</b>\n"]
    rows  = []
    for cid, info in users.items():
        emoji  = _STATUS_EMOJI.get(info.get("status", "pending"), "❓")
        name   = info.get("first_name", "")
        uname  = f" @{info['username']}" if info.get("username") else ""
        joined = info.get("joined", "")[:10]
        lines.append(f"{emoji} <b>{name}</b>{uname} — <code>{cid}</code> ({joined})")
        rows.append([
            {"text": f"✅ {name or cid}", "callback_data": f"allow_{cid}"},
            {"text": f"🚫 {name or cid}", "callback_data": f"block_{cid}"},
        ])
    tg_send_kb("\n".join(lines), admin_id, {"inline_keyboard": rows})

def allow_user(target_id: str, admin_id: str):
    users = load_users()
    if target_id not in users:
        tg_send(f"❌ Пользователь <code>{target_id}</code> не найден.", admin_id)
        return
    users[target_id]["status"] = "allowed"
    save_users(users)
    name = users[target_id].get("first_name", target_id)
    tg_send(f"✅ <b>{name}</b> (<code>{target_id}</code>) — доступ разрешён.", admin_id)
    tg_send_kb("✅ Доступ разрешён! Можешь пользоваться ботом.", target_id, MAIN_KB)

def block_user(target_id: str, admin_id: str):
    users = load_users()
    if target_id not in users:
        tg_send(f"❌ Пользователь <code>{target_id}</code> не найден.", admin_id)
        return
    users[target_id]["status"] = "blocked"
    save_users(users)
    name = users[target_id].get("first_name", target_id)
    tg_send(f"🚫 <b>{name}</b> (<code>{target_id}</code>) — заблокирован.", admin_id)

# ── Импорт логики скринеров ───────────────────────────────────────────────

from screener_bot import run_scan as screener_run_scan
from screener_bot import format_rating, SCREENERS, get_ta

SCREENER_MAP = {s["id"]: s for s in SCREENERS}

# ── Клавиатуры ────────────────────────────────────────────────────────────

MAIN_KB = {"inline_keyboard": [
    [
        {"text": "💎 Value",      "callback_data": "scan1"},
        {"text": "🚀 Growth",     "callback_data": "scan2"},
        {"text": "🏆 Compounder", "callback_data": "scan3"},
    ],
    [{"text": "🔍 Запустить все три (~15 мин)", "callback_data": "scan"}],
    [{"text": "📖 Инструкция по скринерам",     "callback_data": "guide"}],
]}

GUIDE_KB = {"inline_keyboard": [
    [
        {"text": "💎 Value",      "callback_data": "guide1"},
        {"text": "🚀 Growth",     "callback_data": "guide2"},
        {"text": "🏆 Compounder", "callback_data": "guide3"},
    ],
    [{"text": "📊 Общие правила и тайминг входа", "callback_data": "guide4"}],
    [{"text": "« Главное меню", "callback_data": "menu"}],
]}

# ── Тексты инструкций ─────────────────────────────────────────────────────

GUIDE_TEXTS = {
    "guide": (
        "📖 <b>Инструкция по скринерам</b>\n\n"
        "Выбери скринер чтобы узнать как интерпретировать результаты:"
    ),
    "guide1": (
        "💎 <b>Value Scanner — как читать результаты</b>\n\n"
        "Ищет качественные компании дешевле их реальной стоимости.\n"
        "Типичные кандидаты: <b>Alphabet, Meta, Cisco, Dell</b> в периоды коррекции.\n\n"
        "<b>На что смотреть в первую очередь:</b>\n\n"
        "💵 <b>FCF Yield</b> — доходность в реальных деньгах на каждый вложенный доллар\n"
        "  &gt;10% = исторически дёшево\n"
        "  5–8% = справедливая цена с дисконтом\n"
        "  &lt;3% = уже не value\n\n"
        "📊 <b>EV/FCF</b> — лучше P/E, учитывает долг\n"
        "  &lt;15 = дёшево / &lt;20 = нормально / &gt;25 = дорого\n\n"
        "🏷️ <b>PE Дисконт</b> — Forward vs Trailing PE\n"
        "  &gt;20% = аналитики ждут роста прибыли, сильный сигнал\n\n"
        "🔄 <b>ROIC</b> — эффективность использования капитала\n"
        "  &gt;20% = хороший бизнес\n"
        "  ⚠️ Дешёвая цена + ROIC &lt;10% = value trap, обходи стороной\n\n"
        "🏦 <b>Нетто-кэш</b> = Cash − Debt\n"
        "  Положительный = буфер безопасности + топливо для байбэков\n\n"
        "<b>🚩 Красные флаги:</b>\n"
        "— FCF Yield высокий + ROIC &lt;10% → value trap\n"
        "— Нетто-кэш очень отрицательный → риск при росте ставок\n"
        "— Consensus «Hold» при Score &gt;15 → хорошая контрарная возможность"
    ),
    "guide2": (
        "🚀 <b>Growth Scanner v2 — как читать результаты</b>\n\n"
        "Ищет компании с ускоряющимся ростом. Топ-20 акций с sector cap.\n"
        "Типичные кандидаты: <b>NVIDIA, Broadcom, Arista, Palantir, Eli Lilly</b>.\n\n"
        "<b>6 блоков оценки (0–10 баллов):</b>\n\n"
        "📊 <b>Рост</b> — EPS + Rev Growth + Rule of 40 + ⚡ акселерация\n"
        "  ⚡ = EPS квартальный рост ускоряется — сильнейший сигнал роста\n"
        "  Rule40 &gt;80 = элита / &gt;60 = отлично / &gt;40 = минимум\n\n"
        "💎 <b>Качество</b> — Gross Margin + FCF Margin + ROIC\n"
        "  GM &gt;70% = при росте прибыль растёт непропорционально\n"
        "  ROIC &gt;25% = эффективное использование капитала\n\n"
        "🏷️ <b>Оценка</b> — PEG + Upside аналитиков + FCF Yield\n"
        "  PEG &lt;1.0 = покупаешь рост дешевле его темпа → сигнал GARP\n"
        "  🔴 Красный флаг: Upside &lt;5% — цель уже достигнута\n\n"
        "📈 <b>Моментум</b> — RS vs S&amp;P500 + Price trend + TA\n"
        "  RS = доходность акции минус доходность S&amp;P500 за год\n"
        "  RS &gt;+20% = лидер рынка (ключевой фильтр по CAN SLIM)\n"
        "  ✅ Подтверждённый вход = восходящий тренд + бычий MACD\n"
        "  ⏳ Ожидание = нисходящий тренд, RSI не перепродан → не торопись\n\n"
        "⚡ <b>Риск</b> — нетто-кэш + бета + short interest\n"
        "  Нетто-кэш &gt;0 = компания не зависит от долгового рынка\n"
        "  Short &gt;10% = высокий риск, но и потенциал short-squeeze\n\n"
        "🤖 <b>AI</b> — прямая экспозиция к AI-инфраструктуре или платформе\n\n"
        "<b>🚩 Красные флаги:</b>\n"
        "— 🔴 «Цель аналитиков близко/ниже цены» в профиле → не покупай\n"
        "— Rev Growth замедляется: Chg6m хуже Chg1y → история заканчивается\n"
        "— ⏳ Ожидание разворота = жди RSI &lt;35 или пробоя MA50 вверх\n"
        "— EPS &gt;500% = вероятно низкая база прошлого года, проверь вручную"
    ),
    "guide3": (
        "🏆 <b>Compounder Scanner — как читать результаты</b>\n\n"
        "Ищет бизнесы, которые будут стоить в 3–5х дороже через 5–10 лет. "
        "Не ракеты, а машины по созданию стоимости.\n"
        "Типичные кандидаты: <b>Microsoft, Visa, Meta, Alphabet, Mastercard</b>.\n\n"
        "<b>На что смотреть в первую очередь:</b>\n\n"
        "🔄 <b>ROIC</b> — главное (25% веса)\n"
        "  &gt;40% = исключительный (V, MA, NVDA) — элита\n"
        "  25–40% = отличный compounder\n"
        "  15–25% = хороший, достоин внимания\n"
        "  &lt;15% = обычный бизнес, не compounder\n\n"
        "💎 <b>FCF Margin</b> — топливо для роста без внешних источников\n"
        "  &gt;20% = компания сама финансирует развитие и байбэки\n\n"
        "🔁 <b>Buyback Yield</b> — скрытый рост EPS\n"
        "  3% байбэк = +3% к EPS ежегодно даже без роста выручки\n"
        "  META, GOOGL, AAPL — лучшие примеры\n\n"
        "🏰 <b>Moat (ров)</b> — ширина конкурентного преимущества\n"
        "  5⭐ MSFT, AAPL, V, MA, GOOGL — сетевой эффект + switching costs\n"
        "  4⭐ META, AMZN, NVDA, COST — широкий, но с конкуренцией\n"
        "  3⭐ ADBE, CRM, NFLX — умеренный\n\n"
        "<b>🚩 Красные флаги:</b>\n"
        "— ROIC высокий + FCF Margin падает → качество прибыли ухудшается\n"
        "— Buyback Yield &gt;5% при отриц. нетто-кэш → байбэки в долг, риск\n"
        "— Momentum &lt;0 = нормально для compounder, это точка входа, не причина не брать"
    ),
    "guide4": (
        "📊 <b>Общие правила интерпретации</b>\n\n"
        "<b>Шкала Score:</b>\n"
        "██████████ 8–10 баллов = топ-кандидат, изучай детально\n"
        "███████░░░ 6–7  баллов = хороший, достоин позиции\n"
        "█████░░░░░ 4–5  баллов = нейтральный, жди катализатора\n"
        "████░░░░░░ &lt;4  балла  = прошёл фильтр технически, но слабый\n\n"
        "<b>Как использовать все три скринера вместе:</b>\n"
        "• Value + Compounder = приоритет №1 (GOOGL/META после коррекции)\n"
        "• Только Growth = позиция с чётким стоп-лоссом (смотри TA)\n"
        "• Только Compounder = долгосрочная покупка, не торопись\n"
        "• Все три сразу = исключительная ситуация → большая доля\n\n"
        "<b>Тех. анализ — тайминг входа:</b>\n"
        "• RSI &lt;40 + MACD бычий + хорошие фундаменталы → покупай\n"
        "• RSI &gt;70 + восходящий тренд → жди отката\n"
        "• Нисходящий тренд + хорошие фундаменталы → поставь алерт на MA50\n\n"
        "<b>Аналитики:</b>\n"
        "• Strong Buy + Upside &gt;30% = консенсус ещё не отыгран\n"
        "• Hold при Score &gt;15 = контрарная возможность\n"
        "• Upside &lt;5% = не иди против Wall Street без веской причины\n\n"
        "<b>Отчёт (EarningsDate):</b>\n"
        "• Дата близко (&lt;2 нед.) + позиция открыта → осторожно с размером\n"
        "• После отчёта на позитиве + хорошие фундаменталы → добавляй"
    ),
}

def send_guide(section: str, chat_id: str):
    text = GUIDE_TEXTS.get(section, GUIDE_TEXTS["guide"])
    tg_send_kb(text, chat_id, GUIDE_KB)

# ── Запуск скана ───────────────────────────────────────────────────────────
# Синхронно: скрипт запускается одноразово (см. main() ниже), поток не нужен —
# job в GitHub Actions просто выполняется дольше, пока не закончит.

def handle_scan_command(ids: list, chat_id: str):
    try:
        scan = screener_run_scan(ids)

        rating_lines   = []
        dashboard_data = {}
        matches        = {}
        for sc_id in ids:
            r = scan.get(sc_id)
            if not r:
                continue
            rating_lines.append(format_rating(r["sc"], r["ranked"]))
            dashboard_data[sc_id] = r["dashboard_rows"]
            matches[sc_id] = len(r["ranked"])

        save_status(ids, matches)

        url = os.getenv("PAGES_URL", "").rstrip("/") or None
        try:
            from dashboard_generator import generate
            date_only = datetime.now().strftime("%d.%m.%Y")
            generate(dashboard_data, {}, date_only)
        except Exception as e:
            print(f"Дашборд: ошибка — {e}")
            url = None

        if url:
            rating_lines.append("")
            rating_lines.append("🌐 <b>Дашборд:</b>")
            for sc_id in ids:
                sc = SCREENER_MAP[sc_id]
                rating_lines.append(f"{sc['emoji']} {sc['name']} → {url}#sc{sc_id}")

        tg_send_kb("\n".join(rating_lines), chat_id, MAIN_KB)

    except Exception:
        tg_send(f"❌ Ошибка:\n<code>{traceback.format_exc()[-500:]}</code>", chat_id)

# ── Анализ произвольного тикера ────────────────────────────────────────────
# Тот же TA, что считается для карточек в скринерах (get_ta), но по запросу
# для любого тикера — не только для тех, что прошли отбор.

TICKER_RE = re.compile(r"^/ticker\s+([A-Za-z.]{1,10})$")

def format_ta_message(ticker: str, ta: dict) -> str:
    lines = [f"📈 <b>{ticker}</b>"]
    lines.append(f"{ta.get('trend','')} &nbsp; MACD {ta.get('macd','')} &nbsp; "
                 f"RSI {ta.get('rsi','—')} {ta.get('rsi_lbl','')}")
    lines.append(f"Цена закрытия на {ta.get('price_date','—')}: <b>${ta.get('entry','—')}</b>")
    lines.append(f"MA50: ${ta.get('ma50','—')}" + (f"  MA200: ${ta['ma200']}" if ta.get("ma200") else ""))
    lines.append(f"Поддержка: ${ta.get('support','—')}  Сопротивление: ${ta.get('resistance','—')}")
    lines.append("")
    lines.append(f"SL: <b>${ta.get('sl','—')}</b> ({ta.get('sl_pct','—')})")
    lines.append(f"TP1: <b>${ta.get('tp1','—')}</b> ({ta.get('tp1_pct','—')})")
    lines.append(f"TP2: <b>${ta.get('tp2','—')}</b> ({ta.get('tp2_pct','—')})")
    if ta.get("earn_date"):
        lines.append("")
        lines.append(f"📅 Посл. отчёт: {ta['earn_date']} — цена закрытия ${ta.get('earn_close','—')}")
    return "\n".join(lines)

def handle_ticker_command(text: str, chat_id: str):
    m = TICKER_RE.match(text)
    if not m:
        tg_send("Формат: <code>/ticker TSLA</code>", chat_id)
        return
    symbol = m.group(1).upper()
    ta = get_ta(symbol)
    if not ta:
        tg_send(f"Нет данных по «{symbol}» — проверь тикер или попробуй позже.", chat_id)
        return
    tg_send(format_ta_message(symbol, ta), chat_id)

# ── Обработка команд ───────────────────────────────────────────────────────

HELP_TEXT = (
    "📊 <b>Stock Screener Bot</b>\n\n"
    "<b>Скринеры:</b>\n"
    "💎 Value      — недооценённые компании с сильным FCF\n"
    "🚀 Growth     — быстрорастущие компании\n"
    "🏆 Compounder — долгосрочные победители\n\n"
    "Автоматический скан: пн–пт в 08:00\n\n"
    "Выбери действие:"
)

def handle(message: dict):
    chat_id = str(message["chat"]["id"])
    text    = message.get("text", "").strip()

    # Регистрируем нового пользователя при первом контакте
    is_new = register_user(message)

    # Проверка доступа (admin всегда пропускаем)
    if not is_allowed(chat_id):
        if is_new or text in ("/start", "/help"):
            tg_send(
                "👋 Привет! Твой запрос отправлен администратору.\n"
                "Ожидай подтверждения — тебе придёт уведомление когда доступ будет открыт.",
                chat_id,
            )
        else:
            tg_send("⏳ Доступ ещё не открыт. Ожидай подтверждения.", chat_id)
        return

    if text in ("/start", "/help"):
        tg_send_kb(HELP_TEXT, chat_id, MAIN_KB)
    elif text == "/scan":
        handle_scan_command([1, 2, 3], chat_id)
    elif text == "/scan1":
        handle_scan_command([1], chat_id)
    elif text == "/scan2":
        handle_scan_command([2], chat_id)
    elif text == "/scan3":
        handle_scan_command([3], chat_id)
    elif text == "/guide":
        send_guide("guide", chat_id)
    elif text == "/status":
        st = load_status()
        if not st:
            tg_send("ℹ️ Скан ещё не запускался.", chat_id)
        else:
            lines = [f"🕐 Последний скан: <b>{st['time']}</b>"]
            for sc_id, cnt in st.get("matches", {}).items():
                sc = SCREENER_MAP.get(int(sc_id))
                name = f"{sc['emoji']} {sc['name']}" if sc else f"#{sc_id}"
                lines.append(f"  #{sc_id} {name}: {cnt} акций")
            tg_send_kb("\n".join(lines), chat_id, MAIN_KB)
    elif text == "/users" and is_admin(chat_id):
        send_users_list(chat_id)
    elif text.startswith("/allow ") and is_admin(chat_id):
        target = text.split(maxsplit=1)[1].strip()
        allow_user(target, chat_id)
    elif text.startswith("/block ") and is_admin(chat_id):
        target = text.split(maxsplit=1)[1].strip()
        block_user(target, chat_id)
    elif text.startswith("/ticker "):
        handle_ticker_command(text, chat_id)
    else:
        tg_send_kb("Не знаю такой команды.", chat_id, MAIN_KB)

def handle_callback(data: str, chat_id: str):
    # Admin-only: allow/block buttons
    if data.startswith("allow_") and is_admin(chat_id):
        allow_user(data[6:], chat_id)
        return
    if data.startswith("block_") and is_admin(chat_id):
        block_user(data[6:], chat_id)
        return

    if not is_allowed(chat_id):
        tg_send("⏳ Доступ ещё не открыт. Ожидай подтверждения.", chat_id)
        return

    if data == "menu":
        tg_send_kb(HELP_TEXT, chat_id, MAIN_KB)
    elif data == "scan":
        handle_scan_command([1, 2, 3], chat_id)
    elif data == "scan1":
        handle_scan_command([1], chat_id)
    elif data == "scan2":
        handle_scan_command([2], chat_id)
    elif data == "scan3":
        handle_scan_command([3], chat_id)
    elif data in GUIDE_TEXTS:
        send_guide(data, chat_id)

# ── Регистрация меню команд ────────────────────────────────────────────────

def register_commands():
    commands = [
        {"command": "scan",   "description": "🔍 Все три скринера (~15 мин)"},
        {"command": "scan1",  "description": "💎 Value Scanner"},
        {"command": "scan2",  "description": "🚀 Growth Scanner"},
        {"command": "scan3",  "description": "🏆 Compounder Scanner"},
        {"command": "guide",  "description": "📖 Инструкция по интерпретации"},
        {"command": "status", "description": "🕐 Последний скан"},
        {"command": "users",  "description": "👥 Список подписчиков (admin)"},
        {"command": "ticker", "description": "📈 Анализ тикера, например /ticker TSLA"},
        {"command": "start",  "description": "📋 Главное меню"},
    ]
    resp = requests.post(f"{API}/setMyCommands", json={"commands": commands}, timeout=10)
    print("✅ Меню команд зарегистрировано" if resp.ok else f"[menu error] {resp.text}")

# ── Одноразовый проход по апдейтам ──────────────────────────────────────────
# Запускается по cron (GitHub Actions, ~каждые 10 мин) вместо вечного while True —
# так процесс не должен быть постоянно поднят на локальной машине.

def main():
    register_commands()
    updates = tg_get_updates(0)
    max_update_id = 0
    for upd in updates:
        max_update_id = max(max_update_id, upd["update_id"])
        try:
            if "callback_query" in upd:
                cb      = upd["callback_query"]
                chat_id = str(cb["message"]["chat"]["id"])
                tg_answer_cb(cb["id"])
                print(f"[{datetime.now():%H:%M:%S}] callback: {cb['data']}")
                handle_callback(cb["data"], chat_id)
            elif "message" in upd:
                msg = upd["message"]
                if msg and "text" in msg:
                    print(f"[{datetime.now():%H:%M:%S}] msg: {msg['text']}")
                    handle(msg)
        except Exception:
            print(traceback.format_exc())

    if max_update_id:
        # Подтверждаем получение перед выходом (short-poll, без ожидания) — иначе
        # следующий запуск (новый процесс, offset в памяти не сохраняется) получит
        # те же апдейты повторно.
        tg_get_updates(max_update_id + 1, timeout=0)

if __name__ == "__main__":
    main()
