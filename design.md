You are the lead engineer responsible for building gcOS, a production-ready procurement platform for general contractors.

Your task is to inspect the existing repository, understand what is already implemented, and build the system into a reliable, secure, testable production application.

Do not create a visual-only prototype. Build working backend services, persistent data models, background workflows, permissions, auditability, integrations, and end-to-end tests.

# Product Overview

gcOS helps general contractors manage construction procurement.

The core workflow is:

1. A contractor creates a construction project.
2. The contractor uploads project documents.
3. The system extracts and proposes a bill of materials.
4. The user reviews and approves the BOM.
5. Approved BOM items are grouped into procurement packages.
6. The system searches for suppliers based on each procurement package.
7. The user reviews and selects suppliers.
8. The system generates an RFQ from the package.
9. The RFQ is sent to selected suppliers.
10. The system tracks responses and follow-ups.
11. Supplier quotes are extracted and normalized.
12. The system compares quotes and recommends the best purchasing option.
13. The user approves the purchasing decision.
14. The system tracks orders and deliveries against the project schedule.

The primary workflow you must build is:

> Procurement package → supplier discovery → supplier selection → RFQ generation → RFQ delivery → supplier responses → quote comparison → recommendation.

# Core Product Principle

A supplier is searched for based on the requirements of a procurement package.

An RFQ is created from that package and sent to the selected suppliers.

The system should follow this relationship:

```text
Project
  └── Procurement Package
        ├── Approved BOM Items
        ├── Supplier Requirements
        ├── Supplier Candidates
        └── RFQ
              ├── RFQ Recipient A
              ├── RFQ Recipient B
              └── RFQ Recipient C
```

Supplier discovery must happen before RFQ sending.

The package is the source of truth for:

* Material category
* Line items
* Quantities
* Units
* Specifications
* Approved manufacturers
* Delivery location
* Required delivery date
* Quote due date
* Supplier qualification requirements
* Notes and attachments

# Required Production Workflow

## 1. Project Creation

Users can create a project with:

* Project name
* Project address
* Project type
* Description
* Start date
* Completion date
* Project budget
* Project manager
* Procurement manager
* Project status

## 2. Document Upload

Users can upload:

* Site plans
* Civil plans
* Architectural plans
* Structural plans
* Electrical plans
* Plumbing plans
* Specifications
* Project schedules
* Spreadsheets
* Existing material lists
* Quotes

Documents must:

* Be stored in object storage
* Be versioned
* Have a SHA-256 checksum
* Preserve immutable originals
* Be scoped to an organization and project
* Use signed URLs for access
* Be processed asynchronously
* Show processing status in the UI

## 3. BOM Extraction

The system should extract proposed BOM items from uploaded project documents.

Each BOM item must contain:

* Description
* Category
* Quantity
* Unit
* Manufacturer
* Model number
* Specification
* Required delivery date
* Source document
* Source page
* Source text
* Confidence score
* Extraction run
* Model name
* Prompt version
* Review status

BOM items must begin as proposed or requiring review.

Users can:

* Edit
* Approve
* Reject
* Merge
* Split
* Bulk approve
* View source evidence

Do not allow unapproved BOM items to be included in a procurement package.

## 4. Procurement Package Creation

Users can create a procurement package from approved BOM items.

A procurement package must contain:

* Project
* Package name
* Package category
* Description
* Approved BOM items
* Requested quantities
* Required delivery date
* Delivery address
* Quote due date
* Technical requirements
* Approved manufacturers
* Alternate manufacturer rules
* Supplier qualification rules
* Attachments
* Notes
* Status

Package statuses:

```text
DRAFT
READY_FOR_SUPPLIER_SEARCH
SUPPLIER_SEARCH_IN_PROGRESS
SUPPLIERS_READY_FOR_REVIEW
SUPPLIERS_SELECTED
RFQ_DRAFTED
RFQ_APPROVED
RFQ_SENT
QUOTES_PARTIAL
QUOTES_COMPLETE
RECOMMENDATION_READY
AWARDED
CANCELLED
```

Backend services must enforce valid state transitions.

## 5. Supplier Discovery

Supplier discovery must be based on the procurement package.

Create a supplier-search request containing:

* Package ID
* Material category
* Required products
* Manufacturer requirements
* Project location
* Delivery radius
* Required delivery date
* Minimum supplier requirements
* Preferred suppliers
* Excluded suppliers
* Number of suppliers requested

The search should consider:

* Whether the supplier carries the required category
* Whether the supplier serves the project region
* Whether the supplier can deliver to the project location
* Whether the supplier supports required manufacturers
* Existing contractor-supplier relationships
* Historical response rate
* Historical quote quality
* Historical delivery performance
* Verification status
* Contact information completeness
* Distance from the project
* Local supplier requirements
* Supplier risk
* Duplicate supplier records

Implement supplier discovery behind an interface.

Example:

```python
class SupplierDiscoveryProvider(Protocol):
    async def search_suppliers(
        self,
        request: SupplierSearchRequest,
    ) -> SupplierSearchResult:
        ...
```

Implement:

* A database supplier search provider
* A fake provider for testing
* A provider interface for future web or commercial supplier-search integrations

Do not tightly couple supplier discovery to one external provider.

## 6. Supplier Candidate Review

Supplier candidates must not automatically receive an RFQ.

Each candidate should show:

* Supplier name
* Address
* Distance from project
* Email
* Phone
* Website
* Categories
* Manufacturer relationships
* Verification status
* Source of discovery
* Matching package requirements
* Match score
* Match explanation
* Risk flags
* Historical performance
* Missing information

Users can:

* Select suppliers
* Reject suppliers
* Add suppliers manually
* Mark preferred suppliers
* Merge duplicates
* Edit contact details
* Request another supplier search

Preserve the reason each supplier matched the package.

## 7. Supplier Matching

Supplier ranking must not be purely generated by an LLM.

Use deterministic matching components such as:

* Category match
* Manufacturer match
* Geographic fit
* Delivery capability
* Project-date fit
* Verification status
* Historical response rate
* Historical on-time delivery rate
* Contact completeness
* Preferred-supplier bonus
* Risk penalty

The system may use an LLM to produce a readable match explanation after deterministic scores are calculated.

Example:

```text
Supplier Match Score: 87/100

Category match: 25/25
Manufacturer match: 15/20
Geographic fit: 18/20
Delivery capability: 15/15
Verification: 8/10
Historical performance: 6/10
```

## 8. RFQ Generation

Once suppliers are selected, users can generate an RFQ from the package.

The RFQ should include:

* Project name
* Project address
* Procurement package name
* Quote due date
* Delivery location
* Required delivery date
* Requested line items
* Quantities
* Units
* Specifications
* Manufacturer requirements
* Allowed substitutions
* Required quote fields
* Freight requirements
* Tax requirements
* Payment-term request
* Lead-time request
* Attachments
* Contact information
* Questions requiring supplier confirmation

The model may draft the RFQ message, but the line items and requirements must come from structured package data.

The model must not invent:

* Quantities
* Specifications
* Dates
* Manufacturer requirements
* Delivery addresses
* Commercial terms

RFQ statuses:

```text
DRAFT
AWAITING_APPROVAL
APPROVED
SENDING
SENT
PARTIALLY_FAILED
CANCELLED
COMPLETED
```

A user must approve the first outbound RFQ.

## 9. RFQ Recipients

Use an RFQRecipient record for every selected supplier.

Each recipient should track:

* RFQ
* Supplier
* Recipient email
* Contact name
* Customized message
* Included line items
* Included attachments
* Send status
* External message ID
* Sent timestamp
* Delivery status
* Response status
* Last follow-up
* Follow-up count
* Failure reason

The default MVP behavior should be:

> One procurement package → one RFQ → multiple RFQ recipients.

Support supplier-specific RFQ line items when necessary.

For example, one supplier may receive only pipe items while another receives valves and hydrants.

Do not create separate unrelated RFQ records unless the package is intentionally split.

## 10. Email Delivery

Implement an EmailProvider abstraction.

```python
class EmailProvider(Protocol):
    async def send_rfq(
        self,
        request: SendRFQRequest,
    ) -> SendRFQResult:
        ...

    async def send_follow_up(
        self,
        request: SendFollowUpRequest,
    ) -> SendFollowUpResult:
        ...
```

Implement:

* FakeEmailProvider for tests and local development
* A production provider using an environment-configured transactional email service
* Webhook handling for delivery, bounce, and failure events

Do not put provider-specific logic inside RFQ services.

Email sending must be:

* Asynchronous
* Idempotent
* Retryable
* Audited
* Tenant-scoped
* Rate-limited
* Safe from duplicate sends

Use idempotency keys such as:

```text
send_rfq:{rfq_id}:{supplier_id}:{rfq_version}
follow_up:{rfq_recipient_id}:{follow_up_number}
```

## 11. Follow-Up Automation

After an RFQ is approved and sent, the system may automatically send policy-approved follow-ups.

Follow-up configuration should include:

* Initial response deadline
* First follow-up delay
* Second follow-up delay
* Maximum number of follow-ups
* Allowed sending hours
* Weekday restrictions
* Escalation rules

Allowed automatic follow-ups:

* Reminder that the quote due date is approaching
* Request for missing quote fields
* Request for lead-time confirmation
* Request for delivery-date confirmation
* Confirmation that a file was received

Require user approval for:

* Changing quantities
* Changing requested specifications
* Sharing another supplier’s price
* Offering target pricing
* Accepting substitutions
* Negotiating contract terms
* Making purchasing commitments

Follow-up workflows must survive application restarts and multi-day delays.

Use a durable workflow system or a replaceable workflow abstraction.

## 12. Supplier Responses

Support incoming supplier responses through:

* Email webhook ingestion
* Manual message recording
* Quote upload
* Manual quote entry

Incoming messages should be:

* Linked to the correct RFQ recipient
* Linked to the supplier
* Stored as immutable communication records
* Classified
* Audited
* Displayed in the RFQ timeline

Classify responses into:

```text
QUOTE_ATTACHED
DECLINED
NEEDS_CLARIFICATION
PARTIAL_QUOTE
DELIVERY_QUESTION
SUBSTITUTION_PROPOSED
OUT_OF_OFFICE
INVALID_RESPONSE
OTHER
```

The classification may use an LLM, but the user must be able to correct it.

## 13. Quote Processing

Users or suppliers may upload quote documents.

The system should extract:

* Quote number
* Quote date
* Quote expiration date
* Supplier
* RFQ
* Line items
* Description
* Quantity
* Unit
* Unit price
* Extended price
* Manufacturer
* Model
* Freight
* Tax
* Fees
* Discount
* Subtotal
* Total
* Lead time
* Promised delivery date
* Payment terms
* Exclusions
* Substitutions
* Quote notes

Each extracted value must include:

* Source document
* Source page
* Source text
* Confidence
* Extraction run
* Model version
* Prompt version

Quote processing must detect:

* Missing package items
* Additional unrequested items
* Quantity mismatches
* Unit mismatches
* Manufacturer mismatches
* Substitutions
* Missing prices
* Missing lead times
* Missing delivery dates
* Delivery after required date
* Quote expiration before decision date
* Totals that do not reconcile
* Duplicate quotes
* Revised quote versions

Users must review and approve quote extraction before the quote becomes comparison-ready.

## 14. Quote Comparison

Create a side-by-side comparison across suppliers.

Display:

* Supplier
* Line-item coverage
* Material subtotal
* Freight
* Tax
* Fees
* Total landed cost
* Lead time
* Promised delivery date
* Required delivery date
* Schedule variance
* Missing items
* Substitutions
* Exclusions
* Payment terms
* Quote expiration
* Completeness score
* Compliance score
* Risk flags

Normalize:

* Units
* Quantities
* Currency
* Freight
* Taxes
* Manufacturer names
* Part numbers

Do not silently normalize ambiguous values. Flag them for review.

## 15. Recommendation Engine

Calculate deterministic scores for:

* Price
* Schedule
* Completeness
* Specification compliance
* Substitution risk
* Supplier reliability
* Quote validity
* Delivery risk

The recommendation should not be based on price alone.

Example:

```text
Supplier A is recommended even though it is 4.2% more expensive because Supplier B cannot meet the required delivery date and excludes freight.
```

Store:

* Score components
* Calculation version
* Weight configuration
* Recommended supplier
* Recommended quote
* Explanation
* Risks
* Alternative recommendation

The LLM may generate the readable explanation but must use the deterministic calculation as input.

## 16. Purchase Decision

Users can:

* Select the recommended supplier
* Select another supplier
* Split the package between suppliers
* Request revised quotes
* Reject all quotes
* Reopen supplier discovery
* Record negotiation results

Do not automatically purchase materials.

Create a purchase-decision or award record.

An award must record:

* Selected supplier
* Selected quote
* Awarded line items
* Awarded quantity
* Awarded price
* Decision maker
* Decision timestamp
* Approval record
* Reason
* Any deviations from the recommendation

# Architecture

Use a modular monolith.

Do not prematurely create microservices.

Recommended modules:

```text
auth
organizations
users
projects
documents
document_processing
bom
procurement_packages
suppliers
supplier_discovery
rfqs
communications
quotes
recommendations
approvals
workflows
audit
integrations
notifications
```

Business logic must live in application services, not route handlers.

Suggested structure:

```text
apps/api/
  app/
    api/
    core/
    db/
    modules/
      projects/
        models.py
        schemas.py
        repository.py
        service.py
        routes.py
      procurement_packages/
      supplier_discovery/
      suppliers/
      rfqs/
      quotes/
      recommendations/
      audit/
    integrations/
    workflows/
    workers/
    tests/
```

# Technology Stack

Use the existing project stack where reasonable.

If starting from scratch, use:

## Frontend

* Next.js
* TypeScript
* React
* Tailwind CSS
* React Query
* A professional component library
* Playwright

## Backend

* Python
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic
* PostgreSQL
* Pytest

## Infrastructure

* Docker Compose
* PostgreSQL
* Redis
* MinIO locally
* S3-compatible storage abstraction
* A durable workflow engine or replaceable workflow abstraction
* Background workers
* OpenTelemetry-compatible logging and tracing

## AI

* OpenAI API behind a model gateway
* Structured output validation
* Prompt versioning
* Fake model provider
* Model fallback support
* Request and response metadata
* Token and cost tracking

# Database Model

Implement at minimum:

```text
Organization
User
Project
ProjectMember
Document
DocumentVersion
ExtractionRun
BOMItem
BOMItemRevision
ProcurementPackage
ProcurementPackageItem
Supplier
SupplierLocation
SupplierCapability
SupplierContact
SupplierProjectRelationship
SupplierSearchRun
SupplierCandidate
SupplierCandidateDecision
RFQ
RFQVersion
RFQItem
RFQRecipient
RFQRecipientItem
Communication
FollowUpPolicy
FollowUpExecution
Quote
QuoteVersion
QuoteItem
QuoteException
Recommendation
RecommendationScore
PurchaseDecision
ApprovalRequest
AgentRun
ToolCall
AuditEvent
OutboxEvent
BackgroundJob
IntegrationConnection
```

Use UUIDs.

Include:

* organization_id
* created_at
* updated_at
* created_by where applicable
* row version for concurrency-sensitive records
* archived_at where soft deletion is appropriate

Add database constraints for domain rules.

# Multi-Tenancy and Security

This is a multi-tenant production system.

Enforce:

* Organization scoping on every query
* Project membership checks
* Role-based permissions
* Signed file access
* Integration credential encryption
* Secrets-manager compatibility
* Tenant-scoped object keys
* Input validation
* Output sanitization
* Rate limiting
* CSRF protection where applicable
* Secure session handling
* Audit logging
* Least-privilege integrations

Roles:

```text
ORGANIZATION_ADMIN
PROJECT_EXECUTIVE
PROJECT_MANAGER
PROCUREMENT_MANAGER
SUPERINTENDENT
ACCOUNTANT
VIEWER
```

Never trust organization_id from request input as authorization.

Add explicit tests proving that one organization cannot access another organization’s:

* Projects
* Documents
* BOM
* Suppliers
* Packages
* RFQs
* Quotes
* Audit logs

# Reliability Requirements

## Durable State

Procurement workflows may last days or weeks.

Do not rely on:

* In-memory state
* A single web request
* An LLM conversation
* A worker remaining alive

Persist workflow state in PostgreSQL and use durable scheduled jobs or a workflow engine.

## Idempotency

Every consequential operation must be idempotent:

* Document processing
* Supplier search
* RFQ generation
* RFQ sending
* Follow-up sending
* Supplier-response processing
* Quote extraction
* Recommendation generation
* Purchase-decision creation

## Transactional Outbox

Implement an outbox pattern.

When a domain action requires an external or background action:

1. Write the domain change.
2. Write an outbox event in the same transaction.
3. Commit.
4. Process the outbox asynchronously.
5. Mark the event complete.
6. Retry safely on failure.

## Retries

Use bounded retries with exponential backoff and jitter.

Classify errors into:

```text
RETRYABLE
PERMANENT
REQUIRES_USER_ACTION
```

## Dead-Letter and Exception Queue

Failed jobs must appear in an operator-facing exception queue.

Show:

* Job type
* Related entity
* Error
* Attempt count
* Last attempt
* Next retry
* Retry eligibility
* Required user action

## Concurrency Control

Use optimistic locking for:

* BOM review
* Procurement packages
* RFQ drafts
* Quote review
* Purchase decisions

Prevent silent overwrites.

## Audit Trail

Audit:

* Supplier searches
* Search parameters
* Candidate creation
* Candidate selection and rejection
* RFQ drafts
* RFQ edits
* RFQ approvals
* RFQ sends
* Delivery failures
* Follow-ups
* Supplier responses
* Quote uploads
* Quote extraction
* Quote edits
* Recommendations
* Purchase decisions
* Integration actions

Audit events should be append-only.

## Provenance

Every AI-generated or extracted field must preserve:

* Source
* Model
* Prompt version
* Extraction run
* Confidence
* Original output
* Normalized value
* Human modification
* Approval status

## Observability

Add structured logs, metrics, and traces.

Track:

* Supplier-search latency
* Supplier-search result count
* Candidate selection rate
* RFQ generation failures
* RFQ send failures
* Delivery and bounce rate
* Supplier response rate
* Follow-ups per response
* Quote extraction accuracy
* Quote correction rate
* Recommendation overrides
* Duplicate-send incidents
* Background-job failures
* Model cost
* Model latency
* API latency
* Queue depth

Use a trace or correlation ID across:

```text
User action
→ API request
→ domain service
→ workflow
→ model call
→ external provider
→ database write
→ final result
```

# AI and Agent Design

Do not create one unrestricted general agent.

Use bounded operations and specialized workflows.

Suggested AI capabilities:

```text
extract_bom
draft_supplier_search_terms
explain_supplier_match
draft_rfq
classify_supplier_response
extract_quote
explain_quote_exceptions
generate_recommendation_explanation
```

The AI must not:

* Run SQL
* Directly modify the database
* Send arbitrary emails
* Select suppliers without review
* Commit purchases
* Change project scope
* Change quantities
* Approve its own output
* Access unrelated tenant data

Create a typed tool layer such as:

```text
get_procurement_package
get_package_requirements
search_suppliers_for_package
list_supplier_candidates
select_supplier_candidate
create_rfq_draft
approve_rfq
send_approved_rfq
record_supplier_response
extract_quote
compare_quotes
generate_recommendation
record_purchase_decision
```

Every tool must:

* Validate arguments
* Enforce authorization
* Enforce package state
* Be idempotent
* Return structured results
* Write an audit event
* Avoid exposing unnecessary data

# MCP Architecture

Do not make MCP the core internal architecture.

Build core domain services and typed application tools first.

Then create an optional MCP adapter over safe, approved capabilities.

Potential MCP tools:

```text
get_project_summary
get_procurement_package
list_supplier_candidates
get_rfq_status
list_quote_comparisons
get_procurement_risks
create_rfq_draft
```

Do not expose:

```text
run_sql
send_arbitrary_email
modify_any_record
call_quickbooks_api
execute_code
```

MCP tools must call existing application services and preserve all permissions, approval rules, auditing, and idempotency.

# UI Requirements

The UI should be an operational dashboard, not a generic chatbot.

Primary navigation:

```text
Projects
Documents
BOM
Procurement Packages
Suppliers
RFQs
Quotes
Exceptions
Audit Log
Settings
```

## Procurement Package Detail Page

Show:

* Package summary
* Status
* Required delivery date
* Delivery address
* BOM items
* Specifications
* Attachments
* Supplier-search status
* Supplier candidates
* Selected suppliers
* RFQ status
* Quote status
* Recommendation
* Activity timeline

## Supplier Candidate Table

Columns:

* Supplier
* Distance
* Category match
* Manufacturer match
* Delivery fit
* Verification
* Historical performance
* Match score
* Risk flags
* Status
* Actions

## RFQ Review Page

Show:

* Package line items
* Supplier recipients
* Subject
* Message
* Attachments
* Required dates
* Quote fields requested
* Approval status
* Validation warnings

## RFQ Timeline

Show:

* Created
* Approved
* Sent
* Delivered
* Opened when supported
* Follow-up sent
* Supplier replied
* Quote received
* Quote reviewed

## Quote Comparison

Create a dense but readable side-by-side comparison.

Support:

* Filtering
* Highlighting missing items
* Highlighting substitutions
* Delivery-date warnings
* Total landed cost
* Score breakdown
* Recommendation explanation
* Manual supplier selection
* Package splitting

Include:

* Loading states
* Empty states
* Error states
* Retry actions
* Confirmation dialogs
* Accessible forms
* Desktop-first responsive layout

# Testing

Implement:

* Backend unit tests
* Repository tests
* Service tests
* API integration tests
* Background-job tests
* Provider contract tests
* Frontend component tests
* Playwright end-to-end tests
* Tenant-isolation tests
* Permission tests
* Idempotency tests
* Concurrency tests

Required test cases:

1. Create a procurement package from approved BOM items.
2. Reject adding an unapproved BOM item.
3. Search suppliers from package requirements.
4. Prevent candidates from another tenant from appearing.
5. Rank suppliers deterministically.
6. Select supplier candidates.
7. Generate RFQ from package data.
8. Prevent an RFQ from inventing quantities.
9. Require approval before send.
10. Prevent duplicate RFQ sends.
11. Handle partial send failure.
12. Retry temporary email failure.
13. Ingest supplier response.
14. Link response to the correct RFQ recipient.
15. Extract and review a quote.
16. Detect missing package line items.
17. Detect substitutions.
18. Detect late delivery.
19. Reconcile totals.
20. Compare multiple quotes.
21. Generate deterministic recommendation scores.
22. Record recommendation override.
23. Preserve a complete audit trail.
24. Recover a workflow after worker restart.
25. Prevent cross-tenant file access.
26. Handle concurrent RFQ edits.
27. Display failed jobs in the exception queue.
28. Allow safe retry from the exception queue.

# Complete End-to-End Test

Build a Playwright workflow that:

1. Signs in as a procurement manager.
2. Creates a project.
3. Uploads a sample project document.
4. Processes it using the fake model provider.
5. Reviews and approves BOM items.
6. Creates an underground utilities procurement package.
7. Starts supplier search.
8. Reviews supplier candidates.
9. Selects three suppliers.
10. Generates an RFQ.
11. Reviews and approves the RFQ.
12. Sends the RFQ through the fake email provider.
13. Simulates two supplier responses.
14. Uploads two quotes.
15. Processes quotes using the fake model provider.
16. Reviews extracted quote fields.
17. Opens quote comparison.
18. Displays a recommendation.
19. Selects a supplier.
20. Verifies the complete workflow in the audit log.

# Seed Data

Create production-quality seed and demo data.

Include:

* One general contracting company
* Multiple users and roles
* One active construction project
* One underground utilities package
* Multiple suppliers
* Three supplier candidates
* Two selected suppliers
* One RFQ
* Two quotes
* One recommendation
* Audit events

Sample materials:

```text
8-inch PVC water pipe, 1,682.7 LF
8-inch gate valves, 9 EA
Fire hydrants, 5 EA
8-inch SDR26 sewer pipe, 1,264 LF
18-inch RCP storm pipe, 1,012.7 LF
24-inch RCP storm pipe, 301.4 LF
```

# Developer Experience

Provide:

* README
* Architecture document
* Domain-model document
* State-machine document
* Integration guide
* Security guide
* Deployment guide
* Incident-response guide
* Environment-variable reference
* Local setup
* Production setup
* Database migration commands
* Seed commands
* Test commands
* Lint commands
* Type-check commands
* Provider configuration
* Known limitations

The local application should start with a small number of commands.

# Production Deployment

Prepare the application for production deployment.

Include:

* Production Dockerfiles
* Health endpoints
* Readiness endpoints
* Database migrations
* Worker deployment
* Scheduled-job deployment
* Environment validation
* Secret configuration
* Object-storage configuration
* Email-provider configuration
* CORS configuration
* Trusted-host configuration
* Rate limits
* Error reporting
* Structured logging
* Backup guidance
* Restore guidance
* Rollback guidance

Do not hardcode cloud credentials.

Do not claim the system is production-ready merely because it runs locally.

# Implementation Process

## Step 1: Inspect the Repository

Before modifying code:

* Inspect the full repository.
* Identify existing architecture and conventions.
* Identify incomplete or fake implementations.
* Identify security and reliability risks.
* Identify what should be reused versus replaced.

Write findings to:

```text
docs/current-state-review.md
```

## Step 2: Produce an Implementation Plan

Write:

```text
docs/implementation-plan.md
```

Include:

* Milestones
* Module boundaries
* Database changes
* API changes
* UI changes
* Background workflows
* Provider integrations
* Tests
* Migration strategy
* Risks
* Acceptance criteria

After writing the plan, begin implementation. Do not stop after planning.

## Step 3: Build the Vertical Slice First

Prioritize this complete flow:

```text
Package
→ supplier search
→ candidate review
→ supplier selection
→ RFQ draft
→ approval
→ send
→ response
→ quote
→ comparison
→ recommendation
```

Do not add unrelated features until this flow is fully working.

## Step 4: Verify Continuously

After each milestone:

* Format
* Lint
* Type-check
* Run tests
* Run migrations
* Inspect logs
* Fix errors before continuing

Do not disable failing tests.

## Step 5: Perform a Reliability Review

Before declaring completion, create:

```text
docs/reliability-review.md
```

Review:

* Tenant isolation
* Authorization
* Input validation
* File security
* Database constraints
* Idempotency
* Outbox behavior
* Retry behavior
* Workflow recovery
* Duplicate sending
* Email failure handling
* Quote extraction validation
* Audit coverage
* Concurrency
* Deployment configuration
* Backup and recovery
* Monitoring

Fix all critical and high-severity findings.

## Step 6: Run the Full Workflow

Run the application and complete the end-to-end procurement flow through the UI.

Inspect:

* Every page
* Empty states
* Failure states
* Logs
* Database data
* Audit records
* Background jobs
* Provider calls
* Retry behavior

# Rules

* Do not produce only mock screens.
* Do not stop after generating an architecture plan.
* Do not use in-memory persistence for production data.
* Do not place business logic in route handlers.
* Do not allow direct LLM database access.
* Do not let the LLM invent structured project data.
* Do not send an RFQ without approval.
* Do not contact unselected suppliers.
* Do not silently send duplicate messages.
* Do not rank suppliers purely using an LLM.
* Do not rank quotes only by price.
* Do not skip source provenance.
* Do not skip tenant isolation.
* Do not skip audit logging.
* Do not skip failure recovery.
* Do not expose raw SQL through MCP.
* Do not claim integrations work unless they are implemented and tested.
* Do not hide incomplete functionality.
* Prefer a smaller complete workflow over many unfinished features.

# Definition of Done

The implementation is complete only when:

* The application starts successfully in local development.
* Production containers build successfully.
* Migrations work from an empty database.
* Seed data loads.
* Organization isolation tests pass.
* Permission tests pass.
* Supplier search works from procurement package requirements.
* Supplier candidates can be reviewed and selected.
* RFQs are generated from structured package data.
* RFQs require approval before sending.
* Duplicate sending is prevented.
* Email failures are retried safely.
* Supplier responses are linked correctly.
* Quotes are extracted with provenance.
* Quote discrepancies are detected.
* Quote comparison works.
* Recommendation scores are deterministic.
* A purchase decision can be recorded.
* Failed jobs appear in the exception queue.
* Audit logs cover the entire workflow.
* The full Playwright workflow passes.
* Backend tests pass.
* Frontend tests pass.
* Linting passes.
* Type checking passes.
* Reliability review is complete.
* Documentation accurately describes the implementation.
* Any remaining limitations are explicitly documented.

Begin by inspecting the repository, writing the current-state review and implementation plan, and then implementing the complete production-ready vertical slice.
