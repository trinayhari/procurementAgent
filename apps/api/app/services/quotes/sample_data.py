"""Deterministic sample quotes with priced line items.

Used to seed a project so the line-by-line comparison + mix-and-match award flow
is demoable offline. Each supplier prices the *same* BOM lines (keyed by name) at
different unit prices and lead times, and quotes from different distances/freight —
so the optimizer has a real cost/lead/distance tradeoff to solve.

Numbers are tuned so a freight-aware split award genuinely beats the best single
supplier on both packages, while the farthest/most-expensive supplier wins nothing
(showing distance and delivery actually matter).
"""
from typing import Dict, List

# Per package: budget allowance + suppliers, each with the lines they quoted.
# A line = (name, qty_display, qty_num, unit, unit_price, lead_days).
SAMPLE_PACKAGES: Dict[str, dict] = {
    "water": {
        "label": "Water Utilities",
        "budget": 165_000,
        "suppliers": [
            {
                "id": "ferguson",
                "name": "Ferguson Waterworks",
                "email": "mreyes@ferguson.com",
                "logo_bg": "#0a4d8c",
                "freight": 1_800.0,
                "distance_miles": 18.0,
                "validity": "30 days",
                "lines": [
                    ('12" DI Pipe, Class 350', "2,400 LF", 2400, "LF", 41.00, 14),
                    ('12" Gate Valve, RW', "8 EA", 8, "EA", 1_900.00, 14),
                    ("Fire Hydrant Assembly", "6 EA", 6, "EA", 3_150.00, 21),
                    ('12" MJ Tee', "14 EA", 14, "EA", 455.00, 14),
                    ('12" 45° MJ Bend', "22 EA", 22, "EA", 228.00, 14),
                ],
            },
            {
                "id": "coremain",
                "name": "Core & Main",
                "email": "dwhitfield@coreandmain.com",
                "logo_bg": "#16a34a",
                "freight": 1_500.0,
                "distance_miles": 32.0,
                "validity": "30 days",
                "lines": [
                    ('12" DI Pipe, Class 350', "2,400 LF", 2400, "LF", 41.80, 16),
                    ('12" Gate Valve, RW', "8 EA", 8, "EA", 1_650.00, 16),
                    ("Fire Hydrant Assembly", "6 EA", 6, "EA", 3_400.00, 16),
                    ('12" MJ Tee', "14 EA", 14, "EA", 388.00, 16),
                    ('12" 45° MJ Bend', "22 EA", 22, "EA", 210.00, 16),
                ],
            },
            {
                "id": "fortiline",
                "name": "Fortiline Waterworks",
                "email": "lromero@fortiline.com",
                "logo_bg": "#0f766e",
                "freight": 2_400.0,
                "distance_miles": 47.0,
                "validity": "21 days",
                "lines": [
                    ('12" DI Pipe, Class 350', "2,400 LF", 2400, "LF", 43.00, 26),
                    ('12" Gate Valve, RW', "8 EA", 8, "EA", 1_880.00, 26),
                    ("Fire Hydrant Assembly", "6 EA", 6, "EA", 3_300.00, 26),
                    ('12" MJ Tee', "14 EA", 14, "EA", 470.00, 26),
                    ('12" 45° MJ Bend', "22 EA", 22, "EA", 235.00, 26),
                ],
            },
        ],
    },
    "sewer": {
        "label": "Sanitary Sewer",
        "budget": 125_000,
        "suppliers": [
            {
                "id": "coremain",
                "name": "Core & Main",
                "email": "dwhitfield@coreandmain.com",
                "logo_bg": "#16a34a",
                "freight": 1_500.0,
                "distance_miles": 32.0,
                "validity": "30 days",
                "lines": [
                    ('8" PVC SDR-35', "3,200 LF", 3200, "LF", 18.50, 12),
                    ('48" Dia. Manhole', "14 EA", 14, "EA", 2_650.00, 12),
                    ('6" PVC Lateral', "1,100 LF", 1100, "LF", 9.80, 12),
                    ("Frame & Cover", "14 EA", 14, "EA", 540.00, 12),
                ],
            },
            {
                "id": "hdsupply",
                "name": "HD Supply Waterworks",
                "email": "priya.anand@hdsupply.com",
                "logo_bg": "#b45309",
                "freight": 1_200.0,
                "distance_miles": 24.0,
                "validity": "30 days",
                "lines": [
                    ('8" PVC SDR-35', "3,200 LF", 3200, "LF", 19.20, 10),
                    ('48" Dia. Manhole', "14 EA", 14, "EA", 2_480.00, 10),
                    ('6" PVC Lateral', "1,100 LF", 1100, "LF", 10.40, 10),
                    ("Frame & Cover", "14 EA", 14, "EA", 495.00, 10),
                ],
            },
        ],
    },
}


def build_quote_payloads(package_key: str) -> List[dict]:
    """Return create_quote(**payload)-ready dicts for one package's sample suppliers."""
    spec = SAMPLE_PACKAGES.get(package_key)
    if not spec:
        return []
    payloads: List[dict] = []
    for sup in spec["suppliers"]:
        line_items = []
        material = 0.0
        lead = 0
        for name, qty, qty_num, unit, unit_price, line_lead in sup["lines"]:
            extended = round(unit_price * qty_num, 2)
            material += extended
            lead = max(lead, line_lead)
            line_items.append(
                {
                    "name": name,
                    "qty": qty,
                    "qtyNum": qty_num,
                    "unit": unit,
                    "unitPrice": unit_price,
                    "extended": extended,
                    "leadDays": line_lead,
                }
            )
        material = round(material, 2)
        total = round(material + sup["freight"], 2)
        payloads.append(
            {
                "package": package_key,
                "package_label": spec["label"],
                "supplier_id": sup["id"],
                "supplier_name": sup["name"],
                "supplier_email": sup["email"],
                "material_cost": material,
                "freight": sup["freight"],
                "total": total,
                "lead_days": lead,
                "validity": sup["validity"],
                "distance_miles": sup["distance_miles"],
                "line_items": line_items,
                "notes": "Sample quote seeded for the comparison demo.",
                "source": "sample",
                "status": "received",
            }
        )
    return payloads


def budget_for(package_key: str) -> float:
    spec = SAMPLE_PACKAGES.get(package_key)
    return float(spec["budget"]) if spec else 0.0
