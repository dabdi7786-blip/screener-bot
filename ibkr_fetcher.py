"""
IBKR — читает ibkr_snapshot.json, который отдельным скриптом (ibkr_local_fetch.py)
пишет и коммитит в репозиторий с локальной машины, где запущен IB Gateway.
Никакой сети/бриджа здесь нет — GitHub Actions не имеет доступа к живому Gateway,
поэтому данные настолько свежие, насколько давно ты последний раз запускал
ibkr_local_fetch.py локально. Паттерн как у rates_fetcher.py: никогда не бросает
исключений наружу, при отсутствии/битом файле возвращает пустые значения.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SNAPSHOT_FILE = Path(__file__).parent / "ibkr_snapshot.json"


def get_ibkr_data() -> dict:
    """{"fetched_at": "...", "quotes": {...}, "account": {...}, "positions": [...]}"""
    if not SNAPSHOT_FILE.exists():
        log.warning("%s не найден — IBKR ещё ни разу не фетчился локально", SNAPSHOT_FILE.name)
        return {}
    try:
        data = json.loads(SNAPSHOT_FILE.read_text())
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        log.warning("Не удалось прочитать %s: %s", SNAPSHOT_FILE.name, e)
        return {}


# ── Formatter (для Telegram) ───────────────────────────────────────────────────

def _v(val, fmt=".2f", suffix="") -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):{fmt}}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def build_ibkr_message(ibkr: dict) -> str | None:
    """Возвращает None, если снэпшота ещё нет вообще — тогда в Telegram
    просто не шлём блок IBKR."""
    if not ibkr:
        return None

    quotes    = ibkr.get("quotes", {})
    account   = ibkr.get("account", {})
    positions = ibkr.get("positions", [])
    fetched_at = ibkr.get("fetched_at")

    if not quotes and not account and not positions:
        return None

    header = "🏦 <b>INTERACTIVE BROKERS</b>"
    if fetched_at:
        header += f"  <i>(снэпшот от {fetched_at})</i>"
    lines = [header, ""]

    lines.append("📈 <b>КОТИРОВКИ</b>")
    if quotes:
        for sym, q in quotes.items():
            last = q.get("last") if q.get("last") is not None else q.get("close")
            lines.append(f"  {sym}:  <code>{_v(last)}</code>  (bid {_v(q.get('bid'))} / ask {_v(q.get('ask'))})")
    else:
        lines.append("  <i>данные недоступны</i>")

    lines.append("")
    lines.append("💼 <b>СЧЁТ</b>")
    if account:
        net  = account.get("NetLiquidation")
        cash = account.get("TotalCashValue")
        bp   = account.get("BuyingPower")
        pnl  = account.get("UnrealizedPnL")
        if net  is not None: lines.append(f"  NetLiquidation:  <code>{_v(net)}</code>")
        if cash is not None: lines.append(f"  Cash:            <code>{_v(cash)}</code>")
        if bp   is not None: lines.append(f"  Buying power:    <code>{_v(bp)}</code>")
        if pnl  is not None: lines.append(f"  Unrealized P&L:  <code>{_v(pnl)}</code>")
    else:
        lines.append("  <i>данные недоступны</i>")

    lines.append("")
    lines.append("📊 <b>ПОЗИЦИИ</b>")
    if positions:
        for p in positions:
            lines.append(f"  {p.get('symbol')}:  <code>{_v(p.get('position'), 'g')}</code> @ {_v(p.get('avg_cost'))}")
    else:
        lines.append("  <i>нет открытых позиций / данные недоступны</i>")

    return "\n".join(lines)
