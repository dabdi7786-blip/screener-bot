"""
Converts list[CompanyData] to a standalone HTML file and JSON backup.
Data is embedded directly as const DATA = [...] — no server required.
"""
import json
import logging
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

from models import CompanyData

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "dashboard" / "template.html"
OUTPUT_DIR    = Path(__file__).parent / "output"


def export(companies: list[CompanyData], macro_data: dict, output_path: str = "") -> str:
    """
    Write HTML + JSON. Returns path to the HTML file.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    today = date.today().strftime("%Y%m%d")

    if not output_path:
        output_path = str(OUTPUT_DIR / f"screener_{today}.html")
    json_path = output_path.replace(".html", ".json")

    records = _to_records(companies, macro_data)

    # JSON backup
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    logger.info("JSON saved: %s", json_path)

    # HTML
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(records, ensure_ascii=False)
    html = (template
            .replace("{{DATE}}", date.today().strftime("%d.%m.%Y"))
            .replace("{{DATA_JSON}}", data_json))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(output_path) // 1024
    logger.info("HTML saved: %s (%d KB)", output_path, size_kb)
    if size_kb > 500:
        logger.warning("HTML exceeds 500 KB (%d KB) — consider reducing AI text length", size_kb)

    return output_path


def _to_records(companies: list[CompanyData], macro_data: dict) -> list[dict]:
    records = []
    for c in sorted(companies, key=lambda x: x.final_score, reverse=True):
        r = asdict(c)
        r["macro_data"] = macro_data
        records.append(r)
    return records
