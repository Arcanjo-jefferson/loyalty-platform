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

Planned AWS architecture:

- DynamoDB
- Lambda
- API Gateway
- Cognito
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

Current/planned implementations:

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

Authentication will eventually use Amazon Cognito.

Cognito authenticates BUSINESS USERS, not loyalty customers.

Planned roles:

## Owner / Admin

Can:

- manage business configuration
- manage staff
- manage customers
- send campaigns
- view reports
- manage loyalty configuration
- manage vouchers

## Manager

Can:

- manage customers
- send SMS
- record visits
- manage/redeem vouchers
- view appropriate reports

## Staff

Simplified access.

Can:

- scan customer QR
- find customer
- view necessary loyalty information
- record visit
- check voucher
- redeem voucher

Staff should not automatically receive access to sensitive customer documents
or administrative functionality.

Each staff member should have an individual account.

Shared staff accounts should be avoided because actions need to be auditable.

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

Do not expose ID documents to all staff.

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
- trust `business_id` supplied by the frontend once authentication exists

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

Eventually `business_id` must come from the authenticated business user's
identity/session rather than being trusted from frontend input.

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

# Milestone 2 — IMPLEMENTED; LIVE AWS VERIFICATION PENDING

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
Live table schema, permissions and restart persistence still require the
manual acceptance procedure documented in README.md. Do not consider live
AWS verification complete until that procedure succeeds.

Document metadata extensibility is preserved; no document/S3 functionality
or other later milestone has been implemented.

---

# Future Milestones

## Milestone 3
Cognito authentication and staff roles

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