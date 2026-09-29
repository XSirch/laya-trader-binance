from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "scripts"))

from cycle02_path_diagnostics_corrected import (  # noqa: E402
    excursion_r, is_ambiguous_exit_bar,
)


class PathDiagnosticTests(unittest.TestCase):
    def test_long_excursions_use_stop_distance_units(self) -> None:
        mfe, mae = excursion_r([101, 104], [99, 97], 1, 100, 2)
        self.assertEqual(mfe, 2.0)
        self.assertEqual(mae, 1.5)

    def test_short_excursions_reverse_favorable_and_adverse_sides(self) -> None:
        mfe, mae = excursion_r([103, 105], [99, 96], -1, 100, 2)
        self.assertEqual(mfe, 2.0)
        self.assertEqual(mae, 2.5)

    def test_empty_path_is_not_silently_reported_as_zero(self) -> None:
        self.assertEqual(excursion_r([], [], 1, 100, 2), (None, None))

    def test_invalid_stop_distance_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            excursion_r([101], [99], 1, 100, 0)

    def test_gap_and_intrabar_exits_have_ambiguous_exit_candles(self) -> None:
        for reason in ("stop", "target", "stop_gap", "target_gap"):
            with self.subTest(reason=reason):
                self.assertTrue(is_ambiguous_exit_bar(reason))

    def test_close_based_exits_use_a_completed_candle(self) -> None:
        for reason in ("trend_ema21_loss", "time_stop"):
            with self.subTest(reason=reason):
                self.assertFalse(is_ambiguous_exit_bar(reason))
