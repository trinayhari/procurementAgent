"""In-memory seed data mirroring the frontend's src/model.js.

This is the phase-1 data source: plain Python structures that the routes return
directly (FastAPI validates them against the response schemas). Swapping this for
a real database later only requires reimplementing the accessor functions below.
"""
from typing import Dict, List

# --------------------------------------------------------------------- dashboard
METRICS: List[dict] = [
    {"label": "Active Projects", "value": "5", "delta": "+2", "up": True, "sub": "this quarter"},
    {"label": "Active RFQs", "value": "20", "delta": "+6", "up": True, "sub": "5 projects"},
    {"label": "Pending Quotes", "value": "14", "delta": "4 due soon", "sub": ""},
    {"label": "Total Material Spend", "value": "$35.3M", "delta": "+8.1%", "up": True, "sub": "committed"},
    {"label": "Potential Savings", "value": "$1.84M", "delta": "5.2%", "up": True, "sub": "identified", "ai": True},
    {"label": "Procurement Risks", "value": "3", "delta": "2 high", "down": True, "sub": "need review", "risk": True},
]

ACTIVITY: List[dict] = [
    {"icon": "quote", "tone": "success", "title": "Quote received from Ferguson", "meta": "Water Utilities · Riverside WTP", "time": "12m"},
    {"icon": "quote", "tone": "success", "title": "Quote received from Core & Main", "meta": "Water Utilities · Riverside WTP", "time": "35m"},
    {"icon": "sparkles", "tone": "ai", "title": "AI found $1,620 split-award saving", "meta": "Water Utilities · Riverside WTP", "time": "40m"},
    {"icon": "quote", "tone": "success", "title": "Quote received from HD Supply", "meta": "Sanitary Sewer · Riverside WTP", "time": "2h"},
    {"icon": "truck", "tone": "blue", "title": "Delivery schedule updated", "meta": "Storm Drain · Eastgate", "time": "5h"},
    {"icon": "sparkles", "tone": "ai", "title": "AI extracted 142 line items", "meta": "Civil Site Plan Rev 3 · Riverside", "time": "1d"},
]

# --------------------------------------------------------------------- projects
PROJECTS: List[dict] = [
    {"id": "riverside", "name": "Riverside Water Treatment Plant", "loc": "Sacramento, CA", "stage": "Quotes In", "stageTone": "violet", "value": "$4.2M", "progress": 78, "suppliers": 12, "rfqs": 6, "quotes": 5, "risk": "Medium", "riskTone": "warn", "barColor": "var(--primary)"},
    {"id": "eastgate", "name": "Eastgate Mixed-Use Development", "loc": "Austin, TX", "stage": "Quotes In", "stageTone": "violet", "value": "$8.7M", "progress": 82, "suppliers": 18, "rfqs": 3, "quotes": 14, "risk": "Low", "riskTone": "success", "barColor": "var(--violet)"},
    {"id": "hwy50", "name": "Highway 50 Interchange", "loc": "Reno, NV", "stage": "Plans Review", "stageTone": "gray", "value": "$12.1M", "progress": 24, "suppliers": 6, "rfqs": 8, "quotes": 2, "risk": "High", "riskTone": "danger", "barColor": "var(--danger)"},
    {"id": "maple", "name": "Maple Grove Subdivision", "loc": "Boise, ID", "stage": "Complete", "stageTone": "success", "value": "$3.4M", "progress": 100, "suppliers": 9, "rfqs": 0, "quotes": 11, "risk": "Low", "riskTone": "success", "barColor": "var(--success)"},
    {"id": "cedar", "name": "Cedar Point Logistics Hub", "loc": "Phoenix, AZ", "stage": "Sourcing", "stageTone": "blue", "value": "$6.9M", "progress": 45, "suppliers": 11, "rfqs": 4, "quotes": 5, "risk": "Medium", "riskTone": "warn", "barColor": "var(--primary)"},
]

# Workspace detail (only Riverside is fleshed out in the prototype).
OVERVIEW_CARDS: List[dict] = [
    {"label": "Documents", "value": "6", "sub": "4 analyzed", "icon": "file", "tone": "blue"},
    {"label": "Suppliers Found", "value": "12", "sub": "4 quoted", "icon": "supplier", "tone": "violet"},
    {"label": "RFQs Sent", "value": "6", "sub": "5 quoted", "icon": "rfq", "tone": "blue"},
    {"label": "Quotes Received", "value": "5", "sub": "2 packages", "icon": "quote", "tone": "success"},
    {"label": "Savings Identified", "value": "$31.8K", "sub": "AI mix & match", "icon": "sparkles", "tone": "ai", "ai": True},
]

PACKAGES: List[dict] = [
    {"name": "Water Utilities", "pct": 100, "tone": "success"},
    {"name": "Sanitary Sewer", "pct": 100, "tone": "success"},
    {"name": "Storm Drain", "pct": 45, "tone": "warn"},
    {"name": "Electrical", "pct": 25, "tone": "gray"},
]

# --------------------------------------------------------------------- suppliers
SUPPLIERS: List[dict] = [
    {"id": "ferguson", "name": "Ferguson Waterworks", "cats": ["Water", "Fire"], "contact": "Mark Reyes", "phone": "(916) 555-0142", "email": "mreyes@ferguson.com", "web": "ferguson.com", "rfq": "Quoted", "rfqTone": "success", "last": "12m ago", "quotes": "1", "quoteVal": "$145.7K", "lead": "21 days", "logo": "FW", "logoBg": "#0a4d8c", "fin": {"submitted": "1", "total": "$145,686", "avg": "21 days"}},
    {"id": "coremain", "name": "Core & Main", "cats": ["Water", "Sewer"], "contact": "Dana Whitfield", "phone": "(916) 555-0188", "email": "dwhitfield@coreandmain.com", "web": "coreandmain.com", "rfq": "Quoted", "rfqTone": "success", "last": "35m ago", "quotes": "2", "quoteVal": "$261.6K", "lead": "14 days", "logo": "C&M", "logoBg": "#16a34a", "fin": {"submitted": "2", "total": "$261,612", "avg": "14 days"}},
    {"id": "fortiline", "name": "Fortiline Waterworks", "cats": ["Water", "Storm"], "contact": "Luis Romero", "phone": "(775) 555-0119", "email": "lromero@fortiline.com", "web": "fortiline.com", "rfq": "Quoted", "rfqTone": "success", "last": "1h ago", "quotes": "1", "quoteVal": "$152.2K", "lead": "26 days", "logo": "FL", "logoBg": "#0f766e", "fin": {"submitted": "1", "total": "$152,190", "avg": "26 days"}},
    {"id": "hdsupply", "name": "HD Supply Waterworks", "cats": ["Water", "Sewer"], "contact": "Priya Anand", "phone": "(602) 555-0173", "email": "priya.anand@hdsupply.com", "web": "hdsupply.com", "rfq": "Quoted", "rfqTone": "success", "last": "2h ago", "quotes": "1", "quoteVal": "$115.7K", "lead": "10 days", "logo": "HD", "logoBg": "#b45309", "fin": {"submitted": "1", "total": "$115,730", "avg": "10 days"}},
    {"id": "wesco", "name": "WESCO Distribution", "cats": ["Electrical"], "contact": "Greg Tan", "phone": "(916) 555-0150", "email": "gtan@wesco.com", "web": "wesco.com", "rfq": "Sent", "rfqTone": "blue", "last": "Sent 2d ago", "quotes": "0", "quoteVal": "—", "lead": "—", "logo": "WE", "logoBg": "#334155", "fin": {"submitted": "0", "total": "—", "avg": "—"}},
    {"id": "graybar", "name": "Graybar Electric", "cats": ["Electrical"], "contact": "Sara Lin", "phone": "(775) 555-0166", "email": "slin@graybar.com", "web": "graybar.com", "rfq": "Draft", "rfqTone": "gray", "last": "—", "quotes": "0", "quoteVal": "—", "lead": "—", "logo": "GB", "logoBg": "#7c3aed", "fin": {"submitted": "0", "total": "—", "avg": "—"}},
]

SUPPLIER_COMMS: List[dict] = [
    {"tone": "success", "title": "Quote submitted — Water Utilities", "body": "$145,686 total · 21-day lead · Quote-RV-Water.pdf", "time": "Today · 9:42 AM", "icon": "quote"},
    {"tone": "blue", "title": "Follow-up email sent", "body": "Requested confirmation on DI pipe class and hydrant lead times.", "time": "Yesterday · 4:10 PM", "icon": "rfq"},
    {"tone": "success", "title": "Email received", "body": '"We can confirm Class 350 DI. Hydrants ship in ~3 weeks." — Mark Reyes', "time": "Yesterday · 2:30 PM", "icon": "rfq"},
    {"tone": "violet", "title": "RFQ sent — Water Utilities package", "body": "42 line items · due Jun 20", "time": "Jun 12 · 11:05 AM", "icon": "sparkles"},
]

# --------------------------------------------------------------------- documents
# Documents are scoped to a project via `projectId`. Only Riverside is fleshed out
# in the prototype seed; every other (and newly created) project starts with an
# empty document list until plan sets are uploaded to it.
DOCUMENTS: List[dict] = [
    {"id": "civil-site-r3", "projectId": "riverside", "name": "Civil Site Plan — Rev 3", "type": "Civil Plans", "date": "Jun 12, 2026", "status": "Analyzed", "statusTone": "success", "items": "142", "pages": 24},
    {"id": "utility-water-sewer", "projectId": "riverside", "name": "Utility Plan — Water & Sewer", "type": "Utility Plans", "date": "Jun 11, 2026", "status": "Analyzed", "statusTone": "success", "items": "88", "pages": 12},
    {"id": "storm-drainage", "projectId": "riverside", "name": "Storm Drainage Plan", "type": "Civil Plans", "date": "Jun 11, 2026", "status": "Analyzed", "statusTone": "success", "items": "46", "pages": 8},
    {"id": "electrical-single-line", "projectId": "riverside", "name": "Electrical Single-Line", "type": "Electrical Plans", "date": "Jun 10, 2026", "status": "Processing", "statusTone": "blue", "items": "—", "pages": 6, "processing": True},
    {"id": "project-specs", "projectId": "riverside", "name": "Project Specifications", "type": "Specifications", "date": "Jun 9, 2026", "status": "Analyzed", "statusTone": "success", "items": "—", "pages": 210},
    {"id": "addendum-02", "projectId": "riverside", "name": "Addendum 02", "type": "Addenda", "date": "Jun 14, 2026", "status": "Queued", "statusTone": "gray", "items": "—", "pages": 4},
]

LINE_ITEMS: List[dict] = [
    {"group": "Water Materials", "count": 42, "tone": "blue", "items": [{"n": '12" DI Pipe, Class 350', "q": "2,400 LF"}, {"n": '12" Gate Valve, RW', "q": "8 EA"}, {"n": "Fire Hydrant Assembly", "q": "6 EA"}, {"n": '12" MJ Tee', "q": "14 EA"}, {"n": '12" 45° MJ Bend', "q": "22 EA"}]},
    {"group": "Sewer Materials", "count": 31, "tone": "violet", "items": [{"n": '8" PVC SDR-35', "q": "3,200 LF"}, {"n": '48" Dia. Manhole', "q": "14 EA"}, {"n": '6" PVC Lateral', "q": "1,100 LF"}, {"n": "Frame & Cover", "q": "14 EA"}]},
    {"group": "Storm Materials", "count": 46, "tone": "success", "items": [{"n": '24" RCP, Class III', "q": "1,800 LF"}, {"n": "Type A Catch Basin", "q": "22 EA"}, {"n": '18" RCP', "q": "900 LF"}, {"n": "Storm Manhole", "q": "9 EA"}]},
    {"group": "Electrical Materials", "count": 23, "tone": "warn", "items": [{"n": '4" PVC Conduit, Sch 40', "q": "5,000 LF"}, {"n": "#2 AWG Cu Conductor", "q": "12,000 LF"}, {"n": "Pull Box, 24×36", "q": "12 EA"}]},
]

# --------------------------------------------------------------------- quotes
QUOTES: List[dict] = [
    {"id": "q-cm-water", "sup": "Core & Main", "pkg": "Water Utilities", "amount": "$143,972", "freight": "$1,500", "total": "$145,472", "lead": "16 days", "date": "Jun 18", "logo": "C&M", "logoBg": "#16a34a", "best": True},
    {"id": "q-fw-water", "sup": "Ferguson Waterworks", "pkg": "Water Utilities", "amount": "$143,886", "freight": "$1,800", "total": "$145,686", "lead": "21 days", "date": "Jun 19", "logo": "FW", "logoBg": "#0a4d8c"},
    {"id": "q-fl-water", "sup": "Fortiline Waterworks", "pkg": "Water Utilities", "amount": "$149,790", "freight": "$2,400", "total": "$152,190", "lead": "26 days", "date": "Jun 17", "logo": "FL", "logoBg": "#0f766e"},
    {"id": "q-hd-sewer", "sup": "HD Supply Waterworks", "pkg": "Sanitary Sewer", "amount": "$114,530", "freight": "$1,200", "total": "$115,730", "lead": "10 days", "date": "Jun 19", "logo": "HD", "logoBg": "#b45309", "best": True},
    {"id": "q-cm-sewer", "sup": "Core & Main", "pkg": "Sanitary Sewer", "amount": "$114,640", "freight": "$1,500", "total": "$116,140", "lead": "12 days", "date": "Jun 18", "logo": "C&M", "logoBg": "#16a34a"},
]

# Comparison matrix, keyed by package label. (Riverside reads the live, quote-
# driven comparison; these are the fallback for packages with no ingested quotes.)
COMPARISONS: Dict[str, dict] = {
    "Water Utilities": {
        "pkg": "Water Utilities",
        "suppliers": [
            {"name": "Core & Main", "logo": "C&M", "logoBg": "#16a34a", "rec": True},
            {"name": "Ferguson Waterworks", "logo": "FW", "logoBg": "#0a4d8c", "rec": False},
            {"name": "Fortiline Waterworks", "logo": "FL", "logoBg": "#0f766e", "rec": False},
        ],
        "rows": [
            {"label": "Material Cost", "vals": ["$143,972", "$143,886", "$149,790"], "best": 1},
            {"label": "Freight", "vals": ["$1,500", "$1,800", "$2,400"], "best": 0},
            {"label": "Total Cost", "vals": ["$145,472", "$145,686", "$152,190"], "best": 0, "emph": True},
            {"label": "Lead Time", "vals": ["16 days", "21 days", "26 days"], "best": 0},
            {"label": "Risk Score", "vals": ["84 · Med", "79 · Med", "74 · Med"], "best": 0},
        ],
        "recommendation": "Core & Main",
        "reasons": [
            "Lowest total bid",
            "Strong 16-day lead time",
            "Best risk score (84)",
        ],
        "savings": "$6,718",
        "savingsNote": "4% below the highest competing bid",
    },
    "Sanitary Sewer": {
        "pkg": "Sanitary Sewer",
        "suppliers": [
            {"name": "HD Supply Waterworks", "logo": "HD", "logoBg": "#b45309", "rec": True},
            {"name": "Core & Main", "logo": "C&M", "logoBg": "#16a34a", "rec": False},
        ],
        "rows": [
            {"label": "Material Cost", "vals": ["$114,530", "$114,640"], "best": 0},
            {"label": "Freight", "vals": ["$1,200", "$1,500"], "best": 0},
            {"label": "Total Cost", "vals": ["$115,730", "$116,140"], "best": 0, "emph": True},
            {"label": "Lead Time", "vals": ["10 days", "12 days"], "best": 0},
            {"label": "Risk Score", "vals": ["90 · Low", "88 · Low"], "best": 0},
        ],
        "recommendation": "HD Supply Waterworks",
        "reasons": [
            "Lowest total bid",
            "Fastest lead time at 10 days",
            "Lowest delivery risk (score 90)",
        ],
        "savings": "$410",
        "savingsNote": "0.4% below the competing bid",
    },
}

# --------------------------------------------------------------------- rfqs
RFQS: List[dict] = [
    {"id": "rfq-cm-water", "sup": "Core & Main", "pkg": "Water Utilities", "folder": "Completed", "status": "Quoted", "statusTone": "success", "preview": "Quote attached — $145,472 · 16-day lead", "time": "35m", "unread": True, "logo": "C&M", "logoBg": "#16a34a", "qTotal": "$145,472", "qLead": "16-day"},
    {"id": "rfq-fw-water", "sup": "Ferguson Waterworks", "pkg": "Water Utilities", "folder": "Completed", "status": "Quoted", "statusTone": "success", "preview": "Quote attached — $145,686 · 21-day lead", "time": "12m", "unread": False, "logo": "FW", "logoBg": "#0a4d8c", "qTotal": "$145,686", "qLead": "21-day"},
    {"id": "rfq-fl-water", "sup": "Fortiline Waterworks", "pkg": "Water Utilities", "folder": "Completed", "status": "Quoted", "statusTone": "success", "preview": "Quote attached — $152,190 · 26-day lead", "time": "1h", "unread": False, "logo": "FL", "logoBg": "#0f766e", "qTotal": "$152,190", "qLead": "26-day"},
    {"id": "rfq-hd-sewer", "sup": "HD Supply Waterworks", "pkg": "Sanitary Sewer", "folder": "Completed", "status": "Quoted", "statusTone": "success", "preview": "Quote attached — $115,730 · 10-day lead", "time": "2h", "unread": True, "logo": "HD", "logoBg": "#b45309", "qTotal": "$115,730", "qLead": "10-day"},
    {"id": "rfq-cm-sewer", "sup": "Core & Main", "pkg": "Sanitary Sewer", "folder": "Completed", "status": "Quoted", "statusTone": "success", "preview": "Quote attached — $116,140 · 12-day lead", "time": "1h", "unread": False, "logo": "C&M", "logoBg": "#16a34a", "qTotal": "$116,140", "qLead": "12-day"},
    {"id": "rfq-we-elec", "sup": "WESCO Distribution", "pkg": "Electrical", "folder": "Sent", "status": "Sent", "statusTone": "blue", "preview": "RFQ sent — 23 line items", "time": "2d", "unread": False, "logo": "WE", "logoBg": "#334155"},
    {"id": "rfq-gb-elec", "sup": "Graybar Electric", "pkg": "Electrical", "folder": "Draft", "status": "Draft", "statusTone": "gray", "preview": "Draft — not yet sent", "time": "—", "unread": False, "logo": "GB", "logoBg": "#7c3aed"},
]

RFQ_FOLDERS: List[dict] = [
    {"name": "Draft", "count": "1"},
    {"name": "Sent", "count": "1"},
    {"name": "Awaiting Response", "count": "0"},
    {"name": "Completed", "count": "5"},
]

# Line-item count per package (mirrors LINE_ITEMS group counts) for the thread copy.
_PKG_LINES: Dict[str, int] = {
    "Water Utilities": 42, "Sanitary Sewer": 31, "Storm Drain": 46, "Electrical": 23,
}


def _thread_for(rfq: dict) -> List[dict]:
    """Build the email thread for an RFQ, parameterized by supplier/package/quote."""
    sup, pkg, logo, logo_bg = rfq["sup"], rfq["pkg"], rfq["logo"], rfq["logoBg"]
    lines = _PKG_LINES.get(pkg, 42)
    stub = pkg.split()[0]
    thread = [
        {"dir": "out", "who": "You · ProcureAI", "initials": "JM", "time": "Jun 12 · 11:05 AM", "subject": "RFQ: " + pkg + " — Riverside WTP", "body": f"Please find attached our request for quote covering the {pkg} package for the Riverside Water Treatment Plant. {lines} line items, quotes due Jun 20. Let us know if any specs need clarification.", "attach": f"RFQ-Riverside-{stub}.pdf"},
    ]
    if rfq.get("qTotal"):
        thread += [
            {"dir": "in", "who": sup, "initials": logo, "logoBg": logo_bg, "time": "Jun 13 · 2:30 PM", "body": "Thanks — reviewing now. Can you confirm specs on the priced line items?"},
            {"dir": "out", "who": "You · ProcureAI", "initials": "JM", "time": "Jun 13 · 3:10 PM", "body": "Confirmed per spec section 02510. Appreciate the quick turnaround."},
            {"dir": "in", "who": sup, "initials": logo, "logoBg": logo_bg, "time": "Today · 9:42 AM", "body": f"Quote attached. Total comes to {rfq['qTotal']} with a {rfq['qLead']} lead time.", "attach": f"Quote-RV-{stub}.pdf"},
        ]
    else:
        thread += [
            {"dir": "in", "who": sup, "initials": logo, "logoBg": logo_bg, "time": "Jun 13 · 2:30 PM", "body": "Received — we'll get pricing back to you shortly."},
        ]
    return thread


# --------------------------------------------------------------------- timeline
MILESTONES: List[dict] = [
    {"name": "Documents Uploaded", "date": "Jun 9", "status": "Done", "desc": "6 plan sets ingested", "tone": "success", "done": True},
    {"name": "AI Extraction Complete", "date": "Jun 12", "status": "Done", "desc": "307 line items · 4 packages", "tone": "success", "done": True},
    {"name": "RFQs Generated", "date": "Jun 13", "status": "Done", "desc": "2 packages → 5 suppliers", "tone": "success", "done": True},
    {"name": "Quotes Received", "date": "Jun 19", "status": "Done", "desc": "5 of 5 received · Water + Sewer", "tone": "success", "done": True},
    {"name": "Supplier Selected", "date": "Due Jun 24", "status": "In Progress", "desc": "Water + Sewer awards ready", "tone": "blue", "active": True},
    {"name": "Purchase Order Issued", "date": "Jun 27", "status": "Upcoming", "desc": "Pending award", "tone": "gray"},
    {"name": "Delivery Scheduled", "date": "Jul 4", "status": "Upcoming", "desc": "Materials on-site", "tone": "gray"},
]

GANTT: List[dict] = [
    {"name": "Documents & Extraction", "start": 0, "len": 18, "tone": "success", "label": "Done"},
    {"name": "Water Utilities RFQ", "start": 14, "len": 26, "tone": "success", "label": "Quoted"},
    {"name": "Sanitary Sewer RFQ", "start": 22, "len": 30, "tone": "success", "label": "Quoted"},
    {"name": "Storm Drain RFQ", "start": 26, "len": 36, "tone": "blue", "label": "Sent"},
    {"name": "Electrical RFQ", "start": 36, "len": 30, "tone": "gray", "label": "Sent"},
    {"name": "Water Delivery", "start": 64, "len": 14, "tone": "violet", "label": "Jul 4"},
]

GANTT_COLS: List[str] = ["Jun W2", "Jun W3", "Jun W4", "Jul W1", "Jul W2"]


# ============================================================== seeding source
# Every collection above is now persisted in SQLite — see app/models/ and the
# repositories (projects, documents, suppliers, reference). These literals are
# ONLY the starter data loaded into the DB on first run (see each repo's
# seed_* function); routes read exclusively from the DB. `_thread_for` builds
# the email thread seeded onto each demo RFQ.
