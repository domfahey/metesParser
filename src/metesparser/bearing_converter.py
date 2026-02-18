"""Bearing conversion utilities for metes and bounds parsing.

Converts between quadrant bearings (e.g., N 56°40' E) and azimuths (degrees from North, clockwise).
Also handles curve calculations and coordinate deltas.
"""

import math
import re

from .models import DeedCall, Point


class BearingConverter:
    """Convert bearings and calculate coordinate deltas."""

    QUADRANT_PATTERN = re.compile(
        r"(N|S)\s*([0-8]?[0-9]|90)[°º]\s*(?:([0-5]?[0-9])['′])?,?\s*(?:([0-5]?[0-9](?:\.\d+)?)[\"″])?\s*(E|W)",
        re.IGNORECASE,
    )

    COMPASS_POINTS: dict[str, float] = {
        "north": 0.0,
        "north by east": 11.25,
        "north-northeast": 22.5,
        "northeast by north": 33.75,
        "northeast": 45.0,
        "northeast by east": 56.25,
        "east-northeast": 67.5,
        "east by north": 78.75,
        "east": 90.0,
        "east by south": 101.25,
        "east-southeast": 112.5,
        "southeast by east": 123.75,
        "southeast": 135.0,
        "southeast by south": 146.25,
        "south-southeast": 157.5,
        "south by east": 168.75,
        "south": 180.0,
        "south by west": 191.25,
        "south-southwest": 202.5,
        "southwest by south": 213.75,
        "southwest": 225.0,
        "southwest by west": 236.25,
        "west-southwest": 247.5,
        "west by south": 258.75,
        "west": 270.0,
        "west by north": 281.25,
        "west-northwest": 292.5,
        "northwest by west": 303.75,
        "northwest": 315.0,
        "northwest by north": 326.25,
        "north-northwest": 337.5,
        "north by west": 348.75,
    }

    @classmethod
    def compass_point_to_azimuth(cls, compass_point: str) -> float | None:
        """Convert a 32-point compass direction to azimuth.

        Args:
            compass_point: Compass point name (e.g., "North by East", "Northeast")

        Returns:
            Azimuth in degrees or None if not a recognized compass point
        """
        normalized = compass_point.strip().lower()
        return cls.COMPASS_POINTS.get(normalized)

    @classmethod
    def parse_packed_dms(cls, value: float) -> float:
        """Convert packed DMS value to decimal degrees.

        Packed DMS format: degrees.MMSS where MM=minutes, SS=seconds.
        Example: 46.1631 → 46°16'31" → 46.275278°

        Args:
            value: Packed DMS value (e.g., 46.1631)

        Returns:
            Decimal degrees

        Raises:
            ValueError: If minutes >= 60 or seconds >= 60
        """
        degrees = int(value)
        frac = value - degrees

        minutes_seconds = frac * 100
        minutes = int(round(minutes_seconds * 100) // 100)
        seconds = round((minutes_seconds - minutes) * 100, 4)

        if minutes >= 60:
            raise ValueError(f"Invalid packed DMS: minutes={minutes} (must be 0-59)")
        if seconds >= 60:
            raise ValueError(f"Invalid packed DMS: seconds={seconds:.0f} (must be 0-59)")

        return degrees + minutes / 60.0 + seconds / 3600.0

    @classmethod
    def degree_of_curvature_to_radius(cls, degree_of_curve: float) -> float:
        """Convert degree of curvature to radius using arc definition.

        The degree of curvature is the central angle subtended by a 100-ft arc.
        Formula: R = 5729.578 / D°

        Args:
            degree_of_curve: Degree of curvature (must be > 0)

        Returns:
            Radius in feet

        Raises:
            ValueError: If degree_of_curve is zero or negative
        """
        if degree_of_curve <= 0:
            raise ValueError(
                f"Degree of curvature must be positive and non-zero, got {degree_of_curve}"
            )
        return 5729.578 / degree_of_curve

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

        if not (0 <= degrees <= 90):
            return None
        if not (0 <= minutes < 60):
            return None
        if not (0 <= seconds < 60):
            return None

        decimal_degrees = degrees + (minutes / 60.0) + (seconds / 3600.0)

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
            valid_combos = "N-E, S-E, S-W, N-W"
            raise ValueError(
                f"Invalid cardinal combination: {cardinal1}-{cardinal2}. "
                f"Valid combinations are: {valid_combos}"
            )

        return azimuth % 360.0

    _DUE_CARDINAL_RE = re.compile(
        r"^\s*due\s+(north|south|east|west|n|s|e|w)\s*$",
        re.IGNORECASE,
    )

    _DUE_CARDINAL_MAP: dict[str, float] = {
        "north": 0.0,
        "n": 0.0,
        "south": 180.0,
        "s": 180.0,
        "east": 90.0,
        "e": 90.0,
        "west": 270.0,
        "w": 270.0,
    }

    @classmethod
    def due_cardinal_to_azimuth(cls, direction: str) -> float | None:
        """Convert a 'due {cardinal}' direction to azimuth.

        Recognises 'due North', 'due S', 'Due EAST', etc. (case-insensitive).
        Returns ``None`` when *direction* is not a valid due-cardinal string.

        Args:
            direction: Direction string, e.g. "due North" or "due W"

        Returns:
            Azimuth in degrees (0.0, 90.0, 180.0, or 270.0) or None
        """
        m = cls._DUE_CARDINAL_RE.match(direction)
        if m is None:
            return None
        return cls._DUE_CARDINAL_MAP[m.group(1).lower()]

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
        azimuth = azimuth % 360.0

        if 0 <= azimuth <= 90:
            angle = azimuth
            cardinal1, cardinal2 = "N", "E"
        elif 90 < azimuth <= 180:
            angle = 180.0 - azimuth
            cardinal1, cardinal2 = "S", "E"
        elif 180 < azimuth <= 270:
            angle = azimuth - 180.0
            cardinal1, cardinal2 = "S", "W"
        else:
            angle = 360.0 - azimuth
            cardinal1, cardinal2 = "N", "W"

        degrees = int(angle)
        remainder = (angle - degrees) * 60
        minutes = int(remainder)
        seconds = (remainder - minutes) * 60

        if seconds >= 59.95:
            seconds = 0.0
            minutes += 1
            if minutes >= 60:
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
    ) -> dict[str, float | None]:
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
        if radius_ft <= 0:
            raise ValueError(f"Radius must be positive, got {radius_ft}")

        delta_rad = 0.0

        if delta_deg is not None:
            if not (0 <= delta_deg <= 360):
                raise ValueError(f"Delta angle must be 0-360 degrees, got {delta_deg}")

            delta_rad = math.radians(delta_deg)
            arc = radius_ft * delta_rad
            chord = 2 * radius_ft * math.sin(delta_rad / 2)
        elif arc_length_ft is not None:
            if arc_length_ft < 0:
                raise ValueError(f"Arc length must be non-negative, got {arc_length_ft}")

            delta_rad = arc_length_ft / radius_ft
            delta_deg = math.degrees(delta_rad)

            if delta_deg > 360:
                raise ValueError(
                    f"Computed delta angle {delta_deg:.2f}° exceeds 360° "
                    f"(arc={arc_length_ft}, radius={radius_ft})"
                )

            arc = arc_length_ft
            chord = 2 * radius_ft * math.sin(delta_rad / 2)
        else:
            raise ValueError("Must provide either delta_deg or arc_length_ft")

        cos_half = math.cos(delta_rad / 2)
        if abs(cos_half) < 1e-10:
            tangent_length_ft = float("inf")
            external_distance_ft = float("inf")
        else:
            tangent_length_ft = radius_ft * math.tan(delta_rad / 2)
            external_distance_ft = radius_ft * (1.0 / cos_half - 1.0)
        middle_ordinate_ft = radius_ft * (1.0 - math.cos(delta_rad / 2))

        return {
            "radius_ft": radius_ft,
            "delta_deg": delta_deg,
            "delta_rad": delta_rad,
            "arc_length_ft": arc,
            "chord_length_ft": chord,
            "tangent_length_ft": tangent_length_ft,
            "external_distance_ft": external_distance_ft,
            "middle_ordinate_ft": middle_ordinate_ft,
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

        chord_azimuth = (
            tangent_azimuth - half_delta if curve_dir == "left" else tangent_azimuth + half_delta
        )

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
        if radius_ft <= 0:
            raise ValueError(f"Radius must be positive, got {radius_ft}")

        curve_props = cls.calculate_curve_properties(radius_ft, delta_deg=delta_deg)
        chord_length = curve_props["chord_length_ft"]
        if chord_length is None:
            raise ValueError("Curve chord length could not be calculated.")

        chord_azimuth = cls.calculate_chord_bearing(tangent_azimuth, delta_deg, curve_dir)
        dx, dy = cls.calculate_deltas(chord_azimuth, chord_length)

        return Point(x=start_point.x + dx, y=start_point.y + dy)

    @classmethod
    def calculate_missing_curve_elements(
        cls,
        radius_ft: float | None = None,
        delta_deg: float | None = None,
        arc_length_ft: float | None = None,
        chord_length_ft: float | None = None,
    ) -> dict[str, float]:
        """Calculate missing curve elements from provided values.

        Given at least 2 of: radius, delta, arc length, chord length,
        compute the missing elements.

        Args:
            radius_ft: Curve radius in feet
            delta_deg: Central angle in degrees
            arc_length_ft: Arc length in feet
            chord_length_ft: Chord length in feet

        Returns:
            Dict with all curve elements: radius_ft, delta_deg,
            arc_length_ft, chord_length_ft, tangent_length_ft

        Raises:
            ValueError: If fewer than 2 elements provided
        """
        provided = sum(
            1 for v in [radius_ft, delta_deg, arc_length_ft, chord_length_ft] if v is not None
        )
        if provided < 2:
            raise ValueError(f"Need at least two curve elements, got {provided}")

        if delta_deg is not None and delta_deg == 0:
            raise ValueError("Delta angle must be non-zero for curve element calculation")

        if radius_ft is not None and delta_deg is not None:
            pass
        elif radius_ft is not None and arc_length_ft is not None:
            delta_deg = math.degrees(arc_length_ft / radius_ft)
        elif radius_ft is not None and chord_length_ft is not None:
            ratio = chord_length_ft / (2 * radius_ft)
            if abs(ratio) > 1:
                raise ValueError(
                    f"Chord ({chord_length_ft} ft) exceeds diameter ({2 * radius_ft} ft)"
                )
            half_delta = math.asin(ratio)
            delta_deg = math.degrees(2 * half_delta)
        elif arc_length_ft is not None and delta_deg is not None:
            delta_rad = math.radians(delta_deg)
            radius_ft = arc_length_ft / delta_rad
        elif chord_length_ft is not None and delta_deg is not None:
            delta_rad = math.radians(delta_deg)
            radius_ft = chord_length_ft / (2 * math.sin(delta_rad / 2))
        elif arc_length_ft is not None and chord_length_ft is not None:
            if arc_length_ft <= 0:
                raise ValueError(f"Arc length must be positive, got {arc_length_ft}")
            if chord_length_ft >= arc_length_ft:
                raise ValueError(
                    f"Chord ({chord_length_ft} ft) must be less than arc ({arc_length_ft} ft)"
                )
            # Approximate delta from arc/chord ratio
            # For small angles: L/C ≈ delta / (2*sin(delta/2))
            delta_rad = 2 * math.sqrt(6 * (1 - chord_length_ft / arc_length_ft))
            delta_deg = math.degrees(delta_rad)
            radius_ft = arc_length_ft / delta_rad

        # Compute all elements from radius and delta
        delta_rad = math.radians(delta_deg)  # type: ignore[arg-type]
        if arc_length_ft is None:
            arc_length_ft = radius_ft * delta_rad  # type: ignore[operator]
        if chord_length_ft is None:
            chord_length_ft = 2 * radius_ft * math.sin(delta_rad / 2)  # type: ignore[operator]
        cos_half = math.cos(delta_rad / 2)
        if abs(cos_half) < 1e-10:
            tangent_length_ft = float("inf")
            external_distance_ft = float("inf")
        else:
            tangent_length_ft = radius_ft * math.tan(delta_rad / 2)  # type: ignore[operator]
            external_distance_ft = radius_ft * (1.0 / cos_half - 1.0)  # type: ignore[operator]
        middle_ordinate_ft = radius_ft * (1.0 - math.cos(delta_rad / 2))  # type: ignore[operator]

        return {
            "radius_ft": radius_ft,  # type: ignore[dict-item]
            "delta_deg": delta_deg,  # type: ignore[dict-item]
            "arc_length_ft": arc_length_ft,
            "chord_length_ft": chord_length_ft,
            "tangent_length_ft": tangent_length_ft,
            "external_distance_ft": external_distance_ft,
            "middle_ordinate_ft": middle_ordinate_ft,
        }

    @classmethod
    def enrich_call_with_azimuth(cls, call: DeedCall) -> DeedCall:
        """Add azimuth to a DeedCall if bearing_quadrant is present.

        Also handles 'due {cardinal}' directions.

        Args:
            call: DeedCall object

        Returns:
            Updated DeedCall with azimuth calculated
        """
        if call.bearing_quadrant and call.bearing_azimuth_deg_from_north is None:
            azimuth = cls.bearing_to_azimuth(call.bearing_quadrant)
            if azimuth is not None:
                return call.model_copy(update={"bearing_azimuth_deg_from_north": azimuth})
        elif call.bearing_azimuth_deg_from_north is None and call.direction_text:
            due_az = cls.due_cardinal_to_azimuth(call.direction_text)
            if due_az is not None:
                updates: dict[str, object] = {
                    "bearing_azimuth_deg_from_north": due_az,
                }
                if call.notes and "incomplete" in call.notes:
                    updates["notes"] = None
                return call.model_copy(update=updates)

        return call
