"""Reference identity must be explicit, not a guessed township label."""

import pytest
from mp_models.plss import PLSSSectionKey


def test_principal_meridian_is_required():
    with pytest.raises(ValueError, match="principal_meridian"):
        PLSSSectionKey.model_validate(
            {
                "township": 1,
                "township_direction": "N",
                "range": 2,
                "range_direction": "W",
                "section": 3,
            }
        )


@pytest.mark.parametrize(
    ("section", "expected_match"),
    [
        (0, "greater than or equal to 1"),
        (37, "less than or equal to 36"),
        (True, "valid integer"),
        (1.5, "valid integer"),
    ],
)
def test_invalid_section_numbers_cannot_be_coerced(section, expected_match):
    with pytest.raises(ValueError, match=expected_match):
        PLSSSectionKey(
            principal_meridian="Supplied meridian",
            township=1,
            township_direction="N",
            range=2,
            range_direction="W",
            section=section,
        )


def test_plss_reference_dataset_requires_timezone_aware_retrieved_at():
    from mp_models.plot import MapSource, PlotScene
    from mp_models.plss import PLSSCorner, PLSSReferenceDataset, PLSSSectionReference

    sec = PLSSSectionKey(
        principal_meridian="Fifth Principal Meridian",
        township=1,
        township_direction="N",
        range=2,
        range_direction="W",
        section=3,
    )
    scene = PlotScene(
        id="s1", name="Grid", kind="projected", crs="EPSG:3857", units="m", basis="grid"
    )
    ref = PLSSSectionReference(
        id="r1",
        section=sec,
        subdivision_class="rectangular",
        corners=(PLSSCorner(name="SW", xy=(0, 0), source_id="src1"),),
    )
    # Timezone-aware Z timestamp accepted.
    ok = PLSSReferenceDataset(
        id="ds1",
        version="1.0",
        authority_citation="County",
        scene=scene,
        source=MapSource(
            id="src1", label="L", sha256="a" * 64, retrieved_at="2026-01-15T12:00:00Z"
        ),
        references=(ref,),
    )
    assert ok.source.retrieved_at == "2026-01-15T12:00:00Z"

    # Naive timestamp without timezone rejected.
    with pytest.raises(ValueError, match="must include timezone"):
        PLSSReferenceDataset(
            id="ds1",
            version="1.0",
            authority_citation="County",
            scene=scene,
            source=MapSource(
                id="src1", label="L", sha256="a" * 64, retrieved_at="2026-01-15T12:00:00"
            ),
            references=(ref,),
        )
