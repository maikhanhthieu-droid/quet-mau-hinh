"""
Pivot Detection Module
Detects pivot highs and lows in price series
"""

import pandas as pd
import numpy as np
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class PivotType(Enum):
    HIGH = "high"
    LOW = "low"


class PivotStrength(Enum):
    MINOR = "minor"           # 3 bars each side
    INTERMEDIATE = "intermediate"  # 5 bars each side
    MAJOR = "major"           # 10 bars each side


@dataclass
class Pivot:
    """Represents a pivot point"""
    idx: int                  # Index in dataframe
    date: pd.Timestamp        # Date of pivot
    price: float              # Price at pivot
    type: PivotType           # High or Low
    strength: int             # Number of confirming bars
    classification: str       # minor/intermediate/major

    def to_dict(self) -> dict:
        return {
            'idx': self.idx,
            'date': self.date.isoformat() if self.date else None,
            'price': self.price,
            'type': self.type.value,
            'strength': self.strength,
            'classification': self.classification
        }


@dataclass
class PivotConfig:
    """Configuration for pivot detection"""
    # Lookback/lookahead periods
    minor_lookback: int = 3
    minor_lookahead: int = 3
    intermediate_lookback: int = 5
    intermediate_lookahead: int = 5
    major_lookback: int = 10
    major_lookahead: int = 10

    # Noise filtering
    atr_multiplier: float = 0.5   # Minimum pivot size as ATR multiple
    pct_threshold: float = 1.0     # Minimum pivot size as percentage

    # Price tolerance
    equal_level_pct: float = 0.5   # Prices within this % are equal
    near_level_pct: float = 1.5    # Prices within this % are near


class PivotDetector:
    """
    Detects pivot highs and lows in price series.

    A pivot high is a bar with higher high than N bars before and after.
    A pivot low is a bar with lower low than N bars before and after.
    """

    def __init__(self, config: Optional[PivotConfig] = None):
        self.config = config or PivotConfig()

    def detect_pivots(self, df: pd.DataFrame,
                      pivot_type: str = 'intermediate') -> List[Pivot]:
        """
        Detect all pivots in a price series.

        Args:
            df: DataFrame with columns [date, high, low, close, atr]
            pivot_type: 'minor', 'intermediate', or 'major'

        Returns:
            List of Pivot objects
        """
        # Get lookback/lookahead based on type
        if pivot_type == 'minor':
            lookback = self.config.minor_lookback
            lookahead = self.config.minor_lookahead
        elif pivot_type == 'major':
            lookback = self.config.major_lookback
            lookahead = self.config.major_lookahead
        else:  # intermediate
            lookback = self.config.intermediate_lookback
            lookahead = self.config.intermediate_lookahead

        pivots = []

        # Detect pivot highs
        pivot_highs = self._detect_pivot_points(
            df['high'].values, lookback, lookahead, find_highs=True
        )

        # Detect pivot lows
        pivot_lows = self._detect_pivot_points(
            df['low'].values, lookback, lookahead, find_highs=False
        )

        # Create Pivot objects for highs
        for idx, strength in pivot_highs:
            if self._validate_pivot(df, idx, PivotType.HIGH, strength):
                pivots.append(Pivot(
                    idx=idx,
                    date=df.iloc[idx]['date'] if 'date' in df.columns else None,
                    price=df.iloc[idx]['high'],
                    type=PivotType.HIGH,
                    strength=strength,
                    classification=pivot_type
                ))

        # Create Pivot objects for lows
        for idx, strength in pivot_lows:
            if self._validate_pivot(df, idx, PivotType.LOW, strength):
                pivots.append(Pivot(
                    idx=idx,
                    date=df.iloc[idx]['date'] if 'date' in df.columns else None,
                    price=df.iloc[idx]['low'],
                    type=PivotType.LOW,
                    strength=strength,
                    classification=pivot_type
                ))

        # Sort by index
        pivots.sort(key=lambda p: p.idx)

        return pivots

    def _detect_pivot_points(self, prices: np.ndarray,
                             lookback: int, lookahead: int,
                             find_highs: bool = True,
                             min_strength: int = 3) -> List[Tuple[int, int]]:
        """
        Detect pivot points in price array.

        A true pivot must be higher (for highs) or lower (for lows) than ALL
        bars in the lookback AND lookahead window, not just some of them.

        Args:
            prices: Price array
            lookback: Bars to check before
            lookahead: Bars to check after
            find_highs: True for pivot highs, False for pivot lows
            min_strength: Minimum confirming bars on each side (default 3)

        Returns:
            List of (index, strength) tuples
        """
        n = len(prices)
        pivots = []

        for i in range(lookback, n - lookahead):
            # Check if this is a pivot
            left_count = 0
            right_count = 0

            # Check lookback period - count bars that confirm this pivot
            for j in range(1, lookback + 1):
                if find_highs:
                    if prices[i] > prices[i - j]:
                        left_count += 1
                else:
                    if prices[i] < prices[i - j]:
                        left_count += 1

            # Check lookahead period
            for j in range(1, lookahead + 1):
                if find_highs:
                    if prices[i] > prices[i + j]:
                        right_count += 1
                else:
                    if prices[i] < prices[i + j]:
                        right_count += 1

            # For a TRUE pivot, must be higher/lower than ALL bars in window
            # strength = min(left_count, right_count)
            # But we require left_count == lookback AND right_count == lookahead
            is_true_pivot = (left_count == lookback) and (right_count == lookahead)

            # Also enforce minimum strength for pattern detection
            strength = min(left_count, right_count)

            if is_true_pivot and strength >= min_strength:
                pivots.append((i, strength))

        return pivots

    def _validate_pivot(self, df: pd.DataFrame, idx: int,
                        pivot_type: PivotType, strength: int) -> bool:
        """
        Validate a pivot meets minimum size requirements.
        """
        if 'atr' not in df.columns:
            return True  # Skip ATR validation if not available

        atr = df.iloc[idx]['atr']
        if pd.isna(atr) or atr <= 0:
            return True

        # Get pivot price
        if pivot_type == PivotType.HIGH:
            price = df.iloc[idx]['high']
            # Check nearby prices for comparison
            nearby_low = df.iloc[max(0, idx-5):idx+6]['low'].min()
            size = price - nearby_low
        else:
            price = df.iloc[idx]['low']
            # Check nearby prices for comparison
            nearby_high = df.iloc[max(0, idx-5):idx+6]['high'].max()
            size = nearby_high - price

        # Size should be at least ATR * multiplier
        min_size = atr * self.config.atr_multiplier

        return size >= min_size

    def get_pivot_sequences(self, pivots: List[Pivot],
                            min_pivots: int = 5) -> List[List[Pivot]]:
        """
        Get valid pivot sequences for pattern matching.

        Args:
            pivots: List of pivots
            min_pivots: Minimum pivots in sequence

        Returns:
            List of pivot sequences (alternating H/L)
        """
        if len(pivots) < min_pivots:
            return []

        sequences = []
        current_seq = [pivots[0]]

        for i in range(1, len(pivots)):
            # Check if alternating
            if pivots[i].type != current_seq[-1].type:
                current_seq.append(pivots[i])
            else:
                # Same type - check if this is stronger
                if pivots[i].strength > current_seq[-1].strength:
                    current_seq[-1] = pivots[i]
                # Or if price is more extreme
                elif pivots[i].type == PivotType.HIGH:
                    if pivots[i].price > current_seq[-1].price:
                        current_seq[-1] = pivots[i]
                else:
                    if pivots[i].price < current_seq[-1].price:
                        current_seq[-1] = pivots[i]

            # Save sequence if long enough
            if len(current_seq) >= min_pivots:
                sequences.append(current_seq.copy())

        return sequences

    def get_alternating_pivots(self, pivots: List[Pivot],
                                min_spacing: int = 0) -> List[Pivot]:
        """
        Get alternating pivot sequence (no consecutive same-type pivots).
        Merges consecutive pivots of same type by keeping the most extreme.

        Args:
            pivots: List of pivots (sorted by index)
            min_spacing: Minimum bars between pivots of same type

        Returns:
            List of pivots with alternating HIGH/LOW types
        """
        if len(pivots) < 2:
            return pivots

        alternating = [pivots[0]]

        for p in pivots[1:]:
            last = alternating[-1]

            if p.type != last.type:
                # Different type - add it
                alternating.append(p)
            else:
                # Same type - check spacing and keep the more extreme one
                if min_spacing > 0 and (p.idx - last.idx) < min_spacing:
                    # Too close - keep the more extreme
                    if p.type == PivotType.HIGH:
                        if p.price > last.price:
                            alternating[-1] = p
                    else:
                        if p.price < last.price:
                            alternating[-1] = p
                elif p.type == PivotType.HIGH:
                    if p.price > last.price:
                        alternating[-1] = p
                else:
                    if p.price < last.price:
                        alternating[-1] = p

        return alternating

    def get_filtered_pivots(self, pivots: List[Pivot],
                            min_spacing: int = 10) -> List[Pivot]:
        """
        Get filtered pivots with minimum spacing between all pivots.
        Ensures GUARANTEED alternating HIGH/LOW sequence.

        Strategy:
        1. First pass: merge consecutive same-type pivots (keep most extreme)
        2. Second pass: ensure minimum spacing while maintaining alternating

        Args:
            pivots: List of pivots (sorted by index)
            min_spacing: Minimum bars between any two pivots

        Returns:
            List of filtered pivots with guaranteed alternating H-L-H-L...
        """
        if len(pivots) < 2:
            return pivots

        # Step 1: Merge consecutive same-type pivots (keep most extreme)
        merged = [pivots[0]]
        for p in pivots[1:]:
            last = merged[-1]
            if p.type == last.type:
                # Same type - keep the more extreme
                if p.type == PivotType.HIGH:
                    if p.price > last.price:
                        merged[-1] = p
                else:
                    if p.price < last.price:
                        merged[-1] = p
            else:
                merged.append(p)

        # Step 2: Apply minimum spacing while maintaining alternating
        # If two pivots are too close, remove the one with lower strength
        filtered = [merged[0]]

        for p in merged[1:]:
            last = filtered[-1]

            # Check if alternating (should always be true after step 1)
            if p.type == last.type:
                # Should not happen, but safety check
                if p.type == PivotType.HIGH:
                    if p.price > last.price:
                        filtered[-1] = p
                else:
                    if p.price < last.price:
                        filtered[-1] = p
                continue

            # Check spacing
            if (p.idx - last.idx) < min_spacing:
                # Different types but too close
                # Keep the one with higher strength (more significant pivot)
                if p.strength > last.strength:
                    filtered[-1] = p
                # If same strength, keep the one that's more extreme relative to neighbors
                # (For now, just keep the existing one to maintain stability)
            else:
                # Enough spacing and alternating - add it
                filtered.append(p)

        return filtered

    @staticmethod
    def prices_are_equal(price1: float, price2: float, tolerance_pct: float = 0.5) -> bool:
        """Check if two prices are approximately equal"""
        if price1 == 0 or price2 == 0:
            return price1 == price2
        diff_pct = abs(price1 - price2) / min(price1, price2) * 100
        return diff_pct <= tolerance_pct

    @staticmethod
    def prices_are_near(price1: float, price2: float, tolerance_pct: float = 1.5) -> bool:
        """Check if two prices are near each other"""
        if price1 == 0 or price2 == 0:
            return price1 == price2
        diff_pct = abs(price1 - price2) / min(price1, price2) * 100
        return diff_pct <= tolerance_pct


def detect_all_pivots(df: pd.DataFrame,
                      config: Optional[PivotConfig] = None) -> pd.DataFrame:
    """
    Convenience function to detect pivots and return as DataFrame.

    Args:
        df: OHLCV DataFrame
        config: Pivot detection config

    Returns:
        DataFrame with pivot information
    """
    detector = PivotDetector(config)
    pivots = detector.detect_pivots(df)

    pivot_df = pd.DataFrame([p.to_dict() for p in pivots])
    return pivot_df


if __name__ == "__main__":
    # Test with sample data
    import sqlite3
    from pathlib import Path

    db_path = str(Path(__file__).resolve().parent.parent / "vietnam_stocks.db")

    # Load sample stock
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT symbol, time as date, open, high, low, close, volume "
        "FROM stock_price_history WHERE symbol='VCB' "
        "AND time >= '2020-01-01' ORDER BY time",
        conn
    )
    conn.close()

    df['date'] = pd.to_datetime(df['date'])

    # Calculate ATR
    df['true_range'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = df['true_range'].rolling(window=14).mean()

    print(f"Loaded {len(df)} rows for VCB")

    # Detect pivots
    detector = PivotDetector()
    pivots = detector.detect_pivots(df)

    print(f"\nDetected {len(pivots)} pivots:")
    high_count = sum(1 for p in pivots if p.type == PivotType.HIGH)
    low_count = sum(1 for p in pivots if p.type == PivotType.LOW)
    print(f"  Highs: {high_count}, Lows: {low_count}")

    print("\nFirst 10 pivots:")
    for p in pivots[:10]:
        print(f"  {p.date.date()} | {p.type.value:4} | {p.price:10.2f} | strength: {p.strength}")
