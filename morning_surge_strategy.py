"""
Morning Surge Short Strategy - Core Module
Identifies Indian stocks surging in first hour and shorts them for intraday profits.
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from dataclasses import dataclass, field
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    symbol: str
    signal_type: str          # 'SHORT'
    entry_price: float
    stop_loss: float
    target_price: float
    signal_strength: float    # 0-100
    surge_pct: float
    volume_ratio: float
    timestamp: datetime
    notes: str = ""


@dataclass
class Position:
    symbol: str
    entry_price: float
    quantity: int
    stop_loss: float
    target_price: float
    entry_time: datetime
    signal_strength: float
    status: str = "OPEN"      # OPEN, CLOSED_PROFIT, CLOSED_LOSS, CLOSED_TIME
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    pnl: float = 0.0

    def calculate_pnl(self, exit_price: float) -> float:
        # Short position: profit when price falls
        return (self.entry_price - exit_price) * self.quantity


class MorningSurgeStrategy:
    """
    Detects stocks with abnormal morning surges and shorts them
    expecting mean reversion during the day.
    """

    def __init__(self, config: dict = None):
        self.config = config or self._default_config()
        self.positions: list[Position] = []
        self.closed_trades: list[Position] = []
        self.trade_log: list[dict] = []

    def _default_config(self) -> dict:
        return {
            "surge_threshold": 3.0,       # Min % surge to consider
            "volume_spike_multiplier": 1.5, # Volume vs avg multiplier
            "stop_loss_pct": 2.0,          # Stop loss %
            "target_pct": 2.0,             # Profit target %
            "max_position_size": 50000,    # Max INR per trade
            "max_positions": 5,            # Max concurrent positions
            "circuit_buffer": 2.0,         # % buffer from upper circuit
            "min_signal_strength": 50,     # Minimum signal score
            "detection_window_start": "09:15",
            "detection_window_end": "10:15",
            "entry_window_end": "10:30",
            "exit_time": "14:30",
            "lookback_days": 10,           # Days for volume average
        }

    def calculate_signal_strength(self, surge_pct: float, volume_ratio: float,
                                   reversal_probability: float) -> float:
        """Score 0-100 for signal confidence."""
        # Surge component (max 40 pts): stronger surge = higher score up to a point
        surge_score = min(40, (surge_pct - self.config["surge_threshold"]) * 10 + 20)

        # Volume component (max 30 pts): higher volume spike = more confidence
        volume_score = min(30, (volume_ratio - 1) * 15)

        # Reversal history component (max 30 pts)
        reversal_score = reversal_probability * 30

        total = max(0, surge_score + volume_score + reversal_score)
        return round(total, 2)

    def calculate_reversal_probability(self, symbol: str,
                                        historical_data: pd.DataFrame) -> float:
        """
        Estimate probability of reversal based on historical behaviour
        after similar morning surges.
        """
        if historical_data is None or historical_data.empty:
            return 0.5  # Default neutral probability

        # Filter days where stock surged in morning
        surge_threshold = self.config["surge_threshold"]
        surge_days = historical_data[
            historical_data.get('morning_surge_pct', pd.Series(dtype=float)) >= surge_threshold
        ]

        if len(surge_days) < 3:
            return 0.5

        # Count days where it reversed (closed lower than open)
        reversals = surge_days[surge_days.get('close', 0) < surge_days.get('open', 0)]
        return len(reversals) / len(surge_days)

    def is_near_circuit(self, current_price: float, circuit_limit: float) -> bool:
        """Check if stock is dangerously close to upper circuit."""
        buffer = self.config["circuit_buffer"] / 100
        return current_price >= circuit_limit * (1 - buffer)

    def generate_signal(self, symbol: str, current_price: float, open_price: float,
                         volume_today: float, avg_volume: float,
                         circuit_limit: float,
                         historical_data: pd.DataFrame = None) -> Optional[TradeSignal]:
        """
        Analyze a stock and generate SHORT signal if criteria are met.
        Returns None if no signal, or TradeSignal if entry conditions met.
        """
        # 1. Calculate surge
        surge_pct = ((current_price - open_price) / open_price) * 100
        if surge_pct < self.config["surge_threshold"]:
            logger.debug(f"{symbol}: Surge {surge_pct:.2f}% below threshold")
            return None

        # 2. Check volume spike
        volume_ratio = volume_today / avg_volume if avg_volume > 0 else 1
        if volume_ratio < self.config["volume_spike_multiplier"]:
            logger.debug(f"{symbol}: Volume ratio {volume_ratio:.2f} insufficient")
            return None

        # 3. Circuit protection
        if self.is_near_circuit(current_price, circuit_limit):
            logger.warning(f"{symbol}: Too close to circuit limit {circuit_limit}")
            return None

        # 4. Check position limits
        if len(self.positions) >= self.config["max_positions"]:
            logger.warning("Max positions reached, skipping signal")
            return None

        # 5. Calculate reversal probability from history
        rev_prob = self.calculate_reversal_probability(symbol, historical_data)

        # 6. Signal strength
        strength = self.calculate_signal_strength(surge_pct, volume_ratio, rev_prob)
        if strength < self.config["min_signal_strength"]:
            logger.debug(f"{symbol}: Signal strength {strength} below minimum")
            return None

        # 7. Calculate entry levels
        stop_loss = current_price * (1 + self.config["stop_loss_pct"] / 100)
        target = current_price * (1 - self.config["target_pct"] / 100)

        signal = TradeSignal(
            symbol=symbol,
            signal_type="SHORT",
            entry_price=current_price,
            stop_loss=stop_loss,
            target_price=target,
            signal_strength=strength,
            surge_pct=round(surge_pct, 2),
            volume_ratio=round(volume_ratio, 2),
            timestamp=datetime.now(),
            notes=f"Surge:{surge_pct:.1f}% | Vol:{volume_ratio:.1f}x | Rev%:{rev_prob:.0%}"
        )

        logger.info(f"SIGNAL: {symbol} SHORT @ {current_price} | Strength: {strength} | {signal.notes}")
        return signal

    def calculate_position_size(self, entry_price: float) -> int:
        """Calculate number of shares to short based on capital limits."""
        max_capital = self.config["max_position_size"]
        quantity = int(max_capital / entry_price)
        return max(1, quantity)

    def open_position(self, signal: TradeSignal) -> Position:
        """Open a short position from a signal."""
        quantity = self.calculate_position_size(signal.entry_price)
        position = Position(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            target_price=signal.target_price,
            entry_time=signal.timestamp,
            signal_strength=signal.signal_strength
        )
        self.positions.append(position)
        logger.info(f"OPENED SHORT: {signal.symbol} x{quantity} @ {signal.entry_price}")
        return position

    def manage_position(self, position: Position, current_price: float,
                         current_time: datetime) -> Optional[str]:
        """
        Check if position should be closed.
        Returns exit reason string, or None if position stays open.
        """
        exit_time = time(*map(int, self.config["exit_time"].split(":")))

        # Target hit
        if current_price <= position.target_price:
            return "TARGET_HIT"

        # Stop loss hit
        if current_price >= position.stop_loss:
            return "STOP_LOSS_HIT"

        # End-of-day exit
        if current_time.time() >= exit_time:
            return "TIME_EXIT"

        return None

    def close_position(self, position: Position, exit_price: float,
                        reason: str, exit_time: datetime = None) -> float:
        """Close a position and record the trade."""
        position.exit_price = exit_price
        position.exit_time = exit_time or datetime.now()
        position.pnl = position.calculate_pnl(exit_price)

        status_map = {
            "TARGET_HIT": "CLOSED_PROFIT",
            "STOP_LOSS_HIT": "CLOSED_LOSS",
            "TIME_EXIT": "CLOSED_PROFIT" if position.pnl > 0 else "CLOSED_LOSS",
            "MANUAL": "CLOSED_PROFIT" if position.pnl > 0 else "CLOSED_LOSS"
        }
        position.status = status_map.get(reason, "CLOSED_LOSS")

        self.positions.remove(position)
        self.closed_trades.append(position)

        log_entry = {
            "symbol": position.symbol,
            "entry_price": position.entry_price,
            "exit_price": position.exit_price,
            "quantity": position.quantity,
            "pnl": round(position.pnl, 2),
            "pnl_pct": round((position.entry_price - position.exit_price) / position.entry_price * 100, 2),
            "entry_time": position.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_time": position.exit_time.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_reason": reason,
            "signal_strength": position.signal_strength,
            "status": position.status,
        }
        self.trade_log.append(log_entry)

        logger.info(
            f"CLOSED {position.symbol}: {reason} | Exit:{exit_price} | "
            f"PnL: ₹{position.pnl:.2f} ({log_entry['pnl_pct']:.2f}%)"
        )
        return position.pnl

    def get_performance_summary(self) -> dict:
        """Calculate overall strategy performance metrics."""
        if not self.closed_trades:
            return {"message": "No trades closed yet"}

        total_trades = len(self.closed_trades)
        winning = [t for t in self.closed_trades if t.pnl > 0]
        losing = [t for t in self.closed_trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in self.closed_trades)
        win_rate = len(winning) / total_trades * 100

        avg_win = np.mean([t.pnl for t in winning]) if winning else 0
        avg_loss = np.mean([t.pnl for t in losing]) if losing else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # Max drawdown
        cumulative = np.cumsum([t.pnl for t in self.closed_trades])
        running_max = np.maximum.accumulate(cumulative)
        drawdown = running_max - cumulative
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0

        return {
            "total_trades": total_trades,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate_pct": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 3),
            "max_drawdown": round(max_drawdown, 2),
            "best_trade": round(max(t.pnl for t in self.closed_trades), 2),
            "worst_trade": round(min(t.pnl for t in self.closed_trades), 2),
        }
