# Changelog

All notable changes to Proq are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) with 4-digit versions (`MAJOR.MINOR.PATCH.MICRO`).

## [0.2.0.0] - 2026-08-10

### Added
- Subcontractor sourcing: create a named trade (e.g. "Concrete flatwork") with a
  scope-of-work description in the Documents tab, then find nearby trade
  contractors with the same radius/tier search used for material suppliers —
  no preset taxonomy, any trade you type is searchable.
- Bid requests: selected subcontractors get a scope-of-work bid request
  (lump-sum price, schedule, inclusions/exclusions, bid validity) through the
  same review-and-send flow as material RFQs, badged "Sub bid" in the RFQ inbox.
- Email attachments: choose which project documents ride along on any RFQ or
  bid request. Files keep their real type, totals are capped at 15 MB per
  email, and documents deleted after drafting are dropped with a visible notice
  instead of blocking the send.

### Changed
- Trade searches steer Google Places toward installers (contractors), not
  material distributors, with a relevance hint tuned for trades.
- Generated bid-request wording no longer promises attachments that were never
  chosen.

### Fixed
- Outbound email headers (Subject, To, Cc, attachment filenames) are sanitized
  so crafted names can't inject mail headers into messages sent from the
  workspace mailbox.
- Attachment validation counts undeterminable file sizes as errors instead of
  zero bytes, and re-checks the real payload size at send time.
