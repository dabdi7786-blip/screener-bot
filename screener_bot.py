"""
Stock Screener Bot — 3 скринера + уведомления в Telegram
  1. Future S&P Leaders+ — будущие лидеры S&P: рост >15%, PEG<2, Rule40>40
  2. Growth v2           — быстрорастущие акции, топ-8 по скору с sector cap
  3. Compounder          — долгосрочные победители: ROIC>15%, FCF>10%, GM>50%
Запуск: python screener_bot.py
Cron:   0 8 * * 1-5  (пн-пт в 08:00)
"""

import os, time, json, math
from io import StringIO
from datetime import datetime
from pathlib import Path

import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")

# ── S&P 500 return cache (вычисляется один раз за сессию) ──────────────────
_SP500_CACHE: dict = {"return_1y": None}

def _get_sp500_1y_return() -> float:
    if _SP500_CACHE["return_1y"] is not None:
        return _SP500_CACHE["return_1y"]
    try:
        hist = yf.Ticker("^GSPC").history(period="1y", auto_adjust=True)
        if hist.empty or len(hist) < 5:
            return 0.0
        s = hist["Close"].dropna()
        ret = round((float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100, 1)
        _SP500_CACHE["return_1y"] = ret
        return ret
    except Exception:
        return 0.0
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Telegram ───────────────────────────────────────────────────────────────

def tg_send(text: str):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        }, timeout=10)
        if not resp.ok:
            print(f"[Telegram] Ошибка: {resp.text}")

# ── Получение тикеров S&P 500 ──────────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; StockScreener/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    df = pd.read_html(StringIO(resp.text))[0]
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()

# ── Вычисление изменений цен из истории ───────────────────────────────────

def _price_changes(t: yf.Ticker) -> dict:
    try:
        hist = t.history(period="1y", auto_adjust=True)
        if hist.empty or len(hist) < 5:
            return {}
        s = hist["Close"].dropna()
        today = s.index[-1]
        cur   = float(s.iloc[-1])

        def pct(offset):
            target = today - offset
            pos = s.index.searchsorted(target)
            pos = max(0, min(pos, len(s) - 1))
            ref = float(s.iloc[pos])
            return round((cur / ref - 1) * 100, 1) if ref > 0 else None

        return {
            "chg_1m": pct(pd.DateOffset(months=1)),
            "chg_6m": pct(pd.DateOffset(months=6)),
            "chg_1y": pct(pd.DateOffset(years=1)),
        }
    except Exception:
        return {}

# ── EPS акселерация (квартальный рост > TTM рост) ────────────────────────

def _eps_acceleration(info: dict) -> bool:
    """True если квартальный EPS-рост ускоряется относительно TTM."""
    try:
        ttm   = info.get("earningsGrowth") or 0
        qtrly = info.get("earningsQuarterlyGrowth") or 0
        return bool(qtrly > 0 and ttm > 0 and qtrly > ttm)
    except Exception:
        return False

# ── ROIC (NOPAT / invested capital, market-based) ─────────────────────────

def _compute_roic(op_margin: float, revenue: float,
                  total_debt: float, total_cash: float,
                  book_equity: float) -> float:
    nopat = op_margin * revenue * 0.79          # ~21% US effective tax
    invested_capital = book_equity + total_debt - total_cash
    # Отрицательный капитал (агрессивные байбэки, e.g. AAPL) — используем долг как пол
    if invested_capital < 1e6:
        invested_capital = max(total_debt - total_cash, 1e6)
    return round(nopat / invested_capital * 100, 1) if invested_capital > 1e6 else 0.0

# ── Загрузка фундаментальных данных ───────────────────────────────────────

CONSENSUS_LABEL = {
    "strong_buy":  "Strong Buy",
    "buy":         "Buy",
    "hold":        "Hold",
    "sell":        "Sell",
    "strong_sell": "Strong Sell",
    "underperform":"Underperform",
    "outperform":  "Outperform",
}

def fetch_info(ticker: str) -> dict | None:
    try:
        t    = yf.Ticker(ticker)
        info = t.info
        if not info or info.get("quoteType") != "EQUITY":
            return None
        prices = _price_changes(t)

        cap          = info.get("marketCap") or 0
        rev_growth   = info.get("revenueGrowth") or 0
        eps_growth   = info.get("earningsGrowth") or 0
        gross_margin = info.get("grossMargins") or 0
        op_margin    = info.get("operatingMargins") or 0
        net_margin   = info.get("profitMargins") or 0
        peg          = info.get("pegRatio")
        fwd_pe       = info.get("forwardPE")
        trailing_pe  = info.get("trailingPE")
        debt_eq      = info.get("debtToEquity")
        ev_ebitda    = info.get("enterpriseToEbitda")
        roe          = info.get("returnOnEquity") or 0
        price        = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        high_52w     = info.get("fiftyTwoWeekHigh") or 0
        fcf          = info.get("freeCashflow") or 0
        revenue      = info.get("totalRevenue") or 1
        total_cash   = info.get("totalCash") or 0
        total_debt   = info.get("totalDebt") or 0
        enterprise_v = info.get("enterpriseValue") or 0
        div_yield    = info.get("dividendYield") or 0
        fwd_eps      = info.get("forwardEps")
        trailing_eps = info.get("trailingEps")

        fcf_margin   = fcf / revenue
        # Rule of 40 = Revenue Growth % + Operating Margin %
        rule40       = (rev_growth + op_margin) * 100
        pct_off_high = round((high_52w - price) / high_52w * 100, 1) if high_52w > 0 else 0
        fcf_yield    = round(fcf / cap * 100, 2) if cap > 0 and fcf > 0 else 0.0
        ev_fcf       = round(enterprise_v / fcf, 1) if enterprise_v > 0 and fcf > 0 else None
        # ROIC по балансовой стоимости (Book Equity + Debt - Cash)
        book_value_ps = info.get("bookValue") or 0
        shares_out    = info.get("sharesOutstanding") or 0
        book_equity   = book_value_ps * shares_out
        roic          = _compute_roic(op_margin, revenue, total_debt, total_cash, book_equity)
        # Buyback yield ≈ (FCF − estimated dividends) / MarketCap
        est_divs     = (div_yield * cap) if div_yield else 0
        buyback_y    = round(max(0.0, fcf - est_divs) / cap * 100, 2) if cap > 0 else 0.0
        # Forward vs Trailing PE discount (proxy for historical PE discount)
        pe_discount  = round((trailing_pe - fwd_pe) / trailing_pe * 100, 1) \
                       if trailing_pe and fwd_pe and trailing_pe > 0 and fwd_pe > 0 else None

        # Аналитики и цели
        rec_key     = info.get("recommendationKey", "")
        rec_mean    = info.get("recommendationMean")
        n_analysts  = info.get("numberOfAnalystOpinions") or 0
        consensus   = CONSENSUS_LABEL.get(rec_key, rec_key.replace("_", " ").title() if rec_key else "N/A")
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low  = info.get("targetLowPrice")
        upside      = round((target_mean / price - 1) * 100, 1) if target_mean and price else None

        beta          = info.get("beta")
        ps_ratio      = info.get("priceToSalesTrailingTwelveMonths")
        current_ratio = info.get("currentRatio")
        _sp_raw       = info.get("shortPercentOfFloat")
        short_pct     = _sp_raw if (_sp_raw and not math.isnan(float(_sp_raw))) else None
        short_ratio   = info.get("shortRatio")
        insider_pct   = info.get("heldPercentInsiders") or 0
        inst_pct      = info.get("heldPercentInstitutions") or 0

        eps_accel     = _eps_acceleration(info)
        sp500_1y      = _get_sp500_1y_return()
        chg_1y        = prices.get("chg_1y")
        rs_rank       = round(chg_1y - sp500_1y, 1) if chg_1y is not None else None

        earnings_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
        if earnings_ts:
            from datetime import timezone
            earnings_date = datetime.fromtimestamp(earnings_ts, tz=timezone.utc).strftime("%d.%m.%Y")
        else:
            earnings_date = None

        return {
            "Ticker":         ticker,
            "Name":           info.get("shortName", ""),
            "Sector":         info.get("sector", ""),
            "MarketCap_B":    round(cap / 1e9, 1),
            "Price":          round(price, 2),
            "RevGrowth_%":    round(rev_growth * 100, 1),
            "EPSGrowth_%":    round(eps_growth * 100, 1),
            "GrossMargin_%":  round(gross_margin * 100, 1),
            "OpMargin_%":     round(op_margin * 100, 1),
            "NetMargin_%":    round(net_margin * 100, 1),
            "FCFMargin_%":    round(fcf_margin * 100, 1),
            "Rule40":         round(rule40, 1),
            "ROIC_%":         roic,
            "FCFYield_%":     fcf_yield,
            "EV_FCF":         ev_fcf,
            "BuybackYield_%": buyback_y,
            "PEDiscount_%":   pe_discount,
            "PEG":            round(peg, 2) if peg else None,
            "ForwardPE":      round(fwd_pe, 1) if fwd_pe else None,
            "TrailingPE":     round(trailing_pe, 1) if trailing_pe else None,
            "ForwardEPS":     round(fwd_eps, 2) if fwd_eps else None,
            "TrailingEPS":    round(trailing_eps, 2) if trailing_eps else None,
            "PS_Ratio":       round(ps_ratio, 2) if (ps_ratio and not math.isnan(float(ps_ratio))) else None,
            "EV_EBITDA":      round(ev_ebitda, 1) if ev_ebitda else None,
            "Debt/Equity_%":  round(debt_eq, 1) if debt_eq is not None else None,
            "ROE_%":          round(roe * 100, 1),
            "PctOffHigh_%":   pct_off_high,
            "Beta":           round(beta, 2) if beta else None,
            "Cash_B":         round(total_cash / 1e9, 2),
            "Debt_B":         round(total_debt / 1e9, 2),
            "DivYield_%":     round(div_yield * 100, 2),
            "CurrentRatio":   round(current_ratio, 2) if current_ratio else None,
            "ShortPct_%":     round(short_pct * 100, 1) if short_pct else None,
            "ShortRatio":     round(short_ratio, 1) if short_ratio else None,
            "EPSAccel":       eps_accel,
            "RS_Rank":        rs_rank,
            "InsiderPct_%":   round(insider_pct * 100, 1),
            "InstPct_%":      round(inst_pct * 100, 1),
            "Chg1m_%":        prices.get("chg_1m"),
            "Chg6m_%":        prices.get("chg_6m"),
            "Chg1y_%":        prices.get("chg_1y"),
            "Consensus":      consensus,
            "Analysts":       int(n_analysts),
            "RecMean":        round(rec_mean, 2) if rec_mean else None,
            "TargetMean":     round(target_mean, 2) if target_mean else None,
            "TargetHigh":     round(target_high, 2) if target_high else None,
            "TargetLow":      round(target_low, 2) if target_low else None,
            "Upside_%":       upside,
            "EarningsDate":   earnings_date,
        }
    except Exception:
        return None

# ── Технический анализ ────────────────────────────────────────────────────

def _last_earnings_close(tk: "yf.Ticker", hist: pd.DataFrame) -> tuple:
    """Дата и цена закрытия на последний ФАКТИЧЕСКИ прошедший отчёт (не следующий ожидаемый)."""
    try:
        ed = tk.get_earnings_dates(limit=8)
        if ed is None or ed.empty:
            return None, None
        reported = ed[ed["Reported EPS"].notna()]
        if reported.empty:
            return None, None
        last_date = reported.index.max()
        idx    = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
        target = last_date.tz_localize(None) if last_date.tzinfo is not None else last_date
        pos = idx.searchsorted(target)
        pos = max(0, min(pos, len(hist) - 1))
        close = float(hist["Close"].iloc[pos])
        return target.strftime("%d.%m.%Y"), round(close, 2)
    except Exception:
        return None, None


def get_ta(ticker: str) -> dict:
    try:
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="1y", auto_adjust=True)
        if hist.empty or len(hist) < 50:
            return {}

        close = hist["Close"]
        high  = hist["High"]
        low   = hist["Low"]
        price = float(close.iloc[-1])

        ma50  = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = round(float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1])), 1)

        tr  = pd.concat([high - low,
                         (high - close.shift()).abs(),
                         (low  - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])

        macd_line   = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_bull   = float(macd_line.iloc[-1]) > float(macd_signal.iloc[-1])

        support    = round(float(low.rolling(20).min().iloc[-1]), 2)
        resistance = round(float(high.rolling(20).max().iloc[-1]), 2)

        if ma200:
            if price > ma50 and price > ma200:
                trend = "⬆️ Восходящий"
            elif price > ma50 and price < ma200:
                trend = "↗️ Восстановление"
            elif price < ma50 and price > ma200:
                trend = "↘️ Откат"
            else:
                trend = "⬇️ Нисходящий"
        else:
            trend = "⬆️ Выше MA50" if price > ma50 else "⬇️ Ниже MA50"

        if rsi >= 70:   rsi_lbl = "🔴 перекуплен"
        elif rsi >= 55: rsi_lbl = "🟢 бычий"
        elif rsi >= 45: rsi_lbl = "🟡 нейтральный"
        elif rsi >= 30: rsi_lbl = "🟠 медвежий"
        else:           rsi_lbl = "🟢 перепродан"

        entry = round(price, 2)
        sl    = round(entry - 1.5 * atr, 2)
        risk  = entry - sl
        tp1   = round(entry + 2 * risk, 2)
        tp2   = round(entry + 3 * risk, 2)

        def pct(a, b): return f"{round((b/a-1)*100, 1):+.1f}%"

        earn_date, earn_close = _last_earnings_close(tk, hist)

        return {
            "price":      round(price, 2),
            "ma50":       round(ma50, 2),
            "ma200":      round(ma200, 2) if ma200 else None,
            "rsi":        rsi,
            "rsi_lbl":    rsi_lbl,
            "atr":        round(atr, 2),
            "trend":      trend,
            "macd":       "📈 бычий" if macd_bull else "📉 медвежий",
            "support":    support,
            "resistance": resistance,
            "entry":      entry,
            "sl":         sl,   "sl_pct":  pct(entry, sl),
            "tp1":        tp1,  "tp1_pct": pct(entry, tp1),
            "tp2":        tp2,  "tp2_pct": pct(entry, tp2),
            "earn_date":  earn_date,
            "earn_close": earn_close,
        }
    except Exception as e:
        print(f"[TA {ticker}] {e}")
        return {}

# ── Фильтры скринеров ──────────────────────────────────────────────────────

def screener1(r: dict) -> bool:
    """Future S&P Leaders+: mid-cap ($10B-$200B) быстрорастущие + качество."""
    if r.get("Ticker") in DEDUP_SKIP:
        return False
    peg = r.get("PEG")
    fpe = r.get("ForwardPE")
    de  = r.get("Debt/Equity_%")
    upside = r.get("Upside_%")
    if upside is not None and upside < 0:
        return False
    return (
        10 <= r["MarketCap_B"] <= 200
        and r["RevGrowth_%"] > 15
        and r["EPSGrowth_%"] > 15
        and r["GrossMargin_%"] > 50
        and r["Rule40"] > 40
        and peg is not None and 0 < peg < 2
        and fpe is not None and fpe < 40
        and (de is None or de < 150)
    )

def screener_growth(r: dict) -> bool:
    """Growth Scanner v2: быстрорастущие компании — улучшенные фильтры."""
    if r.get("Ticker") in DEDUP_SKIP:
        return False
    upside = r.get("Upside_%")
    # Отсекаем акции, у которых цель аналитиков уже ниже текущей цены
    if upside is not None and upside < 0:
        return False
    return (
        r["RevGrowth_%"] > 15
        and r["EPSGrowth_%"] > 20
        and r["Rule40"] > 40
        and r["GrossMargin_%"] > 40
    )

def screener_compounder(r: dict) -> bool:
    """Compounder Scanner: долгосрочные победители."""
    roic = r.get("ROIC_%") or 0
    fcf_margin = r.get("FCFMargin_%") or 0
    return (
        roic > 15
        and fcf_margin > 10
        and r["GrossMargin_%"] > 50
        and r["EPSGrowth_%"] > 10
    )

# ── AI и Moat константы ────────────────────────────────────────────────────

# Дублирующие тикеры (вторые классы акций того же эмитента) — пропускаем
DEDUP_SKIP = frozenset({
    "GOOG",   # дубль GOOGL
    "MU",     # yfinance даёт аномальные данные по ценовой истории (сплит-артефакт)
})

AI_TICKERS = frozenset({
    "NVDA", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "AMD",  "AVGO", "ORCL",
    "CRM",  "SNOW", "PLTR",  "ANET", "ARM",  "MRVL", "QCOM", "MU",   "IBM",
    "PANW", "CRWD", "ZS",    "NOW",  "ADBE", "DDOG", "NET",  "TSM",  "SMCI",
})

# Ширина рва: 5 = очень широкий, 4 = широкий, 3 = умеренный
MOAT_SCORES = {
    "MSFT": 5, "V": 5, "MA": 5, "AAPL": 5, "GOOGL": 5, "GOOG": 5,
    "META": 4, "AMZN": 4, "NVDA": 4, "AVGO": 4, "UNH": 4, "COST": 4,
    "INTU": 4, "NOW":  4, "LLY": 4,
    "JPM":  3, "BRK-B": 3, "HD": 3, "NKE": 3,
    "ADBE": 3, "CRM": 3, "NFLX": 3, "JNJ": 3, "ABT": 3,
}

# ── Скоринг ────────────────────────────────────────────────────────────────

SC1_CATS    = ["Рост", "Качество+", "Оценка+", "Моментум", "Аналитики", "Риск+"]
GROWTH_CATS = ["Рост", "Качество", "Оценка", "Моментум", "Риск", "AI"]
COMP_CATS   = ["ROIC", "FCF Маржа", "EPS Рост", "Байбэк", "Моат", "Моментум"]

CAT_EMOJI = {
    # Screener 1
    "Рост":        "📊", "Качество+":   "💎", "Оценка+":    "🏷️",
    "Аналитики":   "👥", "Риск+":       "⚠️",
    # Screener 2 (unified 6-block)
    "Качество":    "💎", "Оценка":      "🏷️", "Риск":       "⚡",
    "AI":          "🤖",
    # Shared
    "Моментум":    "📈",
    # Screener 3
    "ROIC":        "🔄", "FCF Маржа":   "💎", "EPS Рост":   "📈",
    "Байбэк":      "🔁", "Моат":        "🏰",
}

def score_sc1(row: dict, ta: dict = None) -> dict:
    """Future S&P Leaders+ v2 — 6 блоков, unified с Growth.
    Макс. raw: Рост 10 + Качество+ 9 + Оценка+ 8 + Аналитики 6 + Моментум 8 + Риск+ 6 = 47
    Практический макс хорошего mid-cap ≈ 32
    """
    s = {}

    # ── 📊 РОСТ (max 10) ────────────────────────────────────────────────────
    eps = row.get("EPSGrowth_%") or 0
    rev = row.get("RevGrowth_%") or 0
    r40 = row.get("Rule40") or 0
    g = 0
    g += 4 if eps > 50 else 3 if eps > 25 else 1 if eps > 15 else 0
    g += 3 if rev > 30 else 2 if rev > 20 else 1 if rev > 15 else 0
    g += 2 if r40 > 60 else 1 if r40 > 40 else 0
    if row.get("EPSAccel"):
        g += 2
    s["Рост"] = min(g, 10)

    # ── 💎 КАЧЕСТВО+ (max 9) ────────────────────────────────────────────────
    gm    = row.get("GrossMargin_%") or 0
    fcf_m = row.get("FCFMargin_%") or 0
    roic  = row.get("ROIC_%") or 0
    fcf_y = row.get("FCFYield_%") or 0
    q = 0
    q += 2 if gm > 70 else 1 if gm > 55 else 0
    q += 2 if fcf_m > 20 else 1 if fcf_m > 10 else -1 if fcf_m < 0 else 0
    q += 3 if fcf_y > 8 else 2 if fcf_y > 5 else 1 if fcf_y > 3 else 0
    q += 2 if roic > 25 else 1 if roic > 15 else 0
    s["Качество+"] = q

    # ── 🏷️ ОЦЕНКА+ (max 8) ─────────────────────────────────────────────────
    peg    = row.get("PEG")
    fpe    = row.get("ForwardPE")
    pe_disc = row.get("PEDiscount_%")
    ev_fcf = row.get("EV_FCF")
    v = 0
    if peg:     v += 2 if peg < 0.75 else 1 if peg < 1.5 else -1 if peg > 2.5 else 0
    if fpe:     v += 2 if fpe < 15   else 1 if fpe < 25   else -1 if fpe > 35  else 0
    if pe_disc is not None: v += 2 if pe_disc > 25 else 1 if pe_disc > 10 else 0
    if ev_fcf and ev_fcf > 0: v += 2 if ev_fcf < 20 else 1 if ev_fcf < 30 else 0
    s["Оценка+"] = v

    # ── 👥 АНАЛИТИКИ (max 6) ────────────────────────────────────────────────
    cons   = row.get("Consensus", "")
    upside = row.get("Upside_%")
    n_an   = row.get("Analysts") or 0
    a = 0
    a += 2 if cons == "Strong Buy" else 1 if cons in ("Buy", "Outperform") else -1 if "Sell" in cons else 0
    if upside is not None:
        a += 3 if upside > 40 else 2 if upside > 20 else -1 if upside < 5 else 0
    a += 1 if n_an >= 15 else 0
    s["Аналитики"] = min(a, 6)

    # ── 📈 МОМЕНТУМ (max 8) ─────────────────────────────────────────────────
    rs    = row.get("RS_Rank")
    chg1y = row.get("Chg1y_%")
    chg1m = row.get("Chg1m_%")
    m = 0
    if rs is not None:
        m += 4 if rs > 20 else 3 if rs > 5 else 1 if rs > 0 else -2
    elif chg1y is not None:
        m += 3 if chg1y > 20 else 1 if chg1y > 0 else -2 if chg1y < -40 else -1
    if chg1m is not None:
        m += 2 if chg1m > 5 else 1 if chg1m > 0 else -1 if chg1m < -15 else 0
    if ta:
        trend = ta.get("trend", "")
        macd  = ta.get("macd", "")
        rsi   = ta.get("rsi", 50)
        if "Восходящий" in trend and "бычий" in macd:
            m += 2
        elif "Нисходящий" in trend and "медвежий" in macd:
            m -= 2
        if 45 <= rsi <= 65:
            m += 1
    s["Моментум"] = min(max(m, -4), 8)

    # ── ⚠️ РИСК+ (max 6) ───────────────────────────────────────────────────
    net_cash = (row.get("Cash_B") or 0) - (row.get("Debt_B") or 0)
    beta     = row.get("Beta")
    short    = row.get("ShortPct_%")
    r = 0
    r += 2 if net_cash > 0 else -1 if net_cash < -5 else 0
    if short is not None:
        r += 1 if short < 2 else -1 if short > 7 else -2 if short > 15 else 0
    if beta:
        r += 2 if beta < 1.0 else 1 if beta < 1.5 else -1 if beta > 2.0 else 0
    r += 1 if (row.get("BuybackYield_%") or 0) > 3 else 0
    s["Риск+"] = min(r, 6)

    raw = sum(v for k, v in s.items() if k != "total")
    # Практический максимум ≈ 28 (качественный mid-cap с ростом + консенсусом Buy + momentum)
    s["total"] = max(0, min(10, round(raw / 28 * 10)))
    return s


def score_value(row: dict, ta: dict = None) -> dict:
    s = {}
    # FCF Yield (25%)
    fcf_y = row.get("FCFYield_%") or 0
    s["FCF Yield"] = 7 if fcf_y > 10 else 5 if fcf_y > 8 else 3 if fcf_y > 5 else 1 if fcf_y > 3 else 0
    # EV/FCF (20%)
    ev_fcf = row.get("EV_FCF")
    if ev_fcf and ev_fcf > 0:
        s["EV/FCF"] = 5 if ev_fcf < 15 else 3 if ev_fcf < 20 else 1 if ev_fcf < 25 else 0
    else:
        s["EV/FCF"] = 0
    # PE Discount: Forward vs Trailing PE (20%)
    pe_disc = row.get("PEDiscount_%")
    fpe     = row.get("ForwardPE")
    if pe_disc is not None:
        s["PE Дисконт"] = 5 if pe_disc > 25 else 3 if pe_disc > 15 else 1 if pe_disc > 5 else 0
    elif fpe and fpe > 0:
        s["PE Дисконт"] = 4 if fpe < 12 else 2 if fpe < 18 else 1 if fpe < 25 else 0
    else:
        s["PE Дисконт"] = 0
    # EPS Growth (15%)
    eps = row.get("EPSGrowth_%") or 0
    s["EPS Рост"] = 4 if eps > 30 else 3 if eps > 20 else 2 if eps > 10 else 1 if eps > 0 else 0
    # ROIC (15%)
    roic = row.get("ROIC_%") or 0
    s["ROIC"] = 4 if roic > 30 else 3 if roic > 20 else 2 if roic > 15 else 1 if roic > 10 else 0
    # Net Cash / Debt (5%)
    net_cash = (row.get("Cash_B") or 0) - (row.get("Debt_B") or 0)
    s["Долг"] = 3 if net_cash > 0 else 1 if net_cash > -2 else 0
    s["total"] = sum(v for k, v in s.items() if k != "total")
    return s


def score_growth(row: dict, ta: dict = None) -> dict:
    """Growth Scanner v2 — unified 6-block scoring.
    Макс. raw: Рост 30 + Качество 25 + Оценка 20 + Моментум 15 + Риск 10 + AI 5 = 105
    """
    s = {}

    # ── 📊 РОСТ (max 30) ────────────────────────────────────────────────────
    eps = row.get("EPSGrowth_%") or 0
    rev = row.get("RevGrowth_%") or 0
    r40 = row.get("Rule40") or 0
    g = 0
    g += 10 if eps > 100 else 8 if eps > 50 else 6 if eps > 35 else 4 if eps > 20 else 2 if eps > 10 else 0
    g += 8 if rev > 30 else 6 if rev > 20 else 4 if rev > 15 else 2 if rev > 10 else 0
    g += 6 if r40 > 80 else 4 if r40 > 60 else 2 if r40 > 40 else 0
    if row.get("EPSAccel"):
        g += 6   # бонус за ускорение EPS
    s["Рост"] = min(g, 30)

    # ── 💎 КАЧЕСТВО (max 25) ────────────────────────────────────────────────
    gm    = row.get("GrossMargin_%") or 0
    fcf_m = row.get("FCFMargin_%") or 0
    roic  = row.get("ROIC_%") or 0
    q = 0
    q += 10 if gm > 80 else 7 if gm > 70 else 5 if gm > 60 else 3 if gm > 50 else 1 if gm > 40 else 0
    q += 8 if fcf_m > 25 else 6 if fcf_m > 15 else 3 if fcf_m > 8 else 0
    q += 7 if roic > 25 else 5 if roic > 15 else 2 if roic > 10 else 0
    s["Качество"] = min(q, 25)

    # ── 🏷️ ОЦЕНКА (max 20) ─────────────────────────────────────────────────
    peg    = row.get("PEG")
    upside = row.get("Upside_%")
    fcf_y  = row.get("FCFYield_%") or 0
    v = 0
    if peg and peg > 0:
        v += 8 if peg < 0.7 else 6 if peg < 1.0 else 4 if peg < 1.5 else 2 if peg < 2.0 else 0
    if upside is not None:
        v += 8 if upside > 50 else 6 if upside > 30 else 4 if upside > 15 else 1 if upside > 5 else 0
    v += 4 if fcf_y > 8 else 3 if fcf_y > 5 else 1 if fcf_y > 3 else 0
    s["Оценка"] = min(v, 20)

    # ── 📈 МОМЕНТУМ (max 15) ────────────────────────────────────────────────
    chg1y = row.get("Chg1y_%")
    chg1m = row.get("Chg1m_%")
    rs    = row.get("RS_Rank")
    m = 0
    if rs is not None:
        m += 6 if rs > 20 else 4 if rs > 5 else 2 if rs > 0 else -2
    elif chg1y is not None:
        m += 5 if chg1y > 20 else 3 if chg1y > 0 else -2
    if chg1m is not None:
        m += 3 if chg1m > 5 else 1 if chg1m > 0 else -1 if chg1m < -15 else 0
    if ta:
        trend = ta.get("trend", "")
        macd  = ta.get("macd", "")
        rsi   = ta.get("rsi", 50)
        if "Восходящий" in trend and "бычий" in macd:
            m += 4
        elif "Восстановление" in trend:
            m += 2
        elif "Нисходящий" in trend and "медвежий" in macd:
            m -= 3
        if 45 <= rsi <= 65:
            m += 2
    s["Моментум"] = min(max(m, -5), 15)

    # ── ⚡ РИСК (max 10) ────────────────────────────────────────────────────
    net_cash = (row.get("Cash_B") or 0) - (row.get("Debt_B") or 0)
    beta  = row.get("Beta")
    short = row.get("ShortPct_%")
    r = 0
    r += 4 if net_cash > 0 else 2 if net_cash > -5 else 0
    if beta:
        r += 3 if beta < 1.0 else 2 if beta < 1.5 else 1 if beta < 2.0 else 0
    if short is not None:
        r += 3 if short < 3 else 1 if short < 5 else 0
    s["Риск"] = min(r, 10)

    # ── 🤖 AI (max 5) ──────────────────────────────────────────────────────
    s["AI"] = 5 if row.get("Ticker") in AI_TICKERS else 0

    raw = sum(v for k, v in s.items() if k != "total")
    # Нормализация: практический максимум ≈ 70
    # (достигается лишь при отличных фундаменталах + росте + техническом подтверждении)
    s["total"] = max(0, min(10, round(raw / 70 * 10)))
    return s


def score_compounder(row: dict, ta: dict = None) -> dict:
    s = {}
    # ROIC (25%)
    roic = row.get("ROIC_%") or 0
    s["ROIC"] = 7 if roic > 40 else 5 if roic > 25 else 3 if roic > 15 else 0
    # FCF Margin (20%)
    fcf_m = row.get("FCFMargin_%") or 0
    s["FCF Маржа"] = 6 if fcf_m > 30 else 4 if fcf_m > 20 else 2 if fcf_m > 10 else 0
    # EPS Growth (20%)
    eps = row.get("EPSGrowth_%") or 0
    s["EPS Рост"] = 6 if eps > 30 else 4 if eps > 20 else 2 if eps > 10 else 0
    # Buyback Yield (15%)
    buyback_y = row.get("BuybackYield_%") or 0
    s["Байбэк"] = 4 if buyback_y > 5 else 3 if buyback_y > 3 else 1 if buyback_y > 1 else 0
    # Moat Score (10%)
    moat = MOAT_SCORES.get(row.get("Ticker", ""), 0)
    s["Моат"] = 3 if moat >= 5 else 2 if moat >= 4 else 1 if moat >= 3 else 0
    # Momentum (10%) — намеренно небольшой вес
    chg1y = row.get("Chg1y_%")
    s["Моментум"] = 3 if chg1y is not None and chg1y > 20 else 1 if chg1y is not None and chg1y > 0 else 0
    raw = sum(v for k, v in s.items() if k != "total")
    s["total"] = max(0, min(10, round(raw / 29 * 10)))  # 29 = теоретический макс
    return s

# ── Список скринеров ───────────────────────────────────────────────────────

SCREENERS = [
    {
        "id": 1, "name": "Future S&amp;P Leaders+", "emoji": "🚀",
        "fn": screener1,
        "sort": "Rule40",      "asc": False,
        "score_fn": score_sc1,
        "cats": SC1_CATS,      "max_score": 10,
    },
    {
        "id": 2, "name": "Growth v2",  "emoji": "📈",
        "fn": screener_growth,
        "sort": "Rule40",      "asc": False,
        "score_fn": score_growth,
        "cats": GROWTH_CATS,   "max_score": 10,
    },
    {
        "id": 3, "name": "Compounder", "emoji": "🏆",
        "fn": screener_compounder,
        "sort": "ROIC_%",      "asc": False,
        "score_fn": score_compounder,
        "cats": COMP_CATS,     "max_score": 10,
    },
]

TOP_N  = 8   # максимум акций в выводе каждого скринера
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# ── Формирование рейтинга ──────────────────────────────────────────────────

def _rank_and_cap(sc: dict, df: pd.DataFrame, ta_data: dict = None) -> list:
    """Скорит, сортирует, режет по TOP_N и (для SC2) по концентрации сектора."""
    score_fn = sc["score_fn"]
    all_scores = {}
    for _, row in df.iterrows():
        ta = (ta_data or {}).get(row["Ticker"], {})
        all_scores[row["Ticker"]] = score_fn(row.to_dict(), ta)

    ranked = sorted(all_scores.items(), key=lambda x: x[1]["total"], reverse=True)
    ranked = ranked[:TOP_N]

    # SC2: sector concentration cap (макс 3 из одного сектора)
    if sc["id"] == 2:
        max_per_sector = 3
        sector_count: dict[str, int] = {}
        filtered_ranked = []
        for tkr, sc_dict in ranked:
            rows = df[df["Ticker"] == tkr]["Sector"].values
            sector = str(rows[0]) if len(rows) > 0 else "Unknown"
            if sector_count.get(sector, 0) < max_per_sector:
                filtered_ranked.append((tkr, sc_dict))
                sector_count[sector] = sector_count.get(sector, 0) + 1
        ranked = filtered_ranked

    return ranked


def format_rating(sc: dict, ranked: list) -> str:
    """Компактная строка рейтинга для Telegram: только медали/тикеры/скор."""
    emoji, name, max_score = sc["emoji"], sc["name"], sc["max_score"]
    if not ranked:
        return f"{emoji} <b>{name}</b> (0): нет совпадений сегодня"
    parts = [
        f"{MEDALS.get(i, f'#{i}')}${ticker} {sc_dict['total']}/{max_score}"
        for i, (ticker, sc_dict) in enumerate(ranked, 1)
    ]
    return f"{emoji} <b>{name}</b> ({len(ranked)}): " + "  ".join(parts)


def run_scan(screener_ids: list) -> dict:
    """
    Фетчит S&P 500, фильтрует/скорит по каждому screener_id.
    Возвращает {sc_id: {"sc": sc_meta, "ranked": [...], "dashboard_rows": [...]}}.
    Никаких tg_send внутри — вызывающий сам решает, что и куда слать.
    """
    tickers = get_sp500_tickers()
    raw = []
    for i, t in enumerate(tickers, 1):
        if i % 50 == 0:
            print(f"[{i}/{len(tickers)}] тикеров обработано")
        info = fetch_info(t)
        if info:
            raw.append(info)
        time.sleep(0.15)
    df_all = pd.DataFrame(raw)

    result = {}
    for sc in SCREENERS:
        if sc["id"] not in screener_ids:
            continue

        passed = df_all[df_all.apply(sc["fn"], axis=1)].copy()
        passed.sort_values(sc["sort"], ascending=sc["asc"], inplace=True)
        passed.reset_index(drop=True, inplace=True)
        passed.to_csv(f"screener{sc['id']}_results.csv", index=False)

        ta_data = {ticker: get_ta(ticker) for ticker in passed["Ticker"]}
        ranked  = _rank_and_cap(sc, passed, ta_data)

        passed_idx = passed.set_index("Ticker")
        dashboard_rows = []
        for ticker, sc_dict in ranked:
            row = passed_idx.loc[ticker].to_dict()
            row["Ticker"] = ticker
            dashboard_rows.append((ticker, row, sc_dict, ta_data.get(ticker, {})))

        result[sc["id"]] = {"sc": sc, "ranked": ranked, "dashboard_rows": dashboard_rows}

    return result

# ── Основной цикл ──────────────────────────────────────────────────────────

def main():
    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"[{date_str}] Запуск скринеров...")

    scan = run_scan([sc["id"] for sc in SCREENERS])

    dashboard_data = {}
    rating_lines   = [f"📊 <b>Screener — {date_str}</b>"]
    for sc in SCREENERS:
        r = scan.get(sc["id"])
        if not r:
            continue
        rating_lines.append(format_rating(r["sc"], r["ranked"]))
        dashboard_data[sc["id"]] = r["dashboard_rows"]
    print("\n".join(rating_lines))

    # ── Сканнер #4: Ставки ────────────────────────────────────────────────────
    print("\nЗагрузка ставок...")
    rates_raw, rates_msg = {}, None
    try:
        from rates_fetcher import (get_nbrk_rates, get_kase_rates,
                                    get_us_rates, get_global_bonds,
                                    build_rates_message, load_previous, save_current)
        prev = load_previous()
        rates_raw = {
            "nbrk":  get_nbrk_rates(),
            "kase":  get_kase_rates(),
            "us":    get_us_rates(),
            "bonds": get_global_bonds(),
        }
        save_current(rates_raw)
        rates_msg = build_rates_message(prev)
    except Exception as e:
        print(f"Ставки: ошибка — {e}")

    # ── Дашборд: генерация HTML (публикуется на GitHub Pages сборкой workflow) ─
    print("\nГенерация дашборда...")
    url = os.getenv("PAGES_URL", "").rstrip("/") or None
    try:
        from dashboard_generator import generate
        date_only = datetime.now().strftime("%d.%m.%Y")
        html_path = generate(dashboard_data, rates_raw, date_only)
        print(f"HTML: {html_path}")
        print(f"Дашборд: {url}" if url else "PAGES_URL не задан — дашборд без ссылки")
    except Exception as e:
        print(f"Дашборд: ошибка — {e}")
        url = None

    if url:
        rating_lines.append("")
        rating_lines.append("🌐 <b>Дашборд:</b>")
        for sc in SCREENERS:
            rating_lines.append(f"{sc['emoji']} {sc['name']} → {url}#sc{sc['id']}")
        rating_lines.append(f"💹 Ставки → {url}#rates")

    tg_send("\n".join(rating_lines))
    if rates_msg:
        tg_send(rates_msg)
    print("Готово.")

if __name__ == "__main__":
    main()
