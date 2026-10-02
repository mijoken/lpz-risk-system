from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"

CORE = {
    "collector": WF / "prospective-feature-collector.yml",
    "watchdog": WF / "prospective-collector-watchdog.yml",
    "public": WF / "public-pages-deploy.yml",
    "daily": WF / "prospective-daily-consolidation.yml",
    "retention": WF / "o8-1-jma-retention-census.yml",
    "observer": WF / "o8-1-e-consecutive-day-observer.yml",
    "cutover": WF / "o8-1-f-final-cutover-audit.yml",
}

MAX_CORE_SCHEDULED_WAKES_PER_DAY = 400
MAX_SINGLE_WORKFLOW_SCHEDULED_WAKES_PER_DAY = 150

errors: list[str] = []
notes: list[str] = []


def read(path: Path) -> str:
    if not path.exists():
        errors.append(f"missing workflow: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def field_count(field: str, lo: int, hi: int) -> int | None:
    field = field.strip()
    if field == "*":
        return hi - lo + 1
    if re.fullmatch(r"\d+(?:,\d+)*", field):
        values = {int(x) for x in field.split(",")}
        if any(x < lo or x > hi for x in values):
            return None
        return len(values)
    if re.fullmatch(r"\*/\d+", field):
        step = int(field[2:])
        if step <= 0:
            return None
        return len(range(lo, hi + 1, step))
    return None


def cron_runs_per_day(expr: str) -> int | None:
    parts = expr.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if dom != "*" or month != "*" or dow != "*":
        return None
    mc = field_count(minute, 0, 59)
    hc = field_count(hour, 0, 23)
    if mc is None or hc is None:
        return None
    return mc * hc


def scheduled_wakes(text: str, label: str) -> int:
    total = 0
    for expr in re.findall(r'cron:\s*["\']([^"\']+)["\']', text):
        n = cron_runs_per_day(expr)
        if n is None:
            notes.append(f"{label}: cron not converted to daily count: {expr}")
            continue
        total += n
    return total


collector = read(CORE["collector"])
watchdog = read(CORE["watchdog"])

if 'workflows: ["LPZ Public Production Cycle (O6)"]' not in collector:
    errors.append("collector lost its O6 workflow_run redundancy")
if 'workflows: ["LPZ Public Production Cycle (O6)"]' in watchdog:
    errors.append("watchdog must not subscribe to O6 workflow_run; this duplicates collector wake-up")

test_names = [
    "Run O8.1 collector unit tests",
    "Run F3 research adapter tests",
    "Run F4 observed-origin join tests",
    "Run F4-1 research point baseline tests",
    "Run F4-2 exact-future verification unit tests",
    "Run F4-2 cross-run exact-time matching tests",
    "Run F4-2 archived-artifact research bridge tests",
    "Run F4-3 cross-slot radar identity continuity tests",
    "Run F4-4 geographic envelope tests",
]
required_if = "if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'"
for name in test_names:
    m = re.search(
        rf"- name: {re.escape(name)}\n(?P<body>(?:\s{{8,}}.*\n){{0,4}})",
        collector,
    )
    if not m:
        errors.append(f"collector regression step missing: {name}")
        continue
    if required_if not in m.group("body"):
        errors.append(f"automatic collector wakes can still run regression step: {name}")

retention_pairs = {
    "prospective-batch-${{ github.run_id }}": 3,
    "prospective-batch-index-${{ github.run_id }}": 10,
}
for artifact_name, max_days in retention_pairs.items():
    pat = (
        rf"name:\s*{re.escape(artifact_name)}.*?"
        rf"retention-days:\s*(\d+)"
    )
    m = re.search(pat, collector, flags=re.S)
    if not m:
        errors.append(f"artifact retention policy missing for {artifact_name}")
        continue
    days = int(m.group(1))
    if days > max_days:
        errors.append(
            f"artifact retention too long for {artifact_name}: {days}d > {max_days}d"
        )

core_counts: dict[str, int] = {}
for label, path in CORE.items():
    text = read(path)
    count = scheduled_wakes(text, label)
    core_counts[label] = count
    if count > MAX_SINGLE_WORKFLOW_SCHEDULED_WAKES_PER_DAY:
        errors.append(
            f"{label} theoretical scheduled wakes/day {count} exceeds "
            f"{MAX_SINGLE_WORKFLOW_SCHEDULED_WAKES_PER_DAY}"
        )

core_total = sum(core_counts.values())
if core_total > MAX_CORE_SCHEDULED_WAKES_PER_DAY:
    errors.append(
        f"core theoretical scheduled wakes/day {core_total} exceeds "
        f"{MAX_CORE_SCHEDULED_WAKES_PER_DAY}"
    )

print("LPZ ACTIONS RESOURCE POLICY")
for label, count in core_counts.items():
    print(f"- {label}: theoretical scheduled wakes/day = {count}")
print(f"- core total: {core_total}")
print(f"- core ceiling: {MAX_CORE_SCHEDULED_WAKES_PER_DAY}")
for note in notes:
    print(f"- NOTE: {note}")

if errors:
    print("LPZ ACTIONS RESOURCE GUARD: FAIL")
    for item in errors:
        print(f"- {item}")
    sys.exit(1)

print("LPZ ACTIONS RESOURCE GUARD: PASS")
print("- O6 direct wake fan-out is bounded")
print("- automatic collector wakes skip repeated pytest")
print("- collector artifact retention is bounded")
