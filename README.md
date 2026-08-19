# croncheck
![CI](https://github.com/realMNohgee/croncheck/actions/workflows/ci.yml/badge.svg) ![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg) ![License](https://img.shields.io/badge/license-MIT-blue.svg)

Validate and analyze crontab expressions.

## Features

- **validate** — Check syntax of a cron expression
- **next** — Show the next N run times for a schedule
- **describe** — Human-readable description of a schedule
- **conflicts** — Detect overlapping schedules between multiple expressions
- Standard 5-field cron with special strings (@daily, @hourly, etc.)
- JSON output (`--format json`)
- Custom start date for next-run calculation (`--from`)
- Zero dependencies — Python 3 stdlib only

## Installation

```bash
# Clone and run directly
git clone git@github.com:realMNohgee/croncheck.git
cd croncheck
python3 croncheck.py --help
```

Or copy `croncheck.py` anywhere on your PATH.

## Usage

### Validate
```bash
# Check if an expression is valid
python3 croncheck.py validate "0 0 * * *"
# ✓ Valid: minute=[0..0](1 values) | hour=[0..0](1 values) | ...

python3 croncheck.py validate "0 0 * * *" --format json
# {"expression": "0 0 * * *", "valid": true, "message": "..."}

python3 croncheck.py validate "invalid"
# ✗ Invalid: Invalid cron expression: invalid
```

### Next runs
```bash
# Show next 5 run times
python3 croncheck.py next "0 12 * * *"
# Next 5 run time(s) for '0 12 * * *':
#   1. Thursday, July 09, 2026 at 12:00

# Show next 10 runs from a specific date
python3 croncheck.py next "0 0 1 * *" --count 10 --from 2026-01-01T00:00:00
```

### Describe
```bash
# Human-readable schedule description
python3 croncheck.py describe "30 9 * * 1-5"
# Schedule: 30 9 * * 1-5
#           at minute 30 past hour 9 on Monday, Tuesday, Wednesday, Thursday, Friday every day of every month

python3 croncheck.py describe "@hourly"
# Schedule: @hourly
#           At minute 0 of every hour
```

### Conflicts
```bash
# Detect overlapping schedules
python3 croncheck.py conflicts "0 12 * * *" "5 12 * * *"
# Found 1 potential overlap(s):
#   Conflict #1:
#     0 12 * * *
#     5 12 * * *
#     Within 60 minutes, near ...
```

## License

MIT — see [LICENSE](LICENSE)

---

Built with ❤️ — find more tools at [hermtica.com/marketplace](https://hermtica.com/marketplace)
