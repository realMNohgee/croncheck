#!/usr/bin/env python3
"""Tests for croncheck."""

import argparse
import json
import sys
import unittest
from datetime import datetime
from croncheck import (
    expand_field,
    parse_cron,
    validate_expression,
    compute_next_runs,
    describe_expression,
    detect_conflicts,
    common_parent,
    build_parser,
)


class TestExpandField(unittest.TestCase):
    def test_star(self):
        result = expand_field("*", "minute")
        self.assertEqual(result, set(range(0, 60)))

    def test_single_value(self):
        result = expand_field("5", "minute")
        self.assertEqual(result, {5})

    def test_range(self):
        result = expand_field("1-5", "hour")
        self.assertEqual(result, {1, 2, 3, 4, 5})

    def test_list(self):
        result = expand_field("1,3,5", "month")
        self.assertEqual(result, {1, 3, 5})

    def test_step(self):
        result = expand_field("*/15", "minute")
        self.assertEqual(result, {0, 15, 30, 45})

    def test_complex_step(self):
        result = expand_field("1-10/3", "day_of_month")
        self.assertEqual(result, {1, 4, 7, 10})

    def test_invalid_value(self):
        result = expand_field("99", "hour")
        self.assertIsNone(result)

    def test_invalid_range(self):
        result = expand_field("10-5", "minute")
        self.assertIsNone(result)

    def test_day_of_week_7_maps_to_0(self):
        result = expand_field("7", "day_of_week")
        self.assertEqual(result, {0})

    def test_day_of_week_star(self):
        result = expand_field("*", "day_of_week")
        self.assertEqual(result, set(range(0, 7)))


class TestParseCron(unittest.TestCase):
    def test_valid_expression(self):
        result = parse_cron("0 0 * * *")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 5)

    def test_every_minute(self):
        result = parse_cron("* * * * *")
        self.assertIsNotNone(result)

    def test_specific_schedule(self):
        result = parse_cron("30 9 1 1 0")
        self.assertIsNotNone(result)

    def test_invalid_expression(self):
        result = parse_cron("invalid cron expression here")
        self.assertIsNone(result)

    def test_fewer_fields(self):
        result = parse_cron("* * *")
        self.assertIsNone(result)

    def test_special_daily(self):
        result = parse_cron("@daily")
        self.assertIsNotNone(result)

    def test_special_hourly(self):
        result = parse_cron("@hourly")
        self.assertIsNotNone(result)


class TestValidateExpression(unittest.TestCase):
    def test_valid(self):
        valid, msg = validate_expression("0 0 * * *")
        self.assertTrue(valid)
        self.assertIn("minute", msg)

    def test_invalid(self):
        valid, msg = validate_expression("not a cron")
        self.assertFalse(valid)
        self.assertIn("Invalid", msg)

    def test_special_string(self):
        valid, msg = validate_expression("@daily")
        self.assertTrue(valid)


class TestComputeNextRuns(unittest.TestCase):
    def test_daily_midnight(self):
        runs = compute_next_runs("0 0 * * *", count=3)
        self.assertEqual(len(runs), 3)
        for r in runs:
            self.assertEqual(r.hour, 0)
            self.assertEqual(r.minute, 0)

    def test_every_minute(self):
        runs = compute_next_runs("* * * * *", count=5)
        self.assertEqual(len(runs), 5)
        # Should be consecutive minutes
        for i in range(len(runs) - 1):
            diff = (runs[i + 1] - runs[i]).total_seconds()
            self.assertEqual(diff, 60)

    def test_from_date(self):
        from_dt = datetime(2026, 1, 1, 0, 0)
        runs = compute_next_runs("0 12 * * *", count=2, from_dt=from_dt)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].hour, 12)
        self.assertEqual(runs[0].minute, 0)
        # Should be Jan 1, 2026 at 12:00
        self.assertEqual(runs[0].year, 2026)
        self.assertEqual(runs[0].month, 1)
        self.assertEqual(runs[0].day, 1)

    def test_count_zero(self):
        runs = compute_next_runs("0 0 * * *", count=0)
        self.assertEqual(runs, [])

    def test_invalid_expression(self):
        runs = compute_next_runs("invalid", count=5)
        self.assertEqual(runs, [])


class TestDescribeExpression(unittest.TestCase):
    def test_daily_midnight(self):
        desc = describe_expression("0 0 * * *")
        self.assertIn("every day", desc)

    def test_specific_time(self):
        desc = describe_expression("30 14 15 * *")
        self.assertIn("day(s) 15", desc)

    def test_every_minute(self):
        desc = describe_expression("* * * * *")
        self.assertIn("every minute", desc)

    def test_weekday_only(self):
        desc = describe_expression("0 9 * * 1-5")
        self.assertIn("Monday", desc)

    def test_special_daily(self):
        desc = describe_expression("@daily")
        self.assertIn("every day", desc.lower())
        self.assertIn("0", desc)

    def test_invalid(self):
        desc = describe_expression("not valid")
        self.assertIn("Invalid", desc)


class TestDetectConflicts(unittest.TestCase):
    def test_no_conflicts(self):
        conflicts = detect_conflicts(["0 0 * * *", "30 12 * * *"])
        self.assertEqual(conflicts, [])

    def test_conflicts(self):
        # Two expressions that run very close together
        conflicts = detect_conflicts(["0 12 * * *", "1 12 * * *"])
        self.assertGreaterEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["window_minutes"], 60)

    def test_identical_expressions(self):
        conflicts = detect_conflicts(["0 0 * * *", "0 0 * * *"])
        self.assertGreaterEqual(len(conflicts), 1)


class TestCommonParent(unittest.TestCase):
    def test_format_default(self):
        parent = common_parent()
        parser = argparse.ArgumentParser(parents=[parent])
        args = parser.parse_args([])
        self.assertEqual(args.format, "text")

    def test_format_json(self):
        parent = common_parent()
        parser = argparse.ArgumentParser(parents=[parent])
        args = parser.parse_args(["--format", "json"])
        self.assertEqual(args.format, "json")


class TestArgParser(unittest.TestCase):
    def test_build_parser(self):
        parser = build_parser()
        self.assertIsNotNone(parser)

    def test_validate_args(self):
        parser = build_parser()
        args = parser.parse_args(["validate", "0 0 * * *"])
        self.assertEqual(args.command, "validate")
        self.assertEqual(args.expression, "0 0 * * *")

    def test_next_args(self):
        parser = build_parser()
        args = parser.parse_args(["next", "0 0 * * *", "--count", "10"])
        self.assertEqual(args.command, "next")
        self.assertEqual(args.count, 10)

    def test_next_from_date(self):
        parser = build_parser()
        args = parser.parse_args([
            "next", "0 0 * * *",
            "--from", "2026-01-01T00:00:00"
        ])
        self.assertEqual(args.from_date, "2026-01-01T00:00:00")

    def test_describe_args(self):
        parser = build_parser()
        args = parser.parse_args(["describe", "0 0 * * *"])
        self.assertEqual(args.command, "describe")

    def test_conflicts_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "conflicts", "0 0 * * *", "0 12 * * *"
        ])
        self.assertEqual(len(args.expressions), 2)

    def test_format_flag(self):
        parser = build_parser()
        args = parser.parse_args(["validate", "0 0 * * *", "--format", "json"])
        self.assertEqual(args.format, "json")


if __name__ == "__main__":
    unittest.main()
