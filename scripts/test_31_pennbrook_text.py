#!/usr/bin/env python3
"""Test extraction from the actual 31 Pennbrook legal description text."""

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.text_parser import TextParser

# Actual legal description from 31 Pennbrook
LEGAL_DESC_TEXT = """
BEGINNING at a point in the southerly line of Pennbrook Drive 125 feet southwestwardly from the southwesterly
line of Concord Drive; thence (1) south 56 degrees 40 minutes west along said southerly line of Pennbrook Drive
50 feet to an angle in same; thence (2) still along said southerly line of Pennbrook Drive south 87 degrees 7
minutes 30 seconds west 28.84 feet to a point in the division line between lots 50 and 52 on plan hereinafter
mentioned; thence (3) southwestwardly along said division line 134.52 feet to a point corner common to lots 28,
29, 50 and 52 said plan; thence (4) southeastwardly along the rear line of lot number 29, 90 feet to a point in line
of lot 30 said plan; thence (5) northeastwardly along said line of lot number 30, 31.47 feet to an angle in same;
thence (6) still continuing along said line of Lot Number 30, 99.37 feet to a point in the rear line of Lot Number 46,
said plan; thence (7) Northwestwardly partly along rear line of Lot Number 46 and all along rear line of Lot
Number 47, 120 feet to a point in the Southerly line of Pennbrook Drive and place of BEGINNING.
"""


def main():
    print("=" * 80)
    print("31 PENNBROOK LEGAL DESCRIPTION - EXTRACTION TEST")
    print("=" * 80)

    print("\n--- STEP 1: NORMALIZE TEXT ---")
    normalized = TextParser.normalize_legal_description(LEGAL_DESC_TEXT)
    print(f"Normalized text ({len(normalized)} chars):")
    print(normalized)

    print("\n--- STEP 2: EXTRACT POB ---")
    pob = TextParser.extract_pob(normalized)
    print(f"POB: {pob}")

    print("\n--- STEP 3: SPLIT INTO CALLS ---")
    call_texts = TextParser.split_into_calls(normalized)
    print(f"Found {len(call_texts)} call segments:\n")
    for i, call_text in enumerate(call_texts, 1):
        print(f"  {i}. {call_text[:80]}..." if len(call_text) > 80 else f"  {i}. {call_text}")
        print()

    print("\n--- STEP 4: EXTRACT CALLS ---")
    calls = CallExtractor.extract_calls(normalized)
    print(f"Extracted {len(calls)} calls:\n")

    for i, call in enumerate(calls, 1):
        print(f"CALL {i}:")
        print(f"  Direction:  {call.direction_text}")
        print(f"  Bearing:    {call.bearing_quadrant or '(incomplete)'}")
        print(
            f"  Azimuth:    {f'{call.bearing_azimuth_deg_from_north:.2f}°' if call.bearing_azimuth_deg_from_north is not None else '(none)'}"
        )
        print(f"  Distance:   {call.distance_ft:.2f} ft")
        print(f"  Along:      {call.along[:60] if call.along else '(none)'}...")
        print(f"  Notes:      {call.notes or '(none)'}")
        print()

    print("\n--- STEP 5: CLOSURE VERIFICATION ---")
    result = ClosureChecker.verify_closure(calls)
    print(f"Misclosure:     {result.misclosure_ft:.4f} ft")
    print(f"Area:           {result.area_sq_ft:.2f} sq ft ({result.area_acres:.4f} acres)")
    print(f"Perimeter:      {result.perimeter_ft:.2f} ft")
    print(f"Closure Status: {result.get_closure_status()}")

    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    print("\n" + "=" * 80)
    print("EXPECTED: 7 calls with 2 complete bearings and 5 cardinal-only")
    print(f"ACTUAL:   {len(calls)} calls extracted")
    print("=" * 80)


if __name__ == "__main__":
    main()
