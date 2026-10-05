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

Planned AWS architecture:

- Lambda
- API Gateway
- S3
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

Future versions should support consent history/evidence.

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

Every visit must eventually record:

- customer
- business
- timestamp
- staff member

After 5 qualifying visits:

- customer receives a €10 voucher
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
- have an active/redeemed status
- only be redeemable once
- record redemption timestamp
- eventually record which staff member redeemed them

Voucher history must be preserved.

---

# Authentication and Roles

Authentication now uses Amazon Cognito for the current customer API.

Cognito authenticates BUSINESS USERS, not loyalty customers.

The following authorization model is finalized. Milestone 3 implements
authentication, role guards and current customer permissions. Permissions for
documents, SMS, visits, vouchers, staff administration and reports remain
requirements for future endpoints, not implemented functionality.

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

Future requirements include:

- customer profile photograph
- ID document image
- signed SMS opt-in form image

Images/files must NOT be stored directly inside DynamoDB.

Future storage:

Private Amazon S3 bucket.

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
including any future private file retrieval.

S3 objects should eventually use encryption, authorization controls and
appropriate retention/deletion policies.

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

Document metadata extensibility is preserved; no document/S3 functionality
or other document/loyalty/messaging milestone has been implemented.

---

# Milestone 3 — IMPLEMENTED; LIVE COGNITO ACCEPTANCE PENDING

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

Live Cognito login acceptance still requires the manual README procedure.
Customer edit audit persistence, production MFA/recovery, immediate token
revocation enforcement and deployment hardening remain future work. ID tokens
already issued remain valid until expiry under local JWT verification.

# Future Milestones

## Milestone 4
Private S3 document storage and webcam capture

## Milestone 5
QR scanning and visit tracking

## Milestone 6
Voucher generation and redemption

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