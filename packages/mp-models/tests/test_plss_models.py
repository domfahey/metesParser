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


@pytest.mark.parametrize("section", [0, 37, True, 1.5])
def test_invalid_section_numbers_cannot_be_coerced(section):
    with pytest.raises(ValueError):
        PLSSSectionKey(
            principal_meridian="Supplied meridian",
            township=1,
            township_direction="N",
            range=2,
            range_direction="W",
            section=section,
        )
