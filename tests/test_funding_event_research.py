import unittest

from jev_trader.derivatives_data import Funding
from jev_trader.funding_event_research import funding_inventory


class FundingEventResearchTests(unittest.TestCase):
    def test_nominal_eight_hour_schedule_accepts_millisecond_jitter(self):
        rows = [Funding(hour*3_600_000+jitter, 8, .0001)
                for hour, jitter in ((0, 47), (8, 0), (16, 23), (24, 1))]
        result = funding_inventory({"BTCUSDT": rows})["BTCUSDT"]
        self.assertEqual(result["nominal_gap_hours"], [8])
        self.assertEqual(result["largest_slot_offset_ms"], 47)
        self.assertEqual(result["events"], 4)

    def test_three_payment_assumption_rejects_other_schedules_or_missing_events(self):
        for hours in ((0, 4, 8), (0, 16, 24), (1, 9, 17), (0, 8, 8)):
            rows = [Funding(hour*3_600_000, 8, .0001) for hour in hours]
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                funding_inventory({"BTCUSDT": rows})


if __name__ == "__main__":
    unittest.main()
