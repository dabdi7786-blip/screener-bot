"""
Генератор HTML-дашборда для screener_bot.py.
Объединяет результаты SC1/SC2/SC3 + ставки в один standalone HTML файл.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from screener_bot import CAT_EMOJI

OUTPUT_DIR = Path(__file__).parent / "output"


def _safe(v, fmt=".1f", suffix=""):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    try:
        return f"{float(v):{fmt}}{suffix}"
    except Exception:
        return str(v)


def _chg(v):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def generate(screener_results: dict, rates_data: dict, date_str: str = "") -> str:
    """
    screener_results: {1: [(ticker, row_dict, score_dict, ta_dict), ...], 2: [...], 3: [...]}
    rates_data:       {"nbrk": {...}, "kase": {...}, "us": {...}, "bonds": {...}}
    Returns path to generated HTML file.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    if not date_str:
        date_str = datetime.now().strftime("%d.%m.%Y")

    html = _build_html(screener_results, rates_data, date_str)
    fname = f"screener_{datetime.now().strftime('%Y%m%d')}.html"
    path  = OUTPUT_DIR / fname
    path.write_text(html, encoding="utf-8")
    return str(path)


def _build_nav(screeners: dict) -> str:
    buttons = []
    for sid in (1, 2, 3):
        sec_id, emoji, name, _ = _SC_META.get(sid, (f"sc{sid}", "📊", f"Screener {sid}", ""))
        count = len(screeners.get(sid, []))
        buttons.append(
            f'<button class="nav-btn" data-id="{sec_id}" onclick="showSection(\'{sec_id}\')">'
            f'{emoji} {name} <span class="nav-count">{count}</span></button>'
        )
    buttons.append(
        '<button class="nav-btn" data-id="rates" onclick="showSection(\'rates\')">💹 Ставки</button>'
    )
    return "\n  ".join(buttons)


def _build_html(screeners: dict, rates: dict, date_str: str) -> str:
    sc_html  = _build_screeners_section(screeners)
    rt_html  = _build_rates_section(rates)
    nav_html = _build_nav(screeners)
    total    = sum(len(v) for v in screeners.values())

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Screener — {date_str}</title>
<style>
:root{{--bg:#0F1117;--bg2:#1A1D27;--bg3:#22263A;--text:#E2E8F0;--muted:#94A3B8;
      --border:#2D3748;--green:#22C55E;--blue:#60A5FA;--amber:#F59E0B;
      --purple:#A78BFA;--red:#F87171;--acc:#3B82F6;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}}
header{{background:var(--bg2);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
header h1{{font-size:18px;font-weight:600}}
.meta{{color:var(--muted);font-size:12px}}
nav{{background:var(--bg2);border-bottom:1px solid var(--border);padding:8px 24px;display:flex;gap:8px;flex-wrap:wrap}}
.nav-btn{{background:var(--bg3);border:1px solid var(--border);color:var(--muted);padding:5px 14px;border-radius:20px;cursor:pointer;font-size:12px;transition:all .15s}}
.nav-btn.active,.nav-btn:hover{{background:var(--acc);border-color:var(--acc);color:#fff}}
.nav-count{{background:rgba(255,255,255,.15);border-radius:10px;padding:1px 7px;font-size:10px;margin-left:4px}}
.section{{display:none;padding:20px 24px}}
.section.active{{display:block}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-top:16px}}
.card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;transition:border-color .15s}}
.card:hover{{border-color:var(--acc)}}
.card-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
.ticker{{font-size:16px;font-weight:700;color:var(--text)}}
.badge{{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.g{{background:rgba(34,197,94,.15);color:var(--green)}}
.b{{background:rgba(96,165,250,.15);color:var(--blue)}}
.a{{background:rgba(245,158,11,.15);color:var(--amber)}}
.p{{background:rgba(167,139,250,.15);color:var(--purple)}}
.r{{background:rgba(248,113,113,.15);color:var(--red)}}
.score-row{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.bar{{height:6px;border-radius:3px;background:var(--border);flex:1}}
.fill{{height:100%;border-radius:3px}}
.kv{{font-size:12px;color:var(--muted);line-height:1.8}}
.kv span{{color:var(--text);font-weight:500}}
.sc-title{{font-size:15px;font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:8px}}
.sc-desc{{color:var(--muted);font-size:12px;margin-bottom:12px}}
.rates-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-top:16px}}
.rates-card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px}}
.rates-card h3{{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}}
.rate-row{{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border)}}
.rate-row:last-child{{border-bottom:none}}
.rate-label{{font-size:12px;color:var(--muted)}}
.rate-val{{font-size:14px;font-weight:600;color:var(--text)}}
.delta-up{{color:var(--green);font-size:11px;margin-left:4px}}
.delta-dn{{color:var(--red);font-size:11px;margin-left:4px}}
.trend-up{{color:var(--green)}}
.trend-dn{{color:var(--red)}}
.trend-neu{{color:var(--muted)}}
.empty{{text-align:center;padding:60px;color:var(--muted);font-size:13px}}
</style>
</head>
<body>
<header>
  <h1>📊 Stock Screener</h1>
  <span class="meta">Дата: {date_str} · Акций: {total}</span>
</header>
<nav>
  {nav_html}
</nav>
{sc_html}
{rt_html}
<script>
function showSection(id){{
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  var sec = document.getElementById(id);
  var btn = document.querySelector('.nav-btn[data-id="' + id + '"]');
  if (sec) sec.classList.add('active');
  if (btn) btn.classList.add('active');
}}
// Deep-link: открыть нужную вкладку по #sc1 / #sc2 / #sc3 / #rates из ссылки
(function(){{
  var valid = ['sc1','sc2','sc3','rates'];
  var hash  = (location.hash || '').replace('#', '');
  showSection(valid.indexOf(hash) !== -1 ? hash : 'sc1');
}})();
</script>
</body>
</html>"""


# ── Screener sections ─────────────────────────────────────────────────────────

_RATING_CLASS = {
    "Strong Buy": "g", "Buy+Watch": "b", "Watch": "a", "Wait": "p", "Skip": "r"
}
_SC_META = {
    1: ("sc1", "🚀", "Future S&P Leaders+", "Будущие лидеры S&P: рост >15%, PEG<2, Rule40>40"),
    2: ("sc2", "📈", "Growth v2",            "Быстрорастущие акции, топ-8 с sector cap"),
    3: ("sc3", "🏆", "Compounder",            "ROIC>15%, FCFMargin>10%, GrossMargin>50%"),
}


def _score_color(score: float) -> str:
    if score >= 8:  return "var(--green)"
    if score >= 6:  return "var(--blue)"
    if score >= 4:  return "var(--amber)"
    return "var(--red)"


def _build_screeners_section(screeners: dict) -> str:
    parts = []
    for sid, rows in screeners.items():
        sec_id, emoji, name, desc = _SC_META.get(sid, (f"sc{sid}", "📊", f"Screener {sid}", ""))
        active = "active" if sid == 1 else ""
        cards  = "".join(_stock_card(r) for r in rows) if rows else '<div class="empty">Нет акций по критериям сегодня</div>'
        parts.append(
            f'<div class="section {active}" id="{sec_id}">'
            f'<div class="sc-title">{emoji} {name}</div>'
            f'<div class="sc-desc">{desc}</div>'
            f'<div class="grid">{cards}</div></div>'
        )
    return "\n".join(parts)


def _ta_html(ta: dict) -> str:
    if not ta:
        return ""
    lines = [
        f'{ta.get("trend","")} &nbsp; MACD {ta.get("macd","")} &nbsp; '
        f'RSI {ta.get("rsi","—")} {ta.get("rsi_lbl","")}',
        f'Вход: <span style="color:var(--text)">${ta.get("entry","—")}</span> &nbsp; '
        f'SL: <span style="color:var(--text)">${ta.get("sl","—")}</span> ({ta.get("sl_pct","—")}) &nbsp; '
        f'TP1: <span style="color:var(--text)">${ta.get("tp1","—")}</span> ({ta.get("tp1_pct","—")})',
    ]
    if ta.get("earn_date"):
        lines.append(
            f'📅 Посл. отчёт: <span style="color:var(--text)">{ta["earn_date"]}</span> — '
            f'цена закрытия <span style="color:var(--text)">${ta.get("earn_close","—")}</span>'
        )
    rows = "".join(f'<div>{l}</div>' for l in lines)
    return (
        '<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);'
        f'font-size:11px;color:var(--muted);line-height:1.6">{rows}</div>'
    )


def _stock_card(r: tuple) -> str:
    ticker, row, sc, ta = r
    score   = sc.get("total", 0)
    rating  = row.get("Consensus", "—")
    upside  = row.get("Upside_%")
    rev_g   = row.get("RevGrowth_%")
    eps_g   = row.get("EPSGrowth_%")
    gm      = row.get("GrossMargin_%")
    r40     = row.get("Rule40")
    peg     = row.get("PEG")
    fpe     = row.get("ForwardPE")
    roic    = row.get("ROIC_%")
    fcf_m   = row.get("FCFMargin_%")
    rs      = row.get("RS_Rank")
    name_s  = row.get("Name", ticker)[:28]
    sector  = row.get("Sector", "")
    accel   = "⚡" if row.get("EPSAccel") else ""

    pct  = min(100, max(0, score / 10 * 100))
    col  = _score_color(score)

    sc_cats = {k: v for k, v in sc.items() if k != "total"}
    cats_html = " ".join(
        f'<span style="font-size:11px;color:var(--muted)">{CAT_EMOJI.get(k, "•")}{k}:'
        f'<span style="color:var(--text);margin-left:2px">{v}</span></span>'
        for k, v in sc_cats.items()
    )

    up_str = f'Upside: <span>{_chg(upside)}</span>' if upside is not None else ""

    return f"""<div class="card">
  <div class="card-head">
    <div><div class="ticker">{ticker} <span style="font-size:11px;color:var(--muted)">{accel}</span></div>
    <div style="font-size:11px;color:var(--muted);margin-top:2px">{name_s}</div></div>
    <span class="badge {_RATING_CLASS.get(rating,'')}">{rating}</span>
  </div>
  <div class="score-row">
    <span style="font-size:13px;font-weight:700">{score}/10</span>
    <div class="bar"><div class="fill" style="width:{pct:.0f}%;background:{col}"></div></div>
  </div>
  <div style="font-size:11px;color:var(--muted);margin-bottom:8px;display:flex;flex-wrap:wrap;gap:6px">{cats_html}</div>
  <div class="kv">
    Rev: <span>{_chg(rev_g)}</span> &nbsp; EPS: <span>{_chg(eps_g)}</span> &nbsp; GM: <span>{_safe(gm,'','')}%</span><br>
    Rule40: <span>{_safe(r40,'','')} </span> &nbsp; PEG: <span>{_safe(peg,'.2f','')}</span> &nbsp; FwdPE: <span>{_safe(fpe,'.1f','')}</span><br>
    ROIC: <span>{_safe(roic,'','')}%</span> &nbsp; FCFm: <span>{_safe(fcf_m,'','')}%</span>
    {"&nbsp; RS: <span>" + _chg(rs) + " vs SPX</span>" if rs is not None else ""}
    {"<br>" + up_str if up_str else ""}
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)">{sector}</div>
  {_ta_html(ta)}
</div>"""


# ── Rates section ─────────────────────────────────────────────────────────────

def _build_rates_section(rates: dict) -> str:
    nbrk  = rates.get("nbrk", {})
    kase  = rates.get("kase", {})
    us    = rates.get("us", {})
    bonds = rates.get("bonds", {})

    def row(label, val, suffix="%", delta_key=None, prev=None):
        v = _safe(val, ".2f", suffix) if val is not None else "—"
        return f'<div class="rate-row"><span class="rate-label">{label}</span><span class="rate-val">{v}</span></div>'

    nbrk_rows = (
        row("Базовая ставка",   nbrk.get("base_rate"))
        + row("Коридор верх",   nbrk.get("corridor_upper"))
        + row("Коридор низ",    nbrk.get("corridor_lower"))
        + row("Инфляция",       nbrk.get("inflation"))
    ) if nbrk else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    kase_rows = (
        row("TONIA",    kase.get("tonia"))
        + row("TWINA",  kase.get("twina"))
        + row("USD/KZT", kase.get("usd_kzt"), suffix=" ₸")
    ) if kase else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    effr = us.get("effr")
    effr_str = (f"{us.get('effr_lo','')} — {us.get('effr_hi','')}" if us.get("effr_lo") else _safe(effr, ".2f", "%")) if effr else "—"
    us_rows = (
        f'<div class="rate-row"><span class="rate-label">Fed Rate (EFFR)</span><span class="rate-val">{effr_str}</span></div>'
        + (row("SOFR",  us.get("sofr")) if us.get("sofr") else "")
        + row("T3M",   us.get("t3m"))
        + row("T5Y",   us.get("t5y"))
        + row("T10Y",  us.get("t10y"))
        + row("T30Y",  us.get("t30y"))
    ) if us else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    bond_items = [
        ("🇩🇪 DE 10Y", "de_10y"), ("🇬🇧 UK 10Y", "uk_10y"),
        ("🇯🇵 JP 10Y", "jp_10y"), ("🇫🇷 FR 10Y", "fr_10y"),
    ]
    bond_rows = "".join(
        row(label, bonds.get(key)) for label, key in bond_items if bonds.get(key) is not None
    ) or '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    return f"""<div class="section" id="rates">
<div class="sc-title">💹 Обзор ставок</div>
<div class="sc-desc">НБРК · KASE · US Treasury · Global Bonds</div>
<div class="rates-grid">
  <div class="rates-card"><h3>🇰🇿 НБРК — Монетарная политика</h3>{nbrk_rows}</div>
  <div class="rates-card"><h3>🏦 KASE — Денежный рынок</h3>{kase_rows}</div>
  <div class="rates-card"><h3>🇺🇸 США — Ставки и трежерис</h3>{us_rows}</div>
  <div class="rates-card"><h3>🌍 Мировые облигации (10Y)</h3>{bond_rows}</div>
</div>
</div>"""
