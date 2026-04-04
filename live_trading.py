"""
Live Trading Module - Morning Surge Short Strategy
Supports paper trading (simulated) and live trading (Zerodha Kite).
"""

import time
import random
import json
import csv
import os
import threading
from datetime import datetime, date
from typing import Optional
import logging

from morning_surge_strategy import MorningSurgeStrategy, TradeSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Market Data Providers
# ---------------------------------------------------------------------------

class PaperMarketFeed:
    """
    Simulates a live market feed for paper trading.
    Generates realistic intraday price movements.
    """

    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.prices = {s: random.uniform(200, 2000) for s in symbols}
        self.open_prices = {}
        self.volumes = {s: 0 for s in symbols}
        self.avg_volumes = {s: random.randint(500_000, 3_000_000) for s in symbols}
        self.circuit_limits = {s: self.prices[s] * 1.20 for s in symbols}
        self._init_day()

    def _init_day(self):
        """Set opening prices with random gaps."""
        for s in self.symbols:
            gap = random.uniform(-0.02, 0.04)
            self.prices[s] = self.prices[s] * (1 + gap)
            self.open_prices[s] = self.prices[s]
            self.volumes[s] = 0

    def tick(self) -> dict:
        """Simulate one market tick for all symbols."""
        snapshot = {}
        for s in self.symbols:
            change = random.gauss(0, 0.003)
            self.prices[s] = max(1, self.prices[s] * (1 + change))
            self.volumes[s] += random.randint(1000, 50000)
            snapshot[s] = {
                "symbol": s,
                "price": round(self.prices[s], 2),
                "open": round(self.open_prices[s], 2),
                "volume": self.volumes[s],
                "avg_volume": self.avg_volumes[s],
                "circuit_limit": round(self.circuit_limits[s], 2),
                "surge_pct": round(
                    (self.prices[s] - self.open_prices[s]) / self.open_prices[s] * 100, 2
                ),
            }
        return snapshot


class ZerodhaKiteFeed:
    """
    Live market data via Zerodha Kite Connect API.
    Requires kiteconnect package: pip install kiteconnect
    """

    def __init__(self, api_key: str, access_token: str, symbols: list[str]):
        try:
            from kiteconnect import KiteConnect
            self.kite = KiteConnect(api_key=api_key)
            self.kite.set_access_token(access_token)
            self.symbols = symbols
            logger.info("Zerodha Kite connected")
        except ImportError:
            raise ImportError(
                "kiteconnect not installed. Run: pip install kiteconnect"
            )

    def tick(self) -> dict:
        """Fetch live quotes from Kite."""
        instruments = [f"NSE:{s}" for s in self.symbols]
        quotes = self.kite.quote(instruments)
        snapshot = {}
        for s in self.symbols:
            q = quotes.get(f"NSE:{s}", {})
            snapshot[s] = {
                "symbol": s,
                "price": q.get("last_price", 0),
                "open": q.get("ohlc", {}).get("open", 0),
                "volume": q.get("volume", 0),
                "avg_volume": q.get("average_price", 1) * q.get("volume", 1) // 100,
                "circuit_limit": q.get("upper_circuit_limit", 9999),
                "surge_pct": 0,  # calculated below
            }
            if snapshot[s]["open"] > 0:
                snapshot[s]["surge_pct"] = round(
                    (snapshot[s]["price"] - snapshot[s]["open"]) / snapshot[s]["open"] * 100, 2
                )
        return snapshot


# ---------------------------------------------------------------------------
# Order Execution
# ---------------------------------------------------------------------------

class PaperBroker:
    """Simulates order execution for paper trading."""

    def __init__(self):
        self.orders = []
        self.balance = 500_000  # ₹5 lakh paper balance

    def place_order(self, symbol: str, quantity: int,
                     order_type: str, price: float) -> str:
        order_id = f"PAPER-{len(self.orders)+1:04d}"
        slippage = price * random.uniform(-0.001, 0.001)
        executed_price = round(price + slippage, 2)
        self.orders.append({
            "order_id": order_id,
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "requested_price": price,
            "executed_price": executed_price,
            "timestamp": datetime.now().isoformat(),
        })
        logger.info(f"[PAPER] {order_type} {symbol} x{quantity} @ {executed_price} (req: {price})")
        return order_id


class ZerodhaBroker:
    """Live order execution via Zerodha Kite."""

    def __init__(self, api_key: str, access_token: str):
        try:
            from kiteconnect import KiteConnect
            self.kite = KiteConnect(api_key=api_key)
            self.kite.set_access_token(access_token)
        except ImportError:
            raise ImportError("kiteconnect not installed")

    def place_order(self, symbol: str, quantity: int,
                     order_type: str, price: float) -> str:
        transaction = "SELL" if order_type == "SHORT" else "BUY"
        order_id = self.kite.place_order(
            tradingsymbol=symbol,
            exchange="NSE",
            transaction_type=transaction,
            quantity=quantity,
            product="MIS",            # Intraday
            order_type="MARKET",
            variety="regular",
        )
        logger.info(f"[LIVE] {order_type} {symbol} x{quantity} - Order ID: {order_id}")
        return order_id


# ---------------------------------------------------------------------------
# Live Trading Engine
# ---------------------------------------------------------------------------

class LiveTradingEngine:
    """
    Orchestrates real-time signal detection, position management,
    and order execution for the Morning Surge Short Strategy.
    """

    def __init__(self, config: dict, symbols: list[str],
                  mode: str = "paper",
                  kite_api_key: str = None,
                  kite_access_token: str = None):
        self.config = config
        self.symbols = symbols
        self.mode = mode
        self.strategy = MorningSurgeStrategy(config)
        self.running = False
        self.trade_log_path = f"trade_log_{date.today().strftime('%Y%m%d')}.csv"
        self._log_initialized = False

        if mode == "paper":
            self.feed = PaperMarketFeed(symbols)
            self.broker = PaperBroker()
        elif mode == "live":
            if not kite_api_key or not kite_access_token:
                raise ValueError("Kite API credentials required for live mode")
            self.feed = ZerodhaKiteFeed(kite_api_key, kite_access_token, symbols)
            self.broker = ZerodhaBroker(kite_api_key, kite_access_token)
        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'paper' or 'live'")

        logger.info(f"LiveTradingEngine initialized in {mode.upper()} mode")

    def _init_log(self):
        if not self._log_initialized:
            with open(self.trade_log_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "symbol", "entry_price", "exit_price", "quantity",
                    "pnl", "pnl_pct", "entry_time", "exit_time",
                    "exit_reason", "signal_strength", "status"
                ])
                writer.writeheader()
            self._log_initialized = True

    def _append_trade_log(self, trade: dict):
        with open(self.trade_log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trade.keys())
            writer.writerow(trade)

    def _is_detection_window(self) -> bool:
        now = datetime.now().time()
        start = datetime.strptime(self.config.get("detection_window_start", "09:15"), "%H:%M").time()
        end = datetime.strptime(self.config.get("entry_window_end", "10:30"), "%H:%M").time()
        return start <= now <= end

    def _is_exit_time(self) -> bool:
        now = datetime.now().time()
        exit_t = datetime.strptime(self.config.get("exit_time", "14:30"), "%H:%M").time()
        return now >= exit_t

    def _is_market_hours(self) -> bool:
        now = datetime.now().time()
        return (
            datetime.strptime("09:15", "%H:%M").time()
            <= now
            <= datetime.strptime("15:30", "%H:%M").time()
        )

    def scan_and_trade(self, snapshot: dict):
        """Process one market snapshot: detect signals and manage positions."""
        # 1. Manage existing positions
        closed_this_tick = []
        for position in list(self.strategy.positions):
            ticker = snapshot.get(position.symbol)
            if not ticker:
                continue
            current_price = ticker["price"]
            reason = self.strategy.manage_position(position, current_price, datetime.now())
            if reason:
                self.broker.place_order(position.symbol, position.quantity, "BUY_COVER", current_price)
                pnl = self.strategy.close_position(position, current_price, reason)
                if self.strategy.trade_log:
                    self._append_trade_log(self.strategy.trade_log[-1])
                closed_this_tick.append(position.symbol)

                # Fun Easter egg for profitable trades
                if pnl > 0:
                    print("⚡ THAT'S A SIX! SMASHED to profit! 🏏")

        # 2. Scan for new signals (only in detection window)
        if self._is_detection_window():
            for symbol, ticker in snapshot.items():
                if symbol in [p.symbol for p in self.strategy.positions]:
                    continue  # Already in position
                signal = self.strategy.generate_signal(
                    symbol=symbol,
                    current_price=ticker["price"],
                    open_price=ticker["open"],
                    volume_today=ticker["volume"],
                    avg_volume=ticker["avg_volume"],
                    circuit_limit=ticker["circuit_limit"],
                )
                if signal:
                    self.broker.place_order(symbol, self.strategy.calculate_position_size(signal.entry_price),
                                             "SHORT", signal.entry_price)
                    self.strategy.open_position(signal)

    def run(self, tick_interval: int = 30, max_runtime_seconds: int = None):
        """
        Main event loop. Polls market data and manages trades.
        tick_interval: seconds between market checks (default 30s)
        max_runtime_seconds: stop after N seconds (useful for testing)
        """
        self._init_log()
        self.running = True
        start_time = time.time()

        logger.info(f"🚀 Starting {self.mode.upper()} trading loop")
        print(f"\n{'='*60}")
        print(f"  MORNING SURGE SHORT STRATEGY — {self.mode.upper()} MODE")
        print(f"  Monitoring: {', '.join(self.symbols)}")
        print(f"  Press Ctrl+C to stop")
        print(f"{'='*60}\n")

        try:
            while self.running:
                if not self._is_market_hours():
                    logger.info("Outside market hours. Waiting...")
                    time.sleep(60)
                    continue

                # Force exit all at end of day
                if self._is_exit_time():
                    logger.info("End-of-day: closing all positions")
                    snapshot = self.feed.tick()
                    for position in list(self.strategy.positions):
                        ticker = snapshot.get(position.symbol, {})
                        price = ticker.get("price", position.entry_price)
                        self.broker.place_order(position.symbol, position.quantity, "BUY_COVER", price)
                        self.strategy.close_position(position, price, "TIME_EXIT")
                    self.running = False
                    break

                snapshot = self.feed.tick()
                self.scan_and_trade(snapshot)

                # Print status
                open_pos = len(self.strategy.positions)
                closed_pos = len(self.strategy.closed_trades)
                total_pnl = sum(t.pnl for t in self.strategy.closed_trades)
                print(
                    f"\r[{datetime.now().strftime('%H:%M:%S')}] "
                    f"Open: {open_pos} | Closed: {closed_pos} | "
                    f"PnL: ₹{total_pnl:+.2f}   ",
                    end="", flush=True
                )

                if max_runtime_seconds and (time.time() - start_time) > max_runtime_seconds:
                    logger.info("Max runtime reached")
                    self.running = False
                    break

                time.sleep(tick_interval)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.running = False
            summary = self.strategy.get_performance_summary()
            print(f"\n\n📊 SESSION SUMMARY")
            print(json.dumps(summary, indent=2))
            logger.info(f"Trade log saved: {self.trade_log_path}")
