#!/usr/bin/env python3
"""croncheck — validate and analyze crontab expressions."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Set


VERSION = "1.0.0"

# Valid ranges for each field
FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 7),  # 0 and 7 both represent Sunday
}

FIELD_NAMES = ["minute", "hour", "day_of_month", "month", "day_of_week"]

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

DOW_NAMES = {
    0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
    4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday",
}


# ---------------------------------------------------------------------------
# Common parent parser
# ---------------------------------------------------------------------------

def common_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)"
    )
    return parent


# ---------------------------------------------------------------------------
# Cron parsing / validation
# ---------------------------------------------------------------------------

CRON_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$"
)

SPECIALS = {"@yearly", "@annually", "@monthly", "@weekly", "@daily", "@hourly", "@reboot"}

SPECIAL_TO_FIELDS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@hourly": "0 * * * *",
}


def expand_field(field: str, field_name: str) -> Optional[Set[int]]:
    """Expand a cron field into a set of valid integer values. Returns None on error."""
    low, high = FIELD_RANGES[field_name]
    values: Set[int] = set()

    # Handle step values by splitting
    step = 1
    if "/" in field:
        field, step_str = field.split("/", 1)
        try:
            step = int(step_str)
        except ValueError:
            return None
        if step < 1:
            return None

    # Handle lists
    parts = field.split(",")
    for part in parts:
        if part == "*":
            for v in range(low, high + 1):
                # For day_of_week, 7 is Sunday, same as 0
                if field_name == "day_of_week":
                    if v == 7:
                        values.add(0)
                    else:
                        values.add(v)
                else:
                    values.add(v)
        elif "-" in part:
            try:
                r_start, r_end = part.split("-", 1)
                r_start = int(r_start)
                r_end = int(r_end)
            except ValueError:
                return None
            if r_start < low or r_end > high or r_start > r_end:
                return None
            for v in range(r_start, r_end + 1):
                if field_name == "day_of_week":
                    if v == 7:
                        values.add(0)
                    else:
                        values.add(v)
                else:
                    values.add(v)
        else:
            try:
                v = int(part)
            except ValueError:
                # Some systems allow month/day names, but we stick to numeric
                return None
            if v < low or v > high:
                return None
            if field_name == "day_of_week":
                if v == 7:
                    values.add(0)
                else:
                    values.add(v)
            else:
                values.add(v)

    # Apply step
    if step > 1:
        values = {v for v in values if (v - low) % step == 0}

    return values if values else None


def parse_cron(expression: str) -> Optional[Tuple[Set[int], ...]]:
    """Parse a cron expression into expanded field sets. Returns None if invalid."""
    expr = expression.strip()

    # Handle special strings
    if expr in SPECIALS:
        if expr == "@reboot":
            # @reboot doesn't parse to fields
            return (set(), set(), set(), set(), set())
        expr = SPECIAL_TO_FIELDS[expr]

    m = CRON_RE.match(expr)
    if not m:
        return None

    fields = m.groups()
    expanded = []
    for field_str, field_name in zip(fields, FIELD_NAMES):
        vals = expand_field(field_str, field_name)
        if vals is None or len(vals) == 0:
            return None
        expanded.append(vals)

    return tuple(expanded)


def validate_expression(expression: str) -> Tuple[bool, str]:
    """Validate a cron expression. Returns (is_valid, message)."""
    if expression.strip() in SPECIALS:
        return True, f"Valid special string: {expression.strip()}"

    fields = parse_cron(expression)
    if fields is None:
        return False, f"Invalid cron expression: {expression}"

    # Check day-of-month and day-of-week constraint
    # Standard cron: if both are specified (not *), the job runs when either matches
    # That's fine.

    msg_parts = []
    for field_name, values in zip(FIELD_NAMES, fields):
        min_v = min(values) if values else "?"
        max_v = max(values) if values else "?"
        msg_parts.append(f"{field_name}=[{min_v}..{max_v}]({len(values)} values)")

    return True, " | ".join(msg_parts)


# ---------------------------------------------------------------------------
# Next run times
# ---------------------------------------------------------------------------

def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            return 29
        return 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def compute_next_runs(
    expression: str,
    count: int = 5,
    from_dt: Optional[datetime] = None,
) -> List[datetime]:
    """Compute the next N run times for a cron expression."""
    fields = parse_cron(expression)
    if fields is None:
        return []

    if from_dt is None:
        from_dt = datetime.now().replace(second=0, microsecond=0)

    # Start from the minute after the reference time
    dt = from_dt + timedelta(minutes=1)
    runs: List[datetime] = []

    mins, hrs, doms, mons, dows = fields

    max_iterations = 525600 * 5  # 5 years worth of minutes
    iterations = 0

    while len(runs) < count and iterations < max_iterations:
        iterations += 1
        if dt.month in mons and dt.hour in hrs and dt.minute in mins:
            dom_ok = dt.day in doms
            dow_ok = dt.weekday() in dows  # Python: 0=Monday, cron: 0=Sunday

            # In standard cron: if both day_of_month and day_of_week are non-*,
            # the job runs when either matches. If one is *, only the other matters.
            all_doms = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                        15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
                        27, 28, 29, 30, 31}
            all_dows = {0, 1, 2, 3, 4, 5, 6}

            dom_is_wild = doms == all_doms
            dow_is_wild = dows == all_dows

            if dom_is_wild and dow_is_wild:
                runs.append(dt)
            elif dom_is_wild:
                if dow_ok:
                    runs.append(dt)
            elif dow_is_wild:
                if dom_ok:
                    runs.append(dt)
            else:
                if dom_ok or dow_ok:
                    runs.append(dt)

        dt += timedelta(minutes=1)

    return runs


# ---------------------------------------------------------------------------
# Human-readable description
# ---------------------------------------------------------------------------

def describe_expression(expression: str) -> str:
    """Produce a human-readable description of a cron schedule."""
    fields = parse_cron(expression)
    if fields is None:
        if expression.strip() in SPECIALS:
            special_descriptions = {
                "@yearly": "At 00:00 on January 1st (once a year)",
                "@annually": "At 00:00 on January 1st (once a year)",
                "@monthly": "At 00:00 on the 1st of every month",
                "@weekly": "At 00:00 every Sunday",
                "@daily": "At 00:00 every day",
                "@hourly": "At minute 0 of every hour",
                "@reboot": "Runs at system reboot (no fixed schedule)",
            }
            return special_descriptions.get(expression.strip(), "Unknown special expression")
        return f"Invalid expression: {expression}"

    mins, hrs, doms, mons, dows = fields

    parts = []

    # Minute
    if min(mins) == 0 and max(mins) == 59:
        parts.append("every minute")
    elif len(mins) == 1:
        parts.append(f"at minute {list(mins)[0]}")
    elif len(mins) < 60:
        sorted_mins = sorted(mins)
        if sorted_mins == list(range(sorted_mins[0], sorted_mins[-1] + 1)):
            parts.append(f"every minute from {sorted_mins[0]} to {sorted_mins[-1]}")
        else:
            parts.append(f"at minutes {','.join(str(m) for m in sorted_mins[:5])}{'...' if len(sorted_mins) > 5 else ''}")

    # Hour
    if min(hrs) == 0 and max(hrs) == 23:
        parts.append("of every hour")
    elif len(hrs) == 1:
        parts.append(f"past hour {list(hrs)[0]}")
    else:
        sorted_hrs = sorted(hrs)
        parts.append(f"past hours {','.join(str(h) for h in sorted_hrs[:5])}{'...' if len(sorted_hrs) > 5 else ''}")

    # Day of month
    all_doms = set(range(1, 32))
    all_dows = set(range(7))
    if doms == all_doms and dows == all_dows:
        parts.append("every day")
    elif doms == all_doms and dows != all_dows:
        dow_str = ", ".join(DOW_NAMES[d] for d in sorted(dows))
        parts.append(f"on {dow_str}")
    elif doms != all_doms and dows == all_dows:
        sorted_doms = sorted(doms)
        if len(sorted_doms) <= 5:
            parts.append(f"on day(s) {','.join(str(d) for d in sorted_doms)}")
        else:
            parts.append(f"on days {sorted_doms[0]} through {sorted_doms[-1]}")
    else:
        sorted_doms = sorted(doms)
        dow_str = ", ".join(DOW_NAMES[d] for d in sorted(dows))
        parts.append(f"on day(s) {','.join(str(d) for d in sorted_doms[:5])} or {dow_str}")

    # Month
    if min(mons) == 1 and max(mons) == 12:
        parts.append("of every month")
    elif len(mons) == 1:
        parts.append(f"in {MONTH_NAMES[list(mons)[0]]}")
    else:
        sorted_mons = sorted(mons)
        parts.append(f"in {', '.join(MONTH_NAMES[m] for m in sorted_mons[:5])}{'...' if len(sorted_mons) > 5 else ''}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def detect_conflicts(
    expressions: List[str],
    check_window: int = 60,
) -> List[dict]:
    """Detect overlapping schedules between cron expressions.
    Checks if any two schedules would fire within `check_window` minutes of each other
    over the next 24 hours.
    """
    conflicts = []
    schedules = []

    for i, expr in enumerate(expressions):
        runs = compute_next_runs(expr, count=1440)  # 24h worth of minutes
        schedules.append(runs)

    for i in range(len(expressions)):
        for j in range(i + 1, len(expressions)):
            overlap = False
            overlap_time = None
            for t1 in schedules[i]:
                for t2 in schedules[j]:
                    diff = abs((t1 - t2).total_seconds()) / 60
                    if diff <= check_window:
                        overlap = True
                        overlap_time = min(t1, t2)
                        break
                if overlap:
                    break
            if overlap:
                conflicts.append({
                    "expr1": expressions[i],
                    "expr2": expressions[j],
                    "overlap_time": overlap_time.isoformat() if overlap_time else None,
                    "window_minutes": check_window,
                })

    return conflicts


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_validate(args: argparse.Namespace) -> None:
    valid, msg = validate_expression(args.expression)
    if args.format == "json":
        print(json.dumps({"expression": args.expression, "valid": valid, "message": msg}))
    else:
        status = "✓ Valid" if valid else "✗ Invalid"
        print(f"{status}: {msg}")


def cmd_next(args: argparse.Namespace) -> None:
    from_dt = None
    if args.from_date:
        try:
            from_dt = datetime.fromisoformat(args.from_date)
        except ValueError:
            print(f"Invalid date format: {args.from_date}. Use ISO format (YYYY-MM-DDTHH:MM:SS).", file=sys.stderr)
            sys.exit(1)

    runs = compute_next_runs(args.expression, args.count, from_dt)

    if args.format == "json":
        print(json.dumps({
            "expression": args.expression,
            "next_runs": [r.isoformat() for r in runs],
        }, indent=2))
    else:
        if not runs:
            print("No run times computed (invalid expression?).")
            return
        print(f"Next {len(runs)} run time(s) for '{args.expression}':")
        for i, dt in enumerate(runs, 1):
            friendly = dt.strftime("%A, %B %d, %Y at %H:%M")
            print(f"  {i}. {friendly}  ({dt.isoformat()})")


def cmd_describe(args: argparse.Namespace) -> None:
    desc = describe_expression(args.expression)
    if args.format == "json":
        print(json.dumps({"expression": args.expression, "description": desc}))
    else:
        print(f"Schedule: {args.expression}")
        print(f"          {desc}")


def cmd_conflicts(args: argparse.Namespace) -> None:
    expressions = args.expressions
    if len(expressions) < 2:
        print("Need at least 2 cron expressions to check for conflicts.", file=sys.stderr)
        sys.exit(1)

    conflicts = detect_conflicts(expressions)

    if args.format == "json":
        print(json.dumps({"conflicts": conflicts}, indent=2))
    else:
        if not conflicts:
            print("No overlapping schedules detected.")
        else:
            print(f"Found {len(conflicts)} potential overlap(s):")
            for i, c in enumerate(conflicts, 1):
                print(f"\n  Conflict #{i}:")
                print(f"    {c['expr1']}")
                print(f"    {c['expr2']}")
                print(f"    Within {c['window_minutes']} minutes, near {c['overlap_time']}")


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parent = common_parent()

    parser = argparse.ArgumentParser(
        prog="croncheck",
        description="Validate and analyze crontab expressions.",
    )
    parser.add_argument("--version", action="version", version=f"croncheck {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- validate ---
    p_val = sub.add_parser("validate", parents=[parent], help="Check syntax of a cron expression")
    p_val.add_argument("expression", help="Cron expression to validate")
    p_val.set_defaults(func=cmd_validate)

    # --- next ---
    p_next = sub.add_parser("next", parents=[parent], help="Show next N run times")
    p_next.add_argument("expression", help="Cron expression")
    p_next.add_argument(
        "--count", type=int, default=5, metavar="N",
        help="Number of next runs to show (default: 5)"
    )
    p_next.add_argument(
        "--from", dest="from_date", type=str, default=None, metavar="ISO_DATE",
        help="Start date in ISO format (YYYY-MM-DDTHH:MM:SS)"
    )
    p_next.set_defaults(func=cmd_next)

    # --- describe ---
    p_desc = sub.add_parser("describe", parents=[parent],
                            help="Human-readable description of schedule")
    p_desc.add_argument("expression", help="Cron expression to describe")
    p_desc.set_defaults(func=cmd_describe)

    # --- conflicts ---
    p_conf = sub.add_parser("conflicts", parents=[parent],
                            help="Detect overlapping schedules between expressions")
    p_conf.add_argument(
        "expressions", nargs="+",
        help="Two or more cron expressions to compare"
    )
    p_conf.set_defaults(func=cmd_conflicts)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
