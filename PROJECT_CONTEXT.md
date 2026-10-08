# Customer Loyalty Platform — Project Context

## Purpose

This repository contains a multi-business customer loyalty and retention platform.

The first business using the platform is Trumps, but the architecture must NOT
be designed specifically for one business.

The long-term goal is to offer the platform as a service to multiple businesses.

Every business-owned resource must therefore be scoped using `business_id`.

Development business:

business_id = "trumps"

---

# Product Goals

The platform allows businesses to:

- Register and manage customers
- Record marketing consent
- Maintain customer profiles
- Identify customers using QR codes
- Record customer visits
- Run loyalty programmes
- Generate vouchers
- Redeem vouchers
- Send SMS campaigns
- Send automated birthday promotions
- Allow staff to scan customer QR codes
- Maintain audit trails
- Store customer-related documents securely

The system should remain inexpensive to operate for small businesses.

Initial expected usage is approximately 150–200 customers per business.

---

# Technology Stack

## Frontend

React
Vite
JavaScript

## Backend

Python
FastAPI

## AWS

Region:

eu-west-1 (Ireland)

Implemented AWS integrations:

- DynamoDB customer persistence
- Cognito business-user authentication
- Private S3 customer media

Planned AWS architecture:

- Lambda
- API Gateway
- CloudFront
- EventBridge
- CloudWatch

## SMS

Twilio

## Source Control

Git / GitHub

---

# AWS Development Configuration

AWS CLI profile:

loyalty-dev

Default application region:

eu-west-1

Never store AWS access keys or secret keys in this repository.

Local development may use the AWS SSO profile.

Production AWS services must use IAM roles.

---

# DynamoDB

Development customer table:

loyalty-customer-dev

Primary key:

Partition key:
business_id

Sort key:
customer_id

Billing mode:

PAY_PER_REQUEST

The architecture must support multiple businesses.

Never perform customer operations using only `customer_id`.

Customer access must always be scoped to `business_id`.

---

# Customer Model

Customer records currently contain:

- business_id
- customer_id
- first_name
- last_name
- phone
- date_of_birth
- email
- address
- eircode
- marketing_consent
- consent_timestamp
- qr_token
- status
- created_at
- updated_at

IDs and QR tokens must be securely/randomly generated.

QR tokens must NEVER contain personal information.

---

# Phone Number Rules

Current target market is Ireland.

Managers may enter:

0871234567

or:

+353871234567

The backend normalizes valid Irish mobile numbers to E.164:

+353871234567

Phone uniqueness is scoped to a business.

The same normalized phone number cannot be registered twice within the same
business.

DynamoDB implementations must NOT scan the entire table to enforce uniqueness.

Use an atomic uniqueness mechanism such as reserved phone-lock records and
DynamoDB conditional/transactional writes.

---

# Age Rules

Customers must be at least 18 years old.

Age must be calculated using the complete date, not simply:

current_year - birth_year

Requirements:

- DOB is required
- Future DOB is rejected
- Under 18 is rejected
- Customer turning 18 tomorrow is rejected
- Customer exactly 18 today is accepted

---

# Marketing Consent

Marketing consent must be explicitly recorded.

The system should preserve:

- consent status
- consent timestamp

Signed consent evidence is implemented in Milestone 4; full consent history remains future work.

A signed consent form may be stored as supporting evidence but does not replace
the structured consent status.

---

# Repository Architecture

The backend uses a repository/service architecture.

Business logic and API routes should not depend directly on DynamoDB.

Storage implementations should conform to the repository abstraction.

Current implementations:

- In-memory repository
- DynamoDB repository

This separation must be preserved.

Do not move DynamoDB-specific logic into FastAPI routes.

---

# Loyalty Rules

Customers will have a unique QR identifier.

Scanning the QR code alone must NOT automatically record a visit.

Flow:

1. Authenticated staff scans QR code
2. Customer is identified
3. Staff sees customer/loyalty information
4. Staff confirms the visit
5. Visit is recorded

Every visit now records:

- customer
- business
- timestamp
- staff member

After 5 qualifying visits:

- Milestone 5B atomically issues a €10 loyalty voucher for that new fifth visit
- displayed loyalty progress returns to 0/5

IMPORTANT:

Historical visits must NEVER be deleted when loyalty progress resets.

The 0/5 progress represents the new loyalty cycle, not deletion of previous
visit records.

---

# Voucher Rules

Vouchers must:

- have random/non-predictable codes
- belong to a customer and business
- have ACTIVE, REDEEMED or effective EXPIRED status
- only be redeemable once
- record redemption timestamp
- record the authenticated Cognito subject that redeemed them

Voucher history must be preserved.

---

# Authentication and Roles

Authentication now uses Amazon Cognito for the current customer API.

Cognito authenticates BUSINESS USERS, not loyalty customers.

The following authorization model is finalized. Milestone 3 implements
authentication, role guards and current customer permissions. Milestone 4 implements protected customer media and manual ID verification.
Milestone 5A implements QR lookup, visit confirmation and progress for all three roles.
Milestone 5B implements automatic vouchers, customer voucher lists, code lookup
and redemption for all three roles.
Permissions for SMS, staff administration and reports remain
requirements for future endpoints.

## OWNER / ADMIN

Can:

- Fully manage customers
- View customer profile photos
- View and verify customer ID documents
- View consent evidence
- Access QR, visit and voucher functionality
- Send SMS campaigns
- View reports and full audit logs
- Manage staff accounts and roles
- Configure the loyalty programme
- Manage business settings

## MANAGER

Can:

- Register, view, search and edit customers
- Deactivate customers
- View customer profile photos
- View and verify customer ID document images
- View signed consent evidence
- Scan QR codes
- Record visits
- View loyalty progress
- View and redeem vouchers
- Send individual and bulk SMS
- View campaign history
- View operational reports
- View appropriate, limited audit information

Cannot:

- Manage staff accounts or roles
- Change business or security settings
- Change owner-level configuration

## STAFF

Can:

- Register customers
- View and search customers
- Edit customer details
- View customer profile photos
- Scan customer QR codes
- Record visits
- View loyalty progress
- View and redeem vouchers

Cannot:

- View customer ID document images
- View signed consent evidence
- Send SMS campaigns
- Manage staff accounts or roles
- Access business settings or administrative reports

## Enforcement and Business Isolation

Backend authorization must enforce these permissions for every protected
operation and resource access. Hiding functionality in React alone is not
sufficient.

Every authenticated business user must belong to a `business_id`. Users from
one business must never access another business's resources, regardless of
role. OWNER / ADMIN privileges apply within the user's business; they do not
grant cross-business access.

Business scope must be derived from the authenticated user's trusted
identity/session, not accepted as authorization from frontend input.

Each business user, including each staff member, should have an individual
account. Shared accounts should be avoided because actions need to be
attributed to an authenticated user.

Staff customer edits must eventually be auditable, including the authenticated
user, customer, timestamp and relevant changed fields, scoped to the business.

---

# Customer Documents

Milestone 4 implements:

- customer profile photograph
- ID document image
- signed SMS opt-in form image

Images/files must NOT be stored directly inside DynamoDB.

Current storage:

Existing private Amazon S3 bucket contactly-private-documents-dev in eu-west-1.
Backend-controlled uploads and authenticated image proxying; no exposed keys or
presigned URLs. Media metadata lives in private media_profile, media_identity
and media_consent attributes on the CUSTOMER item. Ordinary customer responses
exclude it; existing records and phone locks remain compatible.

DynamoDB stores metadata/references.

Possible ID types include:

- Passport
- Driving Licence
- National ID
- Residence Permit
- Other

Document metadata may include:

- document type
- verification status
- verified_by
- verified_at
- S3 object reference

Possible verification states:

- Pending
- Verified
- Rejected

Sensitive documents must have restricted access.

OWNER / ADMIN and MANAGER may view and verify customer ID documents and view
signed consent evidence. STAFF must not access ID document images or signed
consent evidence. Customer profile photos may be viewed by all three roles
within their own business. Backend authorization must enforce this distinction,
including every private image and metadata retrieval.

S3 puts request SSE-S3 (AES256), with no ACL. Block Public Access stays enabled
and ACLs disabled. Development versioning is disabled to minimize cost.
Production retention/deletion and KMS strategy remain future policy work.

Profile photographs are NOT intended for facial recognition.

Do not introduce biometric/facial-recognition functionality.

---

# SMS

Twilio is the selected SMS provider.

Twilio is used for messaging only.

It is NOT the customer database.

Managers will eventually be able to send SMS campaigns through the application.

---

# Birthday Automation

Future architecture:

EventBridge scheduled task
        ↓
Lambda
        ↓
Find eligible birthday customers
        ↓
Generate promotion
        ↓
Twilio SMS

Birthday promotions should eventually use unique promotion/voucher codes with
redemption state and potentially expiry dates.

---

# Security Rules

Never:

- commit AWS credentials
- commit Twilio credentials
- commit `.env`
- commit real customer information
- expose sensitive ID documents publicly
- put personal information inside QR codes
- trust `business_id`, role or permissions supplied by the frontend

Secrets must come from environment configuration or appropriate AWS secret
management mechanisms.

Use fictional/test customer data during development.

---

# Multi-Tenant Design

This is a multi-business platform.

Every relevant resource must be associated with a `business_id`.

Examples:

Customer
Visit
Voucher
Staff
Campaign
Document

Every authenticated business user must belong to a `business_id`. Business
scope comes from the user's verified identity/session rather than being trusted
from frontend input. Cross-business
resource access must be denied for every role.

During local development, `"trumps"` may be used as the development business.

---

# Audit Requirements

Future sensitive actions should be auditable.

Examples:

- customer creation/update
- visit recording
- voucher generation
- voucher redemption
- document verification
- campaign sending

Audit information should include where appropriate:

- business_id
- staff/user ID
- action
- resource
- timestamp

Customer edits by STAFF must record at least:

- business_id
- authenticated user ID
- customer ID
- timestamp
- relevant changed fields

OWNER / ADMIN may view full audit logs within their business. MANAGER may view
appropriate, limited audit information. STAFF must not gain administrative
report or audit access simply because they can edit customers.

---

# Current Development Status

## Milestone 1 — COMPLETE

Implemented:

- React/Vite frontend
- FastAPI backend
- customer registration
- customer listing
- customer search
- customer profile
- customer editing
- Irish phone normalization
- duplicate phone validation
- 18+ DOB validation
- marketing consent
- success/error notifications
- repository/service abstraction
- automated tests

Milestone 1 initially used temporary in-memory storage.

---

# Milestone 2 — COMPLETE; LIVE DYNAMODB VERIFIED BY PROJECT OWNER

Goal:

Replace temporary customer storage with DynamoDB persistence.

AWS resource already exists:

loyalty-customer-dev

Do NOT create another DynamoDB table unless explicitly requested.

Milestone 2 preserves Milestone 1 behaviour and implements:

- Configurable DynamoDB customer persistence via boto3
- Backend-only environment configuration and local SSO profile support
- Business-scoped reads and paginated customer queries
- Conditional/transactional PHONE# uniqueness records
- Atomic new-phone claim, customer update and old-phone release
- Internal record exclusion from customer responses
- Expected-timestamp concurrency checks and sanitized application errors
- AWS-independent repository/configuration/error tests

Target configuration remains loyalty-customer-dev in eu-west-1, with String
partition key business_id and String sort key customer_id. No table is created
by the application. AWS_PROFILE=loyalty-dev is for local SSO development only.

CUSTOMER_REPOSITORY=dynamodb selects durable storage. Optional memory mode
remains available for offline development and tests; it is the default when
no mode is configured and loses records on process restart. AWS failures do
not automatically fall back to memory.

Automated verification uses mocks/fakes/stubs, not the real AWS account.
The project owner reports successful manual AWS DynamoDB persistence
verification. Automated tests continue using fakes/stubs without AWS access.

Milestone 2 preserved document metadata extensibility; Milestone 4 now adds
S3 media. Milestone 5A now adds QR lookup and confirmed visits; Milestone 5B adds vouchers. Messaging remains unimplemented.

---

# Milestone 3 — COMPLETE; LIVE COGNITO VERIFIED BY PROJECT OWNER

- Cognito email/password business-user login with Amplify SRP authentication
- Temporary-password completion, per-tab session storage, refresh and logout
- Backend RS256 JWT verification against configured Cognito JWKS
- Required ID-token issuer, audience/client, expiry, issued-at, subject and token type
- Trusted user context: subject, email where available, business, groups and role
- Explicit Cognito group mapping for owner, manager and staff with ASCII case normalization; precedence Owner > Manager > Staff
- Business scope always derives from verified custom:business_id
- Customer endpoints protected for all three roles; only Owner/Manager change status
- Reusable owner-only, management and customer-access authorization helpers
- Frontend role awareness based on authenticated /auth/me response
- Missing business or recognized group denied; no production authentication bypass
- Automated JWT/tenant/role tests use local keys and injected test fixtures

The public app client must read custom:business_id but MUST NOT be permitted
to write it. Administrative provisioning assigns business membership. No AWS
resources are automatically created or modified. App client ID is required
configuration; there is no hardcoded client secret, token or user identity.

The project owner reports live Cognito login, DynamoDB and tenant isolation working.
Customer edit audit persistence, production MFA/recovery, immediate token
revocation enforcement and deployment hardening remain future work. ID tokens
already issued remain valid until expiry under local JWT verification.

# Milestone 4 — IMPLEMENTED; PROFILE-PHOTO S3 STORAGE/RETRIEVAL VERIFIED

- Backend-controlled JPEG/PNG/WebP uploads, max 5 MiB and 20 million pixels
- Pillow actual-format verification, full decode and fresh-pixel re-encoding;
  embedded metadata stripped, animated/corrupt images rejected
- Server-generated businesses/<business>/customers/<customer>/<profile|identity|consent>/<uuid>.<extension> keys
- Private metadata on customer items, conditional per-category revisions;
  existing customer/phone writes preserve it and never return it in general APIs
- Profile view/upload/replace: Owner, Manager and Staff
- ID and consent metadata/image/upload: Owner and Manager only; Staff denied
- Manual ID Pending/Verified/Rejected, with new/replaced ID reset to Pending
- uploaded_by/at and verified_by/at retained privately; no subject IDs in the UI
- Consent evidence supports structured consent; never modifies marketing_consent
- Authenticated image proxy with no-store headers; no presigned URLs/keys exposed
- Camera preview/capture/retake, device files and camera-denial fallback
- New object then conditional metadata commit then old-object deletion;
  failed cleanup references retained for retry on subsequent replacement
- No distributed S3/DynamoDB transaction: crashes/ambiguous writes may leave
  private orphans requiring operator reconciliation; no background janitor
- S3_DOCUMENTS_BUCKET and S3_REGION backend config; optional local AWS_PROFILE
- AWS-independent media/role/tenant/validation/replacement tests

Use DynamoDB with real S3; memory-mode references disappear on restart.
Bucket resources are never created/modified automatically. Development versioning
is disabled (deleted replacement objects cannot be recovered). Production
retention/deletion, malware policy, rate limits, full audits and KMS evaluation
remain required. Use fictional documents only. No OCR, facial recognition,
biometric matching or automated document verification. See README for setup,
permissions, endpoints and manual acceptance procedure.

# Milestone 5A — COMPLETE

- Business-scoped QR_LOCK index records; existing opaque tokens preserved
- New customers atomically claim CUSTOMER, PHONE_LOCK and QR_LOCK
- Explicit dry-run/apply backfill script for each existing business; no Scan,
  GSI, automatic startup migration or AWS resource changes
- Authenticated QR lookup never creates visits; only active customers resolve
- Owner/Manager/Staff may explicitly confirm visits; recorded_by is Cognito sub
- Immutable VISIT#<customer UUID>#<visit UUID> rows with retained history
- One valid visit per business/customer/calendar date in Europe/Dublin, including DST
- Atomic active-status/counter check plus visit insertion after strongly consistent
  customer history read; concurrent commits retry and recheck the local date
- UTC timestamp plus local_visit_date and business_timezone on new visits
- Legacy timestamps establish local date without backfill; history/counts preserved
- Both repositories enforce the daily rule; no rolling time-window configuration
- Milestone 5C now uses this same date rule for atomic Daily Raffle creation
- Lifetime count, progress=count % 5, visits_until_reward=5-progress;
  reward_earned true only for positive multiples of five
- Fifth visit reports 0/5 progress; Milestone 5B now issues an actual €10 voucher
- Keyboard scanner lookup/confirm UI, profile photo and customer visit history
- Internal records excluded from customer APIs; phone/media metadata preserved
- Automated tests use local fakes and SDK stubs, never the real AWS account

See README for endpoints, explicit backfill commands and live acceptance steps.
Milestone 5B below adds loyalty/birthday vouchers. QR generation is added in 5B.1 below. No physical printing,
Epson integration or other later milestone has been implemented; 5C below adds digital raffle entries. Full customer edit audit logs remain
future work; visits retain their authenticated recorder and server timestamp.

# Milestone 5B — IMPLEMENTED; LIVE VOUCHER ACCEPTANCE PENDING

- Each new fifth valid visit issues one LOYALTY_10 voucher, value_cents=1000
- Valid only on its issue Dublin date; expires at next local midnight
- Valid visit in birthday Monday–Sunday week issues BIRTHDAY_20, value_cents=2000
- Maximum one per customer/birthday year; adjacent years handle New Year weeks
- Feb 29 uses March 1 in non-leap years; leap years retain Feb 29
- Birthday validity ends at following Monday's Dublin midnight
- Both rewards can issue as separate records for the same qualifying visit
- UTC issue/expiry/redemption times; issue local date/timezone and Cognito identities
- Effective ACTIVE/REDEEMED/EXPIRED status enforced at read and redemption time
- Owner/Manager/Staff may list, look up and redeem within their verified business
- No API for arbitrary frontend issuance; QR lookup/duplicate/inactive visits issue nothing
- Atomic transaction includes counter/active/customer revision condition, visit,
  voucher records, reward locks and code locks; no partial visit/reward persistence
- VOUCHER#<customer UUID>#<voucher UUID> rows and paginated per-customer Queries
- REWARD#<customer UUID>#LOYALTY_10#<cycle> locks and
  REWARD#<customer UUID>#BIRTHDAY_20#<birthday year> locks
- VCODE#<random code> VOUCHER_CODE records for atomic uniqueness and lookup
- Codes have 100-bit randomness, human-readable grouping, no PII; no Scan/GSI
- Conditional ACTIVE/unexpired redemption sets REDEEMED and trusted user/time
- UI rewards, profile vouchers and code lookup/redemption; no printing
- Existing customer, phone, QR, visit and private media attributes preserved
- AWS-independent rule, concurrency, expiry, role, tenant, SDK and frontend tests

No backfill/resource/configuration change is needed. Past 5A milestones are not
retroactively rewarded; existing counts/history are preserved. A lost response
may hide a committed result: refresh history/vouchers; daily/reward/redemption
conditions prevent retries creating duplicate rewards or redemptions. Expiry
is effective, not persisted by a scheduled task. Server request timestamps are
trusted; clocks must be synchronized. Per-business timezone/programme settings,
full audits, refunds/voiding and historical remediation remain future work.
See README for exact live acceptance steps and current limitations.

# Milestone 5B.1 — IMPLEMENTED; LIVE ACCEPTANCE PENDING

- Tenant-scoped name/full-name and normalized Irish phone directory search
- Profile QR PNG encodes the existing opaque token; qrcode 8.2 + existing Pillow
- Stable random 256-bit public reference, initialized lazily without token rotation
- Public /q/<reference> view exposes only Contactly branding, QR and instructions
- Copy/recover existing link; authenticated SMS boundary returns unconfigured 501
- Owner/Manager explicit confirmed regeneration; backend denies Staff
- Atomic token/QR_LOCK/public-pointer replacement; old token/link invalidation
- Conditional revision/token checks handle concurrent regeneration safely
- Customer/media/history/counters/vouchers and existing authorization preserved
- Same-table internal PUBLIC_QR routing records: reserved business_id !PUBLIC_QR,
  customer_id PUBLIC#<reference>, owner business/customer pointers. This directory
  is the deliberate exception to tenant partitioning, required for opaque public
  lookup without a Scan/GSI or tenant data in the URL. Verified business IDs cannot
  use this reserved partition; actual customer resources remain tenant-scoped.
- Public responses only PNG with no-store/referrer controls; inactive links fail
- Optional VITE_CUSTOMER_QR_BASE_URL origin; production SPA fallback for /q/*
- No automatic AWS/IAM changes; restrictive IAM may need manual directory access
- No bulk migration; existing missing QR_LOCK records use the previous backfill
- AWS-independent repository, API, role, concurrency, preservation and UI tests

Public links are bearer credentials, not authenticated identity or automatic
visit authorization. Downloaded old images remain visible but invalid for lookup
after rotation. HTTPS, reference-log redaction and abuse controls belong in
production hardening. Generic public branding avoids disclosing customer names.
No Twilio, physical printing or Honeywell drivers are implemented. Milestone 5C below adds digital raffle entries. See README for
endpoints, setup and exact manual acceptance procedure.

# Milestone 5C — IMPLEMENTED; LIVE ACCEPTANCE PENDING

- Every new valid confirmed visit creates exactly one immutable logical raffle entry
- Entry shares the random visit UUID as its deterministic raffle_entry_id
- Records business, customer, visit/number, Dublin raffle date/timezone, UTC
  creation time and authenticated Cognito recorded_by; no unnecessary customer PII
- RAFFLE#<customer UUID>#<visit UUID>, item_type RAFFLE_ENTRY
- RAFFLE_DATE#<YYYY-MM-DD>#<customer UUID>#<visit UUID>, item_type RAFFLE_DATE_INDEX
- Both records in the authenticated business partition; date projection repeats
  immutable non-PII fields for efficient future date reporting without a Scan/GSI
- Counter + visit + raffle + date projection + eligible vouchers/reward/code locks
  commit in one conditional DynamoDB transaction; any failure rolls back everything
- Existing active/daily/counter/revision/reward conditions and bounded retries retained
- Memory repository mirrors atomic operation under its existing lock
- Lookup/rejected visits/redemption/QR regeneration create no raffle entries
- Authenticated GET /customers/{id}/raffle-entries for Owner/Manager/Staff;
  no direct-create, public raffle, date-report or winner-selection endpoint
- Confirm response includes committed raffle_entry; UI shows separate visit/raffle/rewards
- Loyalty visits identifies by QR or reused business directory name/phone search
- Manual selection reads existing customer visit/progress endpoint and writes nothing
- Both methods use the same existing Confirm Visit POST/atomic transaction
- Compact name/phone results, inactive selection protection and clear/change controls
- No manual-visit endpoint or changes to backend eligibility/authorization rules
- Profile displays ten recent entries with dates/Dublin time/visit number and refresh
- Repository/internal service supports business + date Query for future reporting
- No automatic historic backfill, counter/history changes or AWS resource changes
- No new dependency/configuration; existing synthetic historical seed creates no raffle
- AWS-independent rollback, concurrency, rewards, DST, role/tenant, SDK and UI tests

Two physical records represent one logical entry. The date projection adds one
small write/storage record; no customer name/phone is duplicated. Future printing
resolves customer PII when preparing a job. Current history Query pagination is
internal; the API returns retained history and the UI displays ten newest entries.
Large-volume cursor pagination/retention/reporting remain future work. An ambiguous
committed response can produce a daily-duplicate error on retry; refresh history
for reconciliation. Milestone 5C adds no printing, raffle draw, exports, print jobs or Twilio; 5D.1 below adds the durable digital queue.
See README for setup and exact manual acceptance steps. No migration is required.

# Milestone 5D.1 — IMPLEMENTED; LIVE QUEUE ACCEPTANCE PENDING

- Each new valid visit atomically creates raffle ticket job plus jobs for actual
  issued loyalty/birthday vouchers: one, two or three separate jobs
- Canonical tenant PRINT#<customer UUID>.<visit UUID>.<ticket type> records,
  item_type PRINT_JOB; deterministic source/type identity and conditional insertion
- Queries for business, customer, customer/visit prefixes; no Scan/GSI/new AWS resources
- Initial jobs join counter/visit/raffle/date/voucher/reward/code transaction
- Five/nine/thirteen actions for zero/one/two rewards; adapter enforces conservative
  100-action/4 MB transaction and 400 KiB put limits before dispatch
- Customer revision check preserves immutable snapshot/reward consistency
- Template version 1 stores 42-column monochrome receipt text and original
  business/name/phone/source/existing code/issue/expiry/Dublin time/signature data
- No IDs/consent images, DOB, addresses, QR secrets or unrelated PII in snapshots
- Trumps label for existing trumps business; generic Contactly elsewhere pending settings
- PENDING/CLAIMED/PRINTING/COMPLETED/RETRYABLE/FAILED/UNCERTAIN lifecycle
- Random claim fence, verified subject and 120-second expiry; revision CAS transitions
- Start/complete/fail require the same holder/current token/unexpired lease
- Expired/prestart failure retries limited to three; started failure/expired output
  is UNCERTAIN and never automatically reclaimed or endlessly reprinted
- Effective expiry on reads; explicit review persists expiry with CAS
- Explicit Owner/Manager confirmed reprint with reason/request UUID; original audit
  and child commit together, preserve original code/details, mark REPRINT
- Idempotent request UUID; further reprints reference original, never reprint children
- Staff has scoped customer/visit summary status only; no global queue/ticket/admin
- Owner/Manager queue/review/detail/lifecycle/reprint APIs remain Cognito/tenant protected
- Claim token returned only on claim, never queue/detail summaries; safe error codes
- UI displays Queued after visits and in profile; manager queue previews/reprint review
- Memory mirror for tests/offline use, DynamoDB for durability; no new configuration
- No historical automatic jobs/backfill; no physical or browser printing implemented
- AWS-independent transaction/count/rollback/concurrency/snapshot/lease/role/UI tests

Snapshots deliberately retain original customer PII after edits; production
retention/erasure must include print records/audit reasons. Current global queue
reads retained PRINT# range and filters review state; customer UI shows ten recent
jobs. Public pagination/status work discovery are later scaling decisions.
Printed status means authenticated completion acknowledgement, not hardware proof.
No UI can fabricate that state. A lost reply requires queue reconciliation before
another explicit reprint; uncertain paper outcomes cannot be solved by auto-retry.

5D.2A below implements the isolated development Windows agent/EPSON transport.
Production deployment still requires encoding/paper/cut/status acceptance,
onsite spool/ack acceptance. Lease renewal is implemented in 5D.2A. It must use a
separate revocable device identity, verified business/device binding and narrow
queue scopes, not an embedded credential, staff login or auth bypass. Existing
human Owner/Manager lifecycle routes are not a production agent identity. No
issuer/device credentials/resources are invented in 5D.1. The agent must receive
start acknowledgement before hardware output and preserve uncertain-outcome
operator review. See README for complete endpoints, lifecycle and acceptance.

# Future Milestones

## Milestone 5D.2
Physical receipt printing and Windows/Epson print agent

## Milestone 7
Twilio messaging and birthday automation

## Milestone 8
Audit/security/GDPR hardening and production deployment

Exact milestone boundaries may evolve, but major features should not be
implemented prematurely.

---

# Rules for Coding Agents

Before modifying the repository:

1. Read this file.
2. Inspect the existing implementation.
3. Preserve existing working functionality.
4. Follow the repository/service architecture.
5. Do not implement future milestones unless explicitly requested.
6. Do not introduce unnecessary dependencies.
7. Do not hardcode credentials.
8. Preserve multi-business architecture.
9. Add/update tests for behavioural changes.
10. Run existing tests after changes.
11. Run frontend lint/build when frontend code changes.
12. Update README/documentation when architecture or setup changes.

If an implementation request conflicts with this document, do not silently
redesign the system. Report the conflict before making a major architectural
change.
# Milestone 5D.2A — IMPLEMENTED LOCALLY; DEVICE DEPLOYMENT/ONSITE ACCEPTANCE PENDING

- Separate outbound Python Windows worker; simulation defaults to local fixtures,
  no HTTP, claims or Windows printer access
- Explicit Windows queue RAW adapter, immutable 42-column PC858 text and independent
  partial-cut requests; compatibility/physical output not tested
- Durable SQLite intent fence before start, atomic backend claims and safe renewal;
  uncertain output never automatically retried
- Spool acceptance maps to UNCERTAIN with safe diagnostic code and no printed_at;
  physical paper completion is not asserted
- Dedicated development device transport, disabled by default, loopback and exact
  in-memory repository only; business/device bound by backend configuration
- Production transport blocked pending revocable device identity provisioning,
  enrollment, vault storage and TLS; no AWS resources or credentials created
- No Owner/Manager credentials on agent, no new visits/rewards or public QR auth
- Task Scheduler instructions only; no startup task, printer or driver changes
- See print-agent/README.md for configuration, limits and onsite acceptance
