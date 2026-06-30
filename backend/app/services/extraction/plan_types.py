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
# component disciplines, but along how the work is PROCURED (CSI Div 03/04/05/06):
# concrete (CY of ready-mix) and its reinforcing (LB/TON from a rebar shop) are
# separate buys, structural steel is fabricated by tonnage, and embeds/anchor
# bolts/deck/studs are coordinated with — and bought from — the steel package.
register(
    PlanTypeSpec(
        key="building_plan",
        label="Building Plan",
        description=(
            "Architectural / structural building sheets: foundations, framing "
            "plans, structural details, schedules, and general structural notes."
        ),
        prompt_guidance=(
            "These are structural building drawings. Read them in the order an "
            "estimator does, because quantities are spread across the set:\n"
            "  • GENERAL STRUCTURAL NOTES (sheet S0.x) FIRST — they set concrete "
            "strengths per element, rebar grade, lap-splice length, anchor-bolt "
            "spec, and the TYPICAL reinforcing (e.g. standard slab mesh, typical "
            "column ties) that is stated here and NOWHERE else.\n"
            "  • SCHEDULES are the richest source: footing schedule (F/WF marks, "
            "plan size × thickness, bottom/top bars, dowels), grade-beam schedule, "
            "column schedule (mark, size, vertical bars '(8)#9', tie size/spacing, "
            "base plate & anchor bolts), beam schedule (mark, W-designation, "
            "length).\n"
            "  • FRAMING PLANS tag members directly with AISC designations "
            "(W16x40 = 16\" deep, 40 lb/ft) and grid spacing that drives "
            "joist/stud counts.\n"
            "  • SECTIONS & DETAILS are where slab/wall/beam reinforcing actually "
            "appears — do not assume the plan view shows all rebar.\n"
            "Learn these callout patterns: '#5 @ 12\" O.C. E.W.' (#5 bar every 12\" "
            "on center, each way), '#4 @ 12\" O.C. T&B' (top & bottom mats), "
            "'(4) #8' (a count of four #8 bars), '#3 ties @ 10\" O.C.', "
            "'2x6 @ 16\" O.C.' (studs/joists), 'W12x26'/'HSS6x6x1/4'/'L4x4x1/4'/"
            "'PL 3/4\"' (steel), '(2) 3/4\"Ø x 18\" A.B.' (anchor bolts), "
            "'8x8x16 CMU'.\n"
            "RULES: One line item per unique size/grade/shape/strength — never "
            "merge W12x26 with W16x40, #5 Grade 60 with #5 Grade 75, or 3,000 psi "
            "with 4,000 psi concrete. Categorise by who procures it and how it is "
            "measured, NOT by physical location: reinforcing is its own category in "
            "LB/TON (not part of the concrete buy), while anchor bolts, embed "
            "plates, headed studs, steel deck, and connection plates belong to the "
            "STEEL package even though they are cast into or sit on concrete. "
            "Concrete uses CY; reinforcing bar LB/TON and welded wire mesh SF; "
            "steel members TON/LB; deck SF; anchor bolts/studs/embeds/connectors/"
            "joist-hangers EA; masonry units EA with mortar/grout in bags/CY and "
            "joint reinforcement/lintels/control joints LF; lumber BF/LF/EA with "
            "sheathing in SF.\n"
            "A spacing callout like '#5 @ 12\" O.C.' is a RULE, not a count — "
            "preserve it verbatim and, if no run length/area is given to convert it "
            "to a quantity, set quantity to null and note 'spacing given, dimension "
            "needed' in `assumptions`. Deduplicate by mark/tag: the same footing or "
            "column appears on the plan, the schedule, AND a detail — count it ONCE "
            "(the schedule is authoritative for size/reinforcing, the plan for "
            "count). Expand 'TYP.'/typical details by the number of locations they "
            "apply to; if that count is not stated, list the item with quantity "
            "null and say 'shown as TYP., count not specified'. Capture precast, "
            "post-tensioning, and applied fireproofing only when the drawings show "
            "them. Never invent a quantity."
        ),
        categories=[
            BomCategory(
                key="concrete",
                label="Cast-in-Place Concrete",
                tone="gray",
                description=(
                    "Ready-mix concrete by structural element AND strength (mix "
                    "design and placement differ per element): continuous & spread "
                    "footings, grade beams, piers/columns, foundation & shear walls, "
                    "slab-on-grade, elevated slabs/decks, pile caps, equipment pads, "
                    "and stairs. Include the under-slab vapor barrier and slab-edge/"
                    "joint items. Split each placement out by its psi where shown."
                ),
                examples=[
                    "3,000 psi Concrete — Spread & Continuous Footings",
                    "4,000 psi Concrete — Grade Beams",
                    "4,000 psi Concrete — Columns / Piers",
                    "4,500 psi Concrete — Foundation Walls",
                    "4,000 psi Concrete — Slab-on-Grade, 5\" thick",
                    "5,000 psi Concrete — Elevated Slab",
                    "4,000 psi Concrete — Pile Caps",
                    "3,000 psi Concrete — Equipment / Housekeeping Pads",
                    "10-mil Vapor Barrier (under slab)",
                ],
                typical_units=["CY", "SF", "LF"],
            ),
            BomCategory(
                key="rebar",
                label="Reinforcing Steel",
                tone="warn",
                description=(
                    "Deformed reinforcing bar (its own buy, measured by weight — do "
                    "NOT fold into concrete), welded wire reinforcement, and "
                    "accessories: dowels, ties/stirrups, chairs/bar supports, "
                    "mechanical couplers. Break out by bar size AND grade; capture "
                    "epoxy-coated/galvanised as separate variants. Add lap splices "
                    "(~40 bar-diameters) and waste — procured weight exceeds the "
                    "bare geometric length."
                ),
                examples=[
                    "#4 Rebar (Grade 60) — Footing mat",
                    "#5 Rebar (Grade 60) — Slab @ 12\" O.C. E.W.",
                    "#5 Rebar (Grade 60) — Wall vertical @ 12\" O.C.",
                    "#8 Rebar (Grade 60) — Column verticals, (4) #8",
                    "#3 Ties (Grade 60) @ 12\" O.C. — Columns",
                    "#4 Stirrups (Grade 60) — Beams",
                    "#6 Dowels (Grade 60) — Wall/footing",
                    "6x6 W2.9xW2.9 Welded Wire Reinforcement — Slab",
                    "Epoxy-Coated #5 Rebar (Grade 60)",
                    "Rebar Chairs / Bar Supports",
                ],
                typical_units=["LB", "TON", "SF", "EA"],
            ),
            BomCategory(
                key="steel",
                label="Structural Steel & Metals",
                tone="blue",
                description=(
                    "Fabricated structural steel and everything bought with the "
                    "steel package: wide-flange beams/columns/girders (W-shapes), "
                    "HSS tube, channels, angles, tees, bar joists & joist girders, "
                    "base/cap/bent plates — PLUS metal deck (floor/roof), headed "
                    "shear studs, anchor bolts, embed plates, loose lintels, and "
                    "connection hardware. Break out by member designation; members "
                    "are weighed (lb/ft × length), deck is SF, hardware is EA."
                ),
                examples=[
                    "W12x26 Beam (A992)",
                    "W24x76 Girder (A992)",
                    "W10x49 Column (A992)",
                    "HSS6x6x1/4 Column (A500 Gr. C)",
                    "HSS4x4x1/4 Brace",
                    "L4x4x1/4 Angle — Lintel/Bracing",
                    "Steel Bar Joist 18K5",
                    "PL 3/4\" Base Plate, 14\"x14\" (A36)",
                    "1-1/2\" Type B Roof Deck, 22 ga, galvanized",
                    "2\" Composite Floor Deck, 20 ga",
                    "3/4\"x4-1/2\" Headed Shear Stud (Nelson)",
                    "3/4\"Ø x 18\" Anchor Bolt (F1554 Gr. 36)",
                    "Embed Plate PL 1/2\"x8\"x8\" w/ studs",
                ],
                typical_units=["LF", "TON", "LB", "SF", "EA"],
            ),
            BomCategory(
                key="masonry",
                label="Masonry Materials",
                tone="violet",
                description=(
                    "Concrete masonry units and special shapes (bond-beam, lintel/"
                    "knockout, half/corner/sash), brick, and stone, plus the mortar, "
                    "grout, joint reinforcement, ties/anchors, flashing/weeps, and "
                    "control joints that build the wall. Units count EA (or via wall "
                    "SF × 1.125 block/SF for 8x8x16); mortar/grout are bags/CY; "
                    "rebar in masonry cells belongs to the reinforcing category."
                ),
                examples=[
                    "8\"x8\"x16\" CMU — Standard",
                    "8\"x8\"x16\" CMU — Bond Beam unit",
                    "8\"x8\"x16\" CMU — Lintel / Knockout unit",
                    "12\"x8\"x16\" CMU — Loadbearing",
                    "Modular Face Brick",
                    "Type S Mortar",
                    "Coarse Grout (cell fill)",
                    "Ladder Joint Reinforcement, 9 ga",
                    "Veneer Wall Ties",
                    "Through-wall Flashing / Weeps",
                    "Masonry Control Joint",
                ],
                typical_units=["EA", "SF", "CY", "LF"],
            ),
            BomCategory(
                key="framing",
                label="Wood & Light-Gauge Framing",
                tone="success",
                description=(
                    "Dimensional lumber, engineered lumber (LVL/PSL/glulam), wood "
                    "I-joists, posts, sheathing, pressure-treated members, and the "
                    "metal connectors/hangers that join them — plus cold-formed "
                    "(light-gauge) steel studs/joists where the structure uses them. "
                    "Break out by member size and use; carry the spacing callout."
                ),
                examples=[
                    "2x4 Stud (SPF) @ 16\" O.C. — Walls",
                    "2x6 Stud (SPF) @ 16\" O.C. — Ext. walls",
                    "2x6 Top & Bottom Plates",
                    "2x10 Floor Joist @ 16\" O.C.",
                    "2x12 Rafter @ 24\" O.C.",
                    "1-3/4\"x11-7/8\" LVL Beam",
                    "11-7/8\" TJI I-Joist @ 19.2\" O.C.",
                    "6x6 Post",
                    "3/4\" T&G Plywood Subfloor",
                    "7/16\" OSB Wall Sheathing",
                    "2x6 PT Sill Plate",
                    "Simpson Joist Hanger",
                    "600S162-54 Metal Stud (light-gauge)",
                ],
                typical_units=["LF", "BF", "EA", "SF"],
            ),
        ],
    )
)

# ============================================================== ELECTRICAL PLANS
# Power, lighting, single-line/one-line, and panel-schedule sheets (CSI Div 26,
# with low-voltage in Div 27/28). The BOM splits along how an electrician buys
# and prices the work: raceway by type+size (LF), conductors by size+insulation
# (LF), gear/devices/fixtures/grounding by the each (EA), with fire-alarm & other
# low-voltage broken out because code (NEC 760/NFPA 72) and the installer differ.
register(
    PlanTypeSpec(
        key="electrical_plan",
        label="Electrical Plan",
        description=(
            "Electrical power, lighting, single-line/riser, panel-schedule, and "
            "luminaire-schedule sheets."
        ),
        prompt_guidance=(
            "These are electrical construction drawings. Quantities are spread "
            "across plans, schedules, and diagrams — read all of them:\n"
            "  • LUMINAIRE / FIXTURE SCHEDULE defines what each fixture Type letter "
            "(A, B, C…) is (catalog #, lamp/driver, voltage, mounting); the COUNT "
            "of each type comes from counting symbols on the LIGHTING PLAN against "
            "the legend. Use both — the schedule without counts undercounts, the "
            "plan without the schedule loses the description.\n"
            "  • POWER PLAN gives device counts (receptacles, switches, junction "
            "boxes, equipment connections) by counting symbols vs. the legend, plus "
            "homeruns (arrow to a panel with a circuit number) that define branch "
            "circuits.\n"
            "  • PANEL SCHEDULE header gives the panelboard itself ('200A, "
            "208Y/120V, 3Ø 4W, 42-ckt, MLO'); each row gives a breaker "
            "('20A/1P'); rows may specify the branch '#12 THHN, 1/2\" EMT'. A "
            "'SPACE' is not a breaker to buy; an installed 'SPARE' is.\n"
            "  • ONE-LINE / RISER DIAGRAM and the FEEDER SCHEDULE give service & "
            "distribution gear (switchboards, transformers, ATS, disconnects) and "
            "feeders, tagged like '4#3/0 + #4G in 2\" C'.\n"
            "Learn this callout: '3#12 + #12G in 3/4\" C' = three #12 conductors "
            "plus one #12 ground in 3/4\" conduit. CONDUCTOR FOOTAGE = conduit "
            "footage × number of conductors in the run (e.g. 3#12 in 820 ft of "
            "conduit = 2,460 LF of #12 wire) — taking off conduit but forgetting "
            "to multiply the wire is the classic error.\n"
            "RULES: Never merge conduit across type OR size (1/2\" EMT, 3/4\" EMT, "
            "3/4\" PVC, 1\" RMC are four lines); never merge conductors across "
            "size, insulation, or material (#12 THHN Cu ≠ #10 THHN Cu ≠ #12 XHHW "
            "Al); green/bare = ground. Organise fixtures strictly by their schedule "
            "Type letter, one line per type. Each unique gear rating is its own line "
            "(a 200A panel ≠ a 100A panel; breakers itemised by amp rating & pole "
            "count). Conduit & wire & bare grounding conductor use LF; conduit "
            "fittings (couplings, connectors, straps, elbows — conduit ships without "
            "them, so count them separately), boxes, devices, fixtures, gear, "
            "breakers, ground rods, and lugs use EA. Conduit length is usually NOT "
            "dimensioned — if a run's length is not given, set quantity to null and "
            "note 'length not dimensioned, scale required' rather than inventing a "
            "figure. Expand 'TYP.' by the number of locations; if the count is not "
            "stated, list the item with quantity null and say 'shown as TYP., count "
            "not specified'. Deduplicate runs/feeders that appear on more than one "
            "sheet (plan + one-line + riser) — count each once. Never invent a "
            "quantity."
        ),
        categories=[
            BomCategory(
                key="raceway",
                label="Conduit & Raceway",
                tone="warn",
                description=(
                    "All raceway that carries conductors, plus its fittings and "
                    "supports — kept as separate lines per material type × trade "
                    "size. Types: EMT (indoor dry), PVC Sch 40/80 (underground/wet), "
                    "RMC/IMC (exposed/hazardous), flexible (FMC) and liquidtight "
                    "(LFMC) motor whips, wireway/cable tray, and surface raceway. "
                    "Conduit is LF; couplings/connectors/straps/elbows are EA."
                ),
                examples=[
                    "1/2\" EMT Conduit",
                    "3/4\" EMT Conduit",
                    "1\" EMT Conduit",
                    "2\" EMT Conduit",
                    "3/4\" PVC Schedule 40 Conduit",
                    "4\" PVC Sch 40 Conduit (underground feeder)",
                    "1\" Rigid Galvanized (RMC) Conduit",
                    "3/4\" Liquidtight Flexible Conduit (LFMC)",
                    "12\"x12\" Wireway",
                    "3/4\" EMT Setscrew Connector",
                    "3/4\" EMT Coupling",
                    "1\" EMT 90° Elbow",
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="conductors",
                label="Wire & Cable",
                tone="blue",
                description=(
                    "Building wire and cable pulled into raceway, plus pre-assembled "
                    "cable (MC, NM/Romex, SER) and grounding conductors. One line per "
                    "size (AWG/kcmil) × insulation × material; note whether it is "
                    "branch, feeder, or service. Conductor footage = conduit footage "
                    "× number of conductors in the run; add ~10–15% for terminations."
                ),
                examples=[
                    "#14 THHN Copper (branch)",
                    "#12 THHN Copper (branch)",
                    "#10 THHN Copper (branch)",
                    "#12 THHN Copper Green (ground)",
                    "#8 THHN Copper (feeder/EGC)",
                    "#2 THHN Copper (feeder)",
                    "250 kcmil THHN/THWN Copper (feeder)",
                    "500 kcmil XHHW Aluminum (service)",
                    "#4/0 THHN Copper (feeder)",
                    "3/C #12 MC Cable (whip)",
                    "12-2 w/ground NM-B (Romex)",
                    "#6 Bare Copper (grounding electrode conductor)",
                ],
                typical_units=["LF", "EA"],
            ),
            BomCategory(
                key="equipment",
                label="Panels & Distribution Equipment",
                tone="violet",
                description=(
                    "Service and distribution gear read off the one-line and panel "
                    "schedules: panelboards, switchboards/switchgear, branch & main "
                    "breakers, dry-type transformers, fusible/non-fused disconnects "
                    "& safety switches, meter sockets/CT cabinets, automatic transfer "
                    "switches, motor starters/VFDs, and surge protection. Each unique "
                    "rating is its own line."
                ),
                examples=[
                    "200A Panelboard, 208Y/120V, 3Ø 4W, 42-ckt, MLO",
                    "400A Panelboard, 480Y/277V, 3Ø, main breaker",
                    "100A Panelboard, 120/240V, 1Ø, 30-ckt",
                    "20A/1P Bolt-on Circuit Breaker",
                    "100A/3P Circuit Breaker",
                    "800A Switchboard, 480Y/277V, 3Ø 4W",
                    "75 kVA Dry-Type Transformer, 480-208Y/120V",
                    "60A/3P Fusible Disconnect, NEMA 3R",
                    "200A Meter Socket / CT Cabinet",
                    "400A Automatic Transfer Switch",
                    "SPD, Type 2, 120kA",
                ],
                typical_units=["EA"],
            ),
            BomCategory(
                key="devices",
                label="Devices, Boxes & Rough-in",
                tone="gray",
                description=(
                    "Wiring devices and the rough-in hardware they mount in: "
                    "receptacles (incl. GFCI/weatherproof/range), switches (1P/3-way/"
                    "4-way), dimmers, line-voltage occupancy sensors, cover/wall "
                    "plates, and the device/outlet/junction/pull/floor boxes, mud "
                    "rings, and strut/supports. Count by type from the plan symbols "
                    "and legend."
                ),
                examples=[
                    "20A 125V Duplex Receptacle, spec grade",
                    "20A GFCI Duplex Receptacle",
                    "30A/50A Range/Dryer Receptacle",
                    "Single-Pole Toggle Switch, 20A",
                    "3-Way Switch, 20A",
                    "Decora Dimmer, 600W",
                    "Occupancy Sensor Switch",
                    "Stainless Wall Plate, 1-gang",
                    "Weatherproof In-Use Cover, 1-gang",
                    "4\" Square Steel Box, 1-1/2\" deep",
                    "4\" Octagon Ceiling Box",
                    "12\"x12\"x6\" Pull Box",
                ],
                typical_units=["EA", "LF"],
            ),
            BomCategory(
                key="lighting",
                label="Lighting Fixtures",
                tone="success",
                description=(
                    "Luminaires keyed by fixture-schedule Type letter (A, B, C…), "
                    "with lamps, LED drivers, emergency battery packs, exit signs, "
                    "and site-light poles/bases as sub-items. The description comes "
                    "from the schedule's catalog/lamp/voltage; the quantity comes "
                    "from counting the matching symbol on the lighting plan."
                ),
                examples=[
                    "Type A — 2x4 LED Recessed Troffer, 4000K, 0-10V dim",
                    "Type B — 2x2 LED Troffer",
                    "Type C — 6\" LED Recessed Downlight",
                    "Type E — 4' LED Strip / Wraparound",
                    "Type G — LED High-Bay, 150W",
                    "Type H — LED Wall Pack (exterior)",
                    "Type P — LED Pendant",
                    "Type S — Site Pole Light, 20' pole, LED area fixture",
                    "Type X — LED Exit Sign / combo emergency",
                    "Type EM — Emergency Battery Unit (\"bug eye\")",
                ],
                typical_units=["EA"],
                # Lighting/power plans are graphical — fixtures and devices are
                # symbols counted against a legend, not text — so the text layer
                # often carries no counts. Vision the lighting/power sheets.
                vision_fallback=True,
                sheet_keywords=["LIGHTING PLAN", "POWER PLAN", "ELECTRICAL PLAN"],
            ),
            BomCategory(
                key="grounding",
                label="Grounding & Bonding",
                tone="danger",
                description=(
                    "The NEC Article 250 grounding scope: grounding electrodes "
                    "(ground rods), the grounding electrode conductor (GEC) and "
                    "ground ring, bonding jumpers, ground bars/bus, clamps/lugs, "
                    "exothermic weld kits, grounding bushings, and test wells. Bare "
                    "conductor is LF; rods, lugs, clamps, weld kits, and bars are EA."
                ),
                examples=[
                    "3/4\" x 10' Copper-Clad Ground Rod",
                    "5/8\" x 8' Copper-Clad Ground Rod",
                    "#6 Bare Copper GEC",
                    "4/0 Bare Copper Ground Ring",
                    "Ground Rod Clamp (acorn), bronze",
                    "Exothermic Weld Kit (cad-weld), #4/0",
                    "Insulated Grounding Bushing, 2\"",
                    "Ground Bar Kit",
                    "2-hole Compression Lug",
                    "Ground Access / Test Well",
                ],
                typical_units=["EA", "LF"],
            ),
            BomCategory(
                key="lowvoltage",
                label="Low-Voltage & Fire Alarm",
                tone="ai",
                description=(
                    "Low-voltage and life-safety systems, broken out because code "
                    "(NEC 760 / NFPA 72) and the installer differ from power: fire "
                    "alarm (control panel, detectors, pull stations, horn/strobes, "
                    "FPLR/FPLP cable), structured cabling/data (Cat6/6A, jacks, patch "
                    "panels, racks, fiber), and security/AV (cameras, card readers, "
                    "door contacts). Devices/panels are EA; cable is LF."
                ),
                examples=[
                    "Fire Alarm Control Panel (FACP), addressable",
                    "Addressable Smoke Detector",
                    "Duct Smoke Detector",
                    "Manual Pull Station, double-action",
                    "Horn/Strobe, 75cd, wall-mount",
                    "14/2 FPLR Fire Alarm Cable",
                    "Cat6 UTP Cable (data)",
                    "Cat6 RJ45 Jack / Faceplate",
                    "24-port Patch Panel",
                    "IP Dome Camera",
                    "Card Reader / Door Contact",
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
