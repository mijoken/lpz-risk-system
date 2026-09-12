#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
K2_PATH = ROOT / 'research' / 'phase2' / 'phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json'
L_PATH = ROOT / 'local_data' / 'phase2l_l_source_health' / 'phase2l_l_source_health_report.json'
M_ROOT = ROOT / 'local_data' / 'phase2l_m_prospective_collector'
N_LOG_ROOT = ROOT / 'local_data' / 'phase2l_n_scheduler' / 'logs'

EXPECTED_K2_GATE = 'PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE'
EXPECTED_L_GATE = 'PASS_PHASE2L_L_SOURCE_HEALTH_OPERATIONAL_READINESS'
EXPECTED_M_GATE = 'PASS_PHASE2L_M_LOCAL_PROSPECTIVE_COLLECTOR_CYCLE'
TASK_NAME = 'LPZ-Prospective-Collector-15min'


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding='utf-8'))


def latest_manifest() -> tuple[Path, dict[str, Any]]:
    manifests = sorted(
        M_ROOT.glob('runs/*/*/*/LOCAL-*/phase2l_m_run_manifest.json'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        raise FileNotFoundError('No Phase 2L-M run manifest found')
    p = manifests[0]
    return p, load_json(p)


def today_daily_manifest(now: datetime):
    date_s = now.date().isoformat()
    p = M_ROOT / 'daily' / now.strftime('%Y') / now.strftime('%m') / f'{date_s}.manifest.json'
    if not p.exists():
        return None, None
    return p, load_json(p)


def scheduler_info() -> dict[str, Any]:
    ps = f'''\n$ErrorActionPreference = "Stop"\n$t = Get-ScheduledTask -TaskName "{TASK_NAME}"\n$i = Get-ScheduledTaskInfo -TaskName "{TASK_NAME}"\n[pscustomobject]@{{\n  task_name = $t.TaskName\n  state = [string]$t.State\n  last_run_time = if ($i.LastRunTime) {{ $i.LastRunTime.ToString("o") }} else {{ $null }}\n  last_task_result = [int]$i.LastTaskResult\n  next_run_time = if ($i.NextRunTime) {{ $i.NextRunTime.ToString("o") }} else {{ $null }}\n}} | ConvertTo-Json -Compress\n'''
    try:
        cp = subprocess.run(
            ['pwsh.exe', '-NoProfile', '-Command', ps],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if cp.returncode != 0:
            return {
                'task_name': TASK_NAME,
                'state': 'UNKNOWN',
                'last_task_result': None,
                'error': (cp.stderr or cp.stdout).strip(),
            }
        return json.loads(cp.stdout.strip())
    except Exception as exc:
        return {
            'task_name': TASK_NAME,
            'state': 'UNKNOWN',
            'last_task_result': None,
            'error': f'{type(exc).__name__}: {exc}',
        }


def tail_scheduler_log(lines: int = 14) -> list[str]:
    candidates = sorted(N_LOG_ROOT.glob('*.log'), reverse=True)
    if not candidates:
        return []
    try:
        return candidates[0].read_text(encoding='utf-8-sig', errors='replace').splitlines()[-lines:]
    except Exception:
        return []


def esc(x: Any) -> str:
    return html.escape('' if x is None else str(x))


def badge(label: str, state: str) -> str:
    s = state.upper()
    if s in {'PASS', 'READY', 'RUNNING'}:
        cls = 'ok'
    elif s in {'PENDING', 'EXPECTED_PENDING', 'PASS_WITH_V8_PENDING'}:
        cls = 'pending'
    elif s in {'LOCKED', 'NOT ALLOWED'}:
        cls = 'lock'
    else:
        cls = 'bad'
    return f'<span class="badge {cls}">{esc(label)}</span>'


def card(title: str, value: str, sub: str = '') -> str:
    return (
        '<section class="card">'
        f'<div class="card-title">{esc(title)}</div>'
        f'<div class="card-value">{value}</div>'
        f'<div class="card-sub">{esc(sub)}</div>'
        '</section>'
    )


def main() -> int:
    ap = argparse.ArgumentParser(description='Build Phase 2L-O local operational dashboard')
    ap.add_argument('--output-dir', type=Path, default=ROOT / 'local_data' / 'phase2l_o_dashboard')
    args = ap.parse_args()
    outdir = args.output_dir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    now = utc_now()
    k2 = load_json(K2_PATH)
    l = load_json(L_PATH)
    m_path, m = latest_manifest()
    daily_path, daily = today_daily_manifest(now)
    task = scheduler_info()
    log_tail = tail_scheduler_log()

    if k2.get('gate') != EXPECTED_K2_GATE:
        raise RuntimeError(f"K2 gate mismatch: {k2.get('gate')}")
    if l.get('gate') != EXPECTED_L_GATE:
        raise RuntimeError(f"L gate mismatch: {l.get('gate')}")
    if m.get('gate') != EXPECTED_M_GATE:
        raise RuntimeError(f"Latest M gate mismatch: {m.get('gate')}")

    summary = l.get('summary', {})
    source_rows = l.get('live_source_health', [])
    earth = l.get('earthdata_imerg_research_source', {})

    bundle_count = int((daily or {}).get('bundle_count', 0))
    full_day_cov = float((daily or {}).get('coverage_fraction', 0.0))
    minutes = now.hour * 60 + now.minute
    expected_so_far = min(96, max(1, minutes // 15 + 1))
    expected_cov = min(1.0, bundle_count / expected_so_far)

    last_m = m.get('completed_at_utc') or m.get('started_at_utc')
    m_age_min = None
    if last_m:
        try:
            dt = datetime.fromisoformat(str(last_m).replace('Z', '+00:00')).astimezone(timezone.utc)
            m_age_min = max(0.0, (now - dt).total_seconds() / 60.0)
        except Exception:
            pass

    task_result = task.get('last_task_result')
    scheduler_ok = task_result == 0 and str(task.get('state', '')).upper() in {'READY', 'RUNNING'}

    snapshot = {
        'schema_version': '1.0.0',
        'phase': '2L-O-operational-dashboard',
        'generated_at_utc': iso(now),
        'k2_gate': k2.get('gate'),
        'validation_status': k2.get('validation_state', {}).get('status'),
        'source_health_gate': l.get('gate'),
        'operational_source_ready': summary.get('operational_source_ready'),
        'live_sources': source_rows,
        'earthdata_imerg': earth,
        'latest_collector_manifest': str(m_path),
        'latest_collector_gate': m.get('gate'),
        'latest_collector_completed_at_utc': last_m,
        'latest_collector_age_minutes': m_age_min,
        'daily_manifest': str(daily_path) if daily_path else None,
        'daily_bundle_count': bundle_count,
        'daily_full_day_coverage_fraction': full_day_cov,
        'daily_expected_so_far_slots': expected_so_far,
        'daily_expected_so_far_coverage_fraction': expected_cov,
        'scheduler': task,
        'scheduler_ok': scheduler_ok,
        'risk_engine_allowed': False,
        'lpz_classification_available': False,
        'primary_confirmatory_test_run': False,
    }
    snapshot_path = outdir / 'dashboard_snapshot.json'
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    source_rows_html = []
    for row in source_rows:
        health = str(row.get('health', 'UNKNOWN'))
        age = row.get('data_age_seconds')
        age_text = 'n/a' if age is None else f'{int(age)//60} min'
        source_rows_html.append(
            '<tr>'
            f'<td>{esc(row.get("source_id"))}</td>'
            f'<td>{esc(row.get("role"))}</td>'
            f'<td>{badge(health, health)}</td>'
            f'<td>{esc(row.get("probe_status"))}</td>'
            f'<td>{esc(age_text)}</td>'
            '</tr>'
        )
    source_html = ''.join(source_rows_html)

    logs_html = '\n'.join(esc(x) for x in log_tail) or '(no scheduler log yet)'
    sched_badge = badge('PASS' if scheduler_ok else str(task.get('state')), 'PASS' if scheduler_ok else str(task.get('state')))
    collector_age = 'n/a' if m_age_min is None else f'{m_age_min:.1f} min ago'

    cards = ''.join([
        card('Operational sources', badge('READY' if summary.get('operational_source_ready') else 'NOT READY', 'PASS' if summary.get('operational_source_ready') else 'FAIL'), 'Phase 2L-L'),
        card('Local scheduler', sched_badge, f"Next: {task.get('next_run_time')}"),
        card('Latest collector', badge('PASS', 'PASS'), collector_age),
        card("Today's bundles", f'{bundle_count} / 96', f'Full-day coverage {full_day_cov:.2%}'),
        card('Coverage vs elapsed day', f'{expected_cov:.1%}', f'{bundle_count} bundles / {expected_so_far} expected slots so far'),
        card('IMERG Final V08', badge(str(earth.get('imerg_final_v08_metadata', 'UNKNOWN')), str(earth.get('imerg_final_v08_metadata', 'UNKNOWN'))), 'Confirmatory validation remains deferred'),
    ])

    html_text = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LPZ Operational Dashboard</title>
<style>
:root {{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--ok:#3fb950;--pending:#d29922;--bad:#f85149;--lock:#a371f7}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:Segoe UI,Arial,sans-serif}} main{{max-width:1280px;margin:auto;padding:28px}}
h1{{margin:0 0 4px;font-size:28px}} .subtitle{{color:var(--muted);margin-bottom:24px}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.card{{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}} .card-title{{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}}
.card-value{{font-size:26px;font-weight:700;margin:8px 0}} .card-sub{{font-size:13px;color:var(--muted)}} .badge{{display:inline-block;padding:4px 9px;border-radius:999px;font-weight:700;font-size:12px}}
.ok{{background:rgba(63,185,80,.15);color:var(--ok);border:1px solid rgba(63,185,80,.45)}} .pending{{background:rgba(210,153,34,.15);color:var(--pending);border:1px solid rgba(210,153,34,.45)}}
.bad{{background:rgba(248,81,73,.15);color:var(--bad);border:1px solid rgba(248,81,73,.45)}} .lock{{background:rgba(163,113,247,.15);color:var(--lock);border:1px solid rgba(163,113,247,.45)}}
section.block{{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px;margin-top:18px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border-bottom:1px solid var(--border);text-align:left;font-size:14px}}
th{{color:var(--muted)}} pre{{white-space:pre-wrap;word-break:break-word;background:#090c10;border:1px solid var(--border);padding:14px;border-radius:8px;color:#c9d1d9}}
.progress{{height:10px;background:#21262d;border-radius:999px;overflow:hidden;margin-top:10px}} .progress>div{{height:100%;background:var(--ok);width:{expected_cov*100:.2f}%}} .warn{{border-left:4px solid var(--lock)}} .small{{color:var(--muted);font-size:12px}}
</style>
</head>
<body><main>
<h1>LPZ Operational Dashboard</h1>
<div class="subtitle">Generated {esc(iso(now))} · auto-refresh 60s · status only, no operational LPZ classification</div>
<div class="grid">{cards}</div>
<section class="block warn"><h2>Scientific lock state</h2><p>{badge('RISK ENGINE LOCKED','LOCKED')} &nbsp; {badge('2025 PRIMARY NOT RUN','LOCKED')} &nbsp; {badge('V8 PENDING','PENDING')}</p><p>The operational collector may run, but LPZ classification and risk score remain prohibited until the frozen V8 re-entry protocol is completed.</p></section>
<section class="block"><h2>Live source health</h2><table><thead><tr><th>Source</th><th>Role</th><th>Health</th><th>Probe</th><th>Age</th></tr></thead><tbody>{source_html}</tbody></table></section>
<section class="block"><h2>Scheduler</h2><table><tr><th>Task</th><td>{esc(task.get('task_name'))}</td></tr><tr><th>State</th><td>{esc(task.get('state'))}</td></tr><tr><th>Last result</th><td>{esc(task.get('last_task_result'))}</td></tr><tr><th>Last run</th><td>{esc(task.get('last_run_time'))}</td></tr><tr><th>Next run</th><td>{esc(task.get('next_run_time'))}</td></tr></table></section>
<section class="block"><h2>Today — prospective archive progress</h2><div><strong>{bundle_count} / 96 bundles</strong></div><div class="progress"><div></div></div><p class="small">Progress bar shows observed bundles versus 15-minute slots expected to have elapsed so far today (UTC).</p></section>
<section class="block"><h2>Recent scheduler log</h2><pre>{logs_html}</pre></section>
<section class="block"><h2>Current phase state</h2><table><tr><th>K2 validation</th><td>{esc(k2.get('validation_state',{}).get('status'))}</td></tr><tr><th>Primary confirmatory test</th><td>NOT RUN</td></tr><tr><th>2025 ERA5 outcome</th><td>SEALED</td></tr><tr><th>Risk engine</th><td>NOT ALLOWED</td></tr><tr><th>Operational collector</th><td>ACTIVE</td></tr></table></section>
</main></body></html>'''

    html_path = outdir / 'index.html'
    html_path.write_text(html_text, encoding='utf-8')

    print('=' * 104)
    print('LPZ PHASE 2L-O — OPERATIONAL DASHBOARD BUILD')
    print('=' * 104)
    print(f"Operational sources ready        : {summary.get('operational_source_ready')}")
    print(f"Scheduler state                  : {task.get('state')}")
    print(f"Scheduler last task result       : {task.get('last_task_result')}")
    print(f"Latest collector gate            : {m.get('gate')}")
    print(f"Latest collector age             : {collector_age}")
    print(f"Today's bundle count             : {bundle_count} / 96")
    print(f"Coverage vs elapsed UTC day      : {expected_cov:.1%}")
    print(f"IMERG Final V08                  : {earth.get('imerg_final_v08_metadata')}")
    print('2025 ERA5 environment opened     : NO')
    print('Primary confirmatory test run    : NO')
    print('Risk engine                      : NOT ALLOWED')
    print(f'Dashboard                        : {html_path}')
    print(f'Snapshot                         : {snapshot_path}')
    print('=' * 104)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
