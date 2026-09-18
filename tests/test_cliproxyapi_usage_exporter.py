import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "cliproxyapi_exporter",
    Path(__file__).resolve().parents[1]
    / "apps/base/cliproxyapi/cliproxyapi.usage-exporter.py",
)
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)
METRIC = "cliproxyapi_usage_output_tokens_per_second"


class RequestSpeedTest(unittest.TestCase):
    def setUp(self):
        self.state = EXPORTER.ExporterState()

    def observe(self, **overrides):
        record = {
            "provider": "provider-a",
            "model": "model-a",
            "alias": "alias-a",
            "failed": False,
            "stream": True,
            "latency_ms": 3000,
            "ttft_ms": 1000,
            "tokens": {"output_tokens": 100},
        }
        record.update(overrides)
        self.state.observe_record(record)

    def values(self, suffix, timing):
        return [
            float(line.rsplit(" ", 1)[1])
            for line in self.state.metrics.render().splitlines()
            if line.startswith(f"{METRIC}_{suffix}{{")
            and f'timing="{timing}"' in line
        ]

    def test_timing_bases_are_separate(self):
        self.observe()
        self.assertEqual(self.values("sum", "generation"), [50])
        self.assertAlmostEqual(self.values("sum", "end_to_end")[0], 100 / 3)
        self.assertEqual(self.values("count", "generation"), [1])
        self.assertEqual(self.values("count", "end_to_end"), [1])

    def test_mean_weights_each_request_equally(self):
        self.observe()
        self.observe(latency_ms=11000, tokens={"output_tokens": 900})
        total = self.values("sum", "generation")[0]
        count = self.values("count", "generation")[0]
        self.assertEqual(count, 2)
        self.assertEqual(total / count, 70)  # mean(50, 90), not 1000 / 12

    def test_missing_or_invalid_ttft_never_falls_back_in_generation(self):
        for ttft in (None, "invalid", 0, -1, 3000, 4000):
            with self.subTest(ttft=ttft):
                self.setUp()
                self.observe(ttft_ms=ttft)
                self.assertEqual(self.values("count", "generation"), [])
                self.assertEqual(self.values("count", "end_to_end"), [1])

    def test_non_streaming_only_contributes_end_to_end(self):
        self.observe(stream=False)
        self.assertEqual(self.values("count", "generation"), [])
        self.assertEqual(self.values("count", "end_to_end"), [1])

    def test_failed_disabled_or_unmeasurable_requests_are_not_speed_samples(self):
        for overrides in (
            {"failed": True},
            {"generate": False},
            {"latency_ms": 0},
            {"latency_ms": -1000},
            {"latency_ms": "invalid"},
            {"tokens": {}},
            {"tokens": {"output_tokens": 0}},
            {"tokens": {"output_tokens": -1}},
            {"tokens": {"output_tokens": "invalid"}},
        ):
            with self.subTest(overrides=overrides):
                self.setUp()
                self.observe(**overrides)
                self.assertNotIn(METRIC, self.state.metrics.render())
                self.assertIn("cliproxyapi_usage_requests_total{", self.state.metrics.render())

    def test_provider_model_alias_samples_remain_distinct(self):
        self.observe()
        self.observe(provider="provider-b")
        self.observe(model="model-b")
        self.observe(alias="alias-b")
        self.assertEqual(self.values("count", "generation"), [1, 1, 1, 1])
        text = self.state.metrics.render()
        self.assertIn('alias="alias-b",model="model-a",provider="provider-a",timing="generation"', text)

    def test_histogram_preserves_speeds_above_largest_bucket(self):
        self.observe(latency_ms=1001, tokens={"output_tokens": 100})
        self.assertAlmostEqual(self.values("sum", "generation")[0], 100000)
        self.assertEqual(self.values("count", "generation"), [1])
        lines = self.state.metrics.render().splitlines()
        self.assertTrue(any('le="+Inf"' in line and 'timing="generation"' in line and line.endswith(" 1") for line in lines))


if __name__ == "__main__":
    unittest.main()
