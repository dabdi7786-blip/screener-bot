"""
Запускай вручную на своей машине, когда IB Gateway (через IBC) поднят и залогинен.
Забирает заявки, поставленные командой /buy в Telegram и подтверждённые там же
кнопкой «✅ Подтвердить» (bot_server.py переводит их в статус "confirmed" и
коммитит pending_orders.json) — и исполняет через IB Gateway. Подтверждение
происходит в Telegram, этот скрипт сам по себе ничего не спрашивает и не решает,
только исполняет уже подтверждённое.

Только paper-аккаунт (порт 4002) — жёсткая проверка ниже, скрипт откажется
работать на 4001 (live). Переход на live — отдельное решение, не через этот
скрипт по умолчанию.

Зависимость (только локально, как и у ibkr_local_fetch.py):
    pip install ib_async

Использование:
    python3 ibkr_local_execute.py
"""
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from ib_async import IB, MarketOrder, Stock
import requests

REPO_DIR = Path(__file__).parent
load_dotenv(REPO_DIR / ".env")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

IB_HOST      = "127.0.0.1"
IB_PORT      = 4002  # paper — см. проверку в main(), скрипт не пойдёт на 4001
IB_CLIENT_ID = 8

ORDERS_FILE = REPO_DIR / "pending_orders.json"

FILL_WAIT_SECONDS = 10  # сколько ждать подтверждения filled, прежде чем пометить "submitted"


def tg_send(text: str):
    if not TELEGRAM_TOKEN:
        print(f"[TG] {text}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG send error] {e}")


def load_orders() -> list:
    if ORDERS_FILE.exists():
        return json.loads(ORDERS_FILE.read_text())
    return []


def save_orders(orders: list):
    ORDERS_FILE.write_text(json.dumps(orders, ensure_ascii=False, indent=2))


async def execute_order(ib: IB, order: dict) -> None:
    symbol, qty = order["symbol"], order["qty"]
    try:
        contract = Stock(symbol, "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        market_order = MarketOrder("BUY", qty)
        trade = ib.placeOrder(contract, market_order)

        for _ in range(FILL_WAIT_SECONDS):
            await asyncio.sleep(1)
            if trade.isDone():
                break

        status = trade.orderStatus.status
        if status == "Filled":
            order["status"]      = "executed"
            order["fill_price"]  = trade.orderStatus.avgFillPrice
            order["executed_at"] = datetime.now().isoformat(timespec="seconds")
            tg_send(f"✅ Заявка #{order['id']} исполнена: BUY {qty} {symbol} @ {order['fill_price']} (paper)")
        else:
            order["status"] = "submitted"
            order["note"]   = f"IB status: {status} — не подтверждён filled за {FILL_WAIT_SECONDS}с"
            tg_send(f"⏳ Заявка #{order['id']} отправлена (BUY {qty} {symbol}), но ещё не filled: {status} (paper)")
    except Exception as e:
        order["status"] = "failed"
        order["note"]   = str(e)
        tg_send(f"❌ Заявка #{order['id']} не исполнена: BUY {qty} {symbol} — {e}")


async def run(confirmed: list):
    ib = IB()
    await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=15)
    try:
        for order in confirmed:
            print(f"Исполняю заявку #{order['id']}: BUY {order['qty']} {order['symbol']} "
                  f"(подтверждена в Telegram, поставлена {order['queued_at']})")
            await execute_order(ib, order)
    finally:
        ib.disconnect()


def main():
    if IB_PORT != 4002:
        print("Отказ: этот скрипт настроен только на paper (порт 4002). "
              "Переход на live — отдельное решение, не через дефолтные настройки этого файла.")
        sys.exit(1)

    subprocess.run(["git", "pull", "--rebase"], cwd=REPO_DIR, check=True)

    orders    = load_orders()
    confirmed = [o for o in orders if o["status"] == "confirmed"]
    if not confirmed:
        print("Нет подтверждённых заявок (status=confirmed) — подтверди кнопкой в Telegram сначала.")
        return

    asyncio.run(run(confirmed))
    save_orders(orders)

    subprocess.run(["git", "add", str(ORDERS_FILE)], cwd=REPO_DIR, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR).returncode != 0:
        subprocess.run(["git", "commit", "-m", "chore: update order status"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
        print("Статус заявок закоммичен и запушен.")


if __name__ == "__main__":
    main()
