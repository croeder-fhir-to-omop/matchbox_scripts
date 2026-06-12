#!/usr/bin/env python3
"""
Benchmark matchbox $transform throughput and latency.

Three phases:
  1. First call per fixture — cold terminology cache; measures full round-trip
     including Echidna concept-mapping lookups and JVM/StructureMap warmup.
  2. Warm sequential — N rounds cycling through all fixtures; HAPI has cached
     all terminology lookups, so this measures pure StructureMap execution +
     HTTP overhead.
  3. Concurrent throughput — fixed total calls across W worker threads.

The delta between phases 1 and 2 is a proxy for Echidna overhead.
Note: phase 1 confounds Echidna cost with JVM JIT warmup on the very first
call per StructureMap. For a clean Echidna-only measurement, time
GET /matchboxv3/fhir/ConceptMap/$translate directly against a warm matchbox.

Suppressed fixtures (condition_refuted, procedure_not_done) are excluded —
they never reach matchbox.

Usage:
    MATCHBOX_URL=http://localhost:8080 python benchmark.py
    python benchmark.py --url http://localhost:8080 --rounds 50 --workers 8
    python benchmark.py --fixtures-dir volume_population
    FIXTURES_DIR=sample_fixtures python benchmark.py
"""

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import transforms as _t
from transforms import (
    transform_allergy,
    transform_condition,
    transform_encounter,
    transform_immunization,
    transform_measurement,
    transform_medication,
    transform_observation,
    transform_patient,
    transform_procedure,
    transform_vital_signs,
)

# Each entry: (fixture filename, transform fn, display label)
# Multiple fixtures for the same type exercise different codes, which matters
# because HAPI caches terminology lookups per code — repeating the same
# fixture after the first call never touches Echidna again.
CASES = [
    # Three distinct SNOMED codes → three independent cold/warm comparisons
    ("condition_fever.json",             transform_condition,    "Condition/fever"),
    ("condition_hypertension.json",      transform_condition,    "Condition/hypertension"),
    ("condition_unknown_code.json",      transform_condition,    "Condition/unknown-code"),
    # Single fixture per type — warm measurements only after first call
    ("patient.json",                     transform_patient,      "Patient"),
    ("encounter_outpatient.json",        transform_encounter,    "Encounter"),
    ("procedure_completed.json",         transform_procedure,    "Procedure"),
    ("allergy_peanut.json",              transform_allergy,      "Allergy"),
    ("immunization_flu.json",            transform_immunization, "Immunization"),
    ("medication_aspirin.json",          transform_medication,   "Medication"),
    ("observation_weight_int.json",      transform_measurement,  "Measurement"),
    ("observation_temperature_int.json", transform_vital_signs,  "VitalSigns"),
    ("observation_smoking.json",         transform_observation,  "Observation"),
]


def _timed(fn, resource):
    """Call fn(resource), return (result, elapsed_seconds, error_string|None).

    Retries once on connection reset/aborted errors, which occur when the
    server closes a stale keep-alive connection that requests tries to reuse.
    """
    t0 = time.perf_counter()
    last_err = None
    for _ in range(2):
        try:
            result = fn(resource)
            return result, time.perf_counter() - t0, None
        except Exception as e:
            last_err = str(e).split("\n")[0]
            if not any(kw in str(e).lower() for kw in ("reset", "aborted", "broken pipe")):
                break  # not a connection error — don't retry
    return None, time.perf_counter() - t0, last_err


def load_cases(fixtures_dir):
    loaded = []
    for filename, fn, label in CASES:
        path = fixtures_dir / filename
        if not path.exists():
            print(f"  WARNING: {filename} not found in {fixtures_dir}, skipping", file=sys.stderr)
            continue
        resource = json.loads(path.read_text())
        loaded.append((resource, fn, label))
    return loaded


def phase_first_call(cases):
    """One call per fixture — cold terminology cache."""
    print("\n── Phase 1: First call (cold terminology cache) ──")
    first_times = {}
    for resource, fn, label in cases:
        _, elapsed, err = _timed(fn, resource)
        if err:
            print(f"  {label:<38} ERROR: {err}")
        else:
            print(f"  {label:<38} {elapsed*1000:>6.0f} ms")
            first_times[label] = elapsed
    return first_times


def phase_warm(cases, rounds):
    """N rounds cycling through all fixtures — terminology cache is warm."""
    print(f"\n── Phase 2: Warm sequential ({rounds} rounds × {len(cases)} fixtures) ──")
    timings = {label: [] for _, _, label in cases}
    for _ in range(rounds):
        for resource, fn, label in cases:
            _, elapsed, err = _timed(fn, resource)
            if not err:
                timings[label].append(elapsed)

    def pct(s, p):
        return s[min(int(len(s) * p), len(s) - 1)] * 1000

    print(f"  {'Label':<38} {'mean':>7} {'p50':>7} {'p95':>7} {'p99':>7}")
    print(f"  {'-'*38} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
    for label, times in timings.items():
        if not times:
            print(f"  {label:<38}  (no data)")
            continue
        s = sorted(times)
        print(
            f"  {label:<38}"
            f" {statistics.mean(s)*1000:>6.0f}ms"
            f" {pct(s,0.50):>6.0f}ms"
            f" {pct(s,0.95):>6.0f}ms"
            f" {pct(s,0.99):>6.0f}ms"
        )
    return timings


def phase_concurrent(cases, total_calls, workers):
    """Dispatch total_calls across workers threads, cycling through fixtures."""
    print(f"\n── Phase 3: Concurrent throughput ({total_calls} calls, {workers} workers) ──")
    work = [cases[i % len(cases)] for i in range(total_calls)]
    errors, times, first_error = 0, [], None
    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_timed, fn, resource) for resource, fn, _ in work]
        for f in as_completed(futs):
            _, elapsed, err = f.result()
            if err:
                errors += 1
                if first_error is None:
                    first_error = err
            else:
                times.append(elapsed)
    wall = time.perf_counter() - t_start
    rps = len(times) / wall if wall > 0 else 0
    print(f"  Completed: {len(times)}/{total_calls}  errors: {errors}")
    if first_error:
        print(f"  First error: {first_error}")
    print(f"  Wall time: {wall:.1f}s  →  {rps:.1f} transforms/sec")
    if times:
        s = sorted(times)
        print(f"  p50: {s[len(s)//2]*1000:.0f}ms   p95: {s[int(len(s)*0.95)]*1000:.0f}ms")
    return rps


def echidna_summary(first_times, warm_timings):
    """
    Estimate Echidna overhead as first-call − warm p50.
    This conflates Echidna cost with JVM JIT warmup on the very first
    StructureMap call, so treat it as an upper bound, not a precise measurement.
    For a precise number, time $translate directly against Echidna.
    """
    print("\n── Echidna overhead estimate (first call − warm p50) ──")
    print(f"  {'Label':<38} {'first':>7} {'warm p50':>9} {'delta':>9}")
    print(f"  {'-'*38} {'-'*7} {'-'*9} {'-'*9}")
    for label, cold in first_times.items():
        times = warm_timings.get(label, [])
        if not times:
            continue
        s = sorted(times)
        warm_p50 = s[len(s) // 2] * 1000
        delta = cold * 1000 - warm_p50
        print(f"  {label:<38} {cold*1000:>6.0f}ms  {warm_p50:>7.0f}ms  {delta:>+8.0f}ms")
    print()
    print("  Note: delta is an upper bound — also includes JVM JIT on first call.")
    print("  For Echidna-only latency, run:")
    print("    curl -s 'http://localhost:8080/matchboxv3/fhir/ConceptMap/\\$translate?")
    print("      system=http://snomed.info/sct&code=386661006&targetsystem=...'")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url",          default=None,  help="Matchbox base URL (overrides MATCHBOX_URL env var)")
    parser.add_argument("--rounds",       type=int, default=50,  help="Warm sequential rounds per fixture (default: 50)")
    parser.add_argument("--workers",      type=int, default=8,   help="Concurrent worker threads (default: 8)")
    parser.add_argument("--total",        type=int, default=200, help="Total calls for concurrency test (default: 200)")
    parser.add_argument("--fixtures-dir", default=os.environ.get("FIXTURES_DIR", "test_files"),
                        help="Directory containing fixture JSON files (default: test_files; also reads FIXTURES_DIR env var)")
    args = parser.parse_args()

    if args.url:
        _t._BASE_URL = args.url.rstrip("/") + "/matchboxv3/fhir"

    fixtures_dir = HERE / args.fixtures_dir
    cases = load_cases(fixtures_dir)
    if not cases:
        print(f"No fixtures found in {fixtures_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Matchbox URL : {_t._base_url()}")
    print(f"Fixtures dir : {fixtures_dir}")
    print(f"Fixtures     : {len(cases)}")
    print(f"Warm rounds  : {args.rounds} × {len(cases)} = {args.rounds * len(cases)} calls")
    print(f"Concurrency  : {args.total} calls across {args.workers} workers")

    first  = phase_first_call(cases)
    warm   = phase_warm(cases, args.rounds)
    rps    = phase_concurrent(cases, args.total, args.workers)
    echidna_summary(first, warm)

    all_warm = [t for times in warm.values() for t in times]
    print("\n── Overall ──")
    if all_warm:
        print(f"  Warm mean latency : {statistics.mean(all_warm)*1000:.0f} ms/transform")
    print(f"  Concurrent        : {rps:.1f} transforms/sec")


if __name__ == "__main__":
    main()
