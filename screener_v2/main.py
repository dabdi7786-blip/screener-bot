"""
Screener v2 — entry point.
Usage:
  python main.py
  python main.py --tickers NVDA MSFT V
  python main.py --no-ai
  python main.py --output ~/Desktop/today.html
  python main.py --open
  python main.py --telegram
"""
import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

# ── ensure project dir is in sys.path ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import fetcher
import technical
import scoring
import exporter
import ai_analyst
from config import WATCHLIST, SLEEP_BETWEEN_TICKERS, AI_TOP_N
from layers import macro, sector, eps_quality, institutional, catalyst
from models import CompanyData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def run(tickers: list[str], no_ai: bool, output_path: str) -> str:
    logger.info("=== Screener v2 start — %d tickers ===", len(tickers))

    # Macro data: load once for all tickers
    logger.info("Loading macro data (VIX / DXY / 10Y)…")
    macro_multiplier, macro_data = macro.get_macro_multiplier()
    logger.info("Macro multiplier: %.3f", macro_multiplier)

    companies: list[CompanyData] = []

    for i, ticker in enumerate(tickers, 1):
        logger.info("[%d/%d] Processing %s…", i, len(tickers), ticker)

        # 1. Fetch raw data
        company, hist = fetcher.fetch(ticker)
        if company is None:
            logger.warning("%s: skipped (fetch returned None)", ticker)
            continue
        if company.error:
            logger.warning("%s: fetch error — %s", ticker, company.error)
            companies.append(company)
            time.sleep(SLEEP_BETWEEN_TICKERS)
            continue

        # Inject macro multiplier
        company.macro_multiplier = macro_multiplier

        # 2. Layer 1: Sector metrics
        company.sector_score, company.sector_data = sector.analyze(company)

        # 3. Layer 2: EPS quality
        company.eps_quality_score, company.eps_quality_data = eps_quality.analyze(company)

        # 4. Technical (separate module, referenced in formula)
        company.tech_score, company.tech_data = technical.analyze(company, hist)

        # 5. Layer 3: Institutional (EDGAR + short interest)
        company.inst_score, company.inst_data = institutional.analyze(company)

        # 6. Layer 4: Catalyst
        company.catalyst_score, company.catalyst_data = catalyst.analyze(company)

        # 7. Final score + rating
        scoring.compute(company)

        logger.info("  %s → %.1f (%s)  [sector=%.1f eq=%.1f tech=%.1f inst=%.1f cat=%.1f ×%.3f]",
                    ticker, company.final_score, company.rating,
                    company.sector_score, company.eps_quality_score,
                    company.tech_score, company.inst_score,
                    company.catalyst_score, macro_multiplier)

        companies.append(company)
        time.sleep(SLEEP_BETWEEN_TICKERS)

    if not companies:
        logger.error("No companies processed — aborting")
        return ""

    # 8. AI commentary for top-N
    if not no_ai:
        ranked = sorted(
            [c for c in companies if not c.error],
            key=lambda x: x.final_score, reverse=True
        )
        top_n = ranked[:AI_TOP_N]
        logger.info("Generating AI commentary for top %d companies…", len(top_n))
        for c in top_n:
            c.ai_summary = ai_analyst.generate_summary(c)

    # 9. Export HTML + JSON
    html_path = exporter.export(companies, macro_data, output_path)
    logger.info("=== Done. HTML: %s ===", html_path)
    return html_path


def main():
    parser = argparse.ArgumentParser(description="Screener v2 — stock screening with HTML dashboard")
    parser.add_argument("--tickers",  nargs="+",  default=None,  help="Override watchlist tickers")
    parser.add_argument("--no-ai",    action="store_true",        help="Skip AI commentary")
    parser.add_argument("--output",   default="",                 help="Output HTML file path")
    parser.add_argument("--open",     action="store_true",        help="Open HTML in browser after generation")
    parser.add_argument("--telegram", action="store_true",        help="Send HTML file to Telegram channel")
    args = parser.parse_args()

    tickers   = args.tickers if args.tickers else WATCHLIST
    html_path = run(tickers, args.no_ai, args.output)

    if html_path and args.open:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", html_path])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", html_path])
            else:
                import webbrowser
                webbrowser.open(f"file://{html_path}")
            logger.info("Opened in browser: %s", html_path)
        except Exception as e:
            logger.warning("Could not open browser: %s", e)

    if html_path and args.telegram:
        import telegram_sender
        # Pass the already-processed companies list from inside run()
        # We re-read JSON as a lightweight proxy
        import json
        json_path = html_path.replace(".html", ".json")
        try:
            with open(json_path) as f:
                records = json.load(f)
            from models import CompanyData
            cos = [CompanyData(**{k: v for k, v in r.items()
                                  if k in CompanyData.__dataclass_fields__})
                   for r in records]
        except Exception:
            cos = []
        telegram_sender.send_dashboard(html_path, cos)


if __name__ == "__main__":
    main()
