"""In-memory seed data mirroring the frontend's src/model.js.

This is the phase-1 data source: plain Python structures that the routes return
directly (FastAPI validates them against the response schemas). Swapping this for
a real database later only requires reimplementing the accessor functions below.
"""
from typing import Dict, List, Optional

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
    {"icon": "rfq", "tone": "blue", "title": "RFQ sent to Core & Main", "meta": "Sanitary Sewer · Riverside WTP", "time": "1h"},
    {"icon": "check", "tone": "success", "title": "Water Utilities package approved", "meta": "Riverside WTP · by you", "time": "3h"},
    {"icon": "truck", "tone": "blue", "title": "Delivery schedule updated", "meta": "Storm Drain · Eastgate", "time": "5h"},
    {"icon": "supplier", "tone": "violet", "title": "New supplier added — HD Supply", "meta": "Cedar Point Logistics Hub", "time": "1d"},
    {"icon": "sparkles", "tone": "ai", "title": "AI extracted 142 line items", "meta": "Civil Site Plan Rev 3 · Riverside", "time": "1d"},
]

# --------------------------------------------------------------------- projects
PROJECTS: List[dict] = [
    {"id": "riverside", "name": "Riverside Water Treatment Plant", "loc": "Sacramento, CA", "stage": "RFQs Out", "stageTone": "blue", "value": "$4.2M", "progress": 68, "suppliers": 12, "rfqs": 5, "quotes": 9, "risk": "Medium", "riskTone": "warn", "barColor": "var(--primary)"},
    {"id": "eastgate", "name": "Eastgate Mixed-Use Development", "loc": "Austin, TX", "stage": "Quotes In", "stageTone": "violet", "value": "$8.7M", "progress": 82, "suppliers": 18, "rfqs": 3, "quotes": 14, "risk": "Low", "riskTone": "success", "barColor": "var(--violet)"},
    {"id": "hwy50", "name": "Highway 50 Interchange", "loc": "Reno, NV", "stage": "Plans Review", "stageTone": "gray", "value": "$12.1M", "progress": 24, "suppliers": 6, "rfqs": 8, "quotes": 2, "risk": "High", "riskTone": "danger", "barColor": "var(--danger)"},
    {"id": "maple", "name": "Maple Grove Subdivision", "loc": "Boise, ID", "stage": "Complete", "stageTone": "success", "value": "$3.4M", "progress": 100, "suppliers": 9, "rfqs": 0, "quotes": 11, "risk": "Low", "riskTone": "success", "barColor": "var(--success)"},
    {"id": "cedar", "name": "Cedar Point Logistics Hub", "loc": "Phoenix, AZ", "stage": "Sourcing", "stageTone": "blue", "value": "$6.9M", "progress": 45, "suppliers": 11, "rfqs": 4, "quotes": 5, "risk": "Medium", "riskTone": "warn", "barColor": "var(--primary)"},
]

# Workspace detail (only Riverside is fleshed out in the prototype).
OVERVIEW_CARDS: List[dict] = [
    {"label": "Documents", "value": "6", "sub": "4 analyzed", "icon": "file", "tone": "blue"},
    {"label": "Suppliers Found", "value": "12", "sub": "6 quoted", "icon": "supplier", "tone": "violet"},
    {"label": "RFQs Sent", "value": "5", "sub": "3 awaiting", "icon": "rfq", "tone": "blue"},
    {"label": "Quotes Received", "value": "9", "sub": "2 packages", "icon": "quote", "tone": "success"},
    {"label": "Savings Identified", "value": "$184K", "sub": "AI-identified", "icon": "sparkles", "tone": "ai", "ai": True},
]

PACKAGES: List[dict] = [
    {"name": "Water Utilities", "pct": 90, "tone": "success"},
    {"name": "Sanitary Sewer", "pct": 75, "tone": "blue"},
    {"name": "Storm Drain", "pct": 100, "tone": "success"},
    {"name": "Electrical", "pct": 40, "tone": "warn"},
]

# --------------------------------------------------------------------- suppliers
SUPPLIERS: List[dict] = [
    {"id": "ferguson", "name": "Ferguson Waterworks", "cats": ["Water", "Fire"], "contact": "Mark Reyes", "phone": "(916) 555-0142", "email": "mreyes@ferguson.com", "web": "ferguson.com", "rfq": "Quoted", "rfqTone": "success", "last": "12m ago", "quotes": "3", "quoteVal": "$495.6K", "lead": "14 days", "logo": "FW", "logoBg": "#0a4d8c", "fin": {"submitted": "3", "total": "$495,600", "avg": "14 days"}},
    {"id": "coremain", "name": "Core & Main", "cats": ["Water", "Sewer"], "contact": "Dana Whitfield", "phone": "(916) 555-0188", "email": "dwhitfield@coreandmain.com", "web": "coreandmain.com", "rfq": "Quoted", "rfqTone": "success", "last": "1h ago", "quotes": "2", "quoteVal": "$727.2K", "lead": "16 days", "logo": "C&M", "logoBg": "#16a34a", "fin": {"submitted": "2", "total": "$727,200", "avg": "14 days"}},
    {"id": "fortiline", "name": "Fortiline Waterworks", "cats": ["Water", "Storm"], "contact": "Luis Romero", "phone": "(775) 555-0119", "email": "lromero@fortiline.com", "web": "fortiline.com", "rfq": "Quoted", "rfqTone": "success", "last": "2h ago", "quotes": "1", "quoteVal": "$490.7K", "lead": "26 days", "logo": "FL", "logoBg": "#0f766e", "fin": {"submitted": "1", "total": "$490,700", "avg": "26 days"}},
    {"id": "hdsupply", "name": "HD Supply Waterworks", "cats": ["Water", "Sewer"], "contact": "Priya Anand", "phone": "(602) 555-0173", "email": "priya.anand@hdsupply.com", "web": "hdsupply.com", "rfq": "Awaiting", "rfqTone": "warn", "last": "Sent 1d ago", "quotes": "0", "quoteVal": "—", "lead": "—", "logo": "HD", "logoBg": "#b45309", "fin": {"submitted": "0", "total": "—", "avg": "—"}},
    {"id": "wesco", "name": "WESCO Distribution", "cats": ["Electrical"], "contact": "Greg Tan", "phone": "(916) 555-0150", "email": "gtan@wesco.com", "web": "wesco.com", "rfq": "Sent", "rfqTone": "blue", "last": "Sent 2d ago", "quotes": "0", "quoteVal": "—", "lead": "—", "logo": "WE", "logoBg": "#334155", "fin": {"submitted": "0", "total": "—", "avg": "—"}},
    {"id": "graybar", "name": "Graybar Electric", "cats": ["Electrical"], "contact": "Sara Lin", "phone": "(775) 555-0166", "email": "slin@graybar.com", "web": "graybar.com", "rfq": "Draft", "rfqTone": "gray", "last": "—", "quotes": "0", "quoteVal": "—", "lead": "—", "logo": "GB", "logoBg": "#7c3aed", "fin": {"submitted": "0", "total": "—", "avg": "—"}},
]

SUPPLIER_COMMS: List[dict] = [
    {"tone": "success", "title": "Quote submitted — Water Utilities", "body": "$495,600 total · 14-day lead · Quote-RV-Water.pdf", "time": "Today · 9:42 AM", "icon": "quote"},
    {"tone": "blue", "title": "Follow-up email sent", "body": "Requested confirmation on DI pipe class and hydrant lead times.", "time": "Yesterday · 4:10 PM", "icon": "rfq"},
    {"tone": "success", "title": "Email received", "body": '"We can confirm Class 350 DI. Hydrants ship in ~2 weeks." — Mark Reyes', "time": "Yesterday · 2:30 PM", "icon": "rfq"},
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
    {"id": "q-fw-water", "sup": "Ferguson Waterworks", "pkg": "Water Utilities", "amount": "$487,200", "freight": "$8,400", "total": "$495,600", "lead": "14 days", "date": "Jun 14", "logo": "FW", "logoBg": "#0a4d8c", "best": True},
    {"id": "q-cm-water", "sup": "Core & Main", "pkg": "Water Utilities", "amount": "$502,800", "freight": "$6,200", "total": "$509,000", "lead": "16 days", "date": "Jun 13", "logo": "C&M", "logoBg": "#16a34a"},
    {"id": "q-fl-water", "sup": "Fortiline Waterworks", "pkg": "Water Utilities", "amount": "$478,900", "freight": "$11,800", "total": "$490,700", "lead": "26 days", "date": "Jun 15", "logo": "FL", "logoBg": "#0f766e"},
    {"id": "q-cm-sewer", "sup": "Core & Main", "pkg": "Sanitary Sewer", "amount": "$214,300", "freight": "$3,900", "total": "$218,200", "lead": "12 days", "date": "Jun 13", "logo": "C&M", "logoBg": "#16a34a"},
    {"id": "q-hd-sewer", "sup": "HD Supply Waterworks", "pkg": "Sanitary Sewer", "amount": "$221,750", "freight": "$2,800", "total": "$224,550", "lead": "10 days", "date": "Jun 16", "logo": "HD", "logoBg": "#b45309"},
]

# Comparison matrix, keyed by package name.
COMPARISONS: Dict[str, dict] = {
    "Water Utilities": {
        "pkg": "Water Utilities",
        "suppliers": [
            {"name": "Ferguson Waterworks", "logo": "FW", "logoBg": "#0a4d8c", "rec": True},
            {"name": "Core & Main", "logo": "C&M", "logoBg": "#16a34a", "rec": False},
            {"name": "Fortiline Waterworks", "logo": "FL", "logoBg": "#0f766e", "rec": False},
        ],
        "rows": [
            {"label": "Material Cost", "vals": ["$487,200", "$502,800", "$478,900"], "best": 2},
            {"label": "Freight", "vals": ["$8,400", "$6,200", "$11,800"], "best": 1},
            {"label": "Total Cost", "vals": ["$495,600", "$509,000", "$490,700"], "best": 2, "emph": True},
            {"label": "Lead Time", "vals": ["14 days", "16 days", "26 days"], "best": 0},
            {"label": "Delivery Date", "vals": ["Jul 4", "Jul 6", "Jul 16"], "best": 0},
            {"label": "Risk Score", "vals": ["94 · Low", "88 · Low", "69 · Med"], "best": 0},
        ],
        "recommendation": "Ferguson Waterworks",
        "reasons": [
            "Lowest delivery risk (score 94)",
            "Fastest lead time at 14 days",
            "Within 1% of lowest total bid",
        ],
        "savings": "$184,000",
        "savingsNote": "27% under the $679.6K allowance",
    }
}

# --------------------------------------------------------------------- rfqs
RFQS: List[dict] = [
    {"id": "rfq-fw-water", "sup": "Ferguson Waterworks", "pkg": "Water Utilities", "folder": "Completed", "status": "Quoted", "statusTone": "success", "preview": "Quote attached — $495,600 · 14-day lead", "time": "12m", "unread": False, "logo": "FW", "logoBg": "#0a4d8c"},
    {"id": "rfq-cm-sewer", "sup": "Core & Main", "pkg": "Sanitary Sewer", "folder": "Awaiting", "status": "Awaiting", "statusTone": "warn", "preview": "RFQ sent — awaiting response", "time": "1h", "unread": True, "logo": "C&M", "logoBg": "#16a34a"},
    {"id": "rfq-fl-storm", "sup": "Fortiline Waterworks", "pkg": "Storm Drain", "folder": "Awaiting", "status": "Awaiting", "statusTone": "warn", "preview": "Follow-up scheduled for Jun 18", "time": "2h", "unread": False, "logo": "FL", "logoBg": "#0f766e"},
    {"id": "rfq-we-elec", "sup": "WESCO Distribution", "pkg": "Electrical", "folder": "Sent", "status": "Sent", "statusTone": "blue", "preview": "RFQ sent — 23 line items", "time": "2d", "unread": False, "logo": "WE", "logoBg": "#334155"},
    {"id": "rfq-gb-elec", "sup": "Graybar Electric", "pkg": "Electrical", "folder": "Draft", "status": "Draft", "statusTone": "gray", "preview": "Draft — not yet sent", "time": "—", "unread": False, "logo": "GB", "logoBg": "#7c3aed"},
]

RFQ_FOLDERS: List[dict] = [
    {"name": "Draft", "count": "1"},
    {"name": "Sent", "count": "1"},
    {"name": "Awaiting Response", "count": "2"},
    {"name": "Completed", "count": "1"},
]


def _thread_for(rfq: dict) -> List[dict]:
    """Build the email thread for an RFQ (mirrors model.js, parameterized by supplier/pkg)."""
    sup, pkg, logo, logo_bg = rfq["sup"], rfq["pkg"], rfq["logo"], rfq["logoBg"]
    return [
        {"dir": "out", "who": "You · ProcureAI", "initials": "JM", "time": "Jun 12 · 11:05 AM", "subject": "RFQ: " + pkg + " — Riverside WTP", "body": "Please find attached our request for quote covering the " + pkg + " package for the Riverside Water Treatment Plant. 42 line items, quotes due Jun 20. Let us know if any specs need clarification.", "attach": "RFQ-Riverside-Water.pdf"},
        {"dir": "in", "who": sup, "initials": logo, "logoBg": logo_bg, "time": "Jun 13 · 2:30 PM", "body": "Thanks — reviewing now. Can you confirm the DI pipe class on line item 4?"},
        {"dir": "out", "who": "You · ProcureAI", "initials": "JM", "time": "Jun 13 · 3:10 PM", "body": "Class 350 per spec section 02510. Appreciate the quick turnaround."},
        {"dir": "in", "who": sup, "initials": logo, "logoBg": logo_bg, "time": "Today · 9:42 AM", "body": "Quote attached. Total comes to $495,600 with a 14-day lead time. Hydrant assemblies ship in ~2 weeks.", "attach": "Quote-RV-Water.pdf"},
    ]


# --------------------------------------------------------------------- timeline
MILESTONES: List[dict] = [
    {"name": "Documents Uploaded", "date": "Jun 9", "status": "Done", "desc": "6 plan sets ingested", "tone": "success", "done": True},
    {"name": "AI Extraction Complete", "date": "Jun 12", "status": "Done", "desc": "307 line items · 4 packages", "tone": "success", "done": True},
    {"name": "RFQs Generated", "date": "Jun 13", "status": "Done", "desc": "5 packages → 12 suppliers", "tone": "success", "done": True},
    {"name": "Quotes Received", "date": "Due Jun 20", "status": "In Progress", "desc": "9 of 14 received", "tone": "blue", "active": True},
    {"name": "Supplier Selected", "date": "Jun 24", "status": "Upcoming", "desc": "Water decision ready", "tone": "gray"},
    {"name": "Purchase Order Issued", "date": "Jun 27", "status": "Upcoming", "desc": "Pending selection", "tone": "gray"},
    {"name": "Delivery Scheduled", "date": "Jul 4", "status": "Upcoming", "desc": "Water materials on-site", "tone": "gray"},
]

GANTT: List[dict] = [
    {"name": "Documents & Extraction", "start": 0, "len": 18, "tone": "success", "label": "Done"},
    {"name": "Water Utilities RFQ", "start": 14, "len": 26, "tone": "success", "label": "Quoted"},
    {"name": "Sanitary Sewer RFQ", "start": 22, "len": 30, "tone": "blue", "label": "In progress"},
    {"name": "Storm Drain RFQ", "start": 26, "len": 36, "tone": "warn", "label": "Delayed", "warn": True},
    {"name": "Electrical RFQ", "start": 36, "len": 30, "tone": "gray", "label": "Sent"},
    {"name": "Water Delivery", "start": 64, "len": 14, "tone": "violet", "label": "Jul 4"},
]

GANTT_COLS: List[str] = ["Jun W2", "Jun W3", "Jun W4", "Jul W1", "Jul W2"]


# ============================================================== accessor helpers
# NB: projects are persisted in SQLite — see app/repositories/projects.py. The
# PROJECTS list above is only the starter seed loaded into the DB on first run.
def get_supplier(supplier_id: str) -> Optional[dict]:
    return next((s for s in SUPPLIERS if s["id"] == supplier_id), None)


def get_rfq(rfq_id: str) -> Optional[dict]:
    return next((r for r in RFQS if r["id"] == rfq_id), None)


def get_quote(quote_id: str) -> Optional[dict]:
    return next((q for q in QUOTES if q["id"] == quote_id), None)


# NB: documents are now persisted in SQLite — see app/models/document.py and
# app/repositories/documents.py. The DOCUMENTS list above is only the starter
# seed loaded into the DB on first run; LINE_ITEMS is the shared fallback BOM
# served for seed/demo docs that have no extracted items of their own.
