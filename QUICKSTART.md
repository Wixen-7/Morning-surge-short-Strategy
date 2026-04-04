# ⚡ QUICKSTART — Morning Surge Short Strategy

New to this system? Start here. Takes ~10 minutes.

---

## Step 1: Install Python Dependencies

```bash
pip install pandas numpy matplotlib --break-system-packages
```

---

## Step 2: Run Your First Backtest

```bash
python main.py --mode backtest
```

You'll see output like:
```
📊 BACKTEST RESULTS
==================================================
Total Trades     : 47
Win Rate         : 59.57%
Total PnL        : ₹84,320.00
Profit Factor    : 1.412
Max Drawdown     : ₹12,450.00
Sharpe Ratio     : 1.234
==================================================
```

Results are saved in `output/` as CSV and JSON files.

---

## Step 3: Watch Paper Trading

```bash
python main.py --mode paper --paper-duration 5
```

This runs a 5-minute simulation showing how the system scans stocks,
detects surge signals, opens short positions, and manages exits.
No real money involved.

---

## Step 4: Open the Dashboard

Open `dashboard.html` in your browser.

You'll see:
- 📊 Live PnL curve
- 🔍 Detected surge opportunities
- 📋 Simulated open positions
- 🗒 Activity log with trade events

---

## Step 5: Understand the Signal

A signal fires when **ALL** of these are true:

| Check | Condition |
|-------|-----------|
| Price surge | Stock up ≥3% from open |
| Volume | Today's volume ≥1.5× 10-day average |
| Circuit | Not within 2% of upper circuit |
| Positions | Current open positions < 5 |
| Score | Signal strength ≥50/100 |

---

## Step 6: Customize the Config

Edit `config.json` to tune the strategy:

```json
{
  "surge_threshold": 3.5,    ← raise to be more selective
  "stop_loss_pct": 1.5,      ← lower to reduce losses per trade
  "max_positions": 3         ← lower if you want fewer trades
}
```

After editing, re-run the backtest to see how metrics change.

---

## Step 7: Learning Path

| Week | Activity |
|------|----------|
| 1 | Read README + understand signal logic |
| 2–3 | Run paper trading daily, observe patterns |
| 4 | Backtest on different configs |
| 5+ | Live trading with minimal size (₹50k capital) |

---

## Common Questions

**Q: Why does the backtest use "synthetic" data?**
Real NSE historical data requires a paid data vendor (e.g., Zerodha, NSE official). The engine generates realistic simulated data so you can test the system logic without a subscription.

**Q: How accurate is paper trading?**
Paper trading simulates market behaviour but not real slippage, partial fills, or circuit events. Treat it as logic validation, not performance prediction.

**Q: Can I add my own stock list?**
Yes — pass symbols via CLI: `python main.py --mode paper --symbols RELIANCE INFY TCS`

**Q: How do I connect Zerodha for live trading?**
See the README's "Zerodha Kite Integration" section.

---

*Remember: Understand the system fully before trading real money.*
