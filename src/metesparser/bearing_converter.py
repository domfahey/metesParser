"""Bearing conversion utilities for metes and bounds parsing.

Converts between quadrant bearings (e.g., N 56°40' E) and azimuths (degrees from North, clockwise).
Also handles curve calculations and coordinate deltas.
"""

import math
import re

from .models import DeedCall, Point


class BearingConverter:
    """Convert bearings and calculate coordinate deltas."""

    # Regex for parsing quadrant bearings: (N|S) degrees [minutes] [seconds] (E|W)
    # Degrees: 0-90, Minutes: 0-59, Seconds: 0-59
    QUADRANT_PATTERN = re.compile(
        r"(N|S)\s*([0-8]?[0-9]|90)[°º]\s*(?:([0-5]?[0-9])['′])?\s*(?:([0-5]?[0-9](?:\.\d+)?)[\"″])?\s*(E|W)",
        re.IGNORECASE,
    )

    @classmethod
    def parse_quadrant_bearing(cls, bearing_text: str) -> tuple[str, float, str] | None:
        """Parse a quadrant bearing string.

        Args:
            bearing_text: Bearing string like "S 56°40'30\" W" or "N 45° E"

        Returns:
            Tuple of (cardinal1, degrees, cardinal2) or None if not parseable
            Example: ("S", 56.675, "W")
        """
        match = cls.QUADRANT_PATTERN.search(bearing_text)
        if not match:
            return None

        cardinal1 = match.group(1).upper()
        degrees = float(match.group(2))
        minutes = float(match.group(3)) if match.group(3) else 0.0
        seconds = float(match.group(4)) if match.group(4) else 0.0
        cardinal2 = match.group(5).upper()

        # Validate ranges (redundant check since regex constrains, but defensive)
        if not (0 <= degrees <= 90):
            return None
        if not (0 <= minutes < 60):
            return None
        if not (0 <= seconds < 60):
            return None

        # Convert DMS to decimal degrees
        decimal_degrees = degrees + (minutes / 60.0) + (seconds / 3600.0)

        # Validate result is within quadrant range
        if decimal_degrees > 90.0:
            return None

        return (cardinal1, decimal_degrees, cardinal2)

    @classmethod
    def quadrant_to_azimuth(cls, cardinal1: str, degrees: float, cardinal2: str) -> float:
        """Convert quadrant bearing to azimuth (degrees clockwise from North).

        Convention:
        - N θ E → az = θ
        - S θ E → az = 180 - θ
        - S θ W → az = 180 + θ
        - N θ W → az = 360 - θ

        Args:
            cardinal1: First cardinal (N or S)
            degrees: Angle in degrees
            cardinal2: Second cardinal (E or W)

        Returns:
            Azimuth in degrees [0, 360)
        """
        if cardinal1 == "N" and cardinal2 == "E":
            azimuth = degrees
        elif cardinal1 == "S" and cardinal2 == "E":
            azimuth = 180.0 - degrees
        elif cardinal1 == "S" and cardinal2 == "W":
            azimuth = 180.0 + degrees
        elif cardinal1 == "N" and cardinal2 == "W":
            azimuth = 360.0 - degrees
        else:
            # Provide helpful error message for invalid combinations
            valid_combos = "N-E, S-E, S-W, N-W"
            raise ValueError(
                f"Invalid cardinal combination: {cardinal1}-{cardinal2}. "
                f"Valid combinations are: {valid_combos}"
            )

        # Normalize to [0, 360)
        return azimuth % 360.0

    @classmethod
    def bearing_to_azimuth(cls, bearing_text: str) -> float | None:
        """Convert a bearing string to azimuth.

        Args:
            bearing_text: Bearing like "S 56°40'30\" W"

        Returns:
            Azimuth in degrees or None if unparseable
        """
        parsed = cls.parse_quadrant_bearing(bearing_text)
        if parsed is None:
            return None

        cardinal1, degrees, cardinal2 = parsed
        return cls.quadrant_to_azimuth(cardinal1, degrees, cardinal2)

    @classmethod
    def azimuth_to_quadrant(cls, azimuth: float) -> str:
        """Convert azimuth to quadrant bearing string.

        Args:
            azimuth: Azimuth in degrees [0, 360)

        Returns:
            Quadrant bearing string like "N 45°30' E"
        """
        # Normalize
        azimuth = azimuth % 360.0

        # Determine quadrant and angle
        if 0 <= azimuth <= 90:
            # N θ E
            angle = azimuth
            cardinal1, cardinal2 = "N", "E"
        elif 90 < azimuth <= 180:
            # S θ E
            angle = 180.0 - azimuth
            cardinal1, cardinal2 = "S", "E"
        elif 180 < azimuth <= 270:
            # S θ W
            angle = azimuth - 180.0
            cardinal1, cardinal2 = "S", "W"
        else:  # 270 < azimuth < 360
            # N θ W
            angle = 360.0 - azimuth
            cardinal1, cardinal2 = "N", "W"

        # Convert to DMS
        degrees = int(angle)
        remainder = (angle - degrees) * 60
        minutes = int(remainder)
        seconds = (remainder - minutes) * 60

        # Handle rounding edge case: if seconds rounds to 60, carry to minutes
        if seconds >= 59.95:  # Will round to 60.0 in display
            seconds = 0.0
            minutes += 1
            if minutes >= 60:  # Carry to degrees
                minutes = 0
                degrees += 1

        if seconds < 0.5:
            return f"{cardinal1} {degrees}°{minutes:02d}' {cardinal2}"
        else:
            return f"{cardinal1} {degrees}°{minutes:02d}'{seconds:04.1f}\" {cardinal2}"

    @classmethod
    def calculate_deltas(cls, azimuth: float, distance_ft: float) -> tuple[float, float]:
        """Calculate dx, dy deltas from azimuth and distance.

        Formula:
            dx = distance * sin(azimuth)
            dy = distance * cos(azimuth)

        Args:
            azimuth: Azimuth in degrees (clockwise from North)
            distance_ft: Distance in feet

        Returns:
            Tuple of (dx, dy) in feet
        """
        azimuth_rad = math.radians(azimuth)
        dx = distance_ft * math.sin(azimuth_rad)
        dy = distance_ft * math.cos(azimuth_rad)
        return (dx, dy)

    @classmethod
    def calculate_curve_properties(
        cls,
        radius_ft: float,
        delta_deg: float | None = None,
        arc_length_ft: float | None = None,
    ) -> dict:
        """Calculate curve properties from radius and either delta or arc length.

        Given R and Δ:
            L = R * Δ (radians)
            chord = 2R * sin(Δ/2)

        Given R and L:
            Δ = L / R (radians)
            chord = 2R * sin(Δ/2)

        Args:
            radius_ft: Radius in feet (must be > 0)
            delta_deg: Central angle in degrees (optional, 0-360)
            arc_length_ft: Arc length in feet (optional)

        Returns:
            Dict with keys: radius_ft, delta_deg, arc_length_ft, chord_length_ft

        Raises:
            ValueError: If radius <= 0, delta > 360, or neither delta/arc provided
        """
        # Critical: Validate radius to prevent division by zero
        if radius_ft <= 0:
            raise ValueError(f"Radius must be positive, got {radius_ft}")

        # Initialize delta_rad to prevent UnboundLocalError
        delta_rad = 0.0

        if delta_deg is not None:
            # Validate delta angle range
            if not (0 <= delta_deg <= 360):
                raise ValueError(f"Delta angle must be 0-360 degrees, got {delta_deg}")

            # Given R and Δ
            delta_rad = math.radians(delta_deg)
            arc = radius_ft * delta_rad
            chord = 2 * radius_ft * math.sin(delta_rad / 2)
        elif arc_length_ft is not None:
            # Validate arc length
            if arc_length_ft < 0:
                raise ValueError(f"Arc length must be non-negative, got {arc_length_ft}")

            # Given R and L
            delta_rad = arc_length_ft / radius_ft  # Safe: radius_ft > 0
            delta_deg = math.degrees(delta_rad)

            # Validate computed delta
            if delta_deg > 360:
                raise ValueError(
                    f"Computed delta angle {delta_deg:.2f}° exceeds 360° "
                    f"(arc={arc_length_ft}, radius={radius_ft})"
                )

            arc = arc_length_ft
            chord = 2 * radius_ft * math.sin(delta_rad / 2)
        else:
            raise ValueError("Must provide either delta_deg or arc_length_ft")

        return {
            "radius_ft": radius_ft,
            "delta_deg": delta_deg,
            "delta_rad": delta_rad,
            "arc_length_ft": arc,
            "chord_length_ft": chord,
        }

    @classmethod
    def calculate_chord_bearing(
        cls,
        tangent_azimuth: float,
        delta_deg: float,
        curve_dir: str,
    ) -> float:
        """Calculate chord bearing from tangent bearing and curve properties.

        The chord bearing is the tangent bearing rotated by ±(Δ/2) toward the curve.

        Args:
            tangent_azimuth: Azimuth of tangent at PC (degrees)
            delta_deg: Central angle (degrees)
            curve_dir: "left" or "right"

        Returns:
            Chord bearing azimuth (degrees)
        """
        half_delta = delta_deg / 2.0

        if curve_dir == "left":
            # Rotate counterclockwise
            chord_azimuth = tangent_azimuth - half_delta
        else:  # right
            # Rotate clockwise
            chord_azimuth = tangent_azimuth + half_delta

        return chord_azimuth % 360.0

    @classmethod
    def compute_curve_endpoint(
        cls,
        start_point: Point,
        tangent_azimuth: float,
        radius_ft: float,
        delta_deg: float,
        curve_dir: str,
    ) -> Point:
        """Compute the endpoint of a curve given start point and curve parameters.

        This is an approximation using the chord. For precise work, use more
        sophisticated curve traversal methods.

        Args:
            start_point: Starting point
            tangent_azimuth: Tangent azimuth at start (degrees)
            radius_ft: Curve radius (feet, must be > 0)
            delta_deg: Central angle (degrees, 0-360)
            curve_dir: "left" or "right"

        Returns:
            Endpoint of curve

        Raises:
            ValueError: If radius <= 0 or delta out of range
        """
        # Validate inputs (calculate_curve_properties will validate internally)
        # But we add explicit check here for clarity
        if radius_ft <= 0:
            raise ValueError(f"Radius must be positive, got {radius_ft}")

        # Calculate chord - this will also validate delta_deg
        curve_props = cls.calculate_curve_properties(radius_ft, delta_deg=delta_deg)
        chord_length = curve_props["chord_length_ft"]

        # Calculate chord bearing
        chord_azimuth = cls.calculate_chord_bearing(tangent_azimuth, delta_deg, curve_dir)

        # Calculate endpoint using chord
        dx, dy = cls.calculate_deltas(chord_azimuth, chord_length)

        return Point(x=start_point.x + dx, y=start_point.y + dy)

    @classmethod
    def enrich_call_with_azimuth(cls, call: DeedCall) -> DeedCall:
        """Add azimuth to a DeedCall if bearing_quadrant is present.

        Args:
            call: DeedCall object

        Returns:
            Updated DeedCall with azimuth calculated
        """
        if call.bearing_quadrant and call.bearing_azimuth_deg_from_north is None:
            azimuth = cls.bearing_to_azimuth(call.bearing_quadrant)
            if azimuth is not None:
                call.bearing_azimuth_deg_from_north = azimuth

        return call
