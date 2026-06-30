"""Concrete plan-type definitions.

Importing this module registers every spec (side effect). `app.services.extraction`
imports it once at package init so the registry is populated app-wide.

To add a new plan type later: append a `register(PlanTypeSpec(...))` block here.
Set `enabled=False` while a type is still being tuned — it shows in the UI as
"coming soon" but can't be selected for upload.
"""
from app.services.extraction.registry import BomCategory, PlanTypeSpec, register

# ============================================================ SITE / CIVIL PLANS
# The flagship, fully-supported type. Site plans carry the wet-utility and
# grading disciplines, each of which becomes its own Bill of Materials.
register(
    PlanTypeSpec(
        key="site_plan",
        label="Site Plan",
        description=(
            "Civil site plans: utility plans, grading & drainage, paving, and "
            "erosion control sheets for a development."
        ),
        prompt_guidance=(
            "These are civil engineering site/utility drawings. Quantities live in "
            "several places — read ALL of them:\n"
            "  • Pipe runs labeled along their length (e.g. \"240 LF 12\\\" DI\").\n"
            "  • Structure callouts / bubbles (manholes, catch basins, hydrants, valves).\n"
            "  • Schedules and tables (pipe schedule, structure schedule, paving sections).\n"
            "  • Legends that define symbols you then count on the plan.\n"
            "  • Quantity / estimate tables and general-notes counts.\n"
            "Sum repeated runs of the same material into one line item where it is "
            "clearly the same spec. Keep different sizes, classes, and materials as "
            "separate line items. Pipe and linear features use LF; structures and "
            "fittings use EA; surfacing uses SY or SF; earthwork uses CY; rock/aggregate "
            "uses TON. Never invent quantities — if a quantity is not shown or derivable, "
            "set quantity to null and note it in `assumptions`.\n"
            "Capture FITTINGS and APPURTENANCES, not just pipe and structures. Break out "
            "every tee, bend, cross, reducer, valve, tapping sleeve, hydrant, and cap by "
            "its size and (for bends) its angle — '8\"x6\" Tee' and '45° Bend' are separate "
            "line items, counted from the plan-view callouts and fitting schedules. At a "
            "connection to an existing utility main, capture the tapping sleeve & valve. "
            "Capture linear appurtenances that track pipe length (tracer tape/wire, trench "
            "bedding/backfill) in LF tied to the total trench length. When an item is "
            "labeled 'TYP.' (typical) and its total count is not clearly given, STILL list "
            "the item but set quantity to null and write 'shown as TYP., count not "
            "specified' in `assumptions` — do not guess a count and do not omit it."
        ),
        categories=[
            BomCategory(
                key="water",
                label="Water Materials",
                tone="blue",
                description=(
                    "Potable & fire water distribution. Capture EVERY procurable component, "
                    "not just pipe:\n"
                    "  • Water main (DI or PVC, e.g. C900) by size, and fire-hydrant lead "
                    "pipe (often 6\") as a SEPARATE line item from the main.\n"
                    "  • Fittings broken out by type AND size/angle — tees by configuration "
                    "('8\"x8\" Tee', '8\"x6\" Tee to hydrant'), bends/elbows by angle (45°, "
                    "22.5°, 11.25°), plus crosses, reducers, caps, and plugs.\n"
                    "  • Valves by size and location: gate valve at the tap, gate valves at "
                    "tees, blow-off/flushing valve, air-release valve.\n"
                    "  • Tapping sleeve & valve where the new main connects to an existing "
                    "City main (e.g. '24\"x8\" Tapping Sleeve').\n"
                    "  • Fire-hydrant assemblies; service lines & meters (often shown 'TYP.').\n"
                    "  • Appurtenances: tracer tape/wire and trench bedding/backfill quantified "
                    "against total waterline LF; valve boxes, thrust/kicker blocks, polywrap."
                ),
                examples=[
                    '8" PVC Water Main, C900',
                    '6" PVC Hydrant Lead',
                    '24"x8" Tapping Sleeve & Valve',
                    '8" Gate Valve',
                    '8"x8" Tee',
                    '8"x6" Tee (to hydrant)',
                    "45° Bend",
                    "22.5° Bend",
                    "Fire Hydrant Assembly",
                    "Blow-off Valve",
                    '2" Service Line (TYP.)',
                    "Tracer Tape",
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="sewer",
                label="Sewer Materials",
                tone="violet",
                description=(
                    "Sanitary sewer collection: gravity sewer main (PVC SDR-35), laterals, "
                    "manholes, cleanouts, frames & covers, and force-main components."
                ),
                examples=[
                    '8" PVC SDR-35',
                    '48" Dia. Manhole',
                    '6" PVC Lateral',
                    "Frame & Cover",
                    "Sewer Cleanout",
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="storm",
                label="Storm Drain Materials",
                tone="success",
                description=(
                    "Storm drainage: RCP/HDPE storm pipe, catch basins, inlets, storm "
                    "manholes, headwalls, flared end sections, and detention/treatment structures."
                ),
                examples=[
                    '24" RCP, Class III',
                    "Type A Catch Basin",
                    '18" RCP',
                    "Storm Manhole",
                    "Flared End Section",
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="erosion",
                label="Erosion Control Materials",
                tone="warn",
                description=(
                    "Erosion & sediment control (SWPPP/BMP): silt fence, inlet protection, "
                    "construction entrances, fiber rolls/wattles, erosion blanket, hydroseed, "
                    "check dams, and sediment basins."
                ),
                examples=[
                    "Silt Fence",
                    "Inlet Protection",
                    "Stabilized Construction Entrance",
                    "Fiber Roll / Wattle",
                    "Erosion Control Blanket",
                ],
                typical_units=["LF", "EA", "SY", "SF"],
                # Erosion control plans are graphical — BMPs are symbols, not text — so
                # the text layer carries no quantities. Vision the erosion-plan sheet.
                vision_fallback=True,
                sheet_keywords=["EROSION CONTROL PLAN"],
            ),
        ],
    )
)

# =================================================== BUILDING / STRUCTURAL PLANS
# Architectural & structural sheets. Like site plans, the BOM is split into its
# component disciplines (concrete, rebar, steel, masonry, wood) so each becomes
# its own Bill of Materials.
register(
    PlanTypeSpec(
        key="building_plan",
        label="Building Plan",
        description=(
            "Architectural / structural building sheets: foundations, framing "
            "plans, structural details, and schedules."
        ),
        prompt_guidance=(
            "These are architectural/structural building drawings. Quantities live "
            "in several places — read ALL of them:\n"
            "  • Structural schedules (footing, column, beam, slab schedules).\n"
            "  • Framing plans and sections with member callouts (e.g. \"W12x26\", "
            "\"2x6 @ 16\\\" O.C.\").\n"
            "  • Reinforcing callouts (e.g. \"#5 @ 12\\\" O.C. E.W.\", \"(4) #8\").\n"
            "  • Concrete callouts (slab thickness, footing dimensions, wall sections).\n"
            "  • General-notes quantities and material specifications.\n"
            "Keep different sizes, grades, and shapes as separate line items. "
            "Concrete uses CY; reinforcing steel and structural steel use LB or TON "
            "(or LF for shapes by length); framing lumber uses LF or BF; masonry uses "
            "EA (units) or SF (wall area); decking/sheathing uses SF. Never invent "
            "quantities — if a quantity is not shown or derivable, set it to null and "
            "note it in `assumptions`."
        ),
        categories=[
            BomCategory(
                key="concrete",
                label="Concrete Materials",
                tone="gray",
                description=(
                    "Cast-in-place concrete by mix/strength and placement: footings, "
                    "grade beams, slabs-on-grade, foundation/retaining walls, piers, and "
                    "columns. Capture each placement by its concrete strength (e.g. "
                    "3,000 / 4,000 psi) where shown."
                ),
                examples=[
                    '4,000 psi Concrete — Footings',
                    '3,500 psi Concrete — Slab on Grade',
                    "Foundation Wall Concrete",
                    "Anchor Bolts",
                ],
                typical_units=["CY", "SF", "EA"],
            ),
            BomCategory(
                key="rebar",
                label="Reinforcing Steel",
                tone="warn",
                description=(
                    "Reinforcing steel and embeds: deformed bar by size (#3–#11), "
                    "welded wire reinforcement, dowels, ties/stirrups, and "
                    "epoxy-coated bar where specified. Break out by bar size."
                ),
                examples=[
                    '#5 Rebar',
                    '#4 Rebar',
                    'WWF 6x6 W2.9xW2.9',
                    "#8 Dowel",
                ],
                typical_units=["LB", "TON", "LF", "EA"],
            ),
            BomCategory(
                key="steel",
                label="Structural Steel",
                tone="blue",
                description=(
                    "Structural steel framing: wide-flange beams/columns (W-shapes), "
                    "HSS tube, channels, angles, base/cap plates, and the connection "
                    "hardware (anchor rods, bolts). Break out by member designation."
                ),
                examples=[
                    "W12x26 Beam",
                    "W10x33 Column",
                    "HSS6x6x1/4",
                    "L4x4x1/4 Angle",
                    "Base Plate",
                ],
                typical_units=["LF", "EA", "LB", "TON"],
            ),
            BomCategory(
                key="framing",
                label="Wood & Light-Gauge Framing",
                tone="success",
                description=(
                    "Wood and cold-formed framing: dimensional lumber, studs, joists, "
                    "rafters, engineered lumber (LVL/glulam/I-joists), metal studs, "
                    "sheathing/decking, and joist hangers/connectors. Break out by size "
                    "and spacing."
                ),
                examples=[
                    '2x6 Stud @ 16" O.C.',
                    '2x10 Floor Joist',
                    '1-3/4"x11-7/8" LVL',
                    '3/4" Plywood Sheathing',
                    "Joist Hanger",
                ],
                typical_units=["LF", "EA", "SF", "BF"],
            ),
            BomCategory(
                key="masonry",
                label="Masonry Materials",
                tone="violet",
                description=(
                    "Masonry: CMU block by size, brick veneer, grout/mortar, and "
                    "reinforcing accessories (ladder/truss wire, bond beams). Capture "
                    "block by nominal size and wall area where shown."
                ),
                examples=[
                    '8" CMU Block',
                    '12" CMU Block',
                    "Brick Veneer",
                    "Bond Beam",
                    "Masonry Grout",
                ],
                typical_units=["EA", "SF", "CY"],
            ),
        ],
    )
)

# ============================================================== ELECTRICAL PLANS
# Power, lighting, and single-line drawings. The BOM splits into the electrical
# disciplines (raceway, conductors, distribution equipment, devices, lighting,
# grounding) so each is its own Bill of Materials.
register(
    PlanTypeSpec(
        key="electrical_plan",
        label="Electrical Plan",
        description=(
            "Electrical single-line, power, lighting, and panel-schedule sheets."
        ),
        prompt_guidance=(
            "These are electrical engineering drawings. Quantities live in several "
            "places — read ALL of them:\n"
            "  • Panel schedules and one-line diagrams (panels, breakers, feeders).\n"
            "  • Lighting & power plans with fixture/device symbols counted against a "
            "legend.\n"
            "  • Conduit & conductor callouts (e.g. \"3#12 + #12G in 3/4\\\" C\").\n"
            "  • Luminaire schedules (fixture types A, B, C… with counts).\n"
            "  • Feeder schedules and general-notes quantities.\n"
            "Break out conduit by size and type, conductors by size/insulation, and "
            "fixtures by their schedule type. Conduit and wire use LF; fixtures, "
            "devices, panels, and boxes use EA. Never invent quantities — if a count "
            "is shown as TYP. or not given, list the item with quantity null and note "
            "it in `assumptions`."
        ),
        categories=[
            BomCategory(
                key="raceway",
                label="Conduit & Raceway",
                tone="warn",
                description=(
                    "Raceway by type and trade size: EMT, rigid/IMC, PVC, flexible "
                    "conduit, cable tray, wireway, and fittings (connectors, couplings, "
                    "elbows). Break out by size."
                ),
                examples=[
                    '3/4" EMT Conduit',
                    '1" EMT Conduit',
                    '2" PVC Conduit (underground)',
                    'Cable Tray',
                    '1" EMT Connector',
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="conductors",
                label="Wire & Cable",
                tone="blue",
                description=(
                    "Building wire and cable by size and insulation: THHN/THWN copper "
                    "conductors, feeders, MC/AC cable, and grounding conductors. Break "
                    "out by AWG/kcmil size."
                ),
                examples=[
                    '#12 THHN Copper',
                    '#10 THHN Copper',
                    '#3/0 THWN Copper Feeder',
                    "#12 Ground Wire",
                    "3/C #12 MC Cable",
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="equipment",
                label="Panels & Distribution",
                tone="violet",
                description=(
                    "Distribution equipment: panelboards, switchboards, transformers, "
                    "disconnects/safety switches, breakers, meters, and the main "
                    "service gear. Capture each by rating where shown."
                ),
                examples=[
                    "200A Panelboard",
                    "480V-208/120V Transformer",
                    "100A Disconnect",
                    "20A/1P Circuit Breaker",
                    "Meter Base",
                ],
                typical_units=["EA"],
            ),
            BomCategory(
                key="devices",
                label="Devices & Boxes",
                tone="gray",
                description=(
                    "Wiring devices and enclosures: receptacles, switches, junction/"
                    "pull boxes, device boxes, cover plates, and floor boxes. Count by "
                    "type from the plan symbols and legend."
                ),
                examples=[
                    "Duplex Receptacle",
                    "GFCI Receptacle",
                    "Single-Pole Switch",
                    "4-Square Junction Box",
                    "Pull Box",
                ],
                typical_units=["EA"],
            ),
            BomCategory(
                key="lighting",
                label="Lighting Fixtures",
                tone="success",
                description=(
                    "Luminaires by schedule type: recessed troffers, downlights, strip "
                    "fixtures, wall packs, exit/emergency lighting, and exterior pole "
                    "lights. Break out by fixture type designation (A, B, C…)."
                ),
                examples=[
                    "Type A — 2x4 LED Troffer",
                    "Type B — 6\" LED Downlight",
                    "Type C — Wall Pack",
                    "Exit Sign",
                    "Emergency Light",
                ],
                typical_units=["EA"],
                # Lighting/power plans are graphical — fixtures are symbols, not text —
                # so the text layer often carries no counts. Vision the lighting sheet.
                vision_fallback=True,
                sheet_keywords=["LIGHTING PLAN", "ELECTRICAL PLAN", "POWER PLAN"],
            ),
            BomCategory(
                key="grounding",
                label="Grounding & Bonding",
                tone="danger",
                description=(
                    "Grounding electrode system and bonding: ground rods, ground bar, "
                    "bonding jumpers, grounding conductors, and exothermic connections."
                ),
                examples=[
                    "Ground Rod",
                    "#4 Bare Copper Ground",
                    "Ground Bar",
                    "Bonding Jumper",
                    "Exothermic Weld",
                ],
                typical_units=["EA", "LF"],
            ),
        ],
    )
)

# ===================================================== ADDITIONAL DOCUMENTS SLOT
# A catch-all for reference attachments (specs, geotech reports, addenda, …) that
# aren't one of the three plan slots. NOT a singleton — a project may hold many.
# It carries no BOM categories, so the upload route stores it without running
# extraction (there is no discipline to split a BOM into).
register(
    PlanTypeSpec(
        key="other",
        label="Additional Document",
        description=(
            "Supporting documents kept for reference — specifications, geotechnical "
            "reports, addenda, permits. Stored alongside the plans; no BOM is extracted."
        ),
        singleton=False,
        categories=[],
    )
)
