# 📉 Morning Surge Short Strategy

An algorithmic trading system for Indian equities that detects abnormal morning price surges and shorts them for intraday mean-reversion profits.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Market](https://img.shields.io/badge/Market-NSE%20India-orange)
![Mode](https://img.shields.io/badge/Trading-Intraday-red)

---

## 🧠 Strategy Logic

```
09:15 AM  Market opens
          ↓
10:00 AM  Stock surges ≥3% on high volume?
          → YES: Score signal (0–100), check circuit limits
          → Score ≥ 50: ENTER SHORT
          ↓
10:30 AM  Entry window closes
          ↓
Throughout the day:
  • Price hits –2% target → BOOK PROFIT
  • Price hits +2% stop   → EXIT LOSS
          ↓
02:30 PM  Force-close all remaining positions
```

**Thesis**: Stocks that surge >3% in the first hour on abnormally high volume tend to reverse and give back gains as momentum fades.

---

## 🗂 Project Structure

```
morning_surge_strategy/
├── main.py                   # CLI entry point
├── morning_surge_strategy.py # Core signal generation + position management
├── backtesting_engine.py     # Historical simulation + metrics
├── live_trading.py           # Paper & live trading engine (Zerodha Kite)
├── dashboard.html            # Browser-based live dashboard
├── config.json               # Strategy parameters (edit me!)
├── requirements.txt          # Python dependencies
├── QUICKSTART.md             # Beginner guide
└── output/                   # Generated backtest results & trade logs
```

---

## ⚡ Quick Start

### 1. Install dependencies
```bash
pip install pandas numpy matplotlib --break-system-packages
```

### 2. Run backtesting (uses synthetic data if no CSV provided)
```bash
python main.py --mode backtest
```

### 3. Paper trading simulation
```bash
python main.py --mode paper --paper-duration 30
```

### 4. Live trading (requires Zerodha Kite)
```bash
export KITE_API_KEY=your_api_key
export KITE_ACCESS_TOKEN=your_access_token
python main.py --mode live
```

### 5. Open the dashboard
Open `dashboard.html` in any browser — no server required.

---

## ⚙️ Configuration (`config.json`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `surge_threshold` | `3.0` | Minimum % surge to flag a stock |
| `volume_spike_multiplier` | `1.5` | Required volume vs 10-day average |
| `stop_loss_pct` | `2.0` | Stop loss from entry (%) |
| `target_pct` | `2.0` | Profit target from entry (%) |
| `max_position_size` | `50000` | Max INR per position |
| `max_positions` | `5` | Max concurrent short positions |
| `circuit_buffer` | `2.0` | % buffer from upper circuit limit |
| `min_signal_strength` | `50` | Minimum signal score (0–100) |
| `exit_time` | `"14:30"` | Force-close all positions at this time |

### Preset Profiles

**Conservative** — fewer, higher-confidence trades:
```json
{ "surge_threshold": 4.0, "stop_loss_pct": 1.5, "max_positions": 3 }
```

**Balanced** *(default)* — good risk/reward:
```json
{ "surge_threshold": 3.0, "stop_loss_pct": 2.0, "max_positions": 5 }
```

**Aggressive** — more trades, higher risk:
```json
{ "surge_threshold": 2.5, "stop_loss_pct": 3.0, "max_positions": 8 }
```

---

## 📊 Signal Scoring (0–100)

| Component | Max Points | Logic |
|-----------|-----------|-------|
| Surge magnitude | 40 | Stronger surge = higher score |
| Volume spike | 30 | Higher volume ratio = higher score |
| Historical reversal rate | 30 | % of past surge days that reversed |

Only signals scoring **≥50** trigger a trade.

---

## 🔌 Zerodha Kite Integration

1. Create an app at [kite.zerodha.com/connect/login](https://kite.zerodha.com/connect/login)
2. Install the client: `pip install kiteconnect`
3. Authenticate daily to get an access token
4. Set env vars:
```bash
export KITE_API_KEY=xxxxx
export KITE_ACCESS_TOKEN=yyyyy
python main.py --mode live
```

All live orders are placed as **MIS (intraday)** in the NSE segment.

---

## 📈 Backtesting

The engine uses synthetic OHLCV data by default. To use real data:

1. Download CSV files named `SYMBOL.csv` with columns: `date, open, high, low, close, volume, morning_surge_pct, morning_volume_ratio`
2. Place them in a directory (e.g., `data/`)
3. Run: `python main.py --mode backtest`

Backtest outputs are saved to `output/` as:
- `backtest_trades_YYYYMMDD_HHMMSS.csv` — all trade records
- `backtest_metrics_YYYYMMDD_HHMMSS.json` — performance summary

---

## ⚠️ Risk Warnings

- **This is not financial advice.** Trading involves substantial risk of loss.
- Always paper trade extensively before using real capital.
- Never trade with money you cannot afford to lose.
- Upper circuit events can trap short positions — monitor actively.
- This strategy underperforms in strong trending bull markets.
- Execution slippage in live trading will reduce simulated returns.

---

## 🚀 Roadmap

- [ ] News sentiment integration (FinBERT)
- [ ] Telegram/SMS alerts for signals
- [ ] Multi-timeframe confirmation
- [ ] Options strategy layer (buying puts instead of shorting)
- [ ] Cloud deployment (AWS Lambda)
- [ ] Machine learning signal ranking

---

## 📚 Learning Resources

- *Trading in the Zone* — Mark Douglas (psychology)
- *The New Trading for a Living* — Alexander Elder (risk management)
- *Algorithmic Trading* — Ernie Chan (backtesting & systems)
- [NSE India](https://www.nseindia.com/) — official market data
- [Zerodha Varsity](https://zerodha.com/varsity/) — free trading education

---

## 📝 License

MIT License — free to use, modify, and distribute.

---

*Built for educational purposes. Always understand what you're trading before risking real capital.*
