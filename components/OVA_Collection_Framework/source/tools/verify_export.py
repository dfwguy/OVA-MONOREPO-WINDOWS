#!/usr/bin/env python3
"""Verify an EXTRACTED local export and reconstruct a selected artifact without SQLite."""
import argparse,json,hashlib
from pathlib import Path
import duckdb
p=argparse.ArgumentParser();p.add_argument('export_dir',type=Path);p.add_argument('--stored-sha256');p.add_argument('--output',type=Path);a=p.parse_args();c=duckdb.connect();rows=c.execute('select version,job_id,stored_sha256,redacted,source from read_parquet(?)',[str(a.export_dir/'tables/artifacts.parquet')]).fetchall()
needed={r[2] for r in rows};verified={}
for sha in sorted(needed if not a.stored_sha256 else [a.stored_sha256]):
 if sha not in needed:raise SystemExit('Requested payload not referenced by artifacts table')
 pieces=c.execute('select chunk,byte_offset,data from read_parquet(?) order by chunk',[str(a.export_dir/'payloads'/(sha+'.parquet'))]);h=hashlib.sha256();offset=0
 if a.output and len(needed)>1 and not a.stored_sha256:raise SystemExit('Select one stored hash when writing reconstructed output')
 f=a.output.open('wb') if a.output else None
 try:
  def batches():
   while True:
    batch=pieces.fetchmany(4)
    if not batch:return
    yield from batch
  for index,(chunk,pos,b) in enumerate(batches()):
   if chunk!=index or pos!=offset:raise SystemExit('Non-contiguous raw chunks')
   h.update(b);offset+=len(b)
   if f:f.write(b)
 finally:
  if f:f.close()
 if h.hexdigest()!=sha:raise SystemExit('Raw payload checksum mismatch: '+sha)
 verified[sha]=offset
print(json.dumps({'artifacts':len(rows),'referenced_payloads':len(needed),'verified_payloads':len(verified),'payload_bytes':sum(verified.values()),'checksum_roundtrip':True},indent=2))
