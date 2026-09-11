#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, json, tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from lpz_risk.historical_polygon import mask_grid_centres
from lpz_risk.historical_spatial import build_primary_subdivision_geojson
from phase2l_imerg_rolling_3h_pilot import _download_slots, _extract_start_from_filename, _get, _login, _read_imerg_halfhour

SAMPLE_START = datetime(2023, 7, 10, 0, 0, tzinfo=timezone.utc)


def _geometry_points(g):
    kind = g.get('type')
    if kind == 'Polygon':
        for ring in g.get('coordinates') or []:
            for p in ring:
                yield float(p[0]), float(p[1])
    elif kind == 'MultiPolygon':
        for poly in g.get('coordinates') or []:
            for ring in poly:
                for p in ring:
                    yield float(p[0]), float(p[1])
    elif kind == 'GeometryCollection':
        for part in g.get('geometries') or []:
            yield from _geometry_points(part)
    else:
        raise ValueError(f'unsupported geometry type {kind!r}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--reservoir', required=True)
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--gis-config', default='config/jma_primary_subdivision_gis.json')
    a = ap.parse_args()

    codes = set()
    with Path(a.reservoir).open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            codes.add(r['primary_subdivision_code'])
    if len(codes) != 45:
        raise ValueError(f'expected 45 Development primary-subdivision codes, got {len(codes)}')

    gis = json.loads(Path(a.gis_config).read_text(encoding='utf-8'))
    out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
    _login()

    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        jzip = td / 'jma.zip'; _get(gis['zip_url'], jzip)
        geo = build_primary_subdivision_geojson(jzip.read_bytes(), codes)
        if not geo.get('geometry_complete_for_required_codes'):
            raise RuntimeError(f"missing JMA geometries: {geo.get('missing_required_codes')}")
        feats = {str(f['properties']['primary_subdivision_code']): f['geometry'] for f in geo['features']}

        files = _download_slots(SAMPLE_START, SAMPLE_START.replace(minute=29, second=59), td / 'imerg')
        slot = None
        for fp in files:
            try:
                if _extract_start_from_filename(fp) == SAMPLE_START:
                    slot = fp; break
            except ValueError:
                continue
        if slot is None:
            raise RuntimeError('sample IMERG half-hour slot not found')
        lat, lon, _ = _read_imerg_halfhour(slot)

        rows = []
        for code in sorted(codes):
            geom = feats[code]
            pts = list(_geometry_points(geom))
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
            # Restrict point-in-polygon work to the geometry bounding box plus one
            # native-grid cell. This preserves exact cell-centre semantics while
            # avoiding ~45 full-Japan ray-casting passes.
            ix = np.where((lon >= x0 - 0.11) & (lon <= x1 + 0.11))[0]
            iy = np.where((lat >= y0 - 0.11) & (lat <= y1 + 0.11))[0]
            if ix.size == 0 or iy.size == 0:
                count = 0
            else:
                lon2, lat2 = np.meshgrid(lon[ix], lat[iy])
                mask = mask_grid_centres(lat2, lon2, geom)
                count = int(mask.sum())
            rows.append({'primary_subdivision_code': code, 'imerg_polygon_grid_cell_count': count})

    counts = [r['imerg_polygon_grid_cell_count'] for r in rows]
    report = {
        'schema_version':'1.0.1',
        'phase':'2L-C-imerg-official-polygon-coverage-proof',
        'split':'DEVELOPMENT',
        'source_id':'NASA_IMERG_FINAL_V07_HALFHOUR',
        'sample_slot_utc':SAMPLE_START.isoformat(),
        'primary_subdivision_count':len(rows),
        'minimum_grid_cell_count':min(counts),
        'median_grid_cell_count':float(np.median(counts)),
        'maximum_grid_cell_count':max(counts),
        'zero_cell_region_count':sum(x==0 for x in counts),
        'lt4_cell_region_count':sum(x<4 for x in counts),
        'lt8_cell_region_count':sum(x<8 for x in counts),
        'lt16_cell_region_count':sum(x<16 for x in counts),
        'mask_semantics':'GRID_CELL_CENTRE_INSIDE_OFFICIAL_JMA_PRIMARY_SUBDIVISION_POLYGON',
        'bbox_prefilter_only_for_computation':True,
        'threshold_selected':False,
        'candidate_membership_changed':False,
        'environment_variables_used':False,
        'hard_negative_label':None,
        'validation_data_used':False,
        'retrospective_2026_used':False,
        'prospective_holdout_used':False,
        'risk_engine_allowed':False,
        'gate':'PASS_IMERG_OFFICIAL_POLYGON_NONZERO_COVERAGE' if min(counts) > 0 else 'FAIL_IMERG_ZERO_CELL_REGION'
    }
    with (out/'phase2l_imerg_polygon_coverage.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (out/'phase2l_imerg_polygon_coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False)); return 0

if __name__=='__main__': raise SystemExit(main())
