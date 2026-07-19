"""
Configuration Loader for Pattern Scanner
Loads thresholds from digitized spec files
"""

import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class DigitizedConfig:
    """Configuration loaded from digitized spec files"""

    # Pivot detection
    pivot_lookback_intermediate: int = 5
    pivot_min_strength_intermediate: int = 3
    equal_level_threshold_pct: float = 0.5
    near_level_threshold_pct: float = 1.5

    # Trend detection
    prior_trend_min_period: int = 42
    prior_trend_min_change_pct: float = 15.0

    # Breakout confirmation
    close_beyond_threshold_pct: float = 1.0
    volume_threshold_multiplier: float = 1.5
    volume_ma_period: int = 20
    confirmation_window: int = 5
    max_return_days: int = 3

    # Pattern-specific
    double_top_tolerance_pct: float = 3.0
    double_top_min_depth_pct: float = 5.0
    hns_shoulder_tolerance_pct: float = 10.0
    hns_neckline_tolerance_pct: float = 5.0


class ConfigLoader:
    """Load configuration from digitized spec files"""

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            # Default to digitization directory
            config_dir = os.path.join(
                os.path.dirname(__file__),
                '..', 'extraction_phase_1', 'digitization'
            )
        self.config_dir = config_dir
        self._cache: Dict[str, Any] = {}

    def _load_json(self, filename: str) -> Dict[str, Any]:
        """Load JSON file with caching"""
        if filename in self._cache:
            return self._cache[filename]

        filepath = os.path.join(self.config_dir, filename)
        if not os.path.exists(filepath):
            print(f"Warning: Config file not found: {filepath}")
            return {}

        with open(filepath, 'r') as f:
            data = json.load(f)
            self._cache[filename] = data
            return data

    def load_pivot_rules(self) -> Dict[str, Any]:
        """Load pivot detection rules"""
        return self._load_json('pivot_detection_rules.json')

    def load_trend_rules(self) -> Dict[str, Any]:
        """Load trend detection rules"""
        return self._load_json('trend_detection_rules.json')

    def load_breakout_rules(self) -> Dict[str, Any]:
        """Load breakout confirmation rules"""
        return self._load_json('breakout_rules.json')

    def load_volume_rules(self) -> Dict[str, Any]:
        """Load volume rules"""
        return self._load_json('volume_rules.json')

    def load_pattern_spec(self, pattern_name: str) -> Dict[str, Any]:
        """Load specific pattern digitized spec"""
        # Map pattern names to filenames
        name_map = {
            'double_tops': 'double_tops_digitized.json',
            'head_and_shoulders_top': 'head_and_shoulders_top_digitized.json',
        }
        filename = name_map.get(pattern_name, f'{pattern_name}_digitized.json')
        filepath = os.path.join(self.config_dir, 'patterns_digitized', filename)
        if not os.path.exists(filepath):
            return {}
        with open(filepath, 'r') as f:
            return json.load(f)

    def get_config(self) -> DigitizedConfig:
        """Get consolidated config from all rule files"""
        config = DigitizedConfig()

        # Load pivot rules
        pivot_rules = self.load_pivot_rules()
        if pivot_rules:
            pivot_types = pivot_rules.get('pivot_types', {})
            intermediate = pivot_types.get('intermediate_pivot', {})
            config.pivot_lookback_intermediate = intermediate.get('lookback', 5)
            config.pivot_min_strength_intermediate = intermediate.get('min_strength', 3)

            price_tol = pivot_rules.get('price_tolerance', {})
            config.equal_level_threshold_pct = price_tol.get('equal_level_threshold_pct', {}).get('value', 0.5)
            config.near_level_threshold_pct = price_tol.get('near_level_threshold_pct', {}).get('value', 1.5)

        # Load trend rules
        trend_rules = self.load_trend_rules()
        if trend_rules:
            params = trend_rules.get('parameters', {})
            config.prior_trend_min_period = params.get('prior_trend_min_period', {}).get('value', 42)
            config.prior_trend_min_change_pct = params.get('prior_trend_min_change_pct', {}).get('value', 15.0)

        # Load breakout rules
        breakout_rules = self.load_breakout_rules()
        if breakout_rules:
            price_conf = breakout_rules.get('price_confirmation', {})
            config.close_beyond_threshold_pct = price_conf.get('close_beyond_threshold_pct', {}).get('value', 1.0)

            vol_conf = breakout_rules.get('volume_confirmation', {})
            config.volume_threshold_multiplier = vol_conf.get('volume_threshold_multiplier', {}).get('value', 1.5)
            config.volume_ma_period = vol_conf.get('volume_ma_period', {}).get('value', 20)

            time_conf = breakout_rules.get('time_confirmation', {})
            config.confirmation_window = time_conf.get('confirmation_window', {}).get('value', 5)
            config.max_return_days = time_conf.get('max_return_days', {}).get('value', 3)

        return config


def load_config() -> DigitizedConfig:
    """Convenience function to load config"""
    loader = ConfigLoader()
    return loader.get_config()


if __name__ == "__main__":
    # Test config loader
    config = load_config()
    print("Loaded DigitizedConfig:")
    for field_name, value in config.__dict__.items():
        print(f"  {field_name}: {value}")
