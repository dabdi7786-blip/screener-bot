"""
Запускай вручную на своей машине, когда IB Gateway (через IBC) поднят и залогинен —
не постоянный демон, а "освежить данные когда удобно". Подключается к Gateway
напрямую на localhost, без сети наружу и без бриджа. Пишет ibkr_snapshot.json
в корень репозитория; GitHub Actions на своём расписании подхватывает этот файл
через ibkr_fetcher.get_ibkr_data() — так что дашборд свеж настолько, насколько
давно ты последний раз запускал этот скрипт.

Зависимость (только локально — в requirements.txt для GitHub Actions её нет
намеренно, CI этот скрипт не запускает и Gateway ему не нужен):
    pip install ib_async

Использование:
    python3 ibkr_local_fetch.py            # фетч + запись файла
    python3 ibkr_local_fetch.py --push      # + git add/commit/push
"""
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ib_async import IB, Stock

IB_HOST      = "127.0.0.1"
IB_PORT      = 4002  # paper; 4001 — live (отдельное решение, не по умолчанию)
IB_CLIENT_ID = 7

# Отредактируй под себя — список тикеров для котировок через IBKR.
WATCHLIST = ["AAPL", "MSFT", "SPY"]

SNAPSHOT_FILE = Path(__file__).parent / "ibkr_snapshot.json"


def _clean(val):
    """IB API отдаёт -1 или NaN как 'нет данных' — приводим к None,
    чтобы downstream (Telegram/дашборд) не путал это с реальной ценой."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return val
    if f != f or f < 0:  # NaN или -1
        return None
    return f


async def fetch() -> tuple[dict, dict, list]:
    ib = IB()
    await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=15)
    # Свежий paper-аккаунт обычно без live market data subscription —
    # переключаемся на delayed (тип 3), иначе reqTickers падает с ошибкой 10089.
    ib.reqMarketDataType(3)

    quotes = {}
    for sym in WATCHLIST:
        try:
            contract = Stock(sym, "SMART", "USD")
            await ib.qualifyContractsAsync(contract)
            [ticker] = await ib.reqTickersAsync(contract)
            quotes[sym] = {
                "bid": _clean(ticker.bid), "ask": _clean(ticker.ask),
                "last": _clean(ticker.last), "close": _clean(ticker.close),
            }
        except Exception as e:
            print(f"quote {sym}: {e}")

    account = {}
    try:
        wanted = {"NetLiquidation", "TotalCashValue", "BuyingPower", "UnrealizedPnL"}
        for row in await ib.accountSummaryAsync():
            if row.tag in wanted:
                account[row.tag] = row.value
    except Exception as e:
        print(f"account: {e}")

    positions = []
    try:
        for p in await ib.reqPositionsAsync():
            positions.append({
                "symbol": p.contract.symbol,
                "position": p.position,
                "avg_cost": p.avgCost,
            })
    except Exception as e:
        print(f"positions: {e}")

    ib.disconnect()
    return quotes, account, positions


def main():
    quotes, account, positions = asyncio.run(fetch())

    snapshot = {
        "fetched_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "quotes": quotes,
        "account": account,
        "positions": positions,
    }
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"Записал {SNAPSHOT_FILE}")

    if "--push" in sys.argv:
        repo_dir = Path(__file__).parent
        subprocess.run(["git", "add", str(SNAPSHOT_FILE)], cwd=repo_dir, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir).returncode == 0:
            print("Нет изменений — коммитить нечего")
            return
        subprocess.run(["git", "commit", "-m", "chore: update ibkr snapshot"], cwd=repo_dir, check=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print("Закоммитил и запушил снэпшот")


if __name__ == "__main__":
    main()
