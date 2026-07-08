#!/usr/bin/env python3
"""Verify fhir-omop-ig StructureMaps against the FHIR core StructureDefinitions
(source side) and the OMOP logical-model StructureDefinitions (target side).

For each FML map in the IG's input/maps/ this checks:

  * SOURCE  every `src.<elem>` first-segment path exists on the source resource,
            and every typed choice `src.<elem> : <Type>` resolves to a type that
            the corresponding `<elem>[x]` element actually allows in that release.
  * TARGET  every `tgt.<column>` (and group-var target column) exists in the OMOP
            table's logical-model StructureDefinition.

It does NOT walk datatype sub-navigation (`.coding.code` off a group variable) --
those are standard Coding/CodeableConcept accessors and release-invariant.

Release conformance falls out of the SOURCE check: point --fhir-version at r4 and
an R5-only path (e.g. Procedure.occurrence[x], MedicationStatement.medication as
CodeableReference) will report MISSING/BAD.

Advisory: references to the `effective<Type>` / `effectiveDate` shorthand inside
FHIRPath `where()` predicates are reported separately -- they are not resource
element paths in any release (the model is `effective[x]`) and are engine
dependent; `effectiveDate` matches no choice at all.

Exit status is non-zero if any hard MISSING/BAD is found (advisories don't fail).

Target columns are validated against the pinned OMOP IG *package*
(hl7.fhir.uv.omop#<ig-version>), not the transient fsh-generated build output, so
the check runs against a known IG version (default 1.0.0) regardless of what a
prior build_profiles.py run may have written into fsh-generated.

Usage:
    python3 verify_map_conformance.py [--fhir-version r5|r4] [--ig-version 1.0.0]
                                      [--ig-dir PATH]

Defaults: r5 (hl7.fhir.r5.core#5.0.0), OMOP IG 1.0.0 (hl7.fhir.uv.omop#1.0.0),
maps from ../fhir-omop-ig relative to this file.
"""
import argparse
import glob
import json
import os
import re
import sys

CORE_PACKAGE = {
    "r5": "hl7.fhir.r5.core#5.0.0",
    "r4": "hl7.fhir.r4.core#4.0.1",
}
OMOP_PACKAGE = "hl7.fhir.uv.omop"  # + '#<ig-version>'


def load_elements(path):
    """Return (root_type, {element_path: [type_codes]}) from snapshot or differential."""
    with open(path) as f:
        sd = json.load(f)
    elements = {}
    for e in (sd.get("snapshot") or sd.get("differential") or {}).get("element", []):
        elements[e["path"]] = [t.get("code") for t in e.get("type", [])]
    return sd.get("type"), elements


def core_sd(core_dir, url):
    name = url.rsplit("/", 1)[-1]
    p = os.path.join(core_dir, f"StructureDefinition-{name}.json")
    return p if os.path.exists(p) else None


def omop_sd(omop_dir, url):
    name = url.rsplit("/", 1)[-1]
    p = os.path.join(omop_dir, f"StructureDefinition-{name}.json")
    return p if os.path.exists(p) else None


def verify_map(mapf, core_dir, omop_dir):
    """Return (hard_failures, advisories) as lists of strings."""
    txt = open(mapf).read()
    hard, advisory = [], []

    src_m = re.search(r'uses "([^"]+)"[^\n]*as source', txt)
    tgt_urls = re.findall(r'uses "([^"]+)"[^\n]*as target', txt)
    if not src_m:
        return ["no source declared"], []

    src_path = core_sd(core_dir, src_m.group(1))
    if not src_path:
        return [f"SOURCE SD not found in core package: {src_m.group(1)}"], []
    rtype, spaths = load_elements(src_path)

    def elem_types(seg):
        for cand in (f"{rtype}.{seg}", f"{rtype}.{seg}[x]"):
            if cand in spaths:
                return spaths[cand], cand
        return None, None

    # `effective<Type>` / `effectiveDate` FHIRPath shorthand -> advisory, not a path.
    shorthand = set(re.findall(r'src\.(effective[A-Za-z]+)', txt))
    firsts = set(re.findall(r'src\.(\w+)', txt)) - shorthand
    typed = set(re.findall(r'src\.(\w+)\s*:\s*(\w+)', txt))

    for seg in sorted(firsts):
        _, key = elem_types(seg)
        if key is None:
            hard.append(f"SOURCE  missing element  {rtype}.{seg}")
    for seg in sorted(shorthand):
        _, key = elem_types(seg)
        if key is None:
            advisory.append(
                f"SOURCE  {rtype}.{seg} is FHIRPath choice shorthand, not a {rtype} "
                f"element (model is effective[x]); engine dependent"
            )
    for seg, ty in sorted(typed):
        types, key = elem_types(seg)
        if key is None:
            hard.append(f"SOURCE  missing choice  {rtype}.{seg} : {ty}")
        elif ty.lower() not in [t.lower() for t in types]:
            hard.append(f"SOURCE  bad type  {key} : {ty}  (allowed: {types})")

    # Target columns: union across all target SDs (OMOP logical models + core Bundle).
    cols = set()
    for u in tgt_urls:
        p = omop_sd(omop_dir, u) or core_sd(core_dir, u)
        if not p:
            hard.append(f"TARGET SD not found: {u}")
            continue
        _, pp = load_elements(p)
        cols |= {path.split(".", 1)[1].lower() for path in pp if "." in path}

    used = set(re.findall(r'\btgt\.(\w+)', txt))
    # group-var targets (e.g. `sysTable.value_as_number`, `parentTable.measurement_...`)
    used |= set(re.findall(r'\b\w*[Tt]able\.(\w+)', txt))
    for c in sorted(used):
        if c.lower() not in cols:
            hard.append(f"TARGET  missing column  {c}")

    return hard, advisory


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fhir-version", choices=CORE_PACKAGE, default="r5")
    ap.add_argument("--ig-version", default="1.0.0",
                    help="OMOP IG version to validate target columns against "
                         "(default: 1.0.0). Pins to the hl7.fhir.uv.omop#<ver> "
                         "package, not the transient fsh-generated build output.")
    ap.add_argument("--ig-dir", default=os.path.join(here, "..", "fhir-omop-ig"),
                    help="fhir-omop-ig checkout, source of the FML maps (default: ../fhir-omop-ig)")
    ap.add_argument("--packages-dir", default=os.path.expanduser("~/.fhir/packages"),
                    help="FHIR package cache (default: ~/.fhir/packages)")
    args = ap.parse_args()

    core_dir = os.path.join(args.packages_dir, CORE_PACKAGE[args.fhir_version], "package")
    omop_pkg = f"{OMOP_PACKAGE}#{args.ig_version}"
    omop_dir = os.path.join(args.packages_dir, omop_pkg, "package")
    maps_dir = os.path.join(args.ig_dir, "input", "maps")

    for label, d in (("core package", core_dir),
                     (f"OMOP package {omop_pkg}", omop_dir),
                     ("maps", maps_dir)):
        if not os.path.isdir(d):
            sys.exit(f"error: {label} directory not found: {d}")

    maps = sorted(glob.glob(os.path.join(maps_dir, "*.fml")))
    if not maps:
        sys.exit(f"error: no .fml maps in {maps_dir}")

    print(f"Verifying {len(maps)} maps against {CORE_PACKAGE[args.fhir_version]} "
          f"+ {omop_pkg}\n")
    total_hard = 0
    for mapf in maps:
        hard, advisory = verify_map(mapf, core_dir, omop_dir)
        total_hard += len(hard)
        status = "FAIL" if hard else "ok"
        print(f"[{status}] {os.path.basename(mapf)}")
        for h in hard:
            print(f"       {h}")
        for a in advisory:
            print(f"       advisory: {a}")

    print(f"\n{total_hard} hard failure(s) across {len(maps)} maps "
          f"against {args.fhir_version}.")
    sys.exit(1 if total_hard else 0)


if __name__ == "__main__":
    main()
