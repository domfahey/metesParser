# Metes and Bounds Legal Description Reference

A comprehensive reference for reading, interpreting, and parsing legal descriptions found in deeds, mortgages, title documents, and survey plats — written from the perspective of an expert real estate attorney.

---

## Table of Contents

1. [Legal Description Systems Overview](#1-legal-description-systems-overview)
2. [Anatomy of a Metes and Bounds Description](#2-anatomy-of-a-metes-and-bounds-description)
3. [Bearings and Direction](#3-bearings-and-direction)
4. [Distance and Units of Measure](#4-distance-and-units-of-measure)
5. [Curves](#5-curves)
6. [Monuments and Markers](#6-monuments-and-markers)
7. [Point of Commencement vs Point of Beginning](#7-point-of-commencement-vs-point-of-beginning)
8. [Deed Language and Terminology](#8-deed-language-and-terminology)
9. [Water Boundaries and Meanders](#9-water-boundaries-and-meanders)
10. [Exception and Inclusion Clauses](#10-exception-and-inclusion-clauses)
11. [Public Land Survey System (PLSS) References](#11-public-land-survey-system-plss-references)
12. [Subdivision Lot and Block Descriptions](#12-subdivision-lot-and-block-descriptions)
13. [COGO and GIS Integration](#13-cogo-and-gis-integration)
14. [Common Abbreviations](#14-common-abbreviations)
15. [Historical and Archaic Descriptions](#15-historical-and-archaic-descriptions)
16. [Rules of Construction](#16-rules-of-construction)
17. [Common Pitfalls and Ambiguities](#17-common-pitfalls-and-ambiguities)
18. [Verification and Quality Checks](#18-verification-and-quality-checks)

---

## 1. Legal Description Systems Overview

There are three principal systems for legally describing real property in the United States. A single deed may employ one or more of these systems, and they frequently reference each other.

### 1.1 Metes and Bounds

The oldest system, inherited from English common law and used predominantly in the original 13 colonies and states that did not adopt the federal rectangular survey. A metes and bounds description traces the perimeter of a parcel by specifying a series of courses (direction + distance) beginning and ending at a defined point.

**States primarily using metes and bounds**: Connecticut, Delaware, Georgia, Hawaii, Kentucky, Maine, Maryland, Massachusetts, New Hampshire, New Jersey, New York, North Carolina, Pennsylvania, Rhode Island, South Carolina, Tennessee, Texas, Vermont, Virginia, West Virginia.

### 1.2 Public Land Survey System (PLSS)

The rectangular survey system established by the Land Ordinance of 1785. It divides land into townships (6 miles square), sections (1 mile square, 640 acres), and aliquot parts thereof. Used in 30 states, primarily those west of the Appalachians and admitted to the Union after independence.

### 1.3 Subdivision Lot and Block

A recorded plat map divides a larger tract into numbered lots within numbered blocks. The description references the recorded plat rather than reciting individual courses. Example: "Lot 11, Block 3 of Cole Subdivision, as recorded in Plat Book 14, Page 22, Boone County, Missouri."

### 1.4 Priority of Systems

When a deed contains multiple description methods that conflict, the general order of priority is:

1. **Natural monuments** (rivers, ridges, trees) — highest priority
2. **Artificial monuments** (iron pins, concrete markers, fences)
3. **Adjoining boundaries** (calls to abutter lines)
4. **Courses** (bearings/directions)
5. **Distances**
6. **Area/quantity** (acreage) — lowest priority

This hierarchy reflects the legal principle that monuments on the ground are more reliable than written measurements, and that area is the least reliable element of a legal description.

---

## 2. Anatomy of a Metes and Bounds Description

A complete metes and bounds description contains these elements, typically in this order:

### 2.1 Caption / Introductory Clause

Identifies the property in general terms, often including municipality, county, and state:

> "ALL THAT CERTAIN lot or piece of ground situate in the Township of Haddonfield, County of Camden, and State of New Jersey..."

### 2.2 Tie-In or Reference

Connects the description to a larger survey framework (a section corner, intersection, recorded plat, or prior deed):

> "...being known and designated as Lot 24 on a plan entitled 'Pennbrook Estates' prepared by Smith Engineering dated March 15, 1962..."

### 2.3 Point of Commencement (POC) — if applicable

A known reference point from which the surveyor traverses to reach the parcel boundary:

> "COMMENCING at the intersection of the centerline of Main Street and the southerly line of Oak Avenue..."

### 2.4 Tie-In Calls — if applicable

One or more courses from the POC to the Point of Beginning. These are not boundary lines of the parcel; they merely locate where the boundary begins:

> "...thence along the centerline of Main Street South 45°30'00" East 200.00 feet to a point, said point being the POINT OF BEGINNING..."

### 2.5 Point of Beginning (POB)

The starting point of the actual parcel boundary. Every course in the description ultimately returns to this point to close the traverse:

> "BEGINNING at an iron pin found in the southerly right-of-way line of Pennbrook Drive, said pin being located South 56°40'30" West, 200.00 feet from the intersection of said right-of-way line with the westerly right-of-way line of Maple Avenue..."

### 2.6 Courses (Calls)

The body of the description — a sequential series of courses, each specifying:
- **Direction** (bearing or cardinal direction)
- **Distance** (length in feet, chains, or other units)
- **Along** reference (what the line runs along, e.g., "along lands of Smith")
- **To** reference (what the line terminates at, e.g., "to an iron pin set")

> "thence along the southerly line of Pennbrook Drive North 56°40'30" East 100.00 feet to an iron pin found;"

### 2.7 Closure Call

The final course returns to the Point of Beginning:

> "thence South 33°19'30" East 75.00 feet to the point and place of BEGINNING."

### 2.8 Area Statement

Many descriptions conclude with a stated area:

> "CONTAINING 7,500 square feet, or 0.1722 acres, more or less."

The phrase "more or less" is legally significant — it indicates the area is approximate and subordinate to the metes and bounds courses.

### 2.9 Exception Clauses

If portions are excluded from the conveyance:

> "EXCEPTING THEREFROM the northerly 10 feet thereof heretofore conveyed to the Township for road widening purposes by deed dated..."

### 2.10 Recital of Prior Conveyance

> "BEING the same premises which John Smith and Mary Smith, his wife, by deed dated June 15, 1985, and recorded in the Office of the Recorder of Deeds in and for Camden County in Deed Book 4520, Page 217, granted and conveyed unto Robert Jones."

---

## 3. Bearings and Direction

### 3.1 Quadrant Bearing System

The standard system used in modern metes and bounds descriptions. A bearing specifies the angle of departure from either north or south, toward either east or west. This divides the compass into four quadrants.

**Format**: `[N or S] [degrees]°[minutes]'[seconds]" [E or W]`

**Examples**:
- `N 45°00'00" E` — 45 degrees east of north (northeast)
- `S 56°40'30" W` — 56 degrees, 40 minutes, 30 seconds west of south (southwest)
- `N 00°00'00" E` — due north
- `S 90°00'00" E` — due east (equivalent to N 90°00'00" E)

### 3.2 Converting Quadrant Bearings to Azimuths

Azimuth is the angle measured clockwise from north (0° to 360°). This conversion is essential for computational purposes (traverse closure, plotting).

| Quadrant | Formula | Example |
|----------|---------|---------|
| **NE** (N _ E) | Azimuth = angle | N 45° E → 45° |
| **SE** (S _ E) | Azimuth = 180° - angle | S 45° E → 135° |
| **SW** (S _ W) | Azimuth = 180° + angle | S 45° W → 225° |
| **NW** (N _ W) | Azimuth = 360° - angle | N 45° W → 315° |

### 3.3 Degrees, Minutes, Seconds (DMS)

Angles are subdivided:
- 1 degree (°) = 60 minutes (')
- 1 minute (') = 60 seconds (")
- Example: `56°40'30"` = 56 + 40/60 + 30/3600 = 56.675° decimal

### 3.4 Cardinal Directions Without Degrees

Older or informal descriptions may state direction without precise degrees:

> "thence southwesterly 150 feet..."

These are legally valid but geometrically imprecise. A parser should flag these as incomplete bearings and never fabricate numerical values. The direction constrains the line to a general quadrant but does not define a specific angle.

### 3.5 Magnetic vs. True North

Historical deeds used magnetic north (the compass reading at the time of the survey). The earth's magnetic pole shifts over time — the difference between magnetic and true north is called **declination**.

- A deed from 1800 in Philadelphia might have a declination of ~3° west
- A deed from 1850 in the same location might have ~6° west
- Modern surveys typically reference true north or state grid north

When a deed states bearings without specifying "true" or "grid," older deeds are presumed to reference magnetic north at the date of the survey. This can cause apparent closure errors when comparing old and new surveys of the same parcel.

### 3.6 Compass Point System (Historical)

Colonial-era deeds sometimes use the mariner's 32-point compass system instead of degrees:

| Compass Point | Equivalent |
|--------------|------------|
| North | N 0° |
| North by East | N 11.25° E |
| North-Northeast | N 22.5° E |
| Northeast by North | N 33.75° E |
| Northeast | N 45° E |
| East | N 90° E / S 90° E |

Fractional points were also used: "North by East one quarter point North" ≈ N 8.44° E. The phrase "and by" indicated half-point variations.

---

## 4. Distance and Units of Measure

### 4.1 Modern Units

Modern descriptions use **feet** (US survey foot or international foot) and decimal fractions:

> "...North 56°40'30" East 100.00 feet..."

Two-decimal precision (hundredths of a foot) is standard in professional surveys.

### 4.2 Historical Units and Conversions

| Unit | Equivalent | Notes |
|------|-----------|-------|
| **Foot (ft)** | 1 foot | Modern standard |
| **Pole / Rod / Perch** | 16.5 feet | All three terms are synonymous |
| **Chain** (Gunter's) | 66 feet = 4 poles | Standard land measurement chain |
| **Chain** (Engineer's) | 100 feet | 100 links of 1 foot each — different from Gunter's |
| **Link** (Gunter's) | 0.66 feet | 1/100 of a Gunter's chain |
| **Link** (Engineer's) | 1.0 foot | 1/100 of an Engineer's chain |
| **Furlong** | 660 feet = 10 chains | |
| **Mile** | 5,280 feet = 80 chains | |
| **Vara** | ~33.33 inches (~2.778 ft) | Spanish unit, used in Texas, California, and the Southwest |
| **Arpent** | ~191.8 feet | French unit, used in Louisiana and parts of the Mississippi Valley |
| **Toise** | ~6.395 feet | French unit, occasionally in Louisiana |
| **Rood** | ¼ acre (area) | |
| **Acre** | 43,560 sq ft = 10 sq chains = 160 sq poles | |

### 4.3 Context Clues for Unit Identification

When a deed does not explicitly state units:
- Post-1900 US deeds: assume feet unless context indicates otherwise
- Deeds referencing "chains and links": Gunter's chain system
- Texas deeds pre-1900: may use varas
- Louisiana deeds: may use arpents or toises
- New England deeds pre-1850: frequently use rods/poles/perches

### 4.4 Ground Distance vs. Grid Distance

Survey measurements record **ground distance** — the actual horizontal distance between physical markers. Mapped features are projected onto a coordinate system, introducing a **scale factor**. The difference is typically small (a few parts per million) but accumulates over long distances. Modern COGO systems apply a ground-to-grid correction.

---

## 5. Curves

Curves appear in legal descriptions wherever property lines follow roads, cul-de-sacs, streams, or other non-linear features. Understanding curve geometry is critical for accurate plotting and closure.

### 5.1 Curve Elements

| Element | Symbol | Description |
|---------|--------|-------------|
| **Radius** | R | Distance from the center of the circle to the curve |
| **Arc Length** | L or A | Distance along the curve itself |
| **Delta** (Central Angle) | Δ | Angle subtended at the center of the circle |
| **Chord** | C | Straight-line distance from one end of the curve to the other |
| **Chord Bearing** | CB | Direction of the chord (start to end) |
| **Tangent Length** | T | Distance from the curve endpoint to the intersection of the tangent lines |
| **Curve Direction** | — | "To the left" or "to the right" from the direction of travel |
| **Point of Curvature** | PC | Where a straight line transitions into a curve |
| **Point of Tangency** | PT | Where a curve transitions back to a straight line |
| **Point of Reverse Curvature** | PRC | Where one curve transitions directly into a curve bending the opposite direction |

### 5.2 Curve Relationships

The fundamental relationships between curve elements:

```
Arc Length:    L = R × Δ  (Δ in radians)
Chord Length:  C = 2R × sin(Δ/2)
Tangent:       T = R × tan(Δ/2)
```

A deed typically specifies 2-3 of these elements, from which the others can be calculated. Common combinations:
- Radius + Arc Length (most common)
- Radius + Delta
- Radius + Chord + Chord Bearing
- Arc Length + Chord + Chord Bearing

### 5.3 Curve Direction Convention

**"To the right"** = clockwise from direction of travel (positive radius in COGO)
**"To the left"** = counterclockwise from direction of travel (negative radius in COGO)

Example deed language:

> "thence along the arc of a curve to the left, having a radius of 356.37 feet, an arc length of 260.00 feet, the chord of which bears South 34°57'37" East, 254.22 feet..."

### 5.4 Tangent Curves vs. Non-Tangent Curves

A **tangent curve** begins where the previous straight line ends, with the curve tangent to that line at the point of curvature. Most road curves are tangent.

A **non-tangent curve** (or "radial curve") is one where the bearing into the curve is not tangent to the curve. These occur at lot corners along curved streets. The deed typically notes:

> "thence along a non-tangent curve to the right..."

or provides a radial bearing:

> "a radial line to said curve bears North 15°22'00" East..."

### 5.5 Compound and Reverse Curves

- **Compound curve**: Two consecutive curves bending in the same direction but with different radii
- **Reverse curve**: Two consecutive curves bending in opposite directions (forms an S-shape)

Both are common along winding roads and require careful tracking of the transition points (PCC = Point of Compound Curvature, PRC = Point of Reverse Curvature).

### 5.6 Spiral (Transition) Curves

Used in modern highway design to provide a gradual transition between a straight line and a circular curve. A spiral has a continuously changing radius — infinite at the tangent end, equal to the circular curve radius at the other end. Spiral curves are uncommon in property descriptions but may appear in highway right-of-way deeds.

COGO attributes for spirals:
- Direction, Radius (start), Radius2 (end), Arclength

---

## 6. Monuments and Markers

Monuments are physical objects — natural or artificial — that mark survey points on the ground. They are the most legally authoritative element of a legal description.

### 6.1 Natural Monuments

Natural features referenced as boundary markers:
- **Trees**: "to a large white oak" — historical deeds name specific species (oak, hickory, beech, walnut, chestnut, etc.)
- **Streams/Rivers**: "along the center of Muddy Creek"
- **Ridges/Hills**: "along the crest of the ridge"
- **Rock outcrops**: "to a large standing rock"
- **Shorelines**: "along the mean high-water line"

Natural monuments have the highest legal priority but are also the most impermanent. Trees die, streams shift, and shorelines erode.

### 6.2 Artificial Monuments

Man-made markers set by surveyors:

| Monument Type | Description | Permanence |
|--------------|-------------|------------|
| **Iron rod/rebar** | Steel rod driven into ground (typically ½" or ⅝" diameter) | High |
| **Iron pin** | Similar to rod, sometimes with cap | High |
| **Iron pipe** | Hollow iron or steel pipe | High |
| **Capped pin/rod** | Rod with stamped aluminum or plastic cap bearing surveyor's license number | High |
| **Concrete monument** | Precast or poured concrete marker, sometimes with brass disk | Very high |
| **Brass cap/disk** | Brass disk set in concrete, stamped with survey data | Very high |
| **Stone monument** | Cut stone or natural stone set as marker | High |
| **Railroad spike** | Steel spike driven into pavement or root | Moderate |
| **Nail** | Usually a masonry nail in concrete or pavement | Low |
| **Wooden post/stake** | Wooden marker, usually temporary | Low |
| **Hub and tack** | 2"×2" wooden stake with nail marking precise point | Temporary |
| **PK nail** | "Parker Kalon" — a specific type of survey nail | Moderate |

### 6.3 Monument Language in Deeds

Deeds distinguish between monuments that already exist and those placed by the surveyor:

- **"Found"** (FD/FND): The monument was already in place when the survey was conducted
- **"Set"** (S): The monument was placed by the surveyor during this survey

Example:
> "...to an iron pin found..." (pre-existing marker)
> "...to a capped iron rod set..." (placed during survey)

### 6.4 Called-For vs. Found Monuments

A "called-for" monument is one referenced in the deed. A "found" monument is one physically located on the ground. Discrepancies between called-for and found positions create title issues. When a monument is called for but cannot be found, the surveyor must reconstruct its position from the mathematical description.

### 6.5 Witness Trees and Reference Marks

**Witness trees** (bearing trees) were trees near survey corners marked by surveyors as evidence. The surveyor would blaze the tree and record its species, diameter, and bearing/distance from the corner:

> "a white oak, 14 inches diameter, bears N 35° W, 12 links distant"

Reference marks serve a similar purpose with artificial monuments — additional markers set near a primary monument to help relocate it if disturbed.

---

## 7. Point of Commencement vs Point of Beginning

This distinction is critical and frequently misunderstood.

### 7.1 Point of Commencement (POC)

The POC is a **reference point** — a known, identifiable location from which the surveyor navigates to reach the parcel. It is NOT on the parcel boundary. The POC is typically a section corner, road intersection, or other well-established survey control point.

### 7.2 Point of Beginning (POB)

The POB is the **actual starting point of the parcel boundary**. All boundary courses begin and end here. The traverse must close back to this point.

### 7.3 Tie-In Calls

The courses between the POC and POB are called "tie-in calls" or "reference calls." They locate the parcel within the larger survey framework but are not boundary lines. In a deed:

```
COMMENCING at the NW corner of Section 12;        ← POC (reference point)
thence S 89°00'00" E, 500.00 feet;                ← Tie-in call
thence S 00°00'00" W, 200.00 feet to the          ← Tie-in call
POINT OF BEGINNING;                                ← POB (boundary starts)
thence N 45°00'00" E, 200.00 feet;                ← First boundary course
...
thence to the POINT OF BEGINNING.                  ← Closure
```

### 7.4 True Point of Beginning (TPOB) / Remote Point of Beginning (RPOB)

Some jurisdictions use **TPOB** to emphasize the actual start of the boundary (synonymous with POB). **RPOB** appears when the POB is described relative to a distant reference point.

### 7.5 When POC Equals POB

In simpler descriptions, there is no separate POC. The description begins directly at the POB:

> "BEGINNING at an iron pin in the southerly line of Main Street..."

The POC/POB distinction only arises when the surveyor needs to connect the parcel to a distant control point.

---

## 8. Deed Language and Terminology

### 8.1 Transitional Words

| Term | Meaning |
|------|---------|
| **Thence** | "Then" — introduces the next course |
| **Running thence** | Same as "thence" with additional emphasis |
| **Along** | The course follows an existing feature (road, boundary line, stream) |
| **To** | The course terminates at this point or monument |
| **By** | The course runs beside or along |
| **With** | Same as "along" — follows a feature |
| **Across** | The course crosses a feature |
| **Through** | The course passes through an area |

### 8.2 Property Reference Language

| Term | Meaning |
|------|---------|
| **Lands now or formerly (N/F) of Smith** | The adjoining property currently or previously owned by Smith |
| **Other lands of the Grantor** | Adjacent land retained by the seller |
| **Line of** | The boundary line of the referenced property |
| **Right-of-way (R/W, ROW)** | An easement for passage, usually a road |
| **Centerline** | The middle of a road, stream, or right-of-way |

### 8.3 Spatial Qualifiers

| Term | Meaning |
|------|---------|
| **Northerly / Southerly / etc.** | General direction without precise bearing |
| **More or less** | Approximate — distances or areas are not exact |
| **The same more or less** | Legal hedge on stated quantity |
| **As the same is now located** | References current physical position of a feature |
| **Heretofore** | Previously; before this time |
| **Hereinafter** | Later in this document |

### 8.4 Common Phrases and Their Legal Significance

**"Beginning at..."** — Establishes the POB. Everything before this locates the starting point; everything after describes the boundary.

**"Thence along the line of lands N/F of Smith..."** — This course follows the boundary between the subject parcel and the Smith parcel. The bearing and distance describe that shared boundary.

**"To a point"** — The terminus is a mathematical point without a physical monument. Less reliable than "to an iron pin found."

**"To the place of BEGINNING"** — Closure call. The traverse returns to the POB. Legally required for a valid metes and bounds description.

**"Containing X acres, more or less"** — The stated area is approximate. If the courses close to a different area, the courses control.

**"Being the same premises..."** — Chain-of-title recital connecting this deed to the prior conveyance.

**"Together with..."** — Additional rights conveyed (easements, appurtenances).

**"Subject to..."** — Existing encumbrances, easements, or restrictions that burden the property.

---

## 9. Water Boundaries and Meanders

Water boundaries present unique challenges because water features move over time.

### 9.1 Riparian Principles

- **Non-navigable streams**: The boundary typically runs along the **thread of the stream** (center of the main channel at normal low water)
- **Navigable waters**: The boundary is typically the **ordinary high-water mark**; the state owns the bed
- **Tidal waters**: The boundary may be the **mean high-water line**
- **Lakes and ponds**: Similar to streams — center line for non-navigable, high-water mark for navigable

### 9.2 Accretion and Avulsion

- **Accretion**: Gradual, imperceptible addition of land by natural water movement. The boundary moves with the water — the landowner gains the new land.
- **Erosion**: Gradual loss of land. The boundary moves with the water — the landowner loses land.
- **Avulsion**: Sudden, perceptible change (flood, earthquake). The boundary does NOT move — it remains where it was before the event.
- **Reliction**: Water permanently recedes, exposing new land. Generally belongs to the riparian owner.

### 9.3 Meander Lines

When a deed calls for a water boundary, the courses along the water are **meander lines** — they approximate the water's path at the time of the survey but are NOT the actual boundary. The water itself is the boundary.

Three approaches surveyors used:

1. **Unmeasured meanders**: "along Muddy Creek to [a point]" — no bearings or distances given. The surveyor noted the stream as a boundary without measuring along it.

2. **Recorded meanders**: Multiple measured courses tracing the approximate path of the stream. These are reference lines, not true boundaries.

3. **Simplified meanders**: The surveyor drew a straight line between the entry and exit points on the water body.

### 9.4 Water Terminology

| Term | Definition |
|------|-----------|
| **Thread** | Center line of the main channel at low flow |
| **Thalweg** | Line of deepest points along a stream channel |
| **Bed and banks** | The bottom and sides of a water body |
| **Meander** | A curve or winding in a stream |
| **Mouth** | Where a stream empties into a larger body of water |
| **Head / Headwaters** | The source of a stream |
| **Fork** | Where a stream divides |
| **Confluence** | Where two streams join |
| **Run** | A small stream |
| **Branch** | A tributary |
| **Kill** | Dutch-origin term for a stream (common in New York/New Jersey) |
| **Swale** | A low-lying depression, often wet |
| **Arroyo** | A steep-walled, usually dry watercourse with a flat floor (Southwest US) |
| **Vly** | Dutch-origin term for swampy lowland (New York) |

### 9.5 Upstream/Downstream References

Deed language like "up the creek" or "down the stream" indicates the direction of travel along a watercourse:
- **Up**: Against the current, toward the headwaters
- **Down**: With the current, toward the mouth

---

## 10. Exception and Inclusion Clauses

### 10.1 Exception Clauses

An exception removes a portion from the conveyance:

> "EXCEPTING THEREFROM the northerly 50 feet thereof."

> "LESS AND EXCEPT that portion heretofore conveyed to the State Highway Department by deed recorded in Book 1234, Page 567."

Keywords: **EXCEPT**, **EXCEPTING**, **LESS AND EXCEPT**, **SAVE AND EXCEPT**, **EXCLUSIVE OF**

Exception tracts may themselves contain metes and bounds descriptions. When computing area, exception areas must be subtracted from the main tract.

### 10.2 Inclusion Clauses

An inclusion adds a portion to the primary conveyance:

> "ALSO that certain strip or piece of land adjoining the above described premises on the north..."

> "TOGETHER WITH AND INCLUDING..."

Keywords: **ALSO**, **INCLUDING**, **TOGETHER WITH**

### 10.3 Reservations vs. Exceptions

Legally distinct:
- **Exception**: Excludes a physical portion of the land from the grant
- **Reservation**: Retains a right in the granted land (e.g., a mineral rights reservation, an easement reservation)

> "RESERVING unto the Grantor an easement for ingress and egress over the northerly 10 feet..."

---

## 11. Public Land Survey System (PLSS) References

Even in metes and bounds states, deeds may reference PLSS elements for location context.

### 11.1 PLSS Hierarchy

```
Principal Meridian + Baseline
  └── Township (6 mi × 6 mi, 36 sections)
       └── Section (1 mi × 1 mi, 640 acres)
            └── Aliquot Part (NW¼ of SE¼, etc.)
```

### 11.2 Township and Range

- **Township** (T): Rows running east-west, numbered from the baseline (e.g., T3N = Township 3 North)
- **Range** (R): Columns running north-south, numbered from the principal meridian (e.g., R5W = Range 5 West)
- **Section** (S or Sec): Numbered 1-36 within a township, starting NE corner, zigzagging west

### 11.3 Aliquot Parts

Sections are subdivided by halves and quarters:
- NE¼ of Section 12 = 160 acres
- NW¼ of NE¼ of Section 12 = 40 acres
- S½ of NW¼ of NE¼ of Section 12 = 20 acres

Aliquot descriptions read from smallest to largest: "the SE¼ of the NW¼ of Section 12" means find Section 12, find its NW quarter, then find the SE quarter of that.

### 11.4 PLSS in Metes and Bounds Descriptions

PLSS references commonly appear as location anchors:

> "BEGINNING at a point in the SE¼ of Section 17, Township 2 North, Range 4 East, 3rd Principal Meridian, said point being 500 feet north and 200 feet east of the SW corner of said SE¼..."

### 11.5 Principal Meridians

There are 37 principal meridians in the US. Each governs a region. Common examples: Black Hills, Boise, Chickasaw, Cimarron, Copper River, Fairbanks, Fifth, First, Fourth, Gila and Salt River, Humboldt, Huntsville, Indian, Louisiana, Michigan, Mount Diablo, New Mexico, Saint Helena, Saint Stephens, Salt Lake, San Bernardino, Second, Seward, Sixth, Tallahassee, Third, Uintah, Ute, Washington, Willamette, Wind River.

---

## 12. Subdivision Lot and Block Descriptions

### 12.1 Structure

A subdivision plat is a recorded document that divides a larger tract into individual lots. Referencing the plat eliminates the need for each deed to recite full metes and bounds.

**Format**:
> "Lot 15, Block 3, PENNBROOK ESTATES, according to the plat thereof recorded in the Office of the Recorder of Camden County, Missouri, in Plat Book 14 at Pages 22-23."

### 12.2 Advantages Over Metes and Bounds

- Every dimension, bearing, line, and marking on the recorded plat is legally part of the description
- Far less susceptible to transcription errors (copying a lot number vs. copying 20 courses)
- The plat itself provides the metes and bounds — individual deeds need only reference it

### 12.3 Relationship to Metes and Bounds

The recorded plat typically shows full metes and bounds for each lot, including:
- Bearings and distances for each lot line
- Curve data for lots on curved streets
- Lot area
- Monument locations
- Easements and setback lines

Individual lot deeds may recite the full metes and bounds from the plat or simply reference the lot and block number.

---

## 13. COGO and GIS Integration

### 13.1 COGO (Coordinate Geometry)

COGO is the computational framework for working with survey measurements in GIS systems like ArcGIS Pro. It uses the same bearings, distances, and curves found in legal descriptions.

### 13.2 COGO-Enabled Feature Attributes

Any line feature class can store COGO data using five fields:

| Field | Description | Used By |
|-------|-------------|---------|
| **Direction** | North azimuth (0°-360°), decimal degrees | Straight lines, arcs, spirals |
| **Distance** | Length in coordinate system units | Straight lines only |
| **Arclength** | Length along curve | Arcs, spirals |
| **Radius** | Circle radius; positive = right/CW, negative = left/CCW | Arcs, spirals |
| **Radius2** | End radius for spirals | Spirals only |

### 13.3 Ground-to-Grid Correction

Survey measurements (ground distances) differ from projected coordinate system distances (grid distances) due to map projection distortion. COGO-aware tools apply a scale factor to convert between the two. The correction is typically small but matters for high-precision work.

### 13.4 Geometry Types in COGO

| Type | COGO Fields Used |
|------|-----------------|
| Straight line | Direction + Distance |
| Circular arc | Direction + Radius + Arclength |
| Spiral curve | Direction + Radius + Arclength + Radius2 |
| Multi-segment polyline | Direction + Distance (start to end) |

---

## 14. Common Abbreviations

### 14.1 Directional and Location

| Abbrev. | Meaning |
|---------|---------|
| N, S, E, W | North, South, East, West |
| NE, NW, SE, SW | Northeast, Northwest, Southeast, Southwest |
| POB / P.O.B. | Point of Beginning |
| POC / P.O.C. | Point of Commencement |
| TPOB / T.P.O.B. | True Point of Beginning |
| RPOB / R.P.O.B. | Remote Point of Beginning |

### 14.2 Curve Terminology

| Abbrev. | Meaning |
|---------|---------|
| R | Radius |
| A / L | Arc length |
| Δ / D | Delta (central angle) |
| Ch / CB | Chord / Chord bearing |
| T / Tan | Tangent |
| PC | Point of Curvature |
| PT | Point of Tangency |
| PRC | Point of Reverse Curvature |
| PCC | Point of Compound Curvature |

### 14.3 Monuments and Markers

| Abbrev. | Meaning |
|---------|---------|
| IPF | Iron Pin/Pipe Found |
| IPS | Iron Pin/Pipe Set |
| IRF | Iron Rod Found |
| IRS | Iron Rod Set |
| CIP | Capped Iron Pin |
| CMP | Capped Monument/Pin |
| Con Mon F | Concrete Monument Found |
| FD / FND | Found |
| S / SET | Set (by surveyor) |
| PP | Property Pin / Power Pole |
| RR | Railroad |
| PK | Parker Kalon (survey nail) |

### 14.4 Legal and Recording

| Abbrev. | Meaning |
|---------|---------|
| B / Bk | Book |
| P / Pg | Page |
| Rec | Record / Recorded |
| S / Sec | Section |
| T / Twp | Township |
| R / Rng | Range |
| PM | Principal Meridian |
| R/W / ROW | Right-of-Way |
| Ease / Esmt | Easement |
| BRL | Building Restriction Line |
| LOD | Limit of Disturbance |
| N/F | Now or Formerly |
| H/W | Husband and Wife |
| Et Al | And Others |
| NTS | Not to Scale |
| LS | Licensed/Land Surveyor (followed by license number) |

### 14.5 Measurement

| Abbrev. | Meaning |
|---------|---------|
| Ft | Feet |
| Chn / Ch | Chain |
| Lk | Link |
| Ac | Acre |
| M | Measured / Meters |
| Sq Ft | Square feet |

---

## 15. Historical and Archaic Descriptions

### 15.1 Colonial-Era Descriptions

Pre-revolutionary and early American deeds often lack precise measurements:

> "Beginning at a heap of stones near the great oak by the road leading from Hartford to Springfield, thence running northerly by the fence of Goodman Williams to the brook, thence down the brook to the mill dam, thence along the mill pond to the county road, thence along said road to the place of beginning."

These descriptions rely entirely on natural monuments and adjoining features, with no bearings or distances. They are legally valid but geometrically indeterminate.

### 15.2 Archaic Measurement Systems

- **Rods, poles, and perches** (all 16.5 ft): Common through the 19th century
- **Chains and links**: Standard surveying units through the early 20th century
- **Varas**: Spanish colonial unit, still used in Texas deed records
- **Arpents**: French colonial unit, used in Louisiana
- **32-point compass**: Directional system predating degree notation

### 15.3 Indefinite Calls

Historical deeds sometimes include intentionally vague courses:

> "thence westerly to the top of the mountain..."
> "thence down the creek to the old ford..."
> "thence by the road as it now runs..."

These are called **indefinite calls** — they reference physical features rather than mathematical measurements. While legally valid (monuments control), they create significant challenges for modern surveys and title work.

### 15.4 Trees as Monuments

Historical surveyors extensively used trees. Common species referenced in deeds:

Ash, Beech, Birch, Cedar, Cherry, Chestnut, Cottonwood, Dogwood, Elm, Gum, Hackberry, Hemlock, Hickory, Hornbeam, Juniper, Magnolia, Maple, Oak (many varieties: red, white, post, live, Spanish, chestnut, swamp white), Pawpaw, Persimmon, Pine, Poplar, Sassafras, Spruce, Sycamore, Walnut, Yew.

Surveyors would blaze the tree and record its species, diameter, bearing, and distance from the corner point.

---

## 16. Rules of Construction

When a legal description is ambiguous, courts apply established rules to resolve the ambiguity. These rules reflect centuries of case law.

### 16.1 Monument Priority Hierarchy

When elements of a description conflict, the following order of priority generally applies:

1. **Natural monuments** (streams, ridges, shorelines)
2. **Artificial monuments** (iron pins, concrete markers, fences)
3. **Adjoiners** (calls to neighboring property lines)
4. **Courses** (bearings/directions)
5. **Distances**
6. **Area** (acreage)
7. **Coordinates** (if provided)

### 16.2 Key Principles

**Intent of the parties**: The description should be construed to effectuate the parties' intent as expressed in the deed as a whole.

**Description must close**: A valid metes and bounds description must return to its point of beginning, forming a closed polygon.

**Monuments control**: If a bearing says "N 45° E" but the iron pin called for is actually at N 47° E, the pin controls. Physical evidence on the ground outweighs written measurements.

**Senior rights prevail**: When adjacent deeds conflict, the older (senior) deed controls the common boundary.

**Deed construed against grantor**: Ambiguities are resolved in favor of the grantee (the buyer).

**Rejection of surplus**: If a description includes a course that creates an overlap with a previously-conveyed parcel, the overlapping portion is excluded.

**Proportionate measurement**: When section lines are found to be longer or shorter than the theoretical 5,280 feet, lots within the section are proportionally adjusted.

### 16.3 Calls in a Description

In surveying and title law, each element of a description is called a "call." There are different types:

- **Locative calls**: Calls that fix a specific point (e.g., "at an iron pin")
- **Directory calls**: Calls that generally describe but don't precisely fix (e.g., "in the vicinity of the old mill")
- **Informative calls**: Calls that provide context but don't define boundaries (e.g., "containing 5 acres more or less")

---

## 17. Common Pitfalls and Ambiguities

### 17.1 Transcription Errors

Metes and bounds descriptions are copied from deed to deed across generations. Each transcription introduces error risk:
- Transposed digits: `N 56°40'30" E` becomes `N 56°04'30" E`
- Missing seconds: `N 56°40'30" E` becomes `N 56°40' E`
- Wrong quadrant: `N 56°40'30" E` becomes `S 56°40'30" E`
- Distance errors: `100.00` becomes `1000.00` or `10.00`

### 17.2 Gap and Overlap

- **Gap (gore/hiatus)**: An unintentional strip of land between two parcels that neither description covers
- **Overlap**: Two descriptions cover the same strip of land

Both arise from surveying errors, description errors, or magnetic declination changes.

### 17.3 Incomplete Descriptions

Descriptions that fail to close:
- Missing the final course back to the POB
- Missing one or more intermediate courses
- A course with direction but no distance, or vice versa

### 17.4 Ambiguous Monuments

- "To a stake" — stakes rot and disappear
- "To a stone" — which stone?
- "To the corner of Smith's land" — Smith sold the land 50 years ago; where was the corner?
- "Along the road" — the road has been relocated since the deed was written

### 17.5 Magnetic Declination Shifts

A deed from 1850 and a deed from 2020 describing the same parcel will show different bearings because magnetic north has shifted. Without knowing the declination at the time of the original survey, the descriptions cannot be directly compared.

### 17.6 "Along" vs. "To"

- "Along the road 200 feet" — the 200-foot line follows the road, even if the road curves
- "200 feet to the road" — a straight line of 200 feet terminating at the road

This distinction matters when the road is not straight.

### 17.7 Deed vs. Survey Discrepancies

When the description in a deed conflicts with the survey plat:
- If the plat is referenced and recorded, both are part of the description
- If there is a conflict, the hierarchy of calls (Section 16.1) determines priority
- The deed description generally controls over the plat unless the plat is specifically incorporated

---

## 18. Verification and Quality Checks

### 18.1 Traverse Closure

The most fundamental check: do the courses close? Sum the x-components (departures) and y-components (latitudes) of all courses:

```
For each course:
  dx = distance × sin(azimuth)    (departure / easting)
  dy = distance × cos(azimuth)    (latitude / northing)

Misclosure = √(Σdx² + Σdy²)
```

A well-surveyed modern parcel should close to within 0.01 feet or better. Older surveys may have larger misclosures.

**Precision ratio**: Misclosure / Total perimeter. Modern surveys: 1:10,000 or better. Acceptable minimums vary by jurisdiction.

### 18.2 Area Calculation (Shoelace Formula)

Given the coordinates of each traverse point, area can be calculated:

```
Area = ½ |Σ(xᵢ × yᵢ₊₁ - xᵢ₊₁ × yᵢ)|
```

Compare the calculated area to the stated area in the deed. Discrepancies may indicate:
- Missing or incorrect courses
- Transcription errors
- Exception tracts not accounted for
- Unit conversion errors

### 18.3 Interior Angle Sum

For a closed polygon with n sides, the sum of interior angles should equal:

```
(n - 2) × 180°
```

Deviations indicate bearing errors.

### 18.4 Curve Consistency

For each curve, verify internal consistency:

```
Arc Length ≈ Radius × Delta (in radians)
Chord Length ≈ 2 × Radius × sin(Delta/2)
```

Discrepancies between stated and computed values may indicate transcription errors in the curve data.

### 18.5 Bearing Reversal Check

Sequential courses should not double back on themselves unless the description explicitly calls for it. A course bearing that is the exact reverse of the previous course (within a few degrees) may indicate a transcription error in the quadrant designation.

### 18.6 Distance Reasonableness

Flag courses with distances that seem unreasonable:
- Extremely short (< 1 ft) — may indicate a rounding error or typo
- Extremely long relative to other courses — may indicate a unit error (chains vs. feet)
- Distance of exactly 0.00 — invalid

### 18.7 Six-Guardrail Verification Framework

A comprehensive verification system checks:

1. **Traverse closure** — misclosure within tolerance
2. **Interior angle sum** — equals (n-2) × 180°
3. **Parallelism** — opposite sides of rectangular lots are parallel
4. **Curve consistency** — arc ≈ R × Δ
5. **Area reasonableness** — computed area matches stated area within tolerance
6. **Double-entry validation** — each course can be independently verified

---

## Appendix A: Sample Legal Description (Annotated)

```
ALL THAT CERTAIN lot or piece of ground          ← Caption
situate in the Township of Haddonfield,          ← Location
County of Camden, State of New Jersey,           ← Jurisdiction
being known as Lot 24 on a certain plan          ← Plat reference
entitled "Pennbrook Estates" prepared by
Smith Engineering, dated March 15, 1962,
and recorded in the Camden County Clerk's
Office in Map Book 45, Page 12:

BEGINNING at an iron pin found in the            ← POB + monument
southerly right-of-way line of Pennbrook
Drive, said point being located at the
intersection of the southerly line of
Pennbrook Drive and the division line
between Lots 23 and 24 on said plan;

thence (1) along said southerly line of          ← Course 1 (along road)
Pennbrook Drive, North 56°40'30" East,             bearing + distance
100.00 feet to an iron pin found at the            monument at terminus
corner of Lots 24 and 25;

thence (2) along the division line between       ← Course 2 (lot line)
Lots 24 and 25, South 33°19'30" East,
75.00 feet to an iron pin found;

thence (3) South 56°40'30" West,                 ← Course 3 (rear line)
100.00 feet to an iron pin found at the
corner of Lots 23 and 24;

thence (4) along the division line between       ← Course 4 (lot line)
Lots 23 and 24, North 33°19'30" West,
75.00 feet to the point and place of             ← Closure to POB
BEGINNING.

CONTAINING 7,500 square feet or 0.1722           ← Area statement
acres of land, more or less.

BEING the same premises which John Smith         ← Chain of title
and Mary Smith, his wife, by Deed dated
June 15, 1985, and recorded in the Office
of the Recorder of Deeds in and for Camden
County in Deed Book 4520, Page 217, granted
and conveyed unto Robert Jones.
```

---

## Appendix B: Quick Reference — Bearing to Azimuth

| Bearing | Azimuth |
|---------|---------|
| N 0°00'00" E (Due North) | 0° |
| N 45°00'00" E | 45° |
| N 90°00'00" E (Due East) | 90° |
| S 45°00'00" E | 135° |
| S 0°00'00" E (Due South) | 180° |
| S 45°00'00" W | 225° |
| S 90°00'00" W (Due West) | 270° |
| N 45°00'00" W | 315° |
| N 0°00'00" W (Due North) | 360° / 0° |

---

## Appendix C: Unit Conversion Quick Reference

| From | To Feet | Multiply By |
|------|---------|------------|
| Chains (Gunter's) | Feet | 66 |
| Chains (Engineer's) | Feet | 100 |
| Links (Gunter's) | Feet | 0.66 |
| Links (Engineer's) | Feet | 1.0 |
| Poles / Rods / Perches | Feet | 16.5 |
| Varas (Texas) | Feet | 2.778 |
| Arpents | Feet | 191.8 |
| Furlongs | Feet | 660 |
| Miles | Feet | 5,280 |
| Meters | Feet | 3.28084 |
| Toises | Feet | 6.395 |

| Area Unit | Square Feet |
|-----------|------------|
| Acre | 43,560 |
| Square chain | 4,356 |
| Rood | 10,890 |
| Hectare | 107,639 |
| Square vara | 7.716 |
| Square arpent | 36,787 |

---

## Appendix D: Resources

- [Introduction to COGO — ArcGIS Pro Documentation](https://pro.arcgis.com/en/pro-app/latest/help/editing/introduction-to-cogo.htm)
- [Surveying Units and Terms — Direct Line Software](https://www.directlinesoftware.com/survey.htm)
- [Metes and Bounds Deeds — Direct Line Software](https://www.directlinesoftware.com/metes.htm)
- [Reading Land Descriptions — Merebrook LLC](http://www.merebrookllc.com/reading-descriptions.html)
- [Survey Abbreviations — Merebrook LLC](http://www.merebrookllc.com/abbreviations.html)
- [How To Read Metes And Bounds — Probity Title (Part 1)](https://www.probitytitle.com/how-to-read-metes-and-bounds-part-1/)
- [How To Read Metes And Bounds — Probity Title (Part 2)](https://www.probitytitle.com/how-to-read-metes-and-bounds-part-2/)
- [Understanding COGO — Geospatial Training Services](https://geospatialtraining.com/understanding-cogo-a-beginners-guide-to-coordinate-geometry-in-arcgis-pro/)
