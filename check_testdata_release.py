#!/usr/bin/env python3
"""Detect the FHIR release (R4 vs R5) of test-data instances, and flag files that
disagree with their folder label or that mix releases internally.

Method (data driven, no per-resource rules): for each JSON resource it reads the
`resourceType`, loads that type's StructureDefinition from BOTH the R4 and R5 core
packages, and builds each release's set of valid top-level field names -- expanding
choice elements `foo[x]` into the concrete JSON keys `fooDateTime`, `fooPeriod`, ...
Every top-level key in the instance is then classed r4-only / r5-only / both /
neither. Verdict per resource:

    r5-only keys, no r4-only  -> R5
    r4-only keys, no r5-only  -> R4
    both r4-only and r5-only  -> MIXED   (hard flag)
    neither                   -> undetermined (no release-distinct fields present)

Bundles and `contained` are recursed; a file whose resources split across releases,
or contains a MIXED resource, is flagged MIXED.

Discriminating keys come straight from the spec deltas, e.g.:
    Procedure.performed[x] (R4)      vs Procedure.occurrence[x] (R5)
    MedicationStatement.medicationCodeableConcept / .context (R4)
                                     vs .medication / .encounter (R5)
    Immunization.reportOrigin/primarySource (R4) vs .informationSource (R5)
    Encounter.period/.hospitalization (R4) vs .actualPeriod/.admission (R5)
    AllergyIntolerance.type as string (R4) vs CodeableConcept (R5)

If a file's path contains an r4/r5 marker (e.g. sample_fixtures_r4/, test_files_r5/)
the detected release is checked against it and mismatches are reported.

Exit status is non-zero if any file is MIXED or contradicts its labelled release.
Undetermined files (no discriminating field, e.g. a bare Patient) do not fail.

Usage:
    python3 check_testdata_release.py [DIR ...]           # per-file scan
    python3 check_testdata_release.py --pair R4DIR R5DIR  # compare a paired corpus

Per-file scan defaults to the standard test-data dirs under matchbox_scripts.

--pair walks same-named files across an r4 and an r5 fixture dir and classifies
each pair. It FLAGS: files present in only one dir; a copy that classifies as the
opposite release (mislabelled); and -- the useful case -- a pair that is byte
identical even though the resource type IS release-sensitive (its R4 and R5
top-level field sets differ), meaning the fixture omits every distinguishing
field and the r4 copy is not actually R4-distinct (e.g. an Immunization with no
reportOrigin/primarySource or informationSource). Pairs that are identical for a
release-invariant type (Patient, Condition, Observation) are reported as ok.
"""
import glob
import json
import os
import re
import sys

PACKAGES = os.path.expanduser("~/.fhir/packages")
CORE = {"r4": "hl7.fhir.r4.core#4.0.1", "r5": "hl7.fhir.r5.core#5.0.0"}

DEFAULT_DIRS = [
    "sample_fixtures_r4", "sample_fixtures_r5",
    "test_files_r4", "test_files_r5",
    "01_Sample_FHIR_data-stingy_set",
]

# top-level keys that never discriminate a release
INFRA = {"resourceType", "id", "meta", "implicitRules", "language", "text",
         "contained", "extension", "modifierExtension"}

_field_cache = {}


def toplevel_fields(release, rtype):
    """Set of valid top-level JSON field names for rtype in the given release,
    with choice elements expanded to their concrete fooType keys."""
    key = (release, rtype)
    if key in _field_cache:
        return _field_cache[key]
    path = os.path.join(PACKAGES, CORE[release], "package",
                        f"StructureDefinition-{rtype}.json")
    fields = set()
    if os.path.exists(path):
        with open(path) as f:
            sd = json.load(f)
        for e in sd.get("snapshot", {}).get("element", []):
            p = e["path"]
            if p.count(".") != 1:            # top-level only
                continue
            base = p.split(".", 1)[1]
            if base.endswith("[x]"):
                stem = base[:-3]
                for t in e.get("type", []):
                    code = t.get("code", "")
                    fields.add(stem + code[:1].upper() + code[1:])
            else:
                fields.add(base)
    _field_cache[key] = fields
    return fields


def iter_resources(node):
    """Yield every resource dict in a file: the root, Bundle entries, contained."""
    if not isinstance(node, dict):
        return
    if node.get("resourceType"):
        yield node
    for entry in node.get("entry", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
            yield from iter_resources(entry["resource"])
    for c in node.get("contained", []) or []:
        yield from iter_resources(c)


def classify_resource(res):
    """Return (verdict, rtype, r4only_keys, r5only_keys)."""
    rtype = res.get("resourceType")
    r4 = toplevel_fields("r4", rtype)
    r5 = toplevel_fields("r5", rtype)
    if not r4 and not r5:
        return "unknown-type", rtype, [], []
    r4only, r5only = [], []
    for k in res:
        if k in INFRA:
            continue
        in4, in5 = k in r4, k in r5
        if in4 and not in5:
            r4only.append(k)
        elif in5 and not in4:
            r5only.append(k)
    if r4only and r5only:
        verdict = "MIXED"
    elif r5only:
        verdict = "r5"
    elif r4only:
        verdict = "r4"
    else:
        verdict = "undetermined"
    return verdict, rtype, r4only, r5only


def release_distinct_fields(rtype):
    """(r4_only, r5_only) top-level field names for rtype between the two releases.
    Non-empty => an instance of this type *can* look different across releases."""
    r4 = toplevel_fields("r4", rtype)
    r5 = toplevel_fields("r5", rtype)
    return sorted(r4 - r5), sorted(r5 - r4)


def root_type(path):
    try:
        for res in iter_resources(json.load(open(path))):
            return res.get("resourceType")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def pair_analysis(r4dir, r5dir):
    """Compare same-named files across an r4 and r5 fixture dir.

    Return (problems, coverage, oks):
      problems  hard defects -> non-zero exit: a file present in only one dir, or
                a copy that classifies as the OPPOSITE release (mislabelled).
      coverage  advisory, per resource type: identical pairs whose type is
                release-sensitive but whose instances use only common fields, so
                the r4 copy exercises nothing R4-distinct. Not a validity defect.
      oks       correctly-converted pairs and identical release-invariant pairs.
    """
    def names(d):
        return {os.path.relpath(p, d)
                for p in glob.glob(os.path.join(d, "**", "*.json"), recursive=True)}
    n4, n5 = names(r4dir), names(r5dir)
    problems, oks = [], []
    cov = {}  # rtype -> {"count": int, "r4": [...], "r5": [...]}

    for only, other in ((n4 - n5, r4dir), (n5 - n4, r5dir)):
        for rel in sorted(only):
            side = "r4-only" if other == r4dir else "r5-only"
            problems.append(f"{rel}: present {side}, no counterpart")

    for rel in sorted(n4 & n5):
        p4, p5 = os.path.join(r4dir, rel), os.path.join(r5dir, rel)
        identical = open(p4, "rb").read() == open(p5, "rb").read()
        rt = root_type(p4) or root_type(p5)
        v4 = check_file(p4)[0]
        v5 = check_file(p5)[0]

        # a copy classifying as the opposite release is a real mislabel
        if v4 == "r5":
            problems.append(f"{rel}: {rt} in r4 dir classifies as R5")
            continue
        if v5 == "r4":
            problems.append(f"{rel}: {rt} in r5 dir classifies as R4")
            continue

        if not identical:
            oks.append(f"{rel}: {rt} converted r4->r5"
                       if (v4, v5) == ("r4", "r5") else
                       f"{rel}: {rt} differs (r4={v4}, r5={v5})")
            continue

        # identical bytes and neither copy uses a distinguishing field:
        # valid in both releases. Note it only when the type COULD differ.
        r4o, r5o = release_distinct_fields(rt) if rt else ([], [])
        if r4o or r5o:
            c = cov.setdefault(rt, {"count": 0, "r4": r4o, "r5": r5o})
            c["count"] += 1
        else:
            oks.append(f"{rel}: {rt} identical, type is release-invariant")

    coverage = [
        f"{rt}: {c['count']} identical pair(s) use no release-distinct field "
        f"(r4-only {c['r4']}, r5-only {c['r5']}) -> r4 corpus not R4-distinct here"
        for rt, c in sorted(cov.items())
    ]
    return problems, coverage, oks


def label_from_path(path):
    if re.search(r'(^|[/_])r4([/_]|$)', path):
        return "r4"
    if re.search(r'(^|[/_])r5([/_]|$)', path):
        return "r5"
    return None


def check_file(path):
    """Return (file_verdict, list_of_problem_strings, detail_lines)."""
    try:
        data = json.load(open(path))
    except (json.JSONDecodeError, OSError) as e:
        return "error", [f"unreadable: {e}"], []

    resources = list(iter_resources(data))
    if not resources:
        return "no-resource", [], []

    detail, releases, problems = [], set(), []
    for res in resources:
        verdict, rtype, r4o, r5o = classify_resource(res)
        detail.append((rtype, verdict, r4o, r5o))
        if verdict == "MIXED":
            problems.append(f"{rtype} MIXED (r4:{r4o} r5:{r5o})")
        if verdict in ("r4", "r5"):
            releases.add(verdict)

    if len(releases) > 1:
        file_verdict = "MIXED"
        problems.append(f"resources span releases: {sorted(releases)}")
    elif releases:
        file_verdict = releases.pop()
    elif any(v == "MIXED" for _, v, _, _ in detail):
        file_verdict = "MIXED"
    else:
        file_verdict = "undetermined"

    label = label_from_path(path)
    if label and file_verdict in ("r4", "r5") and file_verdict != label:
        problems.append(f"labelled {label} but detected {file_verdict}")

    return file_verdict, problems, detail


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    argv = sys.argv[1:]

    if argv and argv[0] == "--pair":
        if len(argv) != 3:
            sys.exit("usage: check_testdata_release.py --pair R4DIR R5DIR")
        r4dir, r5dir = argv[1], argv[2]
        for d in (r4dir, r5dir):
            if not os.path.isdir(d):
                sys.exit(f"error: not a directory: {d}")
        problems, coverage, oks = pair_analysis(r4dir, r5dir)
        for o in oks:
            print(f"[ok]   {o}")
        for c in coverage:
            print(f"[note] {c}")
        for p in problems:
            print(f"[FLAG] {p}")
        print(f"\n{len(oks)} ok pair(s), {len(coverage)} coverage note(s), "
              f"{len(problems)} flagged.")
        sys.exit(1 if problems else 0)

    dirs = argv or [os.path.join(here, d) for d in DEFAULT_DIRS]

    files = []
    for d in dirs:
        if os.path.isfile(d):
            files.append(d)
        elif os.path.isdir(d):
            files += sorted(glob.glob(os.path.join(d, "**", "*.json"), recursive=True))
        else:
            print(f"warning: not found: {d}", file=sys.stderr)
    if not files:
        sys.exit("error: no .json files to check")

    counts = {}
    problem_files = 0
    for path in files:
        verdict, problems, _ = check_file(path)
        counts[verdict] = counts.get(verdict, 0) + 1
        rel = os.path.relpath(path, here)
        if problems:
            problem_files += 1
            print(f"[{verdict}] {rel}")
            for p in problems:
                print(f"    -> {p}")
        else:
            print(f"[{verdict}] {rel}")

    print("\nsummary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"{problem_files} file(s) with a release problem (MIXED or mislabelled).")
    sys.exit(1 if problem_files else 0)


if __name__ == "__main__":
    main()
