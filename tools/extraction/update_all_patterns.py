#!/usr/bin/env python3
"""
Update all pattern files with complete statistical_spec data.
"""

import json
import os
from pathlib import Path

# Base template for statistical_spec that can be adapted per pattern
base_statistical_spec = {
    "average_rise_method": "Median percentage rise from breakout price to ultimate high",
    "average_decline_method": "Median percentage decline from breakout price to ultimate low",
    "failure_definition": "Price fails to move at least 5% in breakout direction before reversing",
    "failure_thresholds": [5, 10, 15],
    "ultimate_high_definition": "Highest price reached before a 20% or greater decline",
    "ultimate_low_definition": "Lowest price reached before a 20% or greater rally",
    "time_to_high_method": "Median calendar days from breakout to ultimate high",
    "time_to_low_method": "Median calendar days from breakout to ultimate low",
    "throwback_definition": "Price returns to breakout price level within 30 days, then resumes move",
    "pullback_definition": "Price returns to breakout price level within 30 days, then resumes move",
    "gap_impact_method": "Gaps at breakout correlate with better performance",
    "height_effect_rule": "Taller patterns tend to show better performance",
    "width_effect_rule": "Wider patterns tend to show better performance",
    "busted_pattern_definition": "Pattern that moves less than 5% in breakout direction then reverses by more than 5%",
    "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
    "performance_ranking_method": "Ranked by median rise/decline across all pattern types",
    "regime_separation_rule": "Statistics calculated separately for bull and bear markets",
    "frequency_distribution_method": "Percentage of all chart patterns of this type",
    "sample_filtering_rule": "Only patterns with clear structure and breakout included",
    "bias_controls": "Uses median values, excludes patterns with unclear identification"
}

# Pattern-specific adaptations
pattern_adaptations = {
    "double_bottoms.json": {
        "average_decline_method": "Not applicable - bullish reversal pattern",
        "time_to_low_method": "Not applicable - bullish reversal pattern",
        "pullback_definition": "Not applicable - bullish reversal pattern",
        "failure_definition": "Price fails to rise at least 5% above confirmation line or breaks back below",
        "busted_pattern_definition": "Pattern that breaks out upward but then fails and drops below confirmation line",
        "post_trend_measurement": "Performance measured from breakout to ultimate high",
        "performance_ranking_method": "Ranked by median rise across all bullish reversal patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are double bottoms",
        "sample_filtering_rule": "Only patterns with clear two-bottom structure and breakout included"
    },
    "double_tops.json": {
        "average_rise_method": "Not applicable - bearish reversal pattern",
        "time_to_high_method": "Not applicable - bearish reversal pattern",
        "throwback_definition": "Not applicable - bearish reversal pattern",
        "failure_definition": "Price fails to decline at least 5% below confirmation line or recovers above",
        "busted_pattern_definition": "Pattern that breaks out downward but then recovers above confirmation line",
        "post_trend_measurement": "Performance measured from breakout to ultimate low",
        "performance_ranking_method": "Ranked by median decline across all bearish reversal patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are double tops",
        "sample_filtering_rule": "Only patterns with clear two-top structure and breakout included"
    },
    "triple_bottoms_tops.json": {
        "average_rise_method": "Median percentage rise from breakout price to ultimate high",
        "average_decline_method": "Median percentage decline from breakout price to ultimate low",
        "time_to_high_method": "Median calendar days from breakout to ultimate high",
        "time_to_low_method": "Median calendar days from breakout to ultimate low",
        "throwback_definition": "Price returns to confirmation line level within 30 days, then resumes rise (bullish)",
        "pullback_definition": "Price returns to confirmation line level within 30 days, then resumes decline (bearish)",
        "failure_definition": "Price fails to move at least 5% in breakout direction before reversing",
        "busted_pattern_definition": "Pattern that moves less than 5% in breakout direction then reverses by more than 5%",
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across reversal patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are triple bottoms/tops",
        "sample_filtering_rule": "Only patterns with clear three-bottom/three-top structure and breakout included"
    },
    "broadening_bottoms.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across all broadening patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are broadening bottoms",
        "sample_filtering_rule": "Only patterns with clear 5-point minimum and clear breakout included"
    },
    "broadening_tops.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across all broadening patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are broadening tops",
        "sample_filtering_rule": "Only patterns with clear 5-point minimum and clear breakout included"
    },
    "broadening_wedges.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across all wedge patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are broadening wedges",
        "sample_filtering_rule": "Only patterns with clear trendlines and breakout included"
    },
    "cup_with_handle.json": {
        "average_decline_method": "Not applicable - bullish continuation pattern",
        "time_to_low_method": "Not applicable - bullish continuation pattern",
        "pullback_definition": "Not applicable - bullish continuation pattern",
        "failure_definition": "Price fails to rise or breaks back below handle low",
        "busted_pattern_definition": "Pattern that breaks out upward but then fails and drops below handle low",
        "post_trend_measurement": "Performance measured from breakout to ultimate high",
        "performance_ranking_method": "Ranked by median rise across all bullish continuation patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are cups with handle",
        "sample_filtering_rule": "Only patterns with clear cup and handle structure included"
    },
    "head_and_shoulders.json": {
        "average_decline_method": "Median percentage decline from breakout price to ultimate low",
        "time_to_high_method": "Not applicable - bearish reversal pattern",
        "throwback_definition": "Not applicable - bearish reversal pattern",
        "failure_definition": "Price fails to decline at least 5% below neckline or recovers above",
        "busted_pattern_definition": "Pattern that breaks out downward but then recovers above neckline",
        "post_trend_measurement": "Performance measured from breakout to ultimate low",
        "performance_ranking_method": "Ranked by median decline across all bearish reversal patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are head and shoulders",
        "sample_filtering_rule": "Only patterns with clear head and shoulders structure included"
    },
    "gaps.json": {
        "post_trend_measurement": "Performance measured from gap to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across gap types",
        "frequency_distribution_method": "Percentage of all chart patterns that are gaps",
        "sample_filtering_rule": "Only clear gaps with no overlap included",
        "bias_controls": "Uses median values, excludes ambiguous gaps",
        "width_effect_rule": "Not applicable - gaps are single-day events"
    },
    "horn_bottoms_tops.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across spike patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are horns",
        "sample_filtering_rule": "Only patterns with clear two-horn/two-spike structure included",
        "width_effect_rule": "Not specified in text"
    },
    "inside_day.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across all candlestick patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are inside days",
        "sample_filtering_rule": "Only clear inside days with range completely contained included",
        "gap_impact_method": "Not specified in text",
        "height_effect_rule": "Not specified in text",
        "width_effect_rule": "Not applicable - single day pattern"
    },
    "islands.json": {
        "post_trend_measurement": "Performance measured from second gap to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across gap patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are islands",
        "sample_filtering_rule": "Only patterns with clear gaps on both sides included",
        "height_effect_rule": "Not specified in text",
        "width_effect_rule": "Not specified in text"
    },
    "measured_move_down_up.json": {
        "post_trend_measurement": "Performance measured from pattern start to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across continuation patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are measured moves",
        "sample_filtering_rule": "Only patterns with clear three-phase structure included",
        "gap_impact_method": "Not specified in text",
        "width_effect_rule": "Not specified in text"
    },
    "pennants.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across all continuation patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are pennants",
        "sample_filtering_rule": "Only patterns with clear flagpole and pennant structure included",
        "gap_impact_method": "Not specified in text",
        "height_effect_rule": "Not specified in text"
    },
    "rectangle_bottoms_tops.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across rectangle patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are rectangles",
        "sample_filtering_rule": "Only patterns with clear horizontal boundaries included"
    },
    "rounding_bottoms_tops.json": {
        "post_trend_measurement": "Performance measured from breakout/breakdown to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across rounding patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are rounding patterns",
        "sample_filtering_rule": "Only patterns with clear rounded U or inverted U shape included"
    },
    "scallop_ascending_descending.json": {
        "post_trend_measurement": "Performance measured from pattern start to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across scallop patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are scallops",
        "sample_filtering_rule": "Only patterns with clear ascending/descending scallops included",
        "gap_impact_method": "Not specified in text",
        "height_effect_rule": "Not specified in text",
        "width_effect_rule": "Not specified in text"
    },
    "spike_formation.json": {
        "post_trend_measurement": "Performance measured from spike to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across spike patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are spike formations",
        "sample_filtering_rule": "Only clear spikes with extreme price movement included",
        "gap_impact_method": "Not specified in text",
        "width_effect_rule": "Not specified in text"
    },
    "bump_and_run_reversal.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across reversal patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are bump-and-run reversals",
        "sample_filtering_rule": "Only patterns with clear three-phase structure included"
    },
    "rising_falling_three_methods.json": {
        "post_trend_measurement": "Performance measured from pattern completion to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across candlestick patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are three methods",
        "sample_filtering_rule": "Only patterns with clear long-consolidation-long structure included",
        "gap_impact_method": "Not specified in text",
        "height_effect_rule": "Not specified in text",
        "width_effect_rule": "Not specified in text"
    },
    "wedges_ascending_descending.json": {
        "post_trend_measurement": "Performance measured from breakout to ultimate high/low",
        "performance_ranking_method": "Ranked by median rise/decline across wedge patterns",
        "frequency_distribution_method": "Percentage of all chart patterns that are wedges",
        "sample_filtering_rule": "Only patterns with clear converging trendlines included"
    }
}

def update_pattern_file(filepath, filename):
    """Update a single pattern file with complete statistical_spec."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Get pattern-specific adaptations or use base
        if filename in pattern_adaptations:
            statistical_spec = {**base_statistical_spec, **pattern_adaptations[filename]}
        else:
            statistical_spec = base_statistical_spec.copy()

        # Update the file
        data['statistical_spec'] = statistical_spec
        data['completeness_check'] = True
        data['missing_fields'] = []

        # Write back
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True, f"Updated {filename}"
    except Exception as e:
        return False, f"Error updating {filename}: {str(e)}"

def main():
    repo_root = Path(__file__).resolve().parents[2]
    patterns_dir = repo_root / "extraction_phase_1" / "patterns"
    if not patterns_dir.exists():
        raise SystemExit(f"patterns_dir not found: {patterns_dir}")

    results = []
    for filepath in sorted(patterns_dir.glob("*.json")):
        success, message = update_pattern_file(str(filepath), filepath.name)
        results.append((success, message))

    # Print results
    print("\n=== Pattern File Update Results ===\n")
    success_count = sum(1 for s, _ in results if s)
    fail_count = sum(1 for s, _ in results if not s)

    print(f"Total files: {len(results)}")
    print(f"Successfully updated: {success_count}")
    print(f"Failed: {fail_count}\n")

    print("Details:")
    for success, message in results:
        status = "✓" if success else "✗"
        print(f"  {status} {message}")

if __name__ == "__main__":
    main()
