"""
Backtesting Engine for Morning Surge Short Strategy
Tests strategy on historical data and produces performance reports.
"""

import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def generate_synthetic_data(symbol: str, days: int = 90,
                             seed: int = None) -> pd.DataFrame:
    """
    Generate realistic synthetic OHLCV data for backtesting when
    no real data source is available.
    """
    if seed:
        np.random.seed(seed)

    dates = pd.date_range(end=datetime.today(), periods=days, freq='B')
    base_price = np.random.uniform(200, 2000)
    prices = [base_price]

    for _ in range(days - 1):
        change = np.random.normal(0, 0.015)  # ~1.5% daily volatility
        prices.append(prices[-1] * (1 + change))

    records = []
    for i, (date, close) in enumerate(zip(dates, prices)):
        open_p = close * np.random.uniform(0.97, 1.03)
        high = max(open_p, close) * np.random.uniform(1.0, 1.04)
        low = min(open_p, close) * np.random.uniform(0.96, 1.0)
        volume = int(np.random.uniform(100_000, 5_000_000))
        morning_surge = np.random.normal(0, 2.5)  # morning price change %
        records.append({
            "date": date,
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": volume,
            "morning_surge_pct": round(morning_surge, 2),
            "morning_volume_ratio": round(np.random.uniform(0.5, 4.0), 2),
        })

    df = pd.DataFrame(records)
    df.set_index("date", inplace=True)
    return df


class BacktestEngine:
    """
    Simulates the Morning Surge Short Strategy on historical data.
    """

    def __init__(self, config: dict = None):
        from morning_surge_strategy import MorningSurgeStrategy
        self.config = config or {}
        self.strategy = MorningSurgeStrategy(config)
        self.results: list[dict] = []

    def load_data(self, symbol: str, csv_path: str = None) -> pd.DataFrame:
        """Load OHLCV data from CSV or generate synthetic data."""
        if csv_path and os.path.exists(csv_path):
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            logger.info(f"Loaded {len(df)} rows for {symbol} from {csv_path}")
            return df
        else:
            logger.info(f"No data file for {symbol}, generating synthetic data")
            return generate_synthetic_data(symbol, days=90)

    def simulate_intraday(self, date: pd.Timestamp, symbol: str,
                           open_price: float, close_price: float,
                           morning_surge_pct: float,
                           volume_ratio: float) -> Optional[dict]:
        """
        Simulate one intraday trading session for a symbol.
        Returns trade dict if a trade was made, else None.
        """
        config = self.strategy.config
        surge_threshold = config["surge_threshold"]
        stop_loss_pct = config["stop_loss_pct"] / 100
        target_pct = config["target_pct"] / 100

        # Check surge condition
        if morning_surge_pct < surge_threshold:
            return None

        # Check volume condition
        if volume_ratio < config["volume_spike_multiplier"]:
            return None

        # Simulate entry (morning surge price)
        entry_price = open_price * (1 + morning_surge_pct / 100)
        stop_loss = entry_price * (1 + stop_loss_pct)
        target = entry_price * (1 - target_pct)

        # Simulate price path using mean reversion model
        reversal_prob = 0.55 + (morning_surge_pct - surge_threshold) * 0.03
        reversal_prob = min(0.75, reversal_prob)
        reversal = np.random.random() < reversal_prob

        if reversal:
            # Stock reverses towards close
            exit_price = entry_price * np.random.uniform(0.97, 1.0)
            exit_price = max(target, exit_price)  # can't go below target
            reason = "TARGET_HIT" if exit_price <= target else "TIME_EXIT"
        else:
            # Stock continues up, hits stop loss
            exit_price = entry_price * np.random.uniform(1.01, 1.025)
            exit_price = min(stop_loss, exit_price)
            reason = "STOP_LOSS_HIT"

        quantity = int(config["max_position_size"] / entry_price)
        pnl = (entry_price - exit_price) * quantity

        return {
            "date": date.strftime("%Y-%m-%d"),
            "symbol": symbol,
            "morning_surge_pct": round(morning_surge_pct, 2),
            "volume_ratio": round(volume_ratio, 2),
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "stop_loss": round(stop_loss, 2),
            "target_price": round(target, 2),
            "quantity": quantity,
            "pnl": round(pnl, 2),
            "pnl_pct": round((entry_price - exit_price) / entry_price * 100, 2),
            "exit_reason": reason,
            "win": pnl > 0,
        }

    def run(self, symbols: list[str], data_dir: str = None) -> pd.DataFrame:
        """
        Run full backtest across symbols and dates.
        Returns DataFrame of all trades.
        """
        all_trades = []
        logger.info(f"Starting backtest for {len(symbols)} symbols...")

        for symbol in symbols:
            csv_path = os.path.join(data_dir, f"{symbol}.csv") if data_dir else None
            df = self.load_data(symbol, csv_path)

            for date, row in df.iterrows():
                trade = self.simulate_intraday(
                    date=date,
                    symbol=symbol,
                    open_price=row.get("open", 100),
                    close_price=row.get("close", 100),
                    morning_surge_pct=row.get("morning_surge_pct", 0),
                    volume_ratio=row.get("morning_volume_ratio", 1),
                )
                if trade:
                    all_trades.append(trade)

        self.results = all_trades
        df_results = pd.DataFrame(all_trades)
        logger.info(f"Backtest complete: {len(df_results)} trades across {len(symbols)} symbols")
        return df_results

    def compute_metrics(self, df: pd.DataFrame) -> dict:
        """Compute comprehensive performance metrics from backtest results."""
        if df.empty:
            return {"error": "No trades generated"}

        total = len(df)
        wins = df[df["win"] == True]
        losses = df[df["win"] == False]

        cumulative_pnl = df["pnl"].cumsum()
        running_max = cumulative_pnl.cummax()
        drawdown = running_max - cumulative_pnl
        max_drawdown = drawdown.max()

        avg_win = wins["pnl"].mean() if len(wins) > 0 else 0
        avg_loss = losses["pnl"].mean() if len(losses) > 0 else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        # Monthly breakdown
        df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
        monthly = df.groupby("month")["pnl"].sum().reset_index()
        monthly.columns = ["month", "monthly_pnl"]

        return {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(len(wins) / total * 100, 2),
            "total_pnl": round(df["pnl"].sum(), 2),
            "avg_trade_pnl": round(df["pnl"].mean(), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 3),
            "max_drawdown": round(max_drawdown, 2),
            "best_trade": round(df["pnl"].max(), 2),
            "worst_trade": round(df["pnl"].min(), 2),
            "sharpe_ratio": round(
                df["pnl"].mean() / df["pnl"].std() * np.sqrt(252)
                if df["pnl"].std() > 0 else 0, 3
            ),
            "monthly_pnl": monthly.to_dict(orient="records"),
            "exit_reasons": df["exit_reason"].value_counts().to_dict(),
        }

    def save_results(self, df: pd.DataFrame, metrics: dict,
                      output_dir: str = ".") -> None:
        """Save backtest results to CSV and JSON."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        trades_path = os.path.join(output_dir, f"backtest_trades_{timestamp}.csv")
        df.to_csv(trades_path, index=False)

        metrics_path = os.path.join(output_dir, f"backtest_metrics_{timestamp}.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info(f"Results saved: {trades_path}, {metrics_path}")
        print(f"\n📊 BACKTEST RESULTS")
        print(f"{'='*50}")
        print(f"Total Trades     : {metrics['total_trades']}")
        print(f"Win Rate         : {metrics['win_rate_pct']}%")
        print(f"Total PnL        : ₹{metrics['total_pnl']:,.2f}")
        print(f"Profit Factor    : {metrics['profit_factor']}")
        print(f"Max Drawdown     : ₹{metrics['max_drawdown']:,.2f}")
        print(f"Sharpe Ratio     : {metrics['sharpe_ratio']}")
        print(f"Best Trade       : ₹{metrics['best_trade']:,.2f}")
        print(f"Worst Trade      : ₹{metrics['worst_trade']:,.2f}")
        print(f"{'='*50}\n")
