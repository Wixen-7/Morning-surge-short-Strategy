"""
NSE Morning Surge Short Strategy — Date Range Paper Trade
==========================================================
Runs the strategy across a date range using ONE bulk yfinance download.
Dashboard is ALWAYS auto-opened in your browser — no extra flags needed.

Usage:
    python nse_backtest.py --from 2025-03-01 --to 2025-04-01
    python nse_backtest.py --from 2025-01-01 --to 2025-03-31 --capital 200000
    python nse_backtest.py --from 2025-04-01 --to 2025-04-01   # single day

Install:
    pip install yfinance pandas numpy
"""

import argparse, sys, json, os, webbrowser, warnings, tempfile
from datetime import datetime, timedelta, date
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    import pyarrow  # needed for parquet cache
except ImportError as e:
    print(f"\n❌  Missing package: {e}")
    print("    Run:  pip install yfinance pandas numpy pyarrow\n")
    sys.exit(1)

# ─── Watchlist ────────────────────────────────────────────────────────────────
NIFTY50 = [
    "RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","WIPRO","AXISBANK",
    "BAJFINANCE","KOTAKBANK","SBIN","TATASTEEL","HCLTECH","SUNPHARMA",
    "DRREDDY","CIPLA","ONGC","NTPC","POWERGRID","COALINDIA","BPCL",
    "MARUTI","M&M","TATAMOTORS","HEROMOTOCO","EICHERMOT","ADANIENT",
    "ADANIPORTS","ULTRACEMCO","GRASIM","HINDALCO",
]

# ─── Cache dir (guarantees identical data across runs) ───────────────────────
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nse_cache")

def _cache_path(buf_start: date, buf_end: date) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"raw_{buf_start}_{buf_end}.parquet")

# ─── Single bulk download ─────────────────────────────────────────────────────
def fetch_all(start: date, end: date, symbols: list) -> pd.DataFrame:
    """
    ONE yfinance call for the full range + 40-day lookback buffer.
    Saves result to a local Parquet cache so every re-run uses the exact
    same OHLCV values — this is what was causing 3 different results.
    To force a fresh download, delete the .nse_cache/ folder.
    """
    buf_start = start - timedelta(days=40)
    buf_end   = end   + timedelta(days=1)
    cache     = _cache_path(buf_start, buf_end)

    if os.path.exists(cache):
        print(f"\n  Loading cached data ({buf_start} to {buf_end}) ...", end="", flush=True)
        raw = pd.read_parquet(cache)
        print(f" done.  Shape: {raw.shape}  [from cache — results will be identical]")
        return raw

    tickers = [f"{s}.NS" for s in symbols]
    print(f"\n  Downloading {len(symbols)} symbols  {buf_start} to {buf_end} ...", end="", flush=True)
    raw = yf.download(tickers, start=buf_start, end=buf_end,
                      progress=False, auto_adjust=True)
    print(f" done.  Shape: {raw.shape}")

    if raw.empty:
        raise ValueError(
            "No data returned.\n"
            "  * Check internet connection\n"
            "  * Verify date range has trading days\n"
            "  * Yahoo Finance may be rate-limiting — wait a minute and retry"
        )

    raw.to_parquet(cache)
    print(f"  Cached to: {cache}  (delete this folder to force a fresh download)")
    return raw

def get_trading_days(raw: pd.DataFrame, start: date, end: date) -> list:
    """Return list of dates that have actual market data in the range."""
    idx = raw.index
    mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
    return [ts.date() for ts in idx[mask]]

def day_snapshot(raw: pd.DataFrame, trade_date: date, symbols: list) -> dict:
    """
    Extract one trading day's data for all symbols from the bulk DataFrame.
    Also computes 20-day average volume using prior rows only.
    """
    ts  = pd.Timestamp(trade_date)
    idx = raw.index
    prior_mask = idx < ts
    result = {}

    for sym in symbols:
        ns = f"{sym}.NS"
        try:
            o = float(raw["Open"][ns].loc[ts])
            h = float(raw["High"][ns].loc[ts])
            l = float(raw["Low"][ns].loc[ts])
            c = float(raw["Close"][ns].loc[ts])
            v = float(raw["Volume"][ns].loc[ts])
            if any(np.isnan([o, h, l, c, v])): continue

            prior_vol   = raw["Volume"][ns][prior_mask].dropna()
            avg20       = float(prior_vol.tail(20).mean()) if len(prior_vol) >= 5 else v

            prior_close = raw["Close"][ns][prior_mask].dropna()
            pc          = float(prior_close.iloc[-1]) if len(prior_close) > 0 else o

            result[sym] = {
                "open": o, "high": h, "low": l, "close": c,
                "volume": v, "avg_vol_20d": avg20,
                "prev_close": pc, "circuit_up": round(pc * 1.20, 2),
                "change_pct": round((c - pc) / pc * 100, 2),
            }
        except (KeyError, IndexError):
            continue
    return result

# ─── Strategy ─────────────────────────────────────────────────────────────────
def check_signal(sym: str, d: dict, cfg: dict):
    surge = (d["high"] - d["open"]) / d["open"] * 100
    vol_r = d["volume"] / d["avg_vol_20d"] if d["avg_vol_20d"] > 0 else 1
    if surge < cfg["surge_threshold"]:          return None
    if vol_r  < cfg["volume_spike_multiplier"]: return None
    if d["open"] >= d["circuit_up"] * (1 - cfg["circuit_buffer_pct"] / 100): return None
    entry = min(round(d["open"] * (1 + surge / 2 / 100), 2), d["high"])
    return {
        "symbol": sym, "surge_pct": round(surge, 2), "vol_ratio": round(vol_r, 2),
        "entry":  entry,
        "stop_loss": round(entry * (1 + cfg["stop_loss_pct"] / 100), 2),
        "target":    round(entry * (1 - cfg["target_pct"] / 100), 2),
        "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"],
        "change_pct": d["change_pct"],
    }

def simulate_trade(sig: dict, d: dict, max_capital: float) -> dict:
    qty   = max(1, int(max_capital / sig["entry"]))
    hit_t = d["low"]  <= sig["target"]
    hit_s = d["high"] >= sig["stop_loss"]
    if hit_t and hit_s:
        dt     = sig["entry"] - sig["target"]
        ds     = sig["stop_loss"] - sig["entry"]
        exit_p = sig["target"] if dt <= ds else sig["stop_loss"]
        reason = "Target hit" if exit_p == sig["target"] else "Stop loss"
    elif hit_t: exit_p, reason = sig["target"],    "Target hit"
    elif hit_s: exit_p, reason = sig["stop_loss"], "Stop loss"
    else:       exit_p, reason = d["close"],        "Time exit"
    pnl     = round((sig["entry"] - exit_p) * qty, 2)
    pnl_pct = round((sig["entry"] - exit_p) / sig["entry"] * 100, 2)
    brk = calc_brokerage(sig["entry"], exit_p, qty)
    net_pnl     = round(pnl - brk["total_charges"], 2)
    net_pnl_pct = round(net_pnl / (sig["entry"] * qty) * 100, 2)
    return {
        "symbol": sig["symbol"], "surge_pct": sig["surge_pct"],
        "vol_ratio": sig["vol_ratio"], "entry": sig["entry"],
        "exit": round(exit_p, 2), "stop_loss": sig["stop_loss"],
        "target": sig["target"], "qty": qty,
        "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason, "win": pnl > 0,
        "net_pnl": net_pnl, "net_pnl_pct": net_pnl_pct,
        "charges": brk,
        "open": sig["open"], "high": sig["high"],
        "low": sig["low"],   "close": sig["close"],
        "change_pct": sig["change_pct"],
    }


# ─── Zerodha brokerage calculator ─────────────────────────────────────────────
def calc_brokerage(entry: float, exit_p: float, qty: int) -> dict:
    """
    Calculate exact Zerodha charges for an intraday MIS trade (short + cover).
    Rates as per Zerodha schedule (2024-25):
      Brokerage   : Rs.20 per executed order (flat), capped at 2.5% of trade value
      STT         : 0.025% on sell side only (intraday)
      Exchange txn: 0.00297% on turnover (NSE)
      SEBI charges: Rs.10 per crore of turnover
      GST         : 18% on (brokerage + exchange txn + SEBI)
      Stamp duty  : 0.003% on buy side only
    """
    buy_val  = entry  * qty   # cover (buy back) to close short
    sell_val = exit_p * qty   # initial short (sell)
    turnover = buy_val + sell_val

    brokerage_each = min(20.0, 0.025 / 100 * sell_val)   # entry leg
    brokerage_each += min(20.0, 0.025 / 100 * buy_val)   # exit leg
    brokerage = round(brokerage_each, 2)

    stt          = round(0.025 / 100 * sell_val, 2)       # sell side only
    exchange_txn = round(0.00297 / 100 * turnover, 2)
    sebi         = round(10 / 1e7 * turnover, 2)          # Rs.10 per crore
    stamp        = round(0.003 / 100 * buy_val, 2)        # buy side only
    gst          = round(0.18 * (brokerage + exchange_txn + sebi), 2)

    total = round(brokerage + stt + exchange_txn + sebi + stamp + gst, 2)

    return {
        "brokerage":    brokerage,
        "stt":          stt,
        "exchange_txn": exchange_txn,
        "sebi":         sebi,
        "stamp":        stamp,
        "gst":          gst,
        "total_charges":total,
    }

def run_range(raw: pd.DataFrame, trading_days: list,
              capital: float, cfg: dict) -> list:
    """
    Run strategy across all trading days. Returns list of day_result dicts.
    """
    max_per = capital / cfg["max_positions"]
    day_results = []

    for td in trading_days:
        snap = day_snapshot(raw, td, NIFTY50)
        if not snap:
            continue

        signals = sorted(
            filter(None, (check_signal(s, d, cfg) for s, d in snap.items())),
            key=lambda x: x["surge_pct"], reverse=True
        )
        trades = [simulate_trade(s, snap[s["symbol"]], max_per)
                  for s in signals[:cfg["max_positions"]]]

        day_pnl     = round(sum(t["pnl"]     for t in trades), 2)
        day_net_pnl = round(sum(t["net_pnl"] for t in trades), 2)
        day_charges = round(sum(t["charges"]["total_charges"] for t in trades), 2)
        day_wins    = sum(1 for t in trades if t["win"])
        day_losses  = len(trades) - day_wins

        day_results.append({
            "date":     td.strftime("%Y-%m-%d"),
            "date_fmt": td.strftime("%d %b"),
            "trades":   trades,
            "signals":  len(signals),
            "pnl":      day_pnl,
            "net_pnl":  day_net_pnl,
            "charges":  day_charges,
            "wins":     day_wins,
            "losses":   day_losses,
        })
        status = f"  {td.strftime('%d %b %Y')}  {len(trades)} trades  PnL: {'+'if day_pnl>=0 else ''}Rs.{day_pnl:,.2f}"
        print(status)

    return day_results

# ─── HTML Dashboard ───────────────────────────────────────────────────────────
def build_html(day_results: list, start: date, end: date,
               capital: float, cfg: dict) -> str:

    all_trades    = [t for d in day_results for t in d["trades"]]
    total_pnl     = round(sum(t["pnl"]     for t in all_trades), 2)
    total_charges = round(sum(t["charges"]["total_charges"] for t in all_trades), 2)
    total_net_pnl = round(total_pnl - total_charges, 2)
    all_wins      = [t for t in all_trades if t["win"]]
    all_losses    = [t for t in all_trades if not t["win"]]
    win_rate      = round(len(all_wins) / len(all_trades) * 100, 1) if all_trades else 0
    closing_cap   = round(capital + total_net_pnl, 2)
    ret_pct       = round(total_net_pnl / capital * 100, 2)
    trading_days  = len(day_results)
    active_days   = sum(1 for d in day_results if d["trades"])
    avg_daily     = round(total_net_pnl / active_days, 2) if active_days else 0

    best_trade    = max((t["pnl"] for t in all_trades), default=0)
    worst_trade   = min((t["pnl"] for t in all_trades), default=0)
    best_day      = max((d["pnl"] for d in day_results), default=0)
    worst_day     = min((d["pnl"] for d in day_results), default=0)

    # Cumulative PnL series across days
    cum, running = [], 0
    for d in day_results:
        running += d["pnl"]
        cum.append(round(running, 2))

    # Daily PnL series
    daily_pnls   = [d["pnl"]     for d in day_results]
    daily_labels = [d["date_fmt"] for d in day_results]
    daily_colors = ["#10b981" if p >= 0 else "#f43f5e" for p in daily_pnls]

    # Exit reason breakdown
    reasons = {}
    for t in all_trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    pnl_sign  = "+" if total_net_pnl >= 0 else ""
    ret_sign  = "+" if ret_pct  >= 0 else ""
    pnl_color = "#10b981" if total_net_pnl >= 0 else "#f43f5e"
    title_range = (f"{start.strftime('%d %b %Y')}" if start == end
                   else f"{start.strftime('%d %b')} &ndash; {end.strftime('%d %b %Y')}")

    def j(v): return json.dumps(v)

    # ── Day rows for the trade log table ──────────────────────────────────────
    table_rows = ""
    if not all_trades:
        table_rows = '<tr><td colspan="9" class="no-data">No trades triggered in this date range.</td></tr>'
    else:
        for dr in day_results:
            if not dr["trades"]: continue
            # Day subtotal row
            day_pnl_cls = "pos-text" if dr["pnl"] >= 0 else "neg-text"
            table_rows += f"""
            <tr class="day-row">
                <td class="day-label" colspan="2">{datetime.strptime(dr['date'], '%Y-%m-%d').strftime('%a, %d %b %Y')}</td>
                <td colspan="5"></td>
                <td class="td-r {day_pnl_cls}">{'+'if dr['pnl']>=0 else ''}&#8377;{abs(dr['pnl']):,.2f}</td>
                <td class="td-r">{dr['wins']}W {dr['losses']}L</td>
            </tr>"""
            for t in dr["trades"]:
                clr     = "#10b981" if t["win"] else "#f43f5e"
                r_cls   = "tag-win" if t["win"] else ("tag-stop" if t["reason"]=="Stop loss" else "tag-time")
                r_icon  = "&#9670;" if t["reason"]=="Target hit" else ("&#10005;" if t["reason"]=="Stop loss" else "&#9672;")
                pnl_fmt = ("+" if t["pnl"]>=0 else "-") + "&#8377;" + f"{abs(t['pnl']):,.2f}"
                table_rows += f"""
                <tr class="trade-row">
                    <td class="td-sym">{t['symbol']}</td>
                    <td class="td-r surge-col">+{t['surge_pct']}%</td>
                    <td class="td-r">&#8377;{t['entry']:,.2f}</td>
                    <td class="td-r" style="color:{clr}">&#8377;{t['exit']:,.2f}</td>
                    <td class="td-r">&#8377;{t['stop_loss']:,.2f}</td>
                    <td class="td-r">&#8377;{t['target']:,.2f}</td>
                    <td class="td-r">{t['qty']}</td>
                    <td class="td-r" style="color:{clr};font-weight:600">{pnl_fmt}</td>
                    <td class="td-r"><span class="{r_cls}">{r_icon} {t['reason']}</span></td>
                </tr>"""

    # ── Best/Worst trade cards ─────────────────────────────────────────────────
    def mini_card(t, label):
        if t is None: return ""
        clr = "#10b981" if t["pnl"] >= 0 else "#f43f5e"
        bg  = "rgba(16,185,129,0.06)" if t["pnl"] >= 0 else "rgba(244,63,94,0.06)"
        bdr = "rgba(16,185,129,0.2)"  if t["pnl"] >= 0 else "rgba(244,63,94,0.2)"
        pnl_fmt = ("+" if t["pnl"]>=0 else "-") + "₹" + f"{abs(t['pnl']):,.2f}"
        return f"""
        <div class="mini-card" style="border-color:{bdr};background:{bg}">
            <div class="mini-label">{label}</div>
            <div class="mini-sym">{t['symbol']}</div>
            <div class="mini-pnl" style="color:{clr}">{pnl_fmt}</div>
            <div class="mini-detail">&#8377;{t['entry']:,.2f} &rarr; &#8377;{t['exit']:,.2f} &middot; {t['reason']}</div>
        </div>"""

    best_trade_obj  = max(all_trades, key=lambda t: t["pnl"]) if all_trades else None
    worst_trade_obj = min(all_trades, key=lambda t: t["pnl"]) if all_trades else None

    # Top symbols by total PnL
    sym_pnl = {}
    for t in all_trades:
        sym_pnl[t["symbol"]] = sym_pnl.get(t["symbol"], 0) + t["pnl"]
    top_syms = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:6]
    top_sym_labels = j([s[0] for s in top_syms])
    top_sym_pnls   = j([round(s[1], 2) for s in top_syms])
    top_sym_colors = j(["#10b981" if s[1] >= 0 else "#f43f5e" for s in top_syms])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NSE Paper Trade &mdash; {start.strftime('%d %b')} to {end.strftime('%d %b %Y')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#080a0e;--s1:#0e1117;--s2:#141820;--s3:#1a2030;
  --bd:rgba(255,255,255,0.06);--bd2:rgba(255,255,255,0.11);
  --tx:#e2e8f0;--mt:#64748b;--dm:#334155;
  --gn:#10b981;--rd:#f43f5e;--am:#f59e0b;--bl:#38bdf8;--pu:#a78bfa;
  --sy:'Syne',sans-serif;--mo:'JetBrains Mono',monospace;
}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--mo);background:var(--bg);color:var(--tx);min-height:100vh;overflow-x:hidden}}
body::before{{content:'';position:fixed;inset:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.022) 2px,rgba(0,0,0,0.022) 4px);
  pointer-events:none;z-index:0}}

/* topbar */
.top{{position:sticky;top:0;z-index:100;height:50px;
  background:rgba(8,10,14,0.93);backdrop-filter:blur(14px);
  border-bottom:1px solid var(--bd);
  display:flex;align-items:center;justify-content:space-between;padding:0 2rem}}
.top-logo{{font-family:var(--sy);font-size:15px;font-weight:800;color:var(--tx)}}
.top-logo em{{color:var(--gn);font-style:normal}}
.top-meta{{font-size:11px;color:var(--mt);letter-spacing:0.05em;
  border-left:1px solid var(--bd2);padding-left:18px;margin-left:18px}}
.top-left{{display:flex;align-items:center}}
.top-right{{display:flex;gap:8px}}
.chip{{font-size:10px;padding:3px 10px;border-radius:4px;letter-spacing:0.05em;text-transform:uppercase}}
.chip-g{{background:rgba(16,185,129,0.12);color:var(--gn);border:1px solid rgba(16,185,129,0.2)}}
.chip-b{{background:rgba(56,189,248,0.10);color:var(--bl);border:1px solid rgba(56,189,248,0.2)}}

/* layout */
.page{{max-width:1440px;margin:0 auto;padding:2rem;position:relative;z-index:1}}

/* hero */
.hero{{display:grid;grid-template-columns:1fr auto;gap:2rem;align-items:start;
  margin-bottom:2rem;padding-bottom:2rem;border-bottom:1px solid var(--bd)}}
.hero-title{{font-family:var(--sy);font-size:32px;font-weight:800;
  letter-spacing:-1px;line-height:1.15;color:var(--tx)}}
.hero-title .acc{{color:var(--gn)}}
.hero-sub{{font-size:12px;color:var(--mt);margin-top:8px;line-height:1.9}}
.hero-pnl{{text-align:right}}
.hero-pnl-val{{font-family:var(--sy);font-size:44px;font-weight:800;
  letter-spacing:-2px;line-height:1;color:{pnl_color}}}
.hero-pnl-sub{{font-size:12px;color:var(--mt);margin-top:6px}}

/* metrics */
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
  gap:10px;margin-bottom:2rem}}
.metric{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;
  padding:13px 15px;position:relative;overflow:hidden;
  transition:border-color .2s;animation:fu .4s ease both}}
.metric:hover{{border-color:var(--bd2)}}
.metric::after{{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--ac,var(--gn)),transparent);opacity:.4}}
.ml{{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--mt);margin-bottom:7px}}
.mv{{font-family:var(--sy);font-size:20px;font-weight:700;letter-spacing:-.5px}}
.gn{{color:var(--gn)}}.rd{{color:var(--rd)}}.bl{{color:var(--bl)}}.am{{color:var(--am)}}.pu{{color:var(--pu)}}

/* chart grid */
.chart-grid{{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:2rem}}
.chart-grid-bot{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:2rem}}
.cc{{background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:18px;animation:fu .5s ease both}}
.cc-title{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--mt);margin-bottom:14px}}
.cw{{position:relative;width:100%}}
.cw-tall{{height:220px}}.cw-med{{height:180px}}.cw-short{{height:160px}}

/* mini highlight cards */
.highlights{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:2rem}}
.mini-card{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;padding:14px 16px}}
.mini-label{{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--mt);margin-bottom:6px}}
.mini-sym{{font-family:var(--sy);font-size:20px;font-weight:800;color:var(--tx);margin-bottom:2px}}
.mini-pnl{{font-family:var(--sy);font-size:18px;font-weight:700;margin-bottom:4px}}
.mini-detail{{font-size:11px;color:var(--dm)}}

/* trade log table */
.tbl-wrap{{background:var(--s1);border:1px solid var(--bd);border-radius:10px;overflow:hidden;margin-bottom:2rem;animation:fu .6s ease both}}
.tbl-hdr{{padding:14px 18px;border-bottom:1px solid var(--bd);display:flex;align-items:center;justify-content:space-between}}
.tbl-title{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--mt)}}
.tbl-scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--mt);
  padding:8px 14px;text-align:right;border-bottom:1px solid var(--bd);background:var(--s2)}}
th:first-child{{text-align:left}}
.day-row td{{background:var(--s2);padding:7px 14px;border-bottom:1px solid var(--bd);
  border-top:2px solid rgba(255,255,255,0.05)}}
.day-label{{text-align:left;font-size:11px;font-weight:600;color:var(--mt);letter-spacing:.04em;font-family:var(--sy)}}
.trade-row td{{padding:8px 14px;border-bottom:1px solid var(--bd);color:var(--dm)}}
.trade-row:hover td{{background:rgba(255,255,255,0.02)}}
.trade-row:last-child td{{border-bottom:none}}
.td-sym{{text-align:left;font-weight:600;color:var(--tx)}}
.td-r{{text-align:right}}
.surge-col{{color:var(--am)}}
.pos-text{{color:var(--gn)}}.neg-text{{color:var(--rd)}}
.no-data{{text-align:center;padding:3rem;color:var(--mt);font-size:13px}}

/* tags */
.tag-win{{font-size:10px;padding:2px 7px;border-radius:3px;
  background:rgba(16,185,129,0.12);color:var(--gn);border:1px solid rgba(16,185,129,0.2)}}
.tag-stop{{font-size:10px;padding:2px 7px;border-radius:3px;
  background:rgba(244,63,94,0.12);color:var(--rd);border:1px solid rgba(244,63,94,0.2)}}
.tag-time{{font-size:10px;padding:2px 7px;border-radius:3px;
  background:rgba(245,158,11,0.12);color:var(--am);border:1px solid rgba(245,158,11,0.2)}}

/* footer */
.footer{{margin-top:3rem;padding:1.5rem 0;border-top:1px solid var(--bd);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}}
.footer div{{font-size:10px;color:var(--dm);line-height:1.9}}

/* animation */
@keyframes fu{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
.metric:nth-child(1){{animation-delay:.04s}}.metric:nth-child(2){{animation-delay:.08s}}
.metric:nth-child(3){{animation-delay:.12s}}.metric:nth-child(4){{animation-delay:.16s}}
.metric:nth-child(5){{animation-delay:.20s}}.metric:nth-child(6){{animation-delay:.24s}}
.metric:nth-child(7){{animation-delay:.28s}}.metric:nth-child(8){{animation-delay:.32s}}
.metric:nth-child(9){{animation-delay:.36s}}.metric:nth-child(10){{animation-delay:.40s}}

@media(max-width:900px){{
  .chart-grid,.chart-grid-bot{{grid-template-columns:1fr}}
  .hero{{grid-template-columns:1fr}}
  .hero-pnl{{text-align:left}}
  .hero-pnl-val{{font-size:32px}}
  .hero-title{{font-size:24px}}
  .page{{padding:1rem}}
  .top{{padding:0 1rem}}
  .highlights{{grid-template-columns:1fr}}
}}
</style>
</head>
<body>

<div class="top">
  <div class="top-left">
    <div class="top-logo">NSE <em>&#9650;</em> Surge</div>
    <div class="top-meta">{title_range} &nbsp;&middot;&nbsp; {trading_days} trading days</div>
  </div>
  <div class="top-right">
    <span class="chip chip-b">Paper Trade</span>
    <span class="chip chip-g">Morning Surge Short</span>
  </div>
</div>

<div class="page">

  <!-- HERO -->
  <div class="hero">
    <div>
      <div class="hero-title">
        Morning Surge Short<br>Strategy <span class="acc">&middot;</span> NSE
      </div>
      <div class="hero-sub">
        {title_range}
        &nbsp;&middot;&nbsp; Capital &#8377;{capital:,.0f}
        &nbsp;&middot;&nbsp; {trading_days} trading days scanned
        &nbsp;&middot;&nbsp; {active_days} days with trades
        &nbsp;&middot;&nbsp; {len(all_trades)} total positions
      </div>
    </div>
    <div class="hero-pnl">
      <div class="hero-pnl-val">{pnl_sign}&#8377;{abs(total_net_pnl):,.2f}</div>
      <div class="hero-pnl-sub">
        Net P&amp;L after charges &nbsp;&middot;&nbsp;
        <span style="color:{'var(--gn)' if ret_pct>=0 else 'var(--rd)'}">{ret_sign}{ret_pct}%</span>
        return
      </div>
    </div>
  </div>

  <!-- METRICS -->
  <div class="metrics">
    <div class="metric" style="--ac:{'var(--gn)' if closing_cap>=capital else 'var(--rd)'}">
      <div class="ml">Closing capital</div>
      <div class="mv {'gn' if closing_cap>=capital else 'rd'}">&#8377;{closing_cap:,.0f}</div>
    </div>
    <div class="metric" style="--ac:{'var(--gn)' if total_pnl>=0 else 'var(--rd)'}">
      <div class="ml">Net P&amp;L</div>
      <div class="mv {'gn' if total_pnl>=0 else 'rd'}">{pnl_sign}&#8377;{abs(total_pnl):,.2f}</div>
    </div>
    <div class="metric" style="--ac:{'var(--gn)' if ret_pct>=0 else 'var(--rd)'}">
      <div class="ml">Total return</div>
      <div class="mv {'gn' if ret_pct>=0 else 'rd'}">{ret_sign}{ret_pct}%</div>
    </div>
    <div class="metric" style="--ac:var(--bl)">
      <div class="ml">Win rate</div>
      <div class="mv bl">{win_rate}%</div>
    </div>
    <div class="metric" style="--ac:var(--am)">
      <div class="ml">Total trades</div>
      <div class="mv am">{len(all_trades)}</div>
    </div>
    <div class="metric" style="--ac:var(--gn)">
      <div class="ml">Wins</div>
      <div class="mv gn">{len(all_wins)}</div>
    </div>
    <div class="metric" style="--ac:var(--rd)">
      <div class="ml">Losses</div>
      <div class="mv {'rd' if all_losses else ''}">{len(all_losses)}</div>
    </div>
    <div class="metric" style="--ac:var(--pu)">
      <div class="ml">Avg daily P&amp;L</div>
      <div class="mv pu">{'+'if avg_daily>=0 else ''}&#8377;{abs(avg_daily):,.0f}</div>
    </div>
    <div class="metric" style="--ac:var(--gn)">
      <div class="ml">Best day</div>
      <div class="mv gn">+&#8377;{abs(best_day):,.0f}</div>
    </div>
    <div class="metric" style="--ac:var(--rd)">
      <div class="ml">Worst day</div>
      <div class="mv rd">-&#8377;{abs(worst_day):,.0f}</div>
    </div>
    <div class="metric" style="--ac:#f97316">
      <div class="ml">Total charges</div>
      <div class="mv" style="color:#f97316">-&#8377;{total_charges:,.2f}</div>
    </div>
    <div class="metric" style="--ac:var(--pu)">
      <div class="ml">Gross P&amp;L</div>
      <div class="mv {'gn' if total_pnl>=0 else 'rd'}">{'+ ' if total_pnl>=0 else ' '}&#8377;{abs(total_pnl):,.2f}</div>
    </div>
  </div>

  <!-- CHARTS ROW 1 -->
  <div class="chart-grid">
    <div class="cc">
      <div class="cc-title">Cumulative P&amp;L across period</div>
      <div class="cw cw-tall"><canvas id="cumChart"></canvas></div>
    </div>
    <div class="cc">
      <div class="cc-title">Exit reason breakdown</div>
      <div class="cw cw-tall"><canvas id="reasonChart"></canvas></div>
    </div>
  </div>

  <!-- CHARTS ROW 2 -->
  <div class="chart-grid-bot">
    <div class="cc">
      <div class="cc-title">Daily P&amp;L</div>
      <div class="cw cw-med"><canvas id="dailyChart"></canvas></div>
    </div>
    <div class="cc">
      <div class="cc-title">P&amp;L by symbol (all trades)</div>
      <div class="cw cw-med"><canvas id="symChart"></canvas></div>
    </div>
    <div class="cc">
      <div class="cc-title">Trades per day distribution</div>
      <div class="cw cw-med"><canvas id="tradeCountChart"></canvas></div>
    </div>
  </div>

  <!-- HIGHLIGHTS -->
  <div class="highlights">
    {mini_card(best_trade_obj,  "Best single trade")}
    {mini_card(worst_trade_obj, "Worst single trade")}
  </div>

  <!-- TRADE LOG TABLE -->
  <div class="tbl-wrap">
    <div class="tbl-hdr">
      <div class="tbl-title">Full trade log &mdash; {len(all_trades)} trades across {active_days} days</div>
      <div style="font-size:10px;color:var(--mt)">
        Surge &ge;{cfg['surge_threshold']}% &nbsp;&middot;&nbsp;
        Vol &ge;{cfg['volume_spike_multiplier']}&times; &nbsp;&middot;&nbsp;
        SL {cfg['stop_loss_pct']}% &nbsp;&middot;&nbsp; TGT {cfg['target_pct']}%
      </div>
    </div>
    <div class="tbl-scroll">
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Surge</th><th>Entry</th><th>Exit</th>
            <th>Stop loss</th><th>Target</th><th>Qty</th>
            <th>Gross P&amp;L</th><th>Charges</th><th>Net P&amp;L</th><th>Outcome</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="footer">
    <div>
      Strategy &nbsp;&middot;&nbsp;
      Surge &ge; {cfg['surge_threshold']}% &nbsp;&middot;&nbsp;
      Volume &ge; {cfg['volume_spike_multiplier']}&times; 20-day avg &nbsp;&middot;&nbsp;
      Stop loss {cfg['stop_loss_pct']}% &nbsp;&middot;&nbsp;
      Target {cfg['target_pct']}% &nbsp;&middot;&nbsp;
      Max {cfg['max_positions']} positions/day &nbsp;&middot;&nbsp;
      Max &#8377;{capital/cfg['max_positions']:,.0f}/trade
    </div>
    <div>Data: Yahoo Finance (yfinance) &nbsp;&middot;&nbsp; NSE equities &nbsp;&middot;&nbsp; Nifty 50 watchlist</div>
  </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size   = 11;

const dailyLabels = {j(daily_labels)};
const dailyPnls   = {j(daily_pnls)};
const dailyColors = {j(daily_colors)};
const cumPnl      = {j(cum)};
const reasons     = {j(reasons)};
const topSymLabels= {top_sym_labels};
const topSymPnls  = {top_sym_pnls};
const topSymColors= {top_sym_colors};
const tradeCounts = {j([d['wins']+d['losses'] for d in day_results])};

/* ── cumulative ── */
new Chart(document.getElementById('cumChart'), {{
  type: 'line',
  data: {{ labels: dailyLabels, datasets: [{{
    data: cumPnl,
    borderColor: cumPnl[cumPnl.length-1] >= 0 ? '#10b981' : '#f43f5e',
    backgroundColor: cumPnl[cumPnl.length-1] >= 0 ? 'rgba(16,185,129,0.07)' : 'rgba(244,63,94,0.07)',
    fill: true, tension: 0.35, pointRadius: dailyLabels.length > 30 ? 0 : 4,
    pointBackgroundColor: dailyColors, pointBorderColor: 'transparent', borderWidth: 2
  }}] }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins:{{ legend:{{display:false}},
      tooltip:{{ callbacks:{{ label: ctx => (ctx.raw>=0?'+':'')+'₹'+ctx.raw.toFixed(2) }} }} }},
    scales:{{
      x:{{ ticks:{{color:'#64748b', maxTicksLimit:12}}, grid:{{display:false}}, border:{{color:'#1a2030'}} }},
      y:{{ ticks:{{color:'#64748b', callback: v=>(v>=0?'+':'')+'₹'+v.toFixed(0)}},
           grid:{{color:'rgba(255,255,255,0.04)'}}, border:{{color:'#1a2030'}} }}
    }},
    animation:{{duration:1200,easing:'easeOutQuart'}}
  }}
}});

/* ── exit reason donut ── */
const reasonKeys   = Object.keys(reasons);
const reasonVals   = Object.values(reasons);
const reasonColors = {{'Target hit':'#10b981','Stop loss':'#f43f5e','Time exit':'#f59e0b'}};
new Chart(document.getElementById('reasonChart'), {{
  type: 'doughnut',
  data: {{ labels: reasonKeys, datasets: [{{
    data: reasonVals,
    backgroundColor: reasonKeys.map(k => reasonColors[k] || '#64748b'),
    borderColor: '#080a0e', borderWidth: 3, hoverOffset: 6
  }}] }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    cutout: '62%',
    plugins:{{
      legend:{{ position:'bottom', labels:{{color:'#64748b',padding:14,font:{{size:11}}}}}},
      tooltip:{{ callbacks:{{ label: ctx => ` ${{ctx.label}}: ${{ctx.raw}} trades` }} }}
    }},
    animation:{{duration:1000,easing:'easeOutQuart'}}
  }}
}});

/* ── daily PnL bars ── */
new Chart(document.getElementById('dailyChart'), {{
  type:'bar',
  data:{{ labels:dailyLabels, datasets:[{{
    data:dailyPnls,
    backgroundColor:dailyColors.map(c=>c+'99'),
    borderColor:dailyColors, borderWidth:1, borderRadius:3, borderSkipped:false
  }}] }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    plugins:{{ legend:{{display:false}},
      tooltip:{{ callbacks:{{ label: ctx=>(ctx.raw>=0?'+':'')+'₹'+ctx.raw.toFixed(2) }} }} }},
    scales:{{
      x:{{ ticks:{{color:'#64748b',maxTicksLimit:12}}, grid:{{display:false}}, border:{{color:'#1a2030'}} }},
      y:{{ ticks:{{color:'#64748b', callback:v=>(v>=0?'+':'')+'₹'+v.toFixed(0)}},
           grid:{{color:'rgba(255,255,255,0.04)'}}, border:{{color:'#1a2030'}} }}
    }},
    animation:{{duration:900,easing:'easeOutQuart'}}
  }}
}});

/* ── symbol PnL bars ── */
new Chart(document.getElementById('symChart'), {{
  type:'bar',
  data:{{ labels:topSymLabels, datasets:[{{
    data:topSymPnls,
    backgroundColor:topSymColors.map(c=>c+'99'),
    borderColor:topSymColors, borderWidth:1, borderRadius:3, borderSkipped:false
  }}] }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    plugins:{{ legend:{{display:false}},
      tooltip:{{ callbacks:{{ label: ctx=>(ctx.raw>=0?'+':'')+'₹'+ctx.raw.toFixed(2) }} }} }},
    scales:{{
      x:{{ ticks:{{color:'#64748b'}}, grid:{{display:false}}, border:{{color:'#1a2030'}} }},
      y:{{ ticks:{{color:'#64748b', callback:v=>(v>=0?'+':'')+'₹'+v.toFixed(0)}},
           grid:{{color:'rgba(255,255,255,0.04)'}}, border:{{color:'#1a2030'}} }}
    }},
    animation:{{duration:900,easing:'easeOutQuart'}}
  }}
}});

/* ── trades-per-day bar ── */
new Chart(document.getElementById('tradeCountChart'), {{
  type:'bar',
  data:{{ labels:dailyLabels, datasets:[{{
    data:tradeCounts,
    backgroundColor:'rgba(56,189,248,0.3)', borderColor:'#38bdf8',
    borderWidth:1, borderRadius:3, borderSkipped:false
  }}] }},
  options:{{
    responsive:true, maintainAspectRatio:false,
    plugins:{{ legend:{{display:false}} }},
    scales:{{
      x:{{ ticks:{{color:'#64748b',maxTicksLimit:12}}, grid:{{display:false}}, border:{{color:'#1a2030'}} }},
      y:{{ ticks:{{color:'#64748b',stepSize:1}},
           grid:{{color:'rgba(255,255,255,0.04)'}}, border:{{color:'#1a2030'}} }}
    }},
    animation:{{duration:900,easing:'easeOutQuart'}}
  }}
}});
</script>
</body>
</html>"""

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="NSE Morning Surge Short — Date Range Paper Trade",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python nse_backtest.py --from 2025-03-01 --to 2025-04-01
  python nse_backtest.py --from 2025-01-01 --to 2025-03-31 --capital 200000
  python nse_backtest.py --from 2025-04-01 --to 2025-04-01  (single day)
        """
    )
    p.add_argument("--from",      dest="date_from", required=True, help="Start date  YYYY-MM-DD")
    p.add_argument("--to",        dest="date_to",   required=True, help="End date    YYYY-MM-DD")
    p.add_argument("--capital",   type=float, default=100_000, help="Capital in INR (default 100000)")
    p.add_argument("--surge",     type=float, default=3.0,  help="Min surge %%  (default 3.0)")
    p.add_argument("--volume",    type=float, default=1.5,  help="Min volume multiplier (default 1.5)")
    p.add_argument("--stop-loss", type=float, default=2.0,  help="Stop loss %%  (default 2.0)")
    p.add_argument("--target",    type=float, default=2.0,  help="Target %%     (default 2.0)")
    p.add_argument("--max-pos",   type=int,   default=5,    help="Max positions/day (default 5)")
    p.add_argument("--output-dir",default=".",               help="Folder to save HTML (default: .)")
    args = p.parse_args()

    # Parse dates
    try:
        start = datetime.strptime(args.date_from, "%Y-%m-%d").date()
        end   = datetime.strptime(args.date_to,   "%Y-%m-%d").date()
    except ValueError:
        print("❌  Bad date format — use YYYY-MM-DD"); sys.exit(1)
    if start > end:
        print("❌  --from date must be before or equal to --to date"); sys.exit(1)
    if end > date.today():
        print("❌  --to date cannot be in the future"); sys.exit(1)

    cfg = {
        "surge_threshold":         args.surge,
        "volume_spike_multiplier": args.volume,
        "stop_loss_pct":           args.stop_loss,
        "target_pct":              args.target,
        "max_positions":           args.max_pos,
        "circuit_buffer_pct":      2.0,
    }

    print(f"\n{'='*56}")
    print(f"  NSE Morning Surge Short  |  Paper Trade")
    print(f"  {start.strftime('%d %b %Y')}  to  {end.strftime('%d %b %Y')}")
    print(f"  Capital: Rs.{args.capital:,.0f}  |  Max/trade: Rs.{args.capital/cfg['max_positions']:,.0f}")
    print(f"  Surge>={cfg['surge_threshold']}%  Vol>={cfg['volume_spike_multiplier']}x  SL:{cfg['stop_loss_pct']}%  TGT:{cfg['target_pct']}%")
    print(f"{'='*56}")

    # ONE bulk download covering the whole range + lookback
    try:
        raw = fetch_all(start, end, NIFTY50)
    except ValueError as e:
        print(f"\n❌  {e}\n"); sys.exit(1)

    trading_days = get_trading_days(raw, start, end)
    if not trading_days:
        print("❌  No trading days found in the specified range."); sys.exit(1)

    print(f"\n  {len(trading_days)} trading days found. Running strategy...\n")
    day_results = run_range(raw, trading_days, args.capital, cfg)

    if not day_results:
        print("❌  No results — check the date range."); sys.exit(1)

    # Summary
    all_trades = [t for d in day_results for t in d["trades"]]
    total_pnl  = sum(t["pnl"] for t in all_trades)
    wins       = [t for t in all_trades if t["win"]]

    print(f"\n{'='*56}")
    print(f"  SUMMARY")
    print(f"  Trading days : {len(day_results)}")
    print(f"  Total trades : {len(all_trades)}")
    print(f"  Wins         : {len(wins)}  |  Losses: {len(all_trades)-len(wins)}")
    if all_trades:
        print(f"  Win rate     : {len(wins)/len(all_trades)*100:.1f}%")
    total_charges_sum = sum(t["charges"]["total_charges"] for t in all_trades)
    net = total_pnl - total_charges_sum
    print(f"  Gross P&L    : {'+'if total_pnl>=0 else ''}Rs.{total_pnl:,.2f}")
    print(f"  Charges      : -Rs.{total_charges_sum:,.2f}")
    print(f"  Net P&L      : {'+'if net>=0 else ''}Rs.{net:,.2f}")
    print(f"  Return       : {net/args.capital*100:+.2f}%")
    print(f"  Closing cap  : Rs.{args.capital+net:,.2f}")
    print(f"{'='*56}\n")

    # Build & save HTML — always auto-open
    os.makedirs(args.output_dir, exist_ok=True)
    fname   = f"nse_paper_{start.strftime('%Y%m%d')}_to_{end.strftime('%Y%m%d')}.html"
    outpath = os.path.join(args.output_dir, fname)
    html    = build_html(day_results, start, end, args.capital, cfg)

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(html)

    abs_path = os.path.abspath(outpath)
    print(f"  Dashboard saved  ->  {abs_path}")
    print(f"  Opening in browser...\n")
    webbrowser.open(f"file://{abs_path}")

if __name__ == "__main__":
    main()
