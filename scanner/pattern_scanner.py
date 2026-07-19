"""
Pattern Scanner
---------------
Coordinates OHLCV normalization, pivot detection, and pattern scanning.

If local digitized specs exist at `extraction_phase_1/digitization/patterns_digitized/`,
this module will load a spec-driven scanner set that covers all digitized patterns.
If specs are missing (public repo), it falls back to the legacy MVP scanners.
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any, Iterable
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import hashlib

logger = logging.getLogger(__name__)

try:
    # Package imports (preferred)
    from .legacy_guard import require_legacy_enabled
    from .pivot_detector import PivotDetector, Pivot, PivotType, PivotConfig
    from .ohlcv_normalizer import OHLCVNormalizer, NormalizationConfig
    from .digitized_pattern_engine import (
        DigitizedPatternLibrary,
        build_digitized_scanners,
        build_bulkowski_53_scanners,
        build_bulkowski_53_strict_scanners,
        build_bulkowski_strict_ohlcv_scanners,
        build_bulkowski_55_ohlcv_scanners,
        build_event_ohlcv_scanners,
    )
except ImportError:  # pragma: no cover - support running as a script from scanner/
    from legacy_guard import require_legacy_enabled
    from pivot_detector import PivotDetector, Pivot, PivotType, PivotConfig
    from ohlcv_normalizer import OHLCVNormalizer, NormalizationConfig
    from digitized_pattern_engine import (
        DigitizedPatternLibrary,
        build_digitized_scanners,
        build_bulkowski_53_scanners,
        build_bulkowski_53_strict_scanners,
        build_bulkowski_strict_ohlcv_scanners,
        build_bulkowski_55_ohlcv_scanners,
        build_event_ohlcv_scanners,
    )


@dataclass
class PatternDetection:
    """Represents a detected pattern"""
    # Identity
    pattern_id: str
    symbol: str
    pattern_name: str
    pattern_type: str

    # Timing
    formation_start: str
    formation_end: str
    breakout_date: Optional[str]

    # Detection
    breakout_direction: Optional[str]
    breakout_price: Optional[float]
    target_price: Optional[float]
    stop_loss_price: Optional[float]

    # Scoring
    confidence_score: int
    volume_confirmed: bool

    # Features
    pattern_height_pct: float
    pattern_width_bars: int
    touch_count: int
    pivot_indices: List[int]

    # Metadata
    config_hash: str
    breakout_idx: Optional[int] = None
    base_pattern_name: Optional[str] = None
    variant_code: Optional[str] = None
    variant_confidence: Optional[int] = None
    variant_evidence_json: Optional[str] = None
    first_extreme_width_bars: Optional[int] = None
    second_extreme_width_bars: Optional[int] = None
    family_metrics_json: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScannerConfig:
    """Configuration for pattern scanner"""
    # Pivot detection
    pivot_type: str = 'intermediate'
    pivot_lookback: int = 5

    # Pattern requirements
    min_prior_trend_bars: int = 42
    min_prior_trend_pct: float = 15.0
    min_pattern_bars: int = 21
    max_pattern_bars: int = 180

    # Breakout confirmation
    breakout_threshold_pct: float = 1.0
    volume_threshold: float = 1.3

    # Confidence thresholds
    min_confidence_accept: int = 60
    high_confidence_threshold: int = 80


def check_prior_trend(df: pd.DataFrame, pattern_start_idx: int,
                      direction: str, min_bars: int = 42,
                      min_change_pct: float = 15.0) -> bool:
    """
    Check if there's a valid prior trend before the pattern.

    Args:
        df: OHLCV DataFrame
        pattern_start_idx: Index where pattern starts
        direction: 'up' for bullish reversal, 'down' for bearish reversal
        min_bars: Minimum trend duration
        min_change_pct: Minimum price change percentage

    Returns:
        True if valid prior trend exists
    """
    # Need at least min_bars before pattern
    if pattern_start_idx < min_bars:
        return False

    # Get prior trend period
    start_idx = pattern_start_idx - min_bars
    end_idx = pattern_start_idx

    # Calculate price change over the period
    start_price = df.iloc[start_idx]['close']
    end_price = df.iloc[end_idx]['close']

    if start_price <= 0:
        return False

    change_pct = (end_price - start_price) / start_price * 100

    if direction == 'up':
        # For bearish reversal, need prior uptrend
        return change_pct >= min_change_pct
    else:
        # For bullish reversal, need prior downtrend
        return change_pct <= -min_change_pct


class DoubleTopScanner:
    """
    Scanner for Double Top pattern.

    Detection signature: H -> L -> H (where both H at similar level)
    """

    def __init__(self, config: Optional[ScannerConfig] = None):
        self.config = config or ScannerConfig()
        self.pivot_detector = PivotDetector()
        self.pattern_name = "double_tops"
        self.pattern_type = "reversal_bearish"

    def scan(self, symbol: str, df: pd.DataFrame,
             pivots: List[Pivot], pivots_raw: Optional[List[Pivot]] = None) -> List[PatternDetection]:
        """
        Scan for double top patterns.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            pivots: List of detected pivots

        Returns:
            List of PatternDetection objects
        """
        detections = []

        # Find H-L-H sequences
        for i in range(len(pivots) - 2):
            if (pivots[i].type == PivotType.HIGH and
                pivots[i+1].type == PivotType.LOW and
                pivots[i+2].type == PivotType.HIGH):

                p1, trough, p2 = pivots[i], pivots[i+1], pivots[i+2]

                # Check pattern criteria
                if self._validate_double_top(df, p1, trough, p2):
                    detection = self._create_detection(
                        symbol, df, p1, trough, p2
                    )
                    if detection and detection.confidence_score >= self.config.min_confidence_accept:
                        detections.append(detection)

        return detections

    def _validate_double_top(self, df: pd.DataFrame,
                             p1: Pivot, trough: Pivot, p2: Pivot) -> bool:
        """Validate double top criteria"""

        # 1. Both peaks should be at similar level (within 3%)
        if not PivotDetector.prices_are_near(p1.price, p2.price, tolerance_pct=3.0):
            return False

        # 2. Trough must be between peaks
        if trough.price >= p1.price or trough.price >= p2.price:
            return False

        # 3. Pattern width within limits
        width = (p2.idx - p1.idx) + 1
        if width < self.config.min_pattern_bars or width > self.config.max_pattern_bars:
            return False

        # 4. Minimum trough depth (5% below peaks)
        avg_peak = (p1.price + p2.price) / 2
        trough_depth = (avg_peak - trough.price) / avg_peak * 100
        if trough_depth < 5:
            return False

        # 5. Prior uptrend required (double top is bearish reversal)
        if not check_prior_trend(df, p1.idx, direction='up',
                                 min_bars=self.config.min_prior_trend_bars,
                                 min_change_pct=self.config.min_prior_trend_pct):
            return False

        return True

    def _create_detection(self, symbol: str, df: pd.DataFrame,
                          p1: Pivot, trough: Pivot, p2: Pivot) -> Optional[PatternDetection]:
        """Create PatternDetection from validated pattern"""

        # Calculate features
        avg_peak = (p1.price + p2.price) / 2
        pattern_height = (avg_peak - trough.price) / avg_peak * 100
        pattern_width = (p2.idx - p1.idx) + 1

        # Check for breakout
        breakout_idx = None
        breakout_price = None
        volume_confirmed = False

        # Look for breakout after p2
        for idx in range(p2.idx + 1, min(p2.idx + 20, len(df))):
            close = df.iloc[idx]['close']
            if close < trough.price * (1 - self.config.breakout_threshold_pct/100):
                breakout_idx = idx
                breakout_price = close
                # Check volume
                vr = df.iloc[idx].get('volume_ratio', np.nan)
                if pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.config.volume_threshold:
                    volume_confirmed = True
                break

        # Calculate confidence score
        confidence = self._calculate_confidence(df, p1, trough, p2, breakout_idx)

        # Generate pattern ID
        pattern_id = f"{symbol}_{self.pattern_name}_{p1.idx}_{p2.idx}"

        # Config hash for tracking
        config_str = json.dumps({
            'pattern': self.pattern_name,
            'version': '1.0.0',
            'breakout_threshold': self.config.breakout_threshold_pct
        }, sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

        return PatternDetection(
            pattern_id=pattern_id,
            symbol=symbol,
            pattern_name=self.pattern_name,
            pattern_type=self.pattern_type,
            formation_start=str(df.iloc[p1.idx]['date'].date()) if 'date' in df.columns else str(p1.idx),
            formation_end=str(df.iloc[p2.idx]['date'].date()) if 'date' in df.columns else str(p2.idx),
            breakout_date=str(df.iloc[breakout_idx]['date'].date()) if breakout_idx is not None and 'date' in df.columns else None,
            breakout_direction='down' if breakout_idx is not None else None,
            breakout_price=breakout_price,
            target_price=breakout_price - (avg_peak - trough.price) if breakout_price else None,
            stop_loss_price=avg_peak * 1.03 if breakout_price else None,
            confidence_score=confidence,
            volume_confirmed=volume_confirmed,
            pattern_height_pct=round(pattern_height, 2),
            pattern_width_bars=pattern_width,
            touch_count=3,
            pivot_indices=[p1.idx, trough.idx, p2.idx],
            config_hash=config_hash,
            breakout_idx=breakout_idx,
        )

    def _calculate_confidence(self, df: pd.DataFrame,
                              p1: Pivot, trough: Pivot, p2: Pivot,
                              breakout_idx: Optional[int]) -> int:
        """Calculate confidence score (0-100)"""

        score = 50  # Base score

        # Peak symmetry (+15)
        price_diff = abs(p1.price - p2.price) / min(p1.price, p2.price) * 100
        if price_diff <= 1:
            score += 15
        elif price_diff <= 2:
            score += 10
        elif price_diff <= 3:
            score += 5

        # Volume pattern (+15)
        if p1.idx < len(df) and p2.idx < len(df):
            v1 = df.iloc[p1.idx].get('volume', 0)
            v2 = df.iloc[p2.idx].get('volume', 0)
            if v1 and v2 and v2 < v1:  # Lower volume on second peak
                score += 15
            elif v1 and v2:
                score += 5

        # Breakout confirmed (+20)
        if breakout_idx is not None:
            score += 20

        return min(100, max(0, score))


class HeadAndShouldersScanner:
    """
    Scanner for Head and Shoulders Top pattern.

    Detection signature: H -> L -> H -> L -> H (center H highest)
    """

    def __init__(self, config: Optional[ScannerConfig] = None):
        self.config = config or ScannerConfig()
        self.pivot_detector = PivotDetector()
        self.pattern_name = "head_and_shoulders_top"
        self.pattern_type = "reversal_bearish"

    def scan(self, symbol: str, df: pd.DataFrame,
             pivots: List[Pivot], pivots_raw: Optional[List[Pivot]] = None) -> List[PatternDetection]:
        """Scan for head and shoulders top patterns."""
        detections = []

        # Find H-L-H-L-H sequences
        for i in range(len(pivots) - 4):
            if (pivots[i].type == PivotType.HIGH and
                pivots[i+1].type == PivotType.LOW and
                pivots[i+2].type == PivotType.HIGH and
                pivots[i+3].type == PivotType.LOW and
                pivots[i+4].type == PivotType.HIGH):

                ls, nl1, head, nl2, rs = pivots[i:i+5]

                if self._validate_hns(df, ls, nl1, head, nl2, rs):
                    detection = self._create_detection(
                        symbol, df, ls, nl1, head, nl2, rs
                    )
                    if detection and detection.confidence_score >= self.config.min_confidence_accept:
                        detections.append(detection)

        return detections

    def _validate_hns(self, df: pd.DataFrame,
                      ls: Pivot, nl1: Pivot, head: Pivot,
                      nl2: Pivot, rs: Pivot) -> bool:
        """Validate head and shoulders criteria"""

        # 1. Head must be highest
        if head.price <= ls.price or head.price <= rs.price:
            return False

        # 2. Shoulders should be similar level (within 10%)
        if not PivotDetector.prices_are_near(ls.price, rs.price, tolerance_pct=10.0):
            return False

        # 3. Pattern width within limits
        width = (rs.idx - ls.idx) + 1
        if width < 42 or width > 270:
            return False

        # 4. Neckline points should be similar (within 5%)
        if not PivotDetector.prices_are_near(nl1.price, nl2.price, tolerance_pct=5.0):
            return False

        # 5. Prior uptrend required (H&S top is bearish reversal)
        if not check_prior_trend(df, ls.idx, direction='up',
                                 min_bars=self.config.min_prior_trend_bars,
                                 min_change_pct=self.config.min_prior_trend_pct):
            return False

        return True

    def _create_detection(self, symbol: str, df: pd.DataFrame,
                          ls: Pivot, nl1: Pivot, head: Pivot,
                          nl2: Pivot, rs: Pivot) -> Optional[PatternDetection]:
        """Create PatternDetection from validated pattern"""

        # Calculate neckline
        neckline_price = (nl1.price + nl2.price) / 2
        pattern_height = (head.price - neckline_price) / head.price * 100
        pattern_width = (rs.idx - ls.idx) + 1

        # Check for breakout
        breakout_idx = None
        breakout_price = None
        volume_confirmed = False

        for idx in range(rs.idx + 1, min(rs.idx + 20, len(df))):
            close = df.iloc[idx]['close']
            if close < neckline_price * (1 - self.config.breakout_threshold_pct/100):
                breakout_idx = idx
                breakout_price = close
                vr = df.iloc[idx].get('volume_ratio', np.nan)
                if pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.config.volume_threshold:
                    volume_confirmed = True
                break

        # Calculate confidence
        confidence = self._calculate_confidence(df, ls, nl1, head, nl2, rs, breakout_idx)

        pattern_id = f"{symbol}_{self.pattern_name}_{ls.idx}_{rs.idx}"

        config_str = json.dumps({
            'pattern': self.pattern_name,
            'version': '1.0.0'
        }, sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

        return PatternDetection(
            pattern_id=pattern_id,
            symbol=symbol,
            pattern_name=self.pattern_name,
            pattern_type=self.pattern_type,
            formation_start=str(df.iloc[ls.idx]['date'].date()) if 'date' in df.columns else str(ls.idx),
            formation_end=str(df.iloc[rs.idx]['date'].date()) if 'date' in df.columns else str(rs.idx),
            breakout_date=str(df.iloc[breakout_idx]['date'].date()) if breakout_idx is not None and 'date' in df.columns else None,
            breakout_direction='down' if breakout_idx is not None else None,
            breakout_price=breakout_price,
            target_price=breakout_price - (head.price - neckline_price) if breakout_price else None,
            stop_loss_price=head.price * 1.02 if breakout_price else None,
            confidence_score=confidence,
            volume_confirmed=volume_confirmed,
            pattern_height_pct=round(pattern_height, 2),
            pattern_width_bars=pattern_width,
            touch_count=5,
            pivot_indices=[ls.idx, nl1.idx, head.idx, nl2.idx, rs.idx],
            config_hash=config_hash,
            breakout_idx=breakout_idx,
        )

    def _calculate_confidence(self, df: pd.DataFrame,
                              ls: Pivot, nl1: Pivot, head: Pivot,
                              nl2: Pivot, rs: Pivot,
                              breakout_idx: Optional[int]) -> int:
        """Calculate confidence score"""

        score = 50

        # Shoulder symmetry (+15)
        shoulder_diff = abs(ls.price - rs.price) / min(ls.price, rs.price) * 100
        if shoulder_diff <= 3:
            score += 15
        elif shoulder_diff <= 5:
            score += 10
        elif shoulder_diff <= 10:
            score += 5

        # Neckline flatness (+10)
        nl_diff = abs(nl1.price - nl2.price) / min(nl1.price, nl2.price) * 100
        if nl_diff <= 2:
            score += 10
        elif nl_diff <= 5:
            score += 5

        # Volume declining (+10)
        v_ls = df.iloc[ls.idx].get('volume', 0)
        v_head = df.iloc[head.idx].get('volume', 0)
        v_rs = df.iloc[rs.idx].get('volume', 0)
        if v_ls and v_head and v_rs and v_ls > v_head > v_rs:
            score += 10
        elif v_ls and v_rs and v_rs < v_ls:
            score += 5

        # Breakout confirmed (+15)
        if breakout_idx is not None:
            score += 15

        return min(100, max(0, score))


class PatternScanner:
    """
    Main pattern scanner that coordinates multiple pattern detectors.
    """

    def __init__(self, config: Optional[ScannerConfig] = None, *, pattern_set: str = "digitized"):
        require_legacy_enabled("scanner.pattern_scanner.PatternScanner")
        self.config = config or ScannerConfig()
        self.normalizer = OHLCVNormalizer()
        self.pivot_detector = PivotDetector()
        self.pattern_set = str(pattern_set or "digitized")

        # Initialize pattern scanners
        # Prefer digitized scanners when specs are available locally.
        self.scanners: Dict[str, Any] = {}
        try:
            lib = DigitizedPatternLibrary()
            if self.pattern_set == "bulkowski_53":
                digitized = build_bulkowski_53_scanners(lib)
            elif self.pattern_set == "bulkowski_53_strict":
                digitized = build_bulkowski_53_strict_scanners(lib)
            elif self.pattern_set in ("bulkowski_strict_ohlcv", "bulkowski_49_strict_ohlcv"):
                digitized = build_bulkowski_strict_ohlcv_scanners(lib)
            elif self.pattern_set == "bulkowski_55_ohlcv":
                digitized = build_bulkowski_55_ohlcv_scanners(lib)
            elif self.pattern_set == "event_ohlcv":
                digitized = build_event_ohlcv_scanners()
            else:
                digitized = build_digitized_scanners(lib)
            if digitized:
                self.scanners.update(digitized)
        except Exception:
            # Fallback to built-in MVP scanners
            logger.exception("Failed to load digitized scanners; falling back to MVP scanners.")
            self.scanners = {}

        if not self.scanners:
            self.scanners = {
                'double_tops': DoubleTopScanner(self.config),
                'head_and_shoulders_top': HeadAndShouldersScanner(self.config)
            }

        # Some digitized patterns are short-duration and require a tighter pivot spacing than the
        # default (min_spacing=10). If we keep spacing too large, some patterns become impossible
        # to match given width_max constraints (e.g., flags/pennants).
        self._pivot_min_spacing_overrides: Dict[str, int] = {
            "flags": 2,
            "flags_high_tight": 2,
            "pennants": 2,
            "horn_bottoms_tops": 2,
            "horn_bottoms": 2,
            "horn_tops": 2,
            "diamond_top": 3,
            "diamond_bottom": 3,
            "diamond_tops": 3,
            "diamond_bottoms": 3,
            "rounding_bottoms_tops": 4,
            "rounding_bottoms": 4,
            "rounding_tops": 4,
        }

    def _to_detection(self, d: Any) -> PatternDetection:
        if isinstance(d, PatternDetection):
            return d
        if isinstance(d, dict):
            return PatternDetection(**d)
        raise TypeError(f"Unsupported detection type: {type(d)}")

    def scan_symbol(self, symbol: str, df: pd.DataFrame,
                    patterns: Optional[List[str]] = None) -> List[PatternDetection]:
        """
        Scan a single symbol for patterns.

        Args:
            symbol: Stock symbol
            df: OHLCV DataFrame
            patterns: List of patterns to scan (None = all)

        Returns:
            List of PatternDetection objects
        """
        # Normalize data
        df_norm, _ = self.normalizer.normalize(df)

        # Detect pivots
        raw_pivots = self.pivot_detector.detect_pivots(df_norm, self.config.pivot_type)

        # Default filtered pivots with minimum spacing for most chart patterns.
        pivots_by_spacing: Dict[int, List[Pivot]] = {
            10: self.pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=10)
        }

        # Scan for each pattern
        patterns = patterns or list(self.scanners.keys())
        all_detections = []

        for pattern_name in patterns:
            if pattern_name not in self.scanners:
                continue
            scanner = self.scanners[pattern_name]
            spacing = int(self._pivot_min_spacing_overrides.get(pattern_name, 10))
            if spacing not in pivots_by_spacing:
                pivots_by_spacing[spacing] = self.pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=spacing)
            pivots = pivots_by_spacing[spacing]

            # Support both legacy scanners and digitized scanners.
            try:
                detections_any = scanner.scan(
                    symbol=symbol,
                    df=df_norm,
                    pivots_filtered=pivots,
                    pivots_raw=raw_pivots,
                )
            except TypeError:
                # Legacy signature
                detections_any = scanner.scan(symbol, df_norm, pivots, raw_pivots)

            all_detections.extend(self._to_detection(x) for x in detections_any)

        return all_detections

    def scan_database(self, db_path: str,
                      symbols: Optional[List[str]] = None,
                      patterns: Optional[List[str]] = None,
                      min_rows: int = 500,
                      persist: bool = False,
                      output_db: Optional[str] = None,
                      batch_size: int = 100) -> List[PatternDetection]:
        """
        Scan database for patterns.

        Args:
            db_path: Path to SQLite database
            symbols: List of symbols to scan (None = all valid)
            patterns: List of patterns to scan
            min_rows: Minimum rows per symbol
            persist: If True, save results to output_db
            output_db: Path to output database (default: same as db_path)
            batch_size: Commit every N symbols when persisting

        Returns:
            List of all PatternDetection objects
        """
        import sqlite3

        output_db = output_db or db_path

        # Get valid symbols if not specified
        conn = sqlite3.connect(db_path)
        if symbols is None:
            query = """
                SELECT symbol, COUNT(*) as cnt
                FROM stock_price_history
                GROUP BY symbol
                HAVING cnt >= ?
            """
            symbol_df = pd.read_sql_query(query, conn, params=[min_rows])
            symbols = symbol_df['symbol'].tolist()

        # Create output table if persisting
        if persist:
            create_output_table(output_db)

        all_detections = []
        batch_detections = []

        # Scan each symbol (reuse connection)
        for i, symbol in enumerate(symbols):
            if (i + 1) % 50 == 0:
                print(f"Scanning {i+1}/{len(symbols)}: {symbol}")

            try:
                df = pd.read_sql_query(
                    "SELECT symbol, time as date, open, high, low, close, volume "
                    "FROM stock_price_history WHERE symbol = ? ORDER BY time",
                    conn, params=[symbol]
                )

                df['date'] = pd.to_datetime(df['date'])

                if len(df) >= min_rows:
                    detections = self.scan_symbol(symbol, df, patterns)
                    all_detections.extend(detections)
                    batch_detections.extend(detections)

                    # Batch persist
                    if persist and len(batch_detections) >= batch_size:
                        self._persist_detections(batch_detections, output_db)
                        batch_detections = []

            except Exception:
                logger.exception("Error scanning symbol=%s", symbol)

        # Persist remaining
        if persist and batch_detections:
            self._persist_detections(batch_detections, output_db)

        conn.close()
        return all_detections

    def _persist_detections(self, detections: List['PatternDetection'], db_path: str):
        """Persist detections to database"""
        import sqlite3

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        for d in detections:
            cursor.execute("""
                INSERT OR REPLACE INTO pattern_detections (
                    pattern_id, symbol, pattern_name, pattern_type,
                    formation_start, formation_end, breakout_date,
                    breakout_direction, breakout_price, target_price, stop_loss_price,
                    confidence_score, volume_confirmed,
                    pattern_height_pct, pattern_width_bars, touch_count,
                    pivot_indices, config_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d.pattern_id, d.symbol, d.pattern_name, d.pattern_type,
                d.formation_start, d.formation_end, d.breakout_date,
                d.breakout_direction, d.breakout_price, d.target_price, d.stop_loss_price,
                d.confidence_score, 1 if d.volume_confirmed else 0,
                d.pattern_height_pct, d.pattern_width_bars, d.touch_count,
                json.dumps(d.pivot_indices), d.config_hash, d.created_at
            ))

        conn.commit()
        conn.close()


def create_output_table(db_path: str):
    """Create output table for pattern detections"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_detections (
            pattern_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            pattern_type TEXT,
            formation_start DATE,
            formation_end DATE,
            breakout_date DATE,
            breakout_direction TEXT,
            breakout_price REAL,
            target_price REAL,
            stop_loss_price REAL,
            confidence_score INTEGER,
            volume_confirmed BOOLEAN,
            pattern_height_pct REAL,
            pattern_width_bars INTEGER,
            touch_count INTEGER,
            pivot_indices TEXT,
            config_hash TEXT,
            created_at TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    # Test scanner
    from pathlib import Path

    db_path = str(Path(__file__).resolve().parent.parent / "vietnam_stocks.db")

    print("Testing Pattern Scanner MVP")
    print("=" * 50)

    scanner = PatternScanner()

    # Test with a few symbols
    test_symbols = ['VCB', 'FPT', 'HCM', 'MWG', 'VNM']

    print(f"\nScanning {len(test_symbols)} test symbols...")
    detections = scanner.scan_database(db_path, symbols=test_symbols)

    print(f"\nFound {len(detections)} pattern detections:")
    for d in detections[:10]:
        print(f"  {d.symbol}: {d.pattern_name} | confidence: {d.confidence_score}% | breakout: {d.breakout_date}")
