#!/usr/bin/env python3
"""Explicit scientific feature-type audit for gap-estimation research.

Offline only. Does not modify observations and is not connected to O8.1/O9,
Primary, or Risk Engine. Replaces the coarse ANGLE_CIRCULAR/CONTINUOUS typing
used by earlier Stage-A exploratory scripts with semantically safer classes.
"""
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path

TYPES=(
 'DIRECTION_CIRCULAR','BOUNDED_ANGLE','EXTENSIVE_COUNT','EVENT_COUNT',
 'VECTOR_COMPONENT','COORDINATE','NONNEGATIVE_CONTINUOUS','GENERIC_CONTINUOUS'
)

def classify(path:str)->tuple[str,str]:
 p=path.lower()
 # Geographic coordinates.
 if '.centroid.lat' in p or '.centroid.lon' in p:
  return 'COORDINATE','centroid latitude/longitude'
 # True directional variables: wrap at 360 degrees.
 if any(x in p for x in ('rain_axis_deg','wind_axis_deg','wind_from_deg','meteorological_from_deg')):
  return 'DIRECTION_CIRCULAR','physical direction with 0/360 wrap'
 # Angular magnitudes/separations: do NOT wrap as directions.
 if any(x in p for x in ('acute_mismatch_deg','distance_deg','from_angle_deg','mismatch_deg')):
  return 'BOUNDED_ANGLE','angular magnitude/separation, scalar not circular direction'
 # Signed wind-vector components.
 if p.endswith('.u_mps') or p.endswith('.v_mps') or '.u_mps' in p or '.v_mps' in p:
  return 'VECTOR_COMPONENT','signed vector component'
 # Large pixel/tile populations: count-like but exact integer agreement is not useful.
 if 'precipitation_pixels' in p or 'tiles_with_precipitation' in p:
  return 'EXTENSIVE_COUNT','large spatial population/count; evaluate magnitude error'
 # Discrete event/object/descriptor/lineage counts.
 if any(x in p for x in ('event_count','descriptor_count','lineage_count','object_count','component_count','genesis_count')):
  return 'EVENT_COUNT','discrete event/object count'
 # Explicit nonnegative physical magnitudes.
 if any(x in p for x in ('area_km2','aspect_ratio','speed_mps','distance_km','duration_minutes','along_motion_km','along_inflow_km')):
  return 'NONNEGATIVE_CONTINUOUS','nonnegative physical magnitude'
 # Remaining degree-valued quantities are safer as bounded scalar until proven directional.
 if '_deg' in p or 'angle' in p:
  return 'BOUNDED_ANGLE','degree-valued scalar; not explicitly identified as direction'
 return 'GENERIC_CONTINUOUS','fallback dynamic scientific numeric feature'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--role-audit',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
 src=json.loads(a.role_audit.read_text(encoding='utf-8'))
 rows=[]
 for x in src.get('selected',[]):
  t,reason=classify(x['feature_path']);y=dict(x);y['legacy_feature_type']=x.get('feature_type');y['feature_type_v02']=t;y['type_reason']=reason;rows.append(y)
 report={'schema_version':'0.2.0-gap-feature-type-audit','role':'OFFLINE_EXPLICIT_SCIENTIFIC_TYPE_AUDIT','selected_count':len(rows),'type_counts':dict(Counter(x['feature_type_v02'] for x in rows)),'selected':rows,'risk_engine_allowed':False,'scientific_observation_values_modified':False,'notes':['DIRECTION_CIRCULAR is reserved for true 0/360 directions.','BOUNDED_ANGLE uses ordinary scalar error/interpolation.','EXTENSIVE_COUNT is not scored by exact integer agreement.','EVENT_COUNT retains exact/within-one count metrics.','VECTOR_COMPONENT should later be evaluated jointly as u/v vector pairs.']}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'selected_count':len(rows),'type_counts':report['type_counts'],'changed_from_legacy':sum(x.get('legacy_feature_type')!=x['feature_type_v02'] for x in rows)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
