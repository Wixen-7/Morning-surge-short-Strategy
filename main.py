"""
Morning Surge Short Strategy — Main Entry Point
Usage:
    python main.py --mode backtest
    python main.py --mode paper
    python main.py --mode live --api-key YOUR_KEY --access-token YOUR_TOKEN
"""

import argparse
import json
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default watchlist for Indian equities
DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "WIPRO", "AXISBANK", "BAJFINANCE", "KOTAKBANK", "SBIN",
    "TATASTEEL", "HCLTECH", "SUNPHARMA", "DRREDDY", "CIPLA",
    "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL",
    "MARUTI", "M&M", "TATAMOTORS", "HEROMOTOCO", "EICHERMOT",
    "ADANIENT", "ADANIPORTS", "ULTRACEMCO", "GRASIM", "HINDALCO",
]

DEFAULT_CONFIG = {
    "surge_threshold": 3.0,
    "volume_spike_multiplier": 1.5,
    "stop_loss_pct": 2.0,
    "target_pct": 2.0,
    "max_position_size": 50000,
    "max_positions": 5,
    "circuit_buffer": 2.0,
    "min_signal_strength": 50,
    "detection_window_start": "09:15",
    "detection_window_end": "10:15",
    "entry_window_end": "10:30",
    "exit_time": "14:30",
    "lookback_days": 10,
}


def load_config(config_path: str = "config.json") -> dict:
    if os.path.exists(config_path):
        with open(config_path) as f:
            user_config = json.load(f)
            merged = {**DEFAULT_CONFIG, **user_config}
            logger.info(f"Config loaded from {config_path}")
            return merged
    logger.info("No config.json found, using defaults")
    return DEFAULT_CONFIG


def run_backtest(config: dict, symbols: list[str], output_dir: str = "output"):
    """Run backtesting on synthetic/historical data."""
    from backtesting_engine import BacktestEngine

    logger.info(f"Starting backtest on {len(symbols)} symbols")
    engine = BacktestEngine(config)
    results_df = engine.run(symbols)

    if results_df.empty:
        print("No trades generated. Try lowering surge_threshold in config.json")
        return

    metrics = engine.compute_metrics(results_df)
    engine.save_results(results_df, metrics, output_dir)

    print("\n📈 TOP 5 TRADES BY PnL:")
    top5 = results_df.nlargest(5, "pnl")[["date", "symbol", "entry_price", "exit_price", "pnl", "exit_reason"]]
    print(top5.to_string(index=False))


def run_paper(config: dict, symbols: list[str], duration_minutes: int = 10):
    """Run paper trading simulation."""
    from live_trading import LiveTradingEngine

    print(f"\n🧪 PAPER TRADING MODE — Simulating {duration_minutes} minutes")
    print("   (No real money involved)\n")

    engine = LiveTradingEngine(config=config, symbols=symbols, mode="paper")
    engine.run(tick_interval=5, max_runtime_seconds=duration_minutes * 60)


def run_live(config: dict, symbols: list[str],
              api_key: str, access_token: str):
    """Run live trading via Zerodha Kite."""
    if not api_key or not access_token:
        print("❌ ERROR: --api-key and --access-token required for live mode")
        sys.exit(1)

    print("\n🔴 LIVE TRADING MODE — REAL MONEY AT RISK")
    confirm = input("Type 'YES I UNDERSTAND' to continue: ")
    if confirm != "YES I UNDERSTAND":
        print("Aborted.")
        return

    from live_trading import LiveTradingEngine
    engine = LiveTradingEngine(
        config=config,
        symbols=symbols,
        mode="live",
        kite_api_key=api_key,
        kite_access_token=access_token,
    )
    engine.run(tick_interval=30)


def main():
    parser = argparse.ArgumentParser(
        description="Morning Surge Short Strategy — Indian Equities Intraday"
    )
    parser.add_argument(
        "--mode",
        choices=["backtest", "paper", "live"],
        default="paper",
        help="Execution mode (default: paper)"
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON (default: config.json)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="List of NSE symbols (default: 30 Nifty heavyweights)"
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for backtest results (default: output)"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("KITE_API_KEY"),
        help="Zerodha Kite API key (or set KITE_API_KEY env var)"
    )
    parser.add_argument(
        "--access-token",
        default=os.getenv("KITE_ACCESS_TOKEN"),
        help="Zerodha Kite access token (or set KITE_ACCESS_TOKEN env var)"
    )
    parser.add_argument(
        "--paper-duration",
        type=int,
        default=10,
        help="Paper trading duration in minutes (default: 10)"
    )

    args = parser.parse_args()

    config = load_config(args.config)
    symbols = args.symbols or DEFAULT_SYMBOLS

    print(f"""
╔══════════════════════════════════════════════════════╗
║      MORNING SURGE SHORT STRATEGY                    ║
║      Indian Equities Intraday System                 ║
╚══════════════════════════════════════════════════════╝
Mode     : {args.mode.upper()}
Symbols  : {len(symbols)} stocks
Config   : {args.config}
""")

    if args.mode == "backtest":
        run_backtest(config, symbols, args.output_dir)
    elif args.mode == "paper":
        run_paper(config, symbols, args.paper_duration)
    elif args.mode == "live":
        run_live(config, symbols, args.api_key, args.access_token)


if __name__ == "__main__":
    main()
