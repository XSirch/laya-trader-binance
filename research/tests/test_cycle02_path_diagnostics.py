from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "scripts"))

from cycle02_path_diagnostics import excursion_r  # noqa: E402


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
