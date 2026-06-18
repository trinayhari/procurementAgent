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
            ),
        ],
    )
)

# ============================================ FUTURE TYPES (registered, disabled)
# These demonstrate the extension pattern and surface in the UI as "coming soon".
# Flesh out the categories + guidance and flip `enabled=True` to ship them.
register(
    PlanTypeSpec(
        key="building_plan",
        label="Building Plan",
        description="Architectural / structural building sheets.",
        enabled=False,
        categories=[
            BomCategory(
                key="structural",
                label="Structural Materials",
                tone="gray",
                description="Concrete, rebar, structural steel, framing.",
            ),
        ],
    )
)

register(
    PlanTypeSpec(
        key="electrical_plan",
        label="Electrical Plan",
        description="Electrical single-line, power, and lighting plans.",
        enabled=False,
        categories=[
            BomCategory(
                key="electrical",
                label="Electrical Materials",
                tone="warn",
                description="Conduit, conductors, panels, fixtures, pull boxes.",
            ),
        ],
    )
)
