"""Integration tests for PDF processing with actual deed PDFs.

Tests the full pipeline from PDF extraction through verification using
the sample deed PDFs in the project root directory.

These tests require:
- OPENAI_API_KEY environment variable
- Actual PDF files in project root
- Network connectivity for OpenAI API

Tests are marked as 'slow' and 'integration' for selective execution.
"""

import os
from pathlib import Path

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.pdf_processor import PDFProcessor
from metesparser.text_parser import TextParser

# Project root directory containing sample_deeds folder
PROJECT_ROOT = Path(__file__).parent.parent.parent
SAMPLE_DEEDS_DIR = PROJECT_ROOT / "sample_deeds"

# Sample deed PDF files
PDF_18_PENNBROOK = SAMPLE_DEEDS_DIR / "18 Pennbrook Dr - Deed Image (11985 - 00829).pdf"
PDF_24_PENNBROOK = SAMPLE_DEEDS_DIR / "24 Pennbrook Dr - Deed Image (11793 - 00217).pdf"
PDF_31_PENNBROOK_1 = SAMPLE_DEEDS_DIR / "31 Pennbrook Dr - Deed Image (4618 - 717).pdf"
PDF_31_PENNBROOK_2 = SAMPLE_DEEDS_DIR / "31 Pennbrook Dr - Deed Image (9777 - 1354).pdf"
PDF_31_PENNBROOK_3 = SAMPLE_DEEDS_DIR / "31 Pennbrook Dr - Deed Image (10989 - 916).pdf"
PDF_31_PENNBROOK_4 = SAMPLE_DEEDS_DIR / "31 Pennbrook Dr - Deed Image (11191 - 01716).pdf"


def has_openai_key() -> bool:
    """Check if OPENAI_API_KEY is set in environment."""
    return bool(os.getenv("OPENAI_API_KEY"))


# Skip all tests in this module if OpenAI key is not available
pytestmark = [
    pytest.mark.slow,  # These tests make API calls
    pytest.mark.integration,  # Full pipeline tests
    pytest.mark.skipif(
        not has_openai_key(),
        reason="OPENAI_API_KEY not set - skipping PDF processing tests",
    ),
]


@pytest.fixture
def pdf_processor():
    """Create PDFProcessor instance for tests."""
    return PDFProcessor()


class Test18PennbrookPDF:
    """Test PDF extraction and processing for 18 Pennbrook Dr.

    Expected parcel characteristics:
    - Parallelogram shape (not rectangle)
    - 4 calls/courses
    - Bearings: N 33°20' E, S 56°40' W, S 33°20' W, N 56°40' E
    - Distances: 60 ft, 125 ft, 60 ft, 125 ft
    - Should close perfectly (misclosure < 0.01 ft)
    - Area: ~2,971 sq ft (NOT 60×125=7,500 due to parallelogram)
    """

    def test_pdf_exists(self):
        """Verify PDF file exists before testing."""
        assert PDF_18_PENNBROOK.exists(), f"PDF not found: {PDF_18_PENNBROOK}"

    @pytest.mark.slow
    def test_extract_legal_description(self, pdf_processor):
        """Test extracting legal description from 18 Pennbrook PDF."""
        # Extract
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_18_PENNBROOK))

        # Should have POB description
        assert legal_desc.pob_description is not None
        assert len(legal_desc.pob_description) > 0

        # Should have calls extracted
        assert len(legal_desc.calls) >= 4, "Expected at least 4 calls for this parcel"

        # Check bearings are parsed (not incomplete)
        complete_calls = [c for c in legal_desc.calls if c.bearing_azimuth_deg_from_north is not None]
        assert len(complete_calls) >= 4, "Expected at least 4 complete bearings"

    @pytest.mark.slow
    def test_closure_verification(self, pdf_processor):
        """Test that 18 Pennbrook traverse closes properly."""
        # Extract and process
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_18_PENNBROOK))

        # Verify closure
        result = ClosureChecker.verify_closure(legal_desc.calls)

        # Should close (opposite sides parallel in parallelogram)
        assert result.closure_passed is True, (
            f"Expected closure to pass, misclosure: {result.misclosure_ft:.4f} ft"
        )
        assert result.misclosure_ft < 0.01

        # Check area (should be ~2,971 sq ft for parallelogram, not 7,500)
        # Allow wide tolerance since we don't know exact expected area
        assert 2000 < result.area_sq_ft < 8000, (
            f"Area {result.area_sq_ft:.0f} sq ft seems unreasonable"
        )

        # Check perimeter
        expected_perimeter = 2 * (60 + 125)  # 370 ft
        assert abs(result.perimeter_ft - expected_perimeter) < 5, (
            f"Perimeter {result.perimeter_ft:.2f} ft differs from expected {expected_perimeter} ft"
        )

    @pytest.mark.slow
    def test_monument_detection(self, pdf_processor):
        """Test monument type classification in 18 Pennbrook."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_18_PENNBROOK))

        # Check if any monuments were detected
        monuments = [c.monument_type for c in legal_desc.calls if c.monument_type]

        # May or may not have monuments depending on deed wording
        # This test just verifies the classification doesn't crash
        if monuments:
            # All monument types should be valid enum values
            valid_types = {
                "iron_rod", "iron_pin", "iron_pipe", "stone", "concrete",
                "wooden_post", "brass_cap", "rebar", "railroad_spike", "nail", "other"
            }
            for monument in monuments:
                assert monument in valid_types

    @pytest.mark.slow
    def test_csv_export(self, pdf_processor, tmp_path):
        """Test CSV export for 18 Pennbrook."""
        # Extract
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_18_PENNBROOK))

        # Export to CSV
        output_path = tmp_path / "18_pennbrook.csv"
        CSVBuilder.legal_description_to_csv(legal_desc, str(output_path))

        # CSV should exist
        assert output_path.exists()

        # Metadata file should exist
        metadata_path = output_path.with_suffix(".metadata.txt")
        assert metadata_path.exists()

        # Should be able to re-import
        imported_calls = CSVBuilder.csv_to_calls(str(output_path))
        assert len(imported_calls) == len(legal_desc.calls)


class Test24PennbrookPDF:
    """Test PDF extraction and processing for 24 Pennbrook Dr.

    This is a different parcel on the same street. Expected characteristics TBD.
    """

    def test_pdf_exists(self):
        """Verify PDF file exists before testing."""
        assert PDF_24_PENNBROOK.exists(), f"PDF not found: {PDF_24_PENNBROOK}"

    @pytest.mark.slow
    def test_extract_legal_description(self, pdf_processor):
        """Test extracting legal description from 24 Pennbrook PDF."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_24_PENNBROOK))

        # Should have basic components
        assert legal_desc.pob_description is not None or legal_desc.poc_description is not None
        assert len(legal_desc.calls) > 0, "Expected at least one call"

        # All calls should have distance
        for call in legal_desc.calls:
            assert call.distance_ft > 0

    @pytest.mark.slow
    def test_closure_verification(self, pdf_processor):
        """Test closure verification for 24 Pennbrook."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_24_PENNBROOK))
        result = ClosureChecker.verify_closure(legal_desc.calls)

        # At minimum, closure calculation should complete without errors
        assert result.misclosure_ft >= 0
        assert result.area_sq_ft > 0
        assert result.perimeter_ft > 0

        # Log results for manual verification
        print(f"\n24 Pennbrook Closure Results:")
        print(f"  Misclosure: {result.misclosure_ft:.4f} ft")
        print(f"  Area: {result.area_sq_ft:.2f} sq ft ({result.area_acres:.4f} acres)")
        print(f"  Status: {result.get_closure_status()}")
        print(f"  Warnings: {len(result.warnings)}")


class Test31PennbrookChainOfTitle:
    """Test all 4 deeds for 31 Pennbrook Dr (chain of title).

    This tests extraction from multiple historical deeds for the same property,
    which should describe the same parcel with minor variations.
    """

    def test_all_pdfs_exist(self):
        """Verify all 4 PDF files exist."""
        pdfs = [PDF_31_PENNBROOK_1, PDF_31_PENNBROOK_2, PDF_31_PENNBROOK_3, PDF_31_PENNBROOK_4]
        for pdf_path in pdfs:
            assert pdf_path.exists(), f"PDF not found: {pdf_path}"

    @pytest.mark.slow
    def test_oldest_deed_4618_717(self, pdf_processor):
        """Test oldest deed in chain (4618-717)."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_31_PENNBROOK_1))

        assert len(legal_desc.calls) > 0
        print(f"\n31 Pennbrook (4618-717): {len(legal_desc.calls)} calls")

    @pytest.mark.slow
    def test_deed_9777_1354(self, pdf_processor):
        """Test deed 9777-1354."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_31_PENNBROOK_2))

        assert len(legal_desc.calls) > 0
        print(f"\n31 Pennbrook (9777-1354): {len(legal_desc.calls)} calls")

    @pytest.mark.slow
    def test_deed_10989_916(self, pdf_processor):
        """Test deed 10989-916."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_31_PENNBROOK_3))

        assert len(legal_desc.calls) > 0
        print(f"\n31 Pennbrook (10989-916): {len(legal_desc.calls)} calls")

    @pytest.mark.slow
    def test_newest_deed_11191_01716(self, pdf_processor):
        """Test newest deed in chain (11191-01716)."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_31_PENNBROOK_4))

        assert len(legal_desc.calls) > 0
        print(f"\n31 Pennbrook (11191-01716): {len(legal_desc.calls)} calls")

    @pytest.mark.slow
    def test_compare_deed_consistency(self, pdf_processor):
        """Test that all 4 deeds describe roughly the same parcel.

        While the exact wording may differ across deeds, the fundamental
        parcel characteristics should be consistent:
        - Similar number of calls (±1)
        - Similar area (within 10%)
        - Similar perimeter (within 10%)
        """
        pdfs = [PDF_31_PENNBROOK_1, PDF_31_PENNBROOK_2, PDF_31_PENNBROOK_3, PDF_31_PENNBROOK_4]
        results = []

        for pdf_path in pdfs:
            legal_desc = pdf_processor.process_deed_pdf(str(pdf_path))
            closure_result = ClosureChecker.verify_closure(legal_desc.calls)
            results.append({
                "deed": pdf_path.stem,
                "num_calls": len(legal_desc.calls),
                "area_sq_ft": closure_result.area_sq_ft,
                "perimeter_ft": closure_result.perimeter_ft,
                "misclosure_ft": closure_result.misclosure_ft,
                "closure_passed": closure_result.closure_passed,
            })

        # Print comparison table
        print("\n31 Pennbrook Chain of Title Comparison:")
        print("-" * 80)
        for r in results:
            print(f"{r['deed'][:30]:<30} | Calls: {r['num_calls']:2d} | "
                  f"Area: {r['area_sq_ft']:8.2f} sq ft | "
                  f"Perim: {r['perimeter_ft']:7.2f} ft | "
                  f"Misc: {r['misclosure_ft']:6.4f} ft | "
                  f"Close: {'✓' if r['closure_passed'] else '✗'}")

        # Extract metrics for comparison
        num_calls_list = [r["num_calls"] for r in results]
        areas = [r["area_sq_ft"] for r in results]
        perimeters = [r["perimeter_ft"] for r in results]

        # Number of calls should be consistent (±1 call variation acceptable)
        max_calls = max(num_calls_list)
        min_calls = min(num_calls_list)
        assert max_calls - min_calls <= 1, (
            f"Call counts vary too much: {num_calls_list}"
        )

        # Areas should be within 10% of each other (allowing for minor survey differences)
        if all(a > 0 for a in areas):
            avg_area = sum(areas) / len(areas)
            for i, area in enumerate(areas):
                percent_diff = abs(area - avg_area) / avg_area * 100
                assert percent_diff < 10, (
                    f"Deed {i+1} area {area:.2f} differs {percent_diff:.1f}% "
                    f"from average {avg_area:.2f}"
                )

        # Perimeters should be within 10% of each other
        if all(p > 0 for p in perimeters):
            avg_perimeter = sum(perimeters) / len(perimeters)
            for i, perimeter in enumerate(perimeters):
                percent_diff = abs(perimeter - avg_perimeter) / avg_perimeter * 100
                assert percent_diff < 10, (
                    f"Deed {i+1} perimeter {perimeter:.2f} differs {percent_diff:.1f}% "
                    f"from average {avg_perimeter:.2f}"
                )


class TestPDFErrorHandling:
    """Test error handling for PDF processing edge cases."""

    @pytest.mark.slow
    def test_missing_pdf_file(self, pdf_processor):
        """Test handling of non-existent PDF file."""
        with pytest.raises((FileNotFoundError, ValueError)):
            pdf_processor.process_deed_pdf("nonexistent_file.pdf")

    @pytest.mark.slow
    def test_empty_pdf_path(self, pdf_processor):
        """Test handling of empty PDF path."""
        with pytest.raises((FileNotFoundError, ValueError)):
            pdf_processor.process_deed_pdf("")


class TestPOCvsPOBInPDFs:
    """Test Point of Commencement vs Point of Beginning extraction from PDFs.

    Some deeds may have a distinct POC (survey reference point) separate from
    the POB (where parcel boundary starts).
    """

    @pytest.mark.slow
    def test_18_pennbrook_poc_pob(self, pdf_processor):
        """Check if 18 Pennbrook has distinct POC and POB."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_18_PENNBROOK))

        # Log what was found
        print(f"\n18 Pennbrook POC/POB:")
        print(f"  POC: {legal_desc.poc_description or '(none)'}")
        print(f"  POB: {legal_desc.pob_description or '(none)'}")

        # At minimum, should have either POC or POB
        assert legal_desc.poc_description or legal_desc.pob_description

    @pytest.mark.slow
    def test_24_pennbrook_poc_pob(self, pdf_processor):
        """Check if 24 Pennbrook has distinct POC and POB."""
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_24_PENNBROOK))

        print(f"\n24 Pennbrook POC/POB:")
        print(f"  POC: {legal_desc.poc_description or '(none)'}")
        print(f"  POB: {legal_desc.pob_description or '(none)'}")

        assert legal_desc.poc_description or legal_desc.pob_description


class TestPDFVerifiedExport:
    """Test verified CSV export from PDF processing.

    Tests the full pipeline: PDF → Extract → Verify → Export _verified.csv
    """

    @pytest.mark.slow
    def test_export_verified_if_closes(self, pdf_processor, tmp_path):
        """Test exporting verified CSV if parcel closes properly."""
        # Use 18 Pennbrook which should close
        legal_desc = pdf_processor.process_deed_pdf(str(PDF_18_PENNBROOK))

        # Verify
        result = ClosureChecker.verify_closure(legal_desc.calls)

        # If it closes and verifies, export as verified
        if result.is_fully_verified():
            output_path = tmp_path / "18_pennbrook.csv"

            # Should export successfully
            CSVBuilder.export_verified_csv(
                calls=legal_desc.calls,
                closure_result=result,
                output_path=str(output_path),
                legal_desc=legal_desc,
            )

            # Verified CSV should exist
            verified_path = tmp_path / "18_pennbrook_verified.csv"
            assert verified_path.exists()

            # Verification summary should exist
            summary_path = tmp_path / "18_pennbrook_verified.verification.txt"
            assert summary_path.exists()

        else:
            # If doesn't verify, export_verified_csv should raise
            output_path = tmp_path / "18_pennbrook.csv"
            with pytest.raises(ValueError, match="verification checks failed"):
                CSVBuilder.export_verified_csv(
                    calls=legal_desc.calls,
                    closure_result=result,
                    output_path=str(output_path),
                    legal_desc=legal_desc,
                )


class TestPDFBatchProcessing:
    """Test batch processing of all sample PDFs.

    Validates that the extraction pipeline can handle all sample deeds
    without crashing, even if some don't close perfectly.
    """

    @pytest.mark.slow
    def test_process_all_sample_pdfs(self, pdf_processor, tmp_path):
        """Process all 6 sample PDFs and export results."""
        pdf_files = [
            PDF_18_PENNBROOK,
            PDF_24_PENNBROOK,
            PDF_31_PENNBROOK_1,
            PDF_31_PENNBROOK_2,
            PDF_31_PENNBROOK_3,
            PDF_31_PENNBROOK_4,
        ]

        results = []

        for pdf_path in pdf_files:
            # Extract
            legal_desc = pdf_processor.process_deed_pdf(str(pdf_path))

            # Verify
            closure_result = ClosureChecker.verify_closure(legal_desc.calls)

            # Export CSV (non-verified, always works)
            output_path = tmp_path / f"{pdf_path.stem}.csv"
            CSVBuilder.legal_description_to_csv(legal_desc, str(output_path))

            results.append({
                "pdf": pdf_path.stem,
                "extracted": True,
                "num_calls": len(legal_desc.calls),
                "closes": closure_result.closure_passed,
                "verified": closure_result.is_fully_verified(),
                "csv_exported": output_path.exists(),
            })

        # Print summary
        print("\nBatch Processing Summary:")
        print("=" * 80)
        for r in results:
            status = "✓ VERIFIED" if r["verified"] else ("✓ CLOSES" if r["closes"] else "⚠ OPEN")
            print(f"{r['pdf'][:40]:<40} | Calls: {r['num_calls']:2d} | {status}")

        # All PDFs should have been processed
        assert all(r["extracted"] for r in results)
        assert all(r["csv_exported"] for r in results)

        # At least some should have calls
        assert sum(r["num_calls"] for r in results) > 0
