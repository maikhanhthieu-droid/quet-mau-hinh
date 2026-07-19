"""
OHLCV Normalizer Module
Handles data cleaning and normalization for pattern scanning
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class NormalizationConfig:
    """Configuration for OHLCV normalization"""
    remove_null_rows: bool = True
    remove_nonpositive_prices: bool = True
    fix_high_low_inversion: bool = True
    fix_open_close_out_of_range: bool = True
    volume_zero_as_missing: bool = True
    volume_ma_period: int = 20
    min_valid_rows: int = 100


class OHLCVNormalizer:
    """
    Normalizes OHLCV data for pattern scanning.

    Handles:
    - NULL values removal
    - High < Low inversion
    - Open/Close outside High/Low range
    - Volume = 0 treatment for MA calculations
    """

    def __init__(self, config: Optional[NormalizationConfig] = None):
        self.config = config or NormalizationConfig()
        self.stats = {
            'rows_input': 0,
            'rows_removed_null': 0,
            'rows_removed_nonpositive': 0,
            'rows_fixed_hl_inversion': 0,
            'rows_fixed_oc_range': 0,
            'volume_zero_count': 0
        }

    def normalize(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
        """
        Normalize OHLCV dataframe.

        Args:
            df: DataFrame with columns [symbol, time, open, high, low, close, volume]

        Returns:
            Tuple of (normalized_df, stats_dict)
        """
        self.stats = {'rows_input': len(df), 'rows_removed_null': 0,
                      'rows_removed_nonpositive': 0,
                      'rows_fixed_hl_inversion': 0, 'rows_fixed_oc_range': 0,
                      'volume_zero_count': 0}

        df = df.copy()

        # 1. Remove rows with NULL values in critical columns
        if self.config.remove_null_rows:
            critical_cols = ['open', 'high', 'low', 'close']
            null_mask = df[critical_cols].isnull().any(axis=1)
            self.stats['rows_removed_null'] = null_mask.sum()
            df = df[~null_mask].copy()

        # 2. Fix High < Low inversion
        if self.config.fix_high_low_inversion:
            inversion_mask = df['high'] < df['low']
            self.stats['rows_fixed_hl_inversion'] = inversion_mask.sum()
            if inversion_mask.any():
                # Swap high and low
                df.loc[inversion_mask, ['high', 'low']] = df.loc[inversion_mask, ['low', 'high']].values

        # 3. Fix Open/Close outside High/Low range
        if self.config.fix_open_close_out_of_range:
            # Open outside range
            open_too_high = df['open'] > df['high']
            open_too_low = df['open'] < df['low']

            # Close outside range
            close_too_high = df['close'] > df['high']
            close_too_low = df['close'] < df['low']

            fixed_count = (open_too_high | open_too_low | close_too_high | close_too_low).sum()
            self.stats['rows_fixed_oc_range'] = fixed_count

            # Clamp to range
            df.loc[open_too_high, 'open'] = df.loc[open_too_high, 'high']
            df.loc[open_too_low, 'open'] = df.loc[open_too_low, 'low']
            df.loc[close_too_high, 'close'] = df.loc[close_too_high, 'high']
            df.loc[close_too_low, 'close'] = df.loc[close_too_low, 'low']

        # 3b. Remove rows with non-positive OHLC (defensive; avoids divide-by-zero / inf downstream)
        if self.config.remove_nonpositive_prices:
            cols = ['open', 'high', 'low', 'close']
            nonpos_mask = (df[cols] <= 0).any(axis=1) | (~np.isfinite(df[cols])).any(axis=1)
            self.stats['rows_removed_nonpositive'] = int(nonpos_mask.sum())
            if nonpos_mask.any():
                df = df[~nonpos_mask].copy()

        # After row filtering, ensure chronological ordering and a contiguous positional index.
        # Many scanners persist/use pivot indices as 0..N-1 bar positions; leaving a "gapped" index
        # (e.g., after dropping rows) can break `.iloc` usage if a scanner mistakenly treats
        # label-based indices as positions.
        if "date" in df.columns:
            df = df.sort_values("date")
        df = df.reset_index(drop=True)

        # 4. Count volume zeros
        if self.config.volume_zero_as_missing:
            self.stats['volume_zero_count'] = (df['volume'] == 0).sum()

        # 5. Add derived columns
        df = self._add_derived_columns(df)

        self.stats['rows_output'] = len(df)

        return df, self.stats.copy()

    def _add_derived_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add derived columns for analysis"""

        # Typical price
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3

        # True Range
        df['true_range'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )

        # ATR (Average True Range)
        df['atr'] = df['true_range'].rolling(window=14).mean()

        # Volume MA (treating 0 as NaN for calculation)
        if self.config.volume_zero_as_missing:
            volume_for_ma = df['volume'].replace(0, np.nan)
        else:
            volume_for_ma = df['volume']

        df['volume_ma'] = volume_for_ma.rolling(window=self.config.volume_ma_period).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']

        # Returns
        df['return_pct'] = df['close'].pct_change() * 100

        # Range as % of close
        df['range_pct'] = ((df['high'] - df['low']) / df['close']) * 100

        return df

    def get_valid_stocks(self, df: pd.DataFrame, min_rows: Optional[int] = None) -> list:
        """
        Get list of stocks with sufficient data.

        Args:
            df: Full OHLCV dataframe
            min_rows: Minimum rows required (default from config)

        Returns:
            List of valid stock symbols
        """
        min_rows = min_rows or self.config.min_valid_rows

        stock_counts = df.groupby('symbol').size()
        valid_stocks = stock_counts[stock_counts >= min_rows].index.tolist()

        return valid_stocks

    @staticmethod
    def load_from_db(db_path: str, symbols: Optional[list] = None,
                     start_date: Optional[str] = None,
                     end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Load OHLCV data from SQLite database.

        Args:
            db_path: Path to SQLite database
            symbols: List of symbols to load (None = all)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with OHLCV data
        """
        import sqlite3

        query = """
            SELECT symbol, time as date, open, high, low, close, volume
            FROM stock_price_history
            WHERE 1=1
        """
        params = []

        if symbols:
            placeholders = ','.join(['?' for _ in symbols])
            query += f" AND symbol IN ({placeholders})"
            params.extend(symbols)

        if start_date:
            query += " AND time >= ?"
            params.append(start_date)

        if end_date:
            query += " AND time <= ?"
            params.append(end_date)

        query += " ORDER BY symbol, time"

        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        # Convert date
        df['date'] = pd.to_datetime(df['date'])

        return df


def normalize_stock_data(db_path: str, output_path: Optional[str] = None,
                         symbols: Optional[list] = None,
                         config: Optional[NormalizationConfig] = None) -> Tuple[pd.DataFrame, dict]:
    """
    Convenience function to load and normalize stock data.

    Args:
        db_path: Path to SQLite database
        output_path: Optional path to save normalized data
        symbols: List of symbols to process
        config: Normalization configuration

    Returns:
        Tuple of (normalized_df, stats_dict)
    """
    normalizer = OHLCVNormalizer(config)

    # Load data
    df = OHLCVNormalizer.load_from_db(db_path, symbols)

    # Normalize
    df_norm, stats = normalizer.normalize(df)

    # Save if path provided
    if output_path:
        df_norm.to_parquet(output_path, index=False)

    return df_norm, stats


if __name__ == "__main__":
    # Test with actual database
    from pathlib import Path

    db_path = str(Path(__file__).resolve().parent.parent / "vietnam_stocks.db")

    print("Loading sample data...")
    df = OHLCVNormalizer.load_from_db(db_path, symbols=['VCB', 'FPT', 'HCM'], start_date='2020-01-01')
    print(f"Loaded {len(df)} rows for {df['symbol'].nunique()} stocks")

    print("\nNormalizing...")
    normalizer = OHLCVNormalizer()
    df_norm, stats = normalizer.normalize(df)

    print("\nNormalization Stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\nSample normalized data:")
    print(df_norm.head(10))
