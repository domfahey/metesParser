"""Shared regex patterns for parsing metes and bounds legal descriptions.

This module centralizes regex patterns used across multiple parsing modules
to avoid duplication and ensure consistency.
"""

import re

# Cardinal direction pattern matching both long-form and abbreviated cardinal points
# Matches: north, south, east, west, northeast, northwest, southeast, southwest
# Also matches: NE, NW, SE, SW (abbreviations)
# Also matches: northerly, northwardly, etc. (directional suffixes)
CARDINAL_ONLY_PATTERN = re.compile(
    r"(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?",
    re.IGNORECASE,
)

# Unit token pattern for distance measurements
# Matches: feet, foot, ft, poles, rods, perches, chains, links,
#          varas, arpents, toises, furlongs, meters, miles
UNIT_TOKEN = (
    r"(?:feet|foot|ft|poles?|rods?|perches?|chains?|links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
)
