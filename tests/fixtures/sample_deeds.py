"""Sample legal description texts for testing.

Real-world and synthetic legal descriptions for testing the full pipeline.
"""

# ===========================================================================
# Real Parcels (Based on actual deeds)
# ===========================================================================

PENNBROOK_18 = """
BEGINNING at a point in the division line between Lots 46 and 47,
said point being in the southwesterly line of Concord Drive;
THENCE South 33 degrees 20 minutes East 60.00 feet along said
southwesterly line of Concord Drive to a point in said division line;
THENCE South 56 degrees 40 minutes West 125.00 feet along the
division line between Lots 46 and 47 to the corner to Lot 50;
THENCE North 33 degrees 20 minutes West 60.00 feet along the
division line between Lots 46 and 50;
THENCE North 56 degrees 40 minutes East 125.00 feet along the
division line between Lots 46 and 47 to the POINT OF BEGINNING.
"""

PENNBROOK_31 = """
BEGINNING at a point;
THENCE North 56 degrees 40 minutes East 125.26 feet;
THENCE South 33 degrees 20 minutes East 60.00 feet;
THENCE South 56 degrees 40 minutes West 100.00 feet;
THENCE South 33 degrees 20 minutes East 40.00 feet;
THENCE North 56 degrees 40 minutes West 25.26 feet to the POINT OF BEGINNING.
"""

# ===========================================================================
# Simple Geometric Shapes
# ===========================================================================

SQUARE_100FT = """
BEGINNING at a point;
THENCE North 0 degrees East 100 feet;
THENCE North 90 degrees East 100 feet;
THENCE South 0 degrees East 100 feet;
THENCE South 90 degrees West 100 feet to the POINT OF BEGINNING.
"""

RECTANGLE_60X125 = """
BEGINNING at a point;
THENCE North 33 degrees 20 minutes East 60.00 feet along the south line to a point;
THENCE South 56 degrees 40 minutes West 125.00 feet along the division line to a corner;
THENCE South 33 degrees 20 minutes West 60.00 feet along the west line;
THENCE North 56 degrees 40 minutes East 125.00 feet to the POINT OF BEGINNING.
"""

TRIANGLE_RIGHT = """
BEGINNING at a point;
THENCE North 45 degrees East 100 feet;
THENCE South 45 degrees East 100 feet;
THENCE South 45 degrees West 141.42 feet to the POINT OF BEGINNING.
"""

# ===========================================================================
# Parcels with Curves
# ===========================================================================

PARCEL_WITH_CURVE = """
BEGINNING at a point;
THENCE North 0 degrees East 100 feet;
THENCE along a curve to the right, having a radius of 50.00 feet,
a delta angle of 90 degrees 00 minutes, and an arc length of 78.54 feet;
THENCE South 0 degrees East 50 feet to the POINT OF BEGINNING.
"""

CURVE_NO_BEARING = """
BEGINNING at an iron pin;
THENCE along a curve to the left having a radius of 100.00 feet
and a delta angle of 45 degrees 00 minutes to an iron pin;
THENCE South 45 degrees West 100 feet to the POINT OF BEGINNING.
"""

# ===========================================================================
# Incomplete/Meander Calls
# ===========================================================================

PARCEL_WITH_MEANDER = """
BEGINNING at a point;
THENCE North 45 degrees East 100 feet;
THENCE meandering along the stream approximately 150 feet;
THENCE South 45 degrees West 100 feet to the POINT OF BEGINNING.
"""

CARDINAL_ONLY = """
BEGINNING at a point;
THENCE North 45 degrees East 100 feet;
THENCE southwesterly 75 feet;
THENCE North 45 degrees West 100 feet to the POINT OF BEGINNING.
"""

# ===========================================================================
# Mixed Units
# ===========================================================================

MIXED_FEET_AND_POLES = """
BEGINNING at a point;
THENCE North 45 degrees East 100 feet;
THENCE South 45 degrees East 10 poles;
THENCE South 45 degrees West 100 feet;
THENCE North 45 degrees West 10 poles to the POINT OF BEGINNING.
"""

# ===========================================================================
# OCR Errors (for testing correction)
# ===========================================================================

WITH_OCR_ERRORS = """
BEGINNING at a point;
THENCE 5outh 56 0 40' We5t 125 feet;
THENCE NOrth 33 0 20' Ea5t 60 feet to the POINT OF BEGINNING.
"""

LINE_WRAPPING = """
BEGINNING at a point;
THENCE North 45 degrees East 100 feet along the div-
ision line between Lots 1 and 2 to
a point in the north line;
THENCE South 45 degrees East 100 feet to the POINT OF BEGINNING.
"""

# ===========================================================================
# Edge Cases
# ===========================================================================

VERY_SMALL_PARCEL = """
BEGINNING at a point;
THENCE North 0 degrees East 10 feet;
THENCE North 90 degrees East 10 feet;
THENCE South 0 degrees East 10 feet;
THENCE South 90 degrees West 10 feet to the POINT OF BEGINNING.
Containing 100 square feet.
"""

WITH_STATED_AREA = """
BEGINNING at a point;
THENCE North 0 degrees East 100 feet;
THENCE North 90 degrees East 100 feet;
THENCE South 0 degrees East 100 feet;
THENCE South 90 degrees West 100 feet to the POINT OF BEGINNING.
Containing 10,000 square feet, more or less.
"""

OPEN_TRAVERSE = """
BEGINNING at a point;
THENCE North 0 degrees East 100 feet;
THENCE North 90 degrees East 100 feet.
"""

# ===========================================================================
# Malformed Input
# ===========================================================================

EMPTY_TEXT = ""

NO_THENCE = "BEGINNING at a point in the center of Main Street."

INVALID_BEARING = """
BEGINNING at a point;
THENCE North 999 degrees East 100 feet;
THENCE South 45 degrees West 100 feet to the POINT OF BEGINNING.
"""
