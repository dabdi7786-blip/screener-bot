"""
Screener #1 — "Future S&P Leaders"
Criteria:
  Market Cap:       $10B – $200B
  Revenue Growth:   >15%
  EPS Growth:       >15%
  Gross Margin:     >50%
  PEG:              <2
  Forward P/E:      <35
  Debt/Equity:      <150 (proxy for Debt/EBITDA <3)
  Rule of 40:       >40  (Revenue Growth % + FCF Margin %)
"""

import yfinance as yf
import pandas as pd
import requests
import time
from io import StringIO

# ── 1. Get S&P 500 tickers from Wikipedia ──────────────────────────────────
def get_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; StockScreener/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0]
    tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
    return tickers

# ── 2. Fetch fundamentals for a single ticker ──────────────────────────────
def fetch_info(ticker: str) -> dict | None:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        if not info or info.get("quoteType") not in ("EQUITY",):
            return None

        market_cap = info.get("marketCap") or 0
        rev_growth  = info.get("revenueGrowth")       # trailing 12m YoY
        eps_growth  = info.get("earningsGrowth")       # trailing 12m YoY
        gross_margin= info.get("grossMargins")
        peg         = info.get("pegRatio")
        fwd_pe      = info.get("forwardPE")
        debt_eq     = info.get("debtToEquity")         # %

        # Rule of 40: Revenue Growth % + FCF Margin %
        fcf         = info.get("freeCashflow") or 0
        revenue     = info.get("totalRevenue") or 1
        fcf_margin  = fcf / revenue
        rule40      = ((rev_growth or 0) + fcf_margin) * 100

        return {
            "Ticker":        ticker,
            "Name":          info.get("shortName", ""),
            "Sector":        info.get("sector", ""),
            "MarketCap_B":   round(market_cap / 1e9, 1),
            "RevGrowth_%":   round((rev_growth or 0) * 100, 1),
            "EPSGrowth_%":   round((eps_growth or 0) * 100, 1),
            "GrossMargin_%": round((gross_margin or 0) * 100, 1),
            "PEG":           round(peg, 2) if peg else None,
            "ForwardPE":     round(fwd_pe, 1) if fwd_pe else None,
            "Debt/Equity_%": round(debt_eq, 1) if debt_eq is not None else None,
            "FCFMargin_%":   round(fcf_margin * 100, 1),
            "Rule40":        round(rule40, 1),
        }
    except Exception:
        return None

# ── 3. Apply screener filters ──────────────────────────────────────────────
def passes_filter(r: dict) -> bool:
    cap = r["MarketCap_B"]
    if not (10 <= cap <= 200):
        return False
    if r["RevGrowth_%"] <= 15:
        return False
    if r["EPSGrowth_%"] <= 15:
        return False
    if r["GrossMargin_%"] <= 50:
        return False
    peg = r["PEG"]
    if peg is None or peg <= 0 or peg >= 2:
        return False
    fpe = r["ForwardPE"]
    if fpe is None or fpe >= 35:
        return False
    de = r["Debt/Equity_%"]
    if de is not None and de > 150:      # rough proxy for Debt/EBITDA < 3
        return False
    if r["Rule40"] <= 40:
        return False
    return True

# ── 4. Main ────────────────────────────────────────────────────────────────
def main():
    print("Fetching S&P 500 tickers...")
    tickers = get_sp500_tickers()
    print(f"Total tickers: {len(tickers)}\n")

    results = []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker:<8}", end="\r")
        info = fetch_info(ticker)
        if info:
            results.append(info)
        time.sleep(0.15)   # be polite to Yahoo Finance

    print("\nScanning complete.")

    df = pd.DataFrame(results)
    passed = df[df.apply(passes_filter, axis=1)].copy()
    passed.sort_values("Rule40", ascending=False, inplace=True)
    passed.reset_index(drop=True, inplace=True)

    print(f"\n{'='*70}")
    print(f"  Screener #1 — Future S&P Leaders   ({len(passed)} matches)")
    print(f"{'='*70}")

    if passed.empty:
        print("No stocks matched the criteria today.")
    else:
        cols = ["Ticker", "Name", "MarketCap_B", "RevGrowth_%",
                "EPSGrowth_%", "GrossMargin_%", "PEG", "ForwardPE",
                "Rule40", "Debt/Equity_%"]
        print(passed[cols].to_string(index=True))

    # Save to CSV
    out = "screener1_results.csv"
    passed.to_csv(out, index=False)
    print(f"\nResults saved to {out}")

if __name__ == "__main__":
    main()
