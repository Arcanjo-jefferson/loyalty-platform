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

Twilio (selected provider; no sending integration implemented)

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
Owner/Manager SMS simulation endpoints are now implemented; live Twilio delivery,
staff administration and report endpoints remain future work.

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

Twilio is planned for messaging only; no Twilio SDK, sender or webhook is implemented.

It is NOT the customer database.

Owner/Manager can now preview, queue and process simulated individual/bulk SMS.
Actual Twilio delivery remains unimplemented and disabled.

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

The existing Milestone 5B reward engine already issues unique €20 birthday
vouchers with redemption state and expiry, but ONLY following a valid visit in
the birthday week. Scheduled SMS is not implemented. The proposed SMS milestone
must notify/invite without issuing vouchers before a visit; doing so would change
the existing eligibility rules and requires separate approval.

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

## Printing deployment follow-up
Windows/Epson agent code is implemented in 5D.2A/5D.3 below. Physical Epson output
was confirmed on-site by the project owner; full production device deployment
is a separate acceptance scope, not established by paper output alone.

## Milestone 5 — SMS simulation implemented; Twilio activation pending
This is the current user-requested label for the scope previously called
Milestone 7. Preserve the completed 5A–5D history; do not renumber it.
See the dated review, historical proposal and delivered simulation scope at the
end of this document.

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

# Milestone 5D.3 — INTEGRATION IMPLEMENTED; PROVISIONING/LIVE ACCEPTANCE PENDING

- Dedicated Cognito RS256 access-token validation: issuer, expiry/iat, token_use=access,
  exact custom scope and registered confidential client_id resource binding
- Cognito M2M cannot request resource-bound aud; if an audience is supplied it must
  match the scope's resource identifier. Human ID-token validation is unchanged
- One opaque UUID/device/business; tenant DEVICE# records and reserved !PRINT_DEVICES
  CLIENT# directory in existing DynamoDB table, strong reads/CAS/unique transactions
- Owner-only register/list/disable/rotation-pending API, no manager/staff/device access
- Operator-only provider-verified binding tool, dry-run default; never handles secrets
  or provisions/changes Cognito. Old client bindings remain non-reassignable tombstones
- Active registry lookup on every request; disable/rotate blocks existing issued tokens
  on subsequent authorization; in-flight operations/physical bytes cannot be recalled
- Agent-only queue claim/start/renew/fail/submitted; no physical completion/review/reprint,
  customer/media/marketing/staff/settings access. Stable device subject in job audit
- HTTPS-only production transport, verified TLS, no redirects/insecure fallback;
  short-lived OAuth client-credentials tokens cached in memory and renewed before expiry
- Production client secrets in Windows Credential Manager under dedicated account;
  no employee passwords, permanent AWS credentials, config secrets or token logs
- Default local simulation and isolated memory development transport preserved
- Signed local JWT + in-memory fictional-visit simulation + fake-DynamoDB tests only
- Requires external custom resource-server scope/domain and per-device confidential
  client-credentials-only provisioning, verified five-minute TTL and HTTPS deployment
- Existing public SPA SRP client must never be used for M2M; no AWS configuration changed
- No provisioning/live auth, vault integration on real Windows, Epson/cutting or physical
  printing verified. Centralized audit export/retention and last-seen write
  throttling remain future deployment/scaling work
- See print-agent/README.md for endpoint matrix, provisioning/rotation and acceptance

Owner-only Print devices screen implemented: authenticated existing API, label registration,
returned pending device ID/status, list/last-seen and confirmed disable/rotation.
Manager/Staff navigation and direct route access blocked; backend enforcement unchanged.

Ticket template version 3 adds consistent Issued date DD/MM/YYYY and Issued time HH:mm
(hours and actual minutes) to all three ticket types, derived from the original server-issued UTC
snapshot timestamp in Europe/Dublin/DST. Agent validates and preserves text; retries
and REPRINT keep the timestamp. Legacy version 1 remains readable and unchanged.
42-column receipt width and default physical-printing-disabled configuration remain.

Ticket time correction: new version 3 snapshots include actual original minutes (HH:mm).
Existing immutable version 1/2 snapshots remain supported without rewriting history.


# Pre-implementation architecture review — 16 October 2026

This dated review records the branch BEFORE the SMS simulation implementation
below. Its missing-feature statements are historical; the implementation section
at the end is authoritative for current SMS status. It superseded older status
claims at the time of review. Earlier milestone sections
remain as delivery history, not evidence of production deployment.
No SMS implementation or AWS/provisioning change is authorized by this review.

## Verified implementation and acceptance status

| Area | Code status | Verification / remaining boundary |
| --- | --- | --- |
| Customers / storage | Registration, validation, search, updates; memory and DynamoDB adapters | Existing automated tests; owner previously confirmed DynamoDB persistence |
| Authentication / roles | Cognito human ID-token verification, backend role guards and verified business scope | Existing JWT, role and tenant tests; owner previously confirmed login |
| Media / consent evidence | Authenticated private S3 image transport; restricted ID/consent evidence | Tests use fakes; owner confirmed profile-photo persistence; full privacy/audit hardening pending |
| Visits / QR / rewards / raffle | Explicit visit confirmation, daily Dublin limit, permanent history, transactional rewards/raffle/print jobs | Existing memory/fake-DynamoDB, concurrency, calendar and role tests; no new live acceptance claimed |
| Printing | Durable queue, Windows Epson adapter, device-auth integration and Owner device UI | Project owner confirmed successful Epson TM-m30III printing on-site; provisioning/TLS/revocation acceptance must be tracked separately |
| Branding | Loyalty System wordmark, Outfit/Manrope, neutral login, verified-tenant Trumps theme and employee greeting | Present in frontend code/tests; no messaging capability implied |
| Ticket designs | Current checkout defaults to template 3; supports legacy 1/2 | Uses original Dublin issuance time; previously discussed version-4 centred redesign is NOT present in this checkout |
| SMS | Selected provider only; explicit unconfigured QR-send boundary | No real sender, Twilio dependency/configuration, SMS history, campaign UI, birthday scheduler, delivery callback or inbound opt-out handler |

Evidence: `backend/main.py`, `app/{models,service,auth,routes,qr_routes,
voucher_rules,voucher_repository,loyalty_repository,print_models,tickets}.py`;
`frontend/src/{App,qrFlow,branding,employeeProfile}` and customer/QR components;
backend requirements and frontend package manifest. Automated coverage exists in
`test_vouchers.py`, `test_qr_management.py`, `test_auth.py`, `test_customers.py`,
`test_media.py`, loyalty/raffle/print tests and frontend tests. Historical full-suite
results were 271 backend tests plus 86 subtests, 119 frontend tests and 33 agent
tests; these are prior verification results, not a fresh full-suite run here.
During this documentation review, the targeted voucher, QR-management and auth
suites passed: 86 tests plus 40 subtests (`venv/bin/python -m pytest
 tests/test_vouchers.py tests/test_qr_management.py tests/test_auth.py -q`, from
`backend/`). No live provider, AWS or printer was accessed. No frontend code changed.

### Messaging and consent findings

- `POST /customers/{id}/qr/send` verifies a business-scoped customer and always
  returns HTTP 501. It currently allows all customer roles; when enabled, sending
  must become Owner/Manager-only, including the direct API and UI. Staff retain
  QR view/copy and visit/voucher access; that does not authorize SMS sending.
- Frontend QR send displays an error, never delivery success. There are no
  individual-message or campaign routes, sending controls, message receipts or
  communication history. Dashboard opted-in counts are not messaging reports.
- `marketing_consent` defaults false. `CustomerService` sets `consent_timestamp`
  on opt-in and subsequent grant/withdrawal transitions; unrelated edits preserve
  it. This is only the latest transition, not immutable evidence of each consent.
- Staff may currently edit customer details INCLUDING the consent Boolean.
  There is no durable customer-edit/consent audit trail. SMS implementation must
  audit these transitions and must prevent ordinary form edits from clearing an
  explicit suppression. Any re-consent workflow needs evidence and approval.
- Signed evidence lives in protected media metadata/S3, accessible only to
  Owner/Manager. It does not update structured consent. Never give a messaging
  worker access to ID/consent images, and never attach them to an SMS.
- No inbound STOP, suppression list, unsubscribe link, provider-block handling,
  purpose-specific consent, consent wording version, or SMS-specific permissions
  are implemented. Do not treat customer inactivity as the opt-out mechanism.
- Business scope comes from verified Cognito `custom:business_id`; no request body,
  query, branding selection or phone alone may authorize another business.
  Existing type filtering excludes internal rows from customer results; new SMS
  records must explicitly preserve and regression-test that property.

### Birthday and loyalty rules that MUST remain unchanged

`rewards_for_visit` issues LOYALTY_10 (1000 cents) at each new fifth valid visit,
expiring at the next Dublin midnight. BIRTHDAY_20 (2000 cents) requires a valid
visit during the Monday–Sunday birthday week, once per birthday year, expiring
at the following Monday midnight. Adjacent years cover New Year weeks; Feb 29
maps to March 1 in non-leap years. Both rewards may issue together. Consent is
not part of reward eligibility and must not be added as an issuance condition.

There is no scheduled voucher issuance. The Voucher model requires a qualifying
visit and trusted issuer; the repository writes vouchers, REWARD/VCODE locks,
visit, raffle and print jobs together. A scheduler must never fabricate a visit,
issue a duplicate voucher, reset counters or queue paper to send a greeting.

Proposed birthday automation: one consent-aware greeting/invitation per birthday
year, inviting an eligible visit to claim the existing reward. Do not describe
an unissued voucher as issued or include a made-up code. A separate notification
may reference an actually committed birthday voucher. Loyalty notifications must
reference the existing €10 voucher, code and exact expiry, never issue a reward.
Whether greetings run on the birthday itself or the start of birthday week,
catch-up timing and multiple same-day message limits require approval first.

## Original Milestone 5 SMS proposal (historical design; delivered subset below)

### Low-volume architecture recommendation

For 150–200 customers, retain FastAPI + repository/service interfaces, the existing
DynamoDB table and a small durable outbox. Do not introduce another database, a
CRM, per-customer schedules or Kafka. Mirror the repository in memory for tests;
real durable sending requires DynamoDB. Keep Twilio behind an injected provider
adapter with a fake that is the default for tests and local previews.

Human UI → authenticated Owner/Manager messaging service → conditional message /
campaign/outbox writes → bounded background worker → Twilio → signed status /
opt-out webhooks → message history and suppression state.

Use an independently supervised worker process initially, with persisted leases,
conditional claims, bounded batches and a documented restart procedure. Avoid a dedicated VPC/NAT
setup solely for this tiny worker unless a separate security requirement needs it. Do not
rely on browser timers, request-side sends or FastAPI BackgroundTasks as durable
execution. The local app must actually be running for this option to automate.
For always-on deployment, an explicitly approved EventBridge Scheduler timezone
schedule in Europe/Dublin can invoke a Lambda planner/worker; re-use the same
service policy and outbox, not a second implementation of rewards. An approved
business registry/configuration supplies scheduled tenant IDs, never an HTTP
business override. A daily local-time birthday planner plus small due batches is
sufficient here. No Scheduler, Lambda, IAM or table resource is provisioned now.

At this scale, paginated business Query + CUSTOMER filter is adequate for daily
birthday discovery; no full table Scan or birthday GSI is initially necessary.
It still reads filtered internal items and will cost more as history grows.
Use bounded retention and measure before adding a queue/status GSI or SQS/DLQ.
Plan workers by explicit authorized business partitions; no cross-tenant Scan.

Store secret references and sender configuration server-side per business.
Prefer a dedicated Twilio Messaging Service per business and consider subaccounts
for stronger credential/billing separation. No fallback to another tenant's
sender/credential. Use limited send API credentials where supported; webhook
signature verification needs the appropriate Twilio auth token separately.
Secrets stay in backend environment locally and approved secret storage/IAM at
deployment, never Vite, Git, customer records, print-agent config or browser logs.
HTTPS callbacks must validate Twilio signatures with the official helper and the
exact externally configured URL; never trust arbitrary forwarded headers.
Resolve the tenant from a server-owned account/service/sender binding, then
match the provider message SID and stored message. Do not trust callback tenant
parameters or phone numbers alone. Unknown/mismatched events fail closed.

### Consent, sending safety and history

For the first release, require active customer + explicit marketing consent +
no tenant/phone suppression for every birthday, voucher, promotional, individual
and QR-link message. Do not silently classify promotional content as transactional
or infer permission from a voucher, visit, uploaded image or existing relationship.
Any future service-message exception needs a separately approved policy.
Check eligibility when queued AND immediately before provider dispatch; cancel
queued messages after withdrawal, inactivity, phone change or source expiry.
Persist destination and consent revision used; a changed phone requires fresh
verification/consent policy, not transfer of an old consent assertion. Ordinary
customer edits cannot lift an opt-out. Requests already accepted by Twilio cannot
be recalled reliably; disclose that race rather than promise perfect cancellation.

Opt-outs are a prerequisite to live sending. A reply-capable sender can use
Twilio Advanced Opt-Out plus validated inbound events, mirrored locally.
Alphanumeric senders cannot receive replies: do not print 'Reply STOP' when it
cannot work. Provide an approved, simple alternative (e.g. an opaque single-purpose
unsubscribe link with no login) before using that route. Link GET should show a
confirmation page rather than mutate consent on link-preview fetch; withdrawal
POST must be easy and avoid exposing customer/tenant identity. A suppression is
business + normalized phone scoped and survives a new customer record; any
provider/account-wide block must ALSO be honored, never bypassed via another
sender. Shared inbound numbers with ambiguous tenant identity must not guess a
business: use distinct bindings or conservatively suppress all affected bindings.
Re-consent requires a deliberate verified process, not an automatic START or form
checkbox clearing the local restriction without evidence.

Owner/Manager can compose, preview, confirm and inspect scoped individual/campaign
history. Staff must be denied send/campaign/history admin endpoints independently
of hidden controls. Owner controls provider/sender/business spending settings;
Manager cannot configure security/provider credentials. Record trusted Cognito
subject, time, message/campaign purpose, recipient, consent evidence reference,
template version, safe error/status, provider SID and state transitions.
Retain bounded encrypted/protected message content/destination only as needed;
redact bodies, phones, QR bearer links, voucher codes and tokens from logs.
Configure retention/erasure for history and minimal lawful suppression separately;
DynamoDB TTL is eventual cleanup, not an expiry or security decision.

Use separate states such as QUEUED, CLAIMED, SUBMITTING, ACCEPTED, SENT, DELIVERED,
FAILED, UNDELIVERED, SUPPRESSED, CANCELLED and UNKNOWN. API acceptance is not
handset delivery. Authenticate/deduplicate callbacks, tolerate out-of-order events,
and prevent stale status regression. Retry only known-safe pre-submit failures
with bounded backoff. A timeout/crash after submission can mean Twilio accepted:
mark UNKNOWN, reconcile by SID/callback if available, otherwise require operator
review. Do not auto-resend ambiguous submissions or claim exactly-once external
SMS delivery; a DynamoDB transaction cannot include Twilio's HTTP request.

Preview personalised final content, recipient count, encoding/segment count and
estimated spend; require explicit campaign confirmation and an idempotency key.
Re-evaluate recipients before dispatch, deduplicate by normalized phone, use
per-tenant daily/monthly budgets, provider rate limits, quiet hours and a kill
switch. Start with one segment where possible; Euro signs use GSM extension
space and emoji/Unicode can increase billed segments. Do not hardcode a tariff.
Budget = recipients × actual segments × current destination rate, plus number /
sender charges, inbound traffic, fees and small hosting/storage costs. At this
scale segment length and campaign frequency matter more than database size.
An unpaid-preview/fake-provider mode must make no provider network calls.

### Proposed same-table records and access patterns (design, not migration)

Keep String PK `business_id`, SK `customer_id` and typed internal records. Example
key shapes below are a reviewable proposal, not existing repository contracts.

| Proposed SK / item | Purpose and access |
| --- | --- |
| `SMS#<customer UUID>#<message UUID>` / SMS_MESSAGE | Customer history prefix Query; business SMS# Query; purpose, actor, source voucher/year, consent revision, destination snapshot, template, state, SID and UTC timestamps |
| `SMS_LOCK#<purpose>#<source>` / SMS_DEDUP | Conditional idempotency: voucher UUID for reward notice; customer + birthday year for greeting; campaign + customer for campaign; user request key for individual SMS |
| `SMS_DUE#<UTC bucket>#<message UUID>` / SMS_OUTBOX | Query bounded due buckets per business; pointer to canonical message, due time, attempts, lease owner/revision; canonical row remains authority |
| `CAMPAIGN#<UUID>` / SMS_CAMPAIGN | Immutable confirmed audience/content version, creator, timestamps, budget reservation, counters; bounded paginated recipient rows, never a large customer array on one item |
| `SMS_CONSENT#<customer UUID>#<UTC time>#<event UUID>` / SMS_CONSENT_EVENT | Append-only grant/withdrawal/re-consent, actor/source, purpose/wording version, evidence reference and destination binding; transactional projection update |
| `SMS_SUPPRESS#<keyed phone digest>` / SMS_SUPPRESSION | Tenant + canonical phone point lookup, state/source/time; avoid plaintext phone keys; backend-managed stable HMAC key with rotation plan |
| `SMS_PROVIDER#<provider SID>` / SMS_PROVIDER_INDEX | Resolve callbacks inside a server-selected tenant; validate sender/account/service binding and canonical message |
| `SMS_SETTINGS` / SMS_BUSINESS_SETTINGS | Owner-controlled timezone, enabled purposes, sender/service mapping, budgets, quiet hours and secret references only |

Atomically create canonical message + dedup lock + due pointer, with customer
consent/status/revision conditions. Worker claims and lifecycle writes use CAS;
move due pointers atomically and always recheck canonical state. Birthday greeting
locks are distinct from existing REWARD_LOCKs and do not consume voucher eligibility.
Loyalty/birthday-issued notices should join the existing reward transaction as
outbox intents, not network calls; consent failure should omit the notification,
not reject an otherwise valid visit. Serialize against the same customer revision;
recompute on conflicts. Update both memory/DynamoDB implementations and transaction
size accounting, preserving existing customer/media/phone/QR/reward/raffle/print data.
Campaign fan-out is chunked, restartable and idempotent, not one 200-recipient
transaction. Callback lookup must handle the brief SID-persistence race without
creating duplicates; persist validated unmatched events for bounded reconciliation.

No new table or GSI is required for this proposed initial design. Due buckets
must cover overdue work and abandoned leases with a durable cursor/recovery rule;
never query only the current minute. Keep work discovery bounded at this scale.
A static server-owned tenant-to-Messaging-Service mapping suffices initially;
a reserved routing partition or index, if later needed, needs explicit review.
Add all new internal types/prefixes to exclusion and API regression tests.

Backfill policy: no automatic sends, reward issuance or historical message claims.
Existing consent booleans/timestamps are legacy evidence only: preserve them and
record any migration as migration, not newly obtained consent. Audit whether the
original wording/source is adequate before enabling recipients; otherwise obtain
new consent. Enable the worker after a deployment cutover timestamp, with explicit
review for any catch-up and existing vouchers; expired rewards must never notify
as spendable. No backfill or database write is performed by this review.

### Implementation order and approval gates

1. Approve birthday greeting timing, reward wording, consent/re-consent and phone
   change policy, quiet hours, history visibility/retention, sender/opt-out method,
   spend cap and milestone label. Keep existing reward eligibility unchanged.
2. Build models, memory/fake-DynamoDB repositories, consent audit/suppression,
   idempotent outbox and fake provider; use no live Twilio credentials. Test Staff
   denial and tenant isolation, including the existing QR-send placeholder.
3. Implement signed inbound/status callback handling, unsubscribe flow and
   provider adapter behind default-off flags and a development recipient allowlist.
   Unit tests use signed synthetic events and stubbed Twilio; no live sends.
4. Add Owner/Manager individual/QR messaging, campaign preview/confirmation/history,
   segment/spend checks, opt-out cancellation and Owner settings. A 200-recipient
   campaign requires resumable fan-out, budget reservation and no duplicate send.
5. Add commit-linked €10/€20 voucher notification outbox intents; validate expired,
   redeemed, suppressed, changed-phone, duplicate and ambiguous-send cases without
   altering visit, reward or print behavior.
6. Add timezone-aware birthday greeting planner using the existing leap/New Year
   calendar policy, year-level notification locks, cutover/catch-up safeguards and
   no visit/voucher creation. Test DST and scheduler retries with a fake clock.
7. Only after separate approval: provision sender/HTTPS/secret/scheduler resources,
   verify Ireland registration and opt-out operation, then allowlisted acceptance
   with consenting test recipients, budget alerts and staged enablement.

Required tests include concurrent claims/fan-out, callback signature/spoofed tenant,
duplicate/out-of-order callbacks, timeout-after-acceptance, opt-out between queue
and dispatch, consent edit auditing, phone reassignment/re-consent, sender ambiguity,
provider blocks, all roles/tenants, DST/leap/year boundaries, vouchers unchanged,
no historical sends and no regression to customer/media/QR/visits/raffle/printing.
The user subsequently approved the Owner/Manager simulation subset described below.
The remaining real-delivery/automation phases still require separate approval.

### External requirements checked for this proposal

- [Twilio Ireland guidelines](https://www.twilio.com/en-us/guidelines/ie/sms) and
  [ComReg Sender ID Registry](https://www.comreg.ie/industry/electronic-communications/nuisance-communications/sms-sender-id-registry/):
  registered sender requirements must be confirmed before live Irish A2P use.
- [DPC consent guidance](https://www.dataprotection.ie/en/dpc-guidance/faq-consent-electronic-direct-marketing):
  direct marketing has specific consent/opt-out requirements; this proposal uses
  explicit opt-in rather than assuming a customer-relationship exception.
- [Twilio Advanced Opt-Out](https://www.twilio.com/docs/messaging/tutorials/advanced-opt-out)
  and [webhook validation](https://www.twilio.com/docs/messaging/guides/webhook-request):
  provider suppression complements local controls; authenticate external events.
- [Twilio Ireland pricing](https://www.twilio.com/en-us/sms/pricing/ie) and
  [segment limits](https://www.twilio.com/docs/glossary/what-sms-character-limit):
  charged segments/encoding and current route rates drive the estimate, not a
  blanket promise of a fixed monthly price.
- [EventBridge timezone schedules](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html):
  evaluate local-time/DST semantics explicitly rather than treating a day as 24h.


# Milestone 5 — Owner/Manager SMS Messaging simulation IMPLEMENTED

Implementation on `feature/sms-messaging`, 16 October 2026. Real Twilio sending is
NOT implemented; no SDK, credentials, callback, scheduler or provider network call
was added. No birthday/loyalty issuance, receipt/agent, visit or raffle logic changed.
This section supersedes SMS absence claims in the pre-implementation review above.

## Delivered and tested

- Owner/Manager-only `#/sms` navigation and page; direct Staff route displays a
  denial without loading customer/SMS data. All SMS backend routes use existing
  `require_management` and verified business scope, including legacy mismatched
  business query rejection. Neither UI tenant inputs nor client estimates are trusted.
- Individual selection with existing name/Irish-phone search, or all eligible
  customers; editable free text, literal `{first_name}` personalisation only,
  recipient-specific escaped previews, eligible/excluded counts, encoding,
  character/UTF-16-or-GSM unit counts, segment count and illustrative EUR cost.
- A stored 15-minute DRAFT fixes the preview text, sender, recipient identities,
  destination/name/consent/customer-revision snapshots and creator Cognito subject.
  Preview creates no delivery/budget reservation. The explicit confirmation checkbox
  and API `confirmed=true` are required; only the draft creator can first confirm.
- Confirmation rechecks the audience, sender/price and eligibility. Any change
  requires a fresh preview; no newly eligible customer is silently added. Empty
  audiences cannot queue. The immutable draft ID is the idempotency key: repeating
  confirmation after response loss returns that campaign and reserves budget once.
- Budget reservation and DRAFT→QUEUED transition commit atomically. Concurrent
  campaigns cannot overspend the configured limit. Monthly accounting uses Dublin
  calendar months and integer EUR micros, never floating-point money. Reserved
  amounts are conservatively retained for failed/suppressed/unknown outcomes;
  simulation incurs no real charge. Prior-month queued work is suppressed rather
  than spending a reservation in a new month. No automatic refunds or live billing.
- Active status, canonical valid Irish mobile, explicit marketing_consent with
  a nonfuture aware timestamp and absence of phone suppression are mandatory.
  Rechecked before claim and immediately before provider invocation. A changed
  phone or consent transition after queue suppresses the recipient. Customer
  revision and suppression absence fence the durable claim transaction.
- Confirmed manual SMS opt-out creates a permanent tenant/phone suppression.
  Ordinary customer edits/checkboxes cannot clear it. No removal/re-consent API,
  inbound STOP or public unsubscribe handler exists. STOP text in the editable
  example is demonstration content, not a working reply route; the UI says so.
- Typed message-history/status projection, original creator/time, per-recipient
  destination, consent snapshot/decision, current status/update time and safe
  reason/provider ID. SIMULATED is explicitly distinct from SENT/DELIVERED.
  No message bodies, phones, tokens or provider exceptions are logged by SMS code.
- Provider Protocol plus network-free SimulatedSMSProvider. Configuration rejects
  any provider except simulation. UNKNOWN never auto-retries; explicit guaranteed
  pre-submission SafeRetry uses a 30-second delay and at most three attempts.
- Worker uses a unique submission fence, conditional revision writes and a
  two-minute lease. Abandoned SUBMITTING becomes UNKNOWN, never requeued.
  Concurrent worker updates merge only while the same recipient fence is current.
- Owner/Manager can explicitly process the simulated queue in the UI; optional
  supervised standalone worker processes durable DynamoDB campaigns. No implicit
  worker starts with FastAPI, and no request sends real SMS. Memory-mode UI
  simulation uses the same repository/service but loses everything on restart.
- The old QR-send placeholder is now Owner/Manager-only (Staff 403), remains 501
  and does not queue/deliver QR links. QR copying/viewing and visit rules unchanged.

## Implemented storage design (supersedes the proposed per-message layout)

Uses existing DynamoDB String PK `business_id` / SK `customer_id`. No new table,
GSI, full-table Scan, migration, startup backfill or AWS configuration change.

| Key / item type | Current purpose |
| --- | --- |
| `SMS_CAMPAIGN#<UUID>` / SMS_CAMPAIGN | Bounded outbox aggregate: one template plus up to 200 recipient snapshots, per-recipient statuses, attempts/fences and consent decisions; DRAFT or QUEUED/FINISHED |
| `SMS_BUDGET#<Dublin YYYY-MM>` / SMS_BUDGET | Atomic cumulative monthly reservation, protected by revision CAS |
| `SMS_SUPPRESS#<SHA-256 canonical phone>` / SMS_SUPPRESSION | Durable tenant-scoped opt-out; creator/time/reason; no clearing endpoint |

The aggregate intentionally replaces the earlier speculative message/lock/due
index design at this volume: one confirmed campaign and one budget row commit
together, avoiding partial 200-recipient fan-out. The draft UUID is the dedup key;
there is no separate SMS_DEDUP item or repeat-content heuristic (a newly previewed
and deliberately confirmed campaign is a new send). Updates are conditional on
revision; failed transactions leave both outbox and budget unchanged. A companion
SMSRepository follows the existing DeviceRegistry-style adapter pattern: memory
state is owned by the selected repository; DynamoDB reads/writes reuse its SDK
helpers and error boundaries. Routes contain no DynamoDB SDK operations.

The existing transaction wire/item size guards also apply; an unusually large
campaign is rejected before writes rather than partially queued. Query follows
all pages of the tenant SMS_CAMPAIGN# range; workers include older unfinished
campaigns, not just current-time work. History returns the latest 100 non-drafts.
This is suitable for the current small volume, not a status-index design at scale.
All SMS_* keys/types remain excluded from customer lookup/list results.
Phone hashes are pseudonymous, not anonymous or enumeration-resistant; apply the
same private-table/IAM/retention protection as customer records. The previously
proposed keyed digest remains a future hardening option, not an implemented claim.

## API and server-only configuration

All endpoints below require Owner/Manager and return no-store responses:

- `GET /sms/settings`: sender, simulation-only flag, illustrative segment rate,
  current Dublin month, monthly limit and reserved amount; no secret/config writes.
- `POST /sms/preview`: `{audience: "individual"|"all", customer_id?: UUID, message}`.
- `POST /sms/campaigns/{UUID}/confirm`: `{confirmed: true}`; idempotent for that draft.
- `GET /sms/history`: confirmed campaign and recipient results in the business.
- `POST /sms/simulate`: `{}`; bounded batch of up to 200 provider attempts.
- `POST /sms/customers/{UUID}/suppress`: `{confirmed: true}`; permanent phone opt-out.

`SMS_BUSINESS_SETTINGS_JSON` optionally supplies settings keyed by verified
business. Defaults: provider simulation, sender `Loyalty System (simulation)`,
segment_price_micros=100000 (EUR 0.10), monthly_limit_micros=20000000 (EUR 20).
These are transparent simulation assumptions, NOT verified Twilio tariffs.
Only backend operators configure settings; Managers cannot change them. Unknown
businesses get neutral simulation settings, never another business's configuration.
A zero limit prevents new confirmations. No API key, SID or auth token is needed.

Local fictional-data acceptance: restart FastAPI/reload Vite; log in as Owner or
Manager, open SMS Messaging, select an active opted-in fictional customer, edit
text, preview, confirm and click Process simulated queue. Inspect SIMULATED rows
and history; repeat the same confirmation to verify no additional budget charge.
Test an opt-out before dispatch; expect SUPPRESSED and no provider invocation.
Staff cannot see navigation or use direct APIs. Use memory mode to avoid AWS.

Optional operator worker (not executed during implementation), from backend:
`venv/bin/python scripts/run_sms_worker.py --business trumps --once`.
It requires explicitly configured DynamoDB because a separate process cannot
share in-memory customers/outbox. Omit `--once` only under an approved supervisor;
no production run is authorized here. Restart after backend settings changes.

## Pending before Twilio activation / broader automation

- Real Twilio adapter, account/sender registration, credentials, TLS webhooks,
  validated delivery receipts and automated inbound/unsubscribe suppression.
- Full immutable customer-consent/edit auditing, documented consent wording and
  re-consent/phone ownership/reassignment policy. Current structured consent is
  used for simulation only; it is not a legal audit of the imported customer base.
- Birthday greetings, scheduled discovery and €10/€20 reward notifications remain
  unimplemented. Existing voucher rules are unchanged and entirely visit-triggered.
- Live pricing/fees, actual currency billing, provider rate limiting, quiet hours,
  full operational audit export, retention/erasure and public history pagination.
- Bulk history/discovery currently reads all retained campaign rows; aggregate CAS
  can cause contention. Measure before introducing per-message outbox/index/SQS.
  DRAFT cleanup and retention are not automatic. No claim of exactly-once external
  delivery: unknown outcomes require review, and requests already dispatched
  cannot reliably be recalled if consent is withdrawn concurrently.

Automated validation: 314 backend tests plus 86 subtests; 128 frontend tests;
frontend lint/build; 33 Print Agent tests. Tests use local fixtures, fake DynamoDB,
mock providers and synthetic Cognito verification. No live AWS, SMS or hardware.

## SMS recipient search and audience UX — 19 October 2026

Implemented on `feature/sms-messaging`; simulation-only delivery and all existing
confirmation, budget, idempotency, outbox, voucher and printer rules preserved.

Verified root causes in the previous SMS interface:

- Typing filtered options in a CLOSED native select; it did not display selectable
  matches under the search field. The matching helper itself supported names and
  Irish phone formats; there was no SMS-specific search endpoint.
- Customer loading shared one Promise.all with settings/history. Either metadata
  request failing discarded the successful directory response. Initial metadata
  loading also blocked the whole form, including search.
- Global input CSS gave radios full width, visually separating them from labels.
- There was no search-specific loading/error/empty state or backend suppression
  eligibility reason available to the selector. Eligibility was not filtering the
  old directory; a closed/empty dropdown could hide both eligible/ineligible matches.

Current behavior:

- Two full clickable audience cards, native labelled radios with descriptions,
  same-name radio grouping (Tab/arrows/Space), focus-within outlines, tenant theme
  primary borders and soft selected backgrounds. Trumps uses existing burgundy;
  cards stack on mobile and stay side-by-side on wider screens.
- New read-only Owner/Manager `GET /sms/customers?q=...` uses the existing customer
  service/list repository. DynamoDB still performs a paginated business Query,
  filters CUSTOMER records, and never Scans or returns internal SMS/other records.
  No new table/index/migration. Scope comes from verified Cognito business only;
  Staff gets 403, anonymous gets 401, conflicting legacy business query gets 403.
- Search supports case-insensitive partial first/last/full names and equivalent
  Irish national, no-leading-zero, +353 and 353 phones; partial phones work too.
  Registration/update phone validation is untouched. Query length is bounded at
  100 characters; blank query returns no results and prompts the user to type.
- Results include customer UUID for selection, name, masked phone (last four
  digits), SMS eligibility and a safe reason only. No full phone, DOB, signed
  evidence, media, consent timestamp or storage keys are returned by search.
  Match totals are reported with at most 25 displayed results and a refine hint.
  Search query strings should be redacted by production access-log configuration
  because name/phone searches can contain personal information.
- Ineligible customers remain visible, with inactive / invalid phone / no consent /
  invalid consent timestamp / SMS opt-out reasons. They cannot be selected; signed
  image evidence is not an added eligibility condition. The same eligibility
  policy is used for search, preview, confirmation and dispatch.
- Debounced 250 ms typing and Enter search show direct selectable result buttons,
  loading, no-results and retryable error states. Stale/unmounted responses are
  ignored. No metadata request is needed to search; metadata errors are separate.
- Choosing a result stores the selected masked summary and clears an old preview.
  Selection survives a different search until explicitly cleared or the audience
  changes. Clear/audience changes remove selection and preview. Newly returned
  ineligibility/explicit opt-out updates the selection and prevents preview.
- Search/selection write no visits, drafts, campaigns, budgets or messages.
  Preview still calls the original SMS preview; only explicit confirmation queues.
  Backend consent/budget revalidation remains authoritative even after selection.

Regression coverage includes repository parity with fake DynamoDB, partial names,
all Irish phone representations, masked projections, ineligible result reasons,
read-only search, result limits, role/tenant guards, independent metadata failure,
stale/cancelled requests, selection preservation/clear, disabled ineligible results
and native-radio/responsive CSS contracts. Browser/hardware/live-AWS acceptance
is not claimed by those automated tests.

Validation for this improvement: full backend suite 326 passed + 86 subtests;
frontend 138 passed, lint and production build passed; Print Agent regression
33 passed; Python compilation and git diff --check passed. Tests were offline;
no provider calls, production AWS reads/writes or physical printing occurred.
Restart FastAPI for the new search endpoint and reload Vite before acceptance.

## SMS message preview redesign — 19 October 2026

Frontend-only presentation update on `feature/sms-messaging`. The long expandable
recipient rows are replaced by three compact summary cards (eligible recipients,
total SMS segments, estimated EUR cost), with excluded count/reasons separately.
Totals remain the authoritative backend preview values; no price, eligibility or
segment calculation moved into the UI.

A labelled native customer dropdown shows names and masked phones (last four
digits). It defaults to the first eligible recipient; selecting another recipient
immediately changes only the displayed server-personalised body and its encoding,
character and segment metadata. New campaign previews reset the selector. Empty
recipient sets show a clear no-eligible-recipient state rather than an empty bubble.
The selector never changes the audience, invokes an API or alters message content.

The SMS-style bubble preserves original paragraphs, line breaks and spaces using
pre-wrap CSS and safe React text rendering. Sender, simulation badge and per-message
metadata are separate from the exact body. Existing tenant variables provide the
Trumps dark/burgundy styling; layouts stack on mobile without overflowing long text.
Confirmation retains the same explicit checkbox, disabled guards and original
flow.confirm call, with improved spacing and a count-aware label such as
"Confirm and queue 3 messages". Simulation is stated beside the preview and again
in the confirmation section. Backend consent, suppression, cost, budget,
idempotency, outbox, auth, voucher and print behavior is unchanged.

Tests cover first/default and changed recipient selection, immutable personalised
content, masked labels, authoritative summary totals, empty/null previews, escaped
text, responsive CSS contracts and the unchanged explicit confirmation request.
Validation: 146 frontend tests passed; lint/build passed; relevant backend SMS/auth
regressions 71 passed + 40 subtests; git diff --check passed. Browser visual testing
is not claimed. No real SMS, production AWS or printer was used. Reload Vite to
review the redesigned preview; no backend restart is needed for this UI update.


## Simplified SMS workflow — 19 October 2026

This supersedes the earlier technical SMS page and manual-processing instructions.
The Owner/Manager page now uses Compose → Confirm → Result, with separate collapsed
message history. No permission, tenant, consent, suppression, pricing, budget,
idempotency, voucher, raffle or printing rule was relaxed.

- Compose: select one customer or all eligible customers, edit the message, see
  a simple bubble, then use **Send message** or **Cancel**. Encoding/segment counts,
  budget controls, technical statuses, manual processing and refresh buttons are
  not shown. Existing recipient cards/search remain. Cancel starts over without
  confirming/queuing; abandoning a server DRAFT does not reserve budget.
- Compose preview is presentation-only and makes no requests/writes while typing.
  Individual names use the scoped search projection's first_name (new display
  field); bulk uses a clearly labelled fictional Sarah example. Only Send obtains
  the server-authored final preview and actual eligible count/cost. Message text
  submitted to the backend is unchanged; the final server preview is authoritative.
- Confirmation is a separate step showing actual recipient count and estimated
  EUR total, the final personalised preview and simulation notice. Its only action
  buttons are **Yes, confirm send** and **Go back**; no extra checkbox is required.
  Yes sends the existing `{confirmed: true}` request for that reviewed draft.
- Go back preserves composition. Re-review without edits reuses the same draft;
  edits invalidate it. Network errors keep that confirmation ID for safe explicit
  retry; there is no automatic confirmation POST retry. Definitive 409/422 errors
  return to Compose with the server error so a new preview can be obtained.
- Results distinguish waiting/queued from completed simulation and true delivery.
  The simulator emits SIMULATED, never DELIVERED. Unknown outcomes are described
  as needing review and remain blocked from automatic resubmission. A read-only
  status refresh updates a visible pending result. **Start a new message** resets
  compose state without deleting the committed campaign/history.
- Separate history uses plain-language per-customer statuses and Dublin timestamps,
  masks phone numbers and omits internal state codes/consent audit/debug fields.
  Protected backend records still retain the original audit/consent information.
  The manual SMS opt-out compose control is removed; existing suppression records,
  authenticated suppression API and consent-withdrawal enforcement remain intact.

### Safe backend simulation worker

FastAPI lifespan now owns one background simulation thread per application process.
It starts/stops with the backend, wakes on confirmed campaigns and processes bounded
20-attempt batches through the EXISTING SMSService.process implementation. The
persisted outbox, budget reservation, current eligibility/customer-revision checks,
submission fence, retry limit and UNKNOWN policy remain authoritative. No in-memory
background task is used as the source of truth or as the sole record of a send.
Only the exact network-free SimulatedSMSProvider class is permitted by the worker;
introducing a real provider requires an explicit implementation change/approval.

Worker business scopes come only from verified Owner/Manager confirmations, scoped
history/status reads (for recovery), or server-owned SMS_WORKER_BUSINESSES config.
No client business ID is accepted. New protected GET /sms/campaigns/{UUID} returns
the business-scoped campaign status for result polling; missing/foreign IDs fail.
It registers the verified scope but does not create/confirm messages. Search adds
first_name for the local preview; filtering and eligibility policy are unchanged.

For unattended restart recovery, configure `SMS_WORKER_BUSINESSES=trumps` in the
backend environment (optional comma-separated server-approved businesses).
Without that setting, a restarted worker adopts a business when its authorized
user confirms or reads existing history/status; dormant partitions are not Scanned.
Only previously confirmed outbox entries are eligible for processing. Memory mode
still loses all state on restart. Default Uvicorn lifespan support must remain on;
an application that is stopped cannot process messages. The optional standalone
worker remains operator tooling, not a customer-facing requirement.

Shutdown stops new work between recipients and waits for the current bounded call.
A crash during SUBMITTING is reconciled to UNKNOWN after its existing lease,
never automatically replayed. Known-safe pre-submit failures retain the existing
30-second/max-three retry rule. No new retry of uncertain output is introduced.
No Twilio adapter, credentials, AWS resources, birthday/voucher automation or
printer changes were made. Tests cover memory and fake-DynamoDB worker recovery,
role/tenant status access, shutdown, non-simulator refusal and suppression.

Validation: full backend 342 tests + 86 subtests passed; frontend 156 tests passed,
lint/build passed; Print Agent regression 33 passed. No live AWS, real SMS or printer
was used. Restart FastAPI to enable its lifecycle worker and reload Vite. Automated
UI checks do not replace browser acceptance of the simplified workflow.
