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
DOCS_DIR   = Path(__file__).parent / "docs"   # публикуется на GitHub Pages


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


def generate(screener_results: dict, rates_data: dict, date_str: str = "", prev_rates: dict = None, ibkr_data: dict = None) -> str:
    """
    screener_results: {1: [(ticker, row_dict, score_dict, ta_dict), ...], 2: [...], 3: [...]}
    rates_data:       {"nbrk": {...}, "kase": {...}, "us": {...}, "bonds": {...}, "currency": {...}}
    prev_rates:       та же форма, что и rates_data — предыдущий прогон, для дельт день/день.
    ibkr_data:        {"quotes": {...}, "account": {...}, "positions": [...]}
    Пишет docs/{YYYY-MM-DD}.html (архив) + docs/index.html (= сегодня, для GitHub Pages).
    Returns path to generated HTML file (в output/, для локальной истории).
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    if not date_str:
        date_str = datetime.now().strftime("%d.%m.%Y")

    iso_date = datetime.now().strftime("%Y-%m-%d")
    # Список дат для фильтра — уже заархивированные + сегодняшняя
    dates = sorted({p.stem for p in DOCS_DIR.glob("????-??-??.html")} | {iso_date}, reverse=True)

    html = _build_html(screener_results, rates_data, date_str, dates, iso_date, prev_rates, ibkr_data)

    fname = f"screener_{datetime.now().strftime('%Y%m%d')}.html"
    path  = OUTPUT_DIR / fname
    path.write_text(html, encoding="utf-8")

    (DOCS_DIR / f"{iso_date}.html").write_text(html, encoding="utf-8")
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")

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
    buttons.append(
        '<button class="nav-btn" data-id="ibkr" onclick="showSection(\'ibkr\')">🏦 IBKR</button>'
    )
    return "\n  ".join(buttons)


def _build_date_select(dates: list, current_date: str) -> str:
    options = "".join(
        f'<option value="{d}.html"{" selected" if d == current_date else ""}>{d}</option>'
        for d in dates
    )
    return (
        '<select id="dateSelect" onchange="location.href=this.value+location.hash" '
        f'title="Выбрать дату">{options}</select>'
    )


def _build_html(screeners: dict, rates: dict, date_str: str, dates: list = None, current_date: str = "", prev_rates: dict = None, ibkr: dict = None) -> str:
    sc_html    = _build_screeners_section(screeners)
    rt_html    = _build_rates_section(rates, prev_rates)
    ib_html    = _build_ibkr_section(ibkr or {})
    nav_html   = _build_nav(screeners)
    date_select = _build_date_select(dates or [current_date], current_date) if dates else ""
    total      = sum(len(v) for v in screeners.values())

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
#dateSelect{{background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:4px 10px;border-radius:6px;font-size:12px;cursor:pointer}}
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
  {date_select}
</header>
<nav>
  {nav_html}
</nav>
{sc_html}
{rt_html}
{ib_html}
<script>
function showSection(id){{
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  var sec = document.getElementById(id);
  var btn = document.querySelector('.nav-btn[data-id="' + id + '"]');
  if (sec) sec.classList.add('active');
  if (btn) btn.classList.add('active');
}}
// Deep-link: открыть нужную вкладку по #sc1 / #sc2 / #sc3 / #rates / #ibkr из ссылки
(function(){{
  var valid = ['sc1','sc2','sc3','rates','ibkr'];
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
        f'Цена закрытия на {ta.get("price_date","—")}: <span style="color:var(--text)">${ta.get("entry","—")}</span> &nbsp; '
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

def _delta_html(val, prev_section: dict, key: str) -> str:
    prev_val = (prev_section or {}).get(key)
    if val is None or prev_val is None:
        return ""
    try:
        diff = float(val) - float(prev_val)
    except (TypeError, ValueError):
        return ""
    if abs(diff) < 0.001:
        return ""
    cls  = "delta-up" if diff > 0 else "delta-dn"
    arr  = "↑" if diff > 0 else "↓"
    sign = "+" if diff > 0 else ""
    return f'<span class="{cls}">{arr}{sign}{diff:.2f}</span>'


def _build_rates_section(rates: dict, prev_rates: dict = None) -> str:
    prev_rates = prev_rates or {}
    nbrk        = rates.get("nbrk", {})
    kase        = rates.get("kase", {})
    us          = rates.get("us", {})
    bonds       = rates.get("bonds", {})
    currency    = rates.get("currency", {})
    commodities = rates.get("commodities", {})

    def row(label, val, suffix="%", delta_key=None, prev=None):
        v = _safe(val, ".2f", suffix) if val is not None else "—"
        d = _delta_html(val, prev, delta_key) if (val is not None and delta_key and prev is not None) else ""
        return f'<div class="rate-row"><span class="rate-label">{label}</span><span class="rate-val">{v}{d}</span></div>'

    prev_nbrk = prev_rates.get("nbrk", {})
    nbrk_rows = (
        row("Базовая ставка",   nbrk.get("base_rate"),      delta_key="base_rate", prev=prev_nbrk)
        + row("Коридор верх",   nbrk.get("corridor_upper"))
        + row("Коридор низ",    nbrk.get("corridor_lower"))
        + row("Инфляция",       nbrk.get("inflation"),       delta_key="inflation", prev=prev_nbrk)
    ) if nbrk else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    prev_kase = prev_rates.get("kase", {})
    kase_rows = (
        row("TONIA",    kase.get("tonia"), delta_key="tonia", prev=prev_kase)
        + row("TWINA",  kase.get("twina"), delta_key="twina", prev=prev_kase)
    ) if kase else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    prev_cur = prev_rates.get("currency", {})
    currency_rows = (
        row("USD/KZT", currency.get("usd_kzt"), suffix=" ₸", delta_key="usd_kzt", prev=prev_cur)
        + row("EUR/KZT", currency.get("eur_kzt"), suffix=" ₸", delta_key="eur_kzt", prev=prev_cur)
        + row("RUB/KZT", currency.get("rub_kzt"), suffix=" ₸", delta_key="rub_kzt", prev=prev_cur)
        + row("TRY/KZT", currency.get("try_kzt"), suffix=" ₸", delta_key="try_kzt", prev=prev_cur)
    ) if currency else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    prev_comm = prev_rates.get("commodities", {})
    def commodity_row(label, key, suffix=" $"):
        price = commodities.get(f"{key}_price")
        if price is None:
            return ""
        d = _delta_html(price, prev_comm, f"{key}_price")
        chg30 = commodities.get(f"{key}_chg30d")
        chg30_html = ""
        if chg30 is not None:
            cls = "delta-up" if chg30 > 0 else "delta-dn" if chg30 < 0 else ""
            chg30_html = f' <span class="{cls}" style="font-size:10px">30д {chg30:+.1f}%</span>'
        v = _safe(price, ".2f", suffix)
        return f'<div class="rate-row"><span class="rate-label">{label}</span><span class="rate-val">{v}{d}{chg30_html}</span></div>'

    commodity_rows = (
        commodity_row("Нефть (WTI)", "oil")
        + commodity_row("Золото", "gold")
        + commodity_row("Серебро", "silver")
        + commodity_row("Медь", "copper")
        + commodity_row("Уран (U3O8)", "uranium")
    ) if commodities else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    prev_us = prev_rates.get("us", {})
    effr = us.get("effr")
    effr_str = (f"{us.get('effr_lo','')} — {us.get('effr_hi','')}" if us.get("effr_lo") else _safe(effr, ".2f", "%")) if effr else "—"
    effr_delta = _delta_html(effr, prev_us, "effr") if effr is not None else ""
    us_rows = (
        f'<div class="rate-row"><span class="rate-label">Fed Rate (EFFR)</span><span class="rate-val">{effr_str}{effr_delta}</span></div>'
        + (row("SOFR",  us.get("sofr"), delta_key="sofr", prev=prev_us) if us.get("sofr") else "")
        + row("T3M",   us.get("t3m"),  delta_key="t3m",  prev=prev_us)
        + row("T5Y",   us.get("t5y"),  delta_key="t5y",  prev=prev_us)
        + row("T10Y",  us.get("t10y"), delta_key="t10y", prev=prev_us)
        + row("T30Y",  us.get("t30y"), delta_key="t30y", prev=prev_us)
    ) if us else '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    prev_bonds = prev_rates.get("bonds", {})
    bond_items = [
        ("🇩🇪 DE 10Y", "de_10y"), ("🇬🇧 UK 10Y", "uk_10y"),
        ("🇯🇵 JP 10Y", "jp_10y"), ("🇫🇷 FR 10Y", "fr_10y"),
    ]
    bond_rows = "".join(
        row(label, bonds.get(key), delta_key=key, prev=prev_bonds) for label, key in bond_items if bonds.get(key) is not None
    ) or '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    return f"""<div class="section" id="rates">
<div class="sc-title">💹 Обзор ставок</div>
<div class="sc-desc">НБРК · KASE · Валюты · Сырьё · US Treasury · Global Bonds</div>
<div class="rates-grid">
  <div class="rates-card"><h3>🇰🇿 НБРК — Монетарная политика</h3>{nbrk_rows}</div>
  <div class="rates-card"><h3>🏦 KASE — Денежный рынок</h3>{kase_rows}</div>
  <div class="rates-card"><h3>💱 Валюты</h3>{currency_rows}</div>
  <div class="rates-card"><h3>🛢️ Сырьевые товары</h3>{commodity_rows}</div>
  <div class="rates-card"><h3>🇺🇸 США — Ставки и трежерис</h3>{us_rows}</div>
  <div class="rates-card"><h3>🌍 Мировые облигации (10Y)</h3>{bond_rows}</div>
</div>
</div>"""


# ── IBKR section ────────────────────────────────────────────────────────────────

def _build_ibkr_section(ibkr: dict) -> str:
    quotes     = ibkr.get("quotes", {})
    account    = ibkr.get("account", {})
    positions  = ibkr.get("positions", [])
    fetched_at = ibkr.get("fetched_at")

    quote_rows = "".join(
        f'<div class="rate-row"><span class="rate-label">{sym}</span>'
        f'<span class="rate-val">{_safe(q.get("last") if q.get("last") is not None else q.get("close"), ".2f", " $")}</span></div>'
        for sym, q in quotes.items()
    ) or '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    acc_items = [
        ("NetLiquidation", "Net Liquidation"), ("TotalCashValue", "Cash"),
        ("BuyingPower", "Buying power"), ("UnrealizedPnL", "Unrealized P&L"),
    ]
    account_rows = "".join(
        f'<div class="rate-row"><span class="rate-label">{label}</span>'
        f'<span class="rate-val">{_safe(account.get(key), ".2f", " $")}</span></div>'
        for key, label in acc_items if account.get(key) is not None
    ) or '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">данные недоступны</span></div>'

    position_rows = "".join(
        f'<div class="rate-row"><span class="rate-label">{p.get("symbol","—")}</span>'
        f'<span class="rate-val">{_safe(p.get("position"), "g")} @ {_safe(p.get("avg_cost"), ".2f", " $")}</span></div>'
        for p in positions
    ) or '<div class="rate-row"><span class="rate-label" style="color:var(--muted)">нет открытых позиций / данные недоступны</span></div>'

    freshness = f"Котировки watchlist · Счёт · Позиции (paper) · снэпшот от {fetched_at}" if fetched_at \
        else "Котировки watchlist · Счёт · Позиции (paper) · снэпшота ещё нет — запусти ibkr_local_fetch.py"

    return f"""<div class="section" id="ibkr">
<div class="sc-title">🏦 Interactive Brokers</div>
<div class="sc-desc">{freshness}</div>
<div class="rates-grid">
  <div class="rates-card"><h3>📈 Котировки</h3>{quote_rows}</div>
  <div class="rates-card"><h3>💼 Счёт</h3>{account_rows}</div>
  <div class="rates-card"><h3>📊 Позиции</h3>{position_rows}</div>
</div>
</div>"""
