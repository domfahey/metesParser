"""Constants for metes and bounds deed parsing."""

PERMANENT_MONUMENTS: frozenset[str] = frozenset(
    {
        "iron_rod",
        "iron_pin",
        "iron_pipe",
        "concrete",
        "brass_cap",
        "rebar",
        "capped_pin",
        "capped_rod",
        "railroad_spike",
    }
)
PRIOR_CONVEYANCE_SIGNALS: frozenset[str] = frozenset(
    {
        "BEING the same premises",
        "previously conveyed",
        "derived from",
        "by deed dated",
        "recorded in Book",
        "Instrument Number",
    }
)
