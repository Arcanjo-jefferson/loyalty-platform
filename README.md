# Loyalty Platform

A local MVP for a future multi-business customer loyalty and SMS marketing platform. The project is designed to give managers a customer directory and, tools for recording visits and, in later milestones, issuing rewards and communicating with customers who have opted into marketing.

**Current status: Milestones 1–3 completed and manually verified against AWS by the project owner; Milestone 4 profile-photo storage/retrieval manually verified; Milestone 5A implemented, awaiting live QR/visit acceptance testing.** The application runs locally with a React manager dashboard and a FastAPI customer API. Customer persistence is configurable between DynamoDB and an optional in-memory repository. Cognito business-user login and server-side role/tenant authorization are implemented. Private customer images, camera capture and ID verification are implemented. QR lookup, explicit visit confirmation and loyalty progress are implemented. Voucher issuance and SMS sending remain planned. DynamoDB persistence was manually verified by the project owner.

## Implemented features

- Responsive dashboard, sidebar and customer-management pages for desktop, tablet and mobile.
- Dashboard counts from actual local records: total customers, marketing opted-in and birthdays this month. Birthday month uses the manager's browser date; there are no invented business analytics.
- Customer directory with name/phone search, date of birth, promotional SMS consent, status and profile actions.
- Customer registration, read-only profiles and a separate edit page.
- Irish mobile input with a visible Ireland `+353` indicator. National and international formats are normalized to E.164 by the backend before storage and per-business duplicate checks. Incomplete or malformed numbers are rejected. Validation checks format, not phone ownership or service availability.
- Minimum age of 18 enforced in frontend and backend using the full birth date and the current date in `Europe/Dublin`. Invalid and future dates are rejected. February 29 birthdays reach the age threshold on March 1 in non-leap years.
- Explicit promotional/marketing SMS consent, with a UTC timestamp for the most recent consent transition.
- Secure UUID4 customer IDs and separate random, opaque `qr_token` values containing no personal data. Keyboard scanner lookup and confirmed visit tracking are implemented; QR rendering/printing remains planned.
- Server-managed UTC creation/update timestamps and active/inactive customer status.
- Successful registration and updates automatically open the customer's profile using the saved API response immediately. Reusable accessible notifications display `Customer registered successfully.` or `Customer details updated successfully.`
- Failed submissions remain on the form, preserve entered values and show an error without success feedback.
- Business-scoped storage and API queries use the verified Cognito user's `custom:business_id`; the frontend cannot choose another tenant.

- Configurable DynamoDB persistence through boto3, preserving the repository/service boundary and all Milestone 1 validation and UX.
- Atomic per-business phone-lock transactions, paginated business-scoped queries, optimistic concurrency checks and sanitized storage errors.

- Cognito email/password login, temporary-password completion, per-tab sessions, token refresh and logout; no public sign-up.
- Verified JWT authentication and reusable Owner/Manager/Staff guards on every customer endpoint.
- Private profile photos, ID documents and signed consent evidence; device image selection, camera preview/capture/retake and manual ID verification.

## Technology stack

| Area     | Current technology |
| ---      | --- |
| Frontend | React 19, JavaScript, Vite 8, Amplify Auth, reusable components and CSS |
| Backend  | Python, FastAPI, Pydantic 2, Uvicorn, PyJWT with cryptography, Pillow |
| Storage  | DynamoDB and private S3 via boto3; optional process-local in-memory customer repository |
| Checks   | Python `unittest`, Node.js test runner, Oxlint, Vite production build |

No large UI framework or additional routing library is used. The backend reuses boto3 for DynamoDB and S3. Pillow validates and re-encodes images; no npm dependencies were added for Milestone 4.

## Project structure

```text
loyalty-platform/
├── README.md
├── PROJECT_CONTEXT.md         # Architectural constraints and milestone scope
├── .gitignore
├── backend/
│   ├── main.py                 # Application factory, CORS, errors, health endpoints
│   ├── requirements.txt
│   ├── .env.example            # Backend storage and AWS profile configuration
│   ├── app/
│   │   ├── auth.py             # Cognito JWT verification, identity and role guards
│   │   ├── config.py           # Environment loading and repository selection
│   │   ├── dynamodb_repository.py # DynamoDB mapping, queries and transactions
│   │   ├── media_routes.py     # Authenticated metadata/upload/image/verification endpoints
│   │   ├── media_service.py    # Validation, revisions, audit metadata and replacement cleanup
│   │   ├── media_storage.py    # Private S3 adapter and SDK configuration
│   │   ├── models.py           # Customer models and input validation
│   │   ├── routes.py           # Customer HTTP endpoints
│   │   ├── service.py          # Customer IDs, consent and timestamp logic
│   │   └── repository.py       # Storage protocol and in-memory implementation
│   └── tests/
│       ├── test_customers.py
│       ├── test_age_validation.py
│       ├── test_auth.py
│       ├── auth_test_server.py # Test-only injected verifier; never deploy
│       ├── test_media.py
│       ├── test_config.py
│       ├── test_dynamodb_repository.py
│       └── fake_dynamodb.py
└── frontend/
    ├── .env.example            # Public local configuration defaults
    ├── package.json
    ├── package-lock.json
    ├── vite.config.js
    ├── index.html
    ├── src/
    │   ├── App.jsx             # Dashboard, pages and hash navigation
    │   ├── api.js              # Backend requests and API errors
    │   ├── validation.js       # Irish phone and age validation helpers
    │   ├── format.js           # Date display helpers
    │   ├── main.jsx
    │   ├── App.css
    │   ├── index.css
    │   └── components/
    │       ├── CustomerForm.jsx
    │       ├── CustomerMedia.jsx
    │       ├── ImageCapture.jsx
    │       ├── CustomerProfile.jsx
    │       ├── CustomerTable.jsx
    │       └── Notification.jsx
    └── tests/
        └── validation.test.js
```

HTTP handling, validation, business logic and storage are separate. `CustomerRepository` defines business-scoped `list/get/save` operations. `config.py` selects the adapter; routes and services contain no DynamoDB SDK calls. The service supplies the previous `updated_at` when saving an update, allowing both adapters to reject concurrent changes.

## DynamoDB architecture

Use the existing table; the application does not create tables or change their schema.

| Setting | Development configuration |
| --- | --- |
| Table | `loyalty-customer-dev` |
| Region | `eu-west-1` (Ireland) |
| Partition key (String) | `business_id` |
| Sort key (String) | `customer_id` |
| Billing | On-demand / `PAY_PER_REQUEST`, as specified in project context |

The project owner has manually verified the existing DynamoDB persistence. The application does not alter the live table; the schema-check command below remains available for setup verification.

Customer rows use their UUID as the sort key and `item_type=CUSTOMER`. Phone-lock rows use `PHONE#<normalized E.164 phone>` as the sort key, `item_type=PHONE_LOCK` and an `owner_customer_id`. Both records remain in the customer's business partition.

- **Create:** one conditional transaction claims the phone and QR locks and inserts the customer. A conflicting lock returns the existing user-friendly duplicate-phone error (409).
- **Update without a phone change:** a transaction verifies lock ownership and conditionally updates the customer.
- **Phone change:** one transaction claims the new phone, conditionally updates the customer and releases the old lock after verifying ownership. Failure rolls back every action. The old phone becomes reusable only after a successful change.
- **Concurrency:** the stored phone and expected update timestamp must match. A concurrent modification returns 409 rather than overwriting newer data. Transient transaction conflicts receive bounded retries with the same idempotency token.
- **Reads:** `GetItem` uses both keys; listing uses a strongly consistent, paginated `Query` for one business. No table scan is used for reads or phone uniqueness. Lists filter `item_type=CUSTOMER` and defensively exclude `PHONE#`, `QR#` and `VISIT#` keys; direct lookup of a phone-lock key returns no customer.
- **Serialization:** dates and UTC timestamps are ISO strings, consent is Boolean and optional empty fields are null. All existing customer fields are persisted. Storage-only fields are excluded from customer responses.
- **Failures:** AWS/credential/network errors become a generic 503 response; raw AWS messages and stack traces are not returned to the frontend. There is no automatic fallback to memory.

Updates modify only managed editable fields, consent timestamp and update timestamp. Immutable fields and unknown future metadata attributes remain intact. Future document references can use separate typed records in the same business partition (with a customer association) or additional metadata attributes. Milestone 4 uses private media attributes on existing customer items, as described below.

The adapter expects records created through this application, including their phone locks and type markers. It does not migrate old in-memory records or automatically adopt manually inserted customer rows. Treat pre-existing unmanaged rows as a separate migration task rather than bypassing lock ownership.

## Cognito authentication and authorization

Cognito authenticates business users, not loyalty customers. The frontend uses Amplify Auth with the existing public user-pool app client and `USER_SRP_AUTH` email/password flow. No Amplify deployment, identity pool, hosted-login domain or OAuth redirect URL is required by this flow. Tokens are persisted in session storage for reloads in the same tab, not localStorage or DynamoDB. Closing the tab normally ends local persistence. Browser storage is accessible to JavaScript; this is not HttpOnly cookie authentication.

Every customer operation requires an `Authorization: Bearer <ID token>` header. ID tokens are deliberately used because the standard Cognito ID token contains `custom:business_id`. The backend pins RS256, selects a key from the configured pool's cached JWKS, verifies signature, issuer, expiration, issued-at and exact app-client audience, and requires `token_use=id` plus subject. Access tokens, tokens from another client/pool and unsigned/invalid/expired tokens are rejected. This follows the [Cognito token verification guidance](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html); custom attributes are available in [Cognito ID tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html).

The verified user context contains subject, optional email, business, groups and effective role. An explicit allowlist recognizes `owner`, `manager` and `staff` after ASCII case normalization (also accepting `Owner`, `Manager` and `Staff`); precedence is **Owner > Manager > Staff**. Missing/invalid business membership or no recognized role returns 403. Authentication failure returns 401; unavailable configuration/JWKS returns 503. No tokens or passwords are logged by application code.

`GET /auth/me` returns the authenticated user's minimal context to initialize the UI. All customer routes derive storage scope from that identity. A legacy `business_id` query is allowed only if it matches the verified business; it never selects the tenant, and a mismatch returns 403. Cross-tenant customer IDs return 404. No frontend role or permission value is trusted. Owner privileges apply to one business, not across businesses.

| Role | Current customer permissions | Future authorization helpers |
| --- | --- | --- |
| Owner | Create, list/search, view, edit and change active/inactive status | `require_owner` for owner-only administration |
| Manager | Create, list/search, view, edit and change active/inactive status | `require_management` for Owner/Manager, including sensitive documents |
| Staff | Create active customers, list/search, view and edit details; cannot change status | `require_customer_access` for all three roles |

The full finalized role model remains in `PROJECT_CONTEXT.md`. Guards for future sensitive operations are available; document endpoints are now implemented; staff-management, SMS and report endpoints remain planned. Hiding UI controls is supplementary; the backend is authoritative. Staff edit auditing remains a future requirement, not an implemented audit log.

Amplify refreshes expired tokens when a refresh token is available ([session documentation](https://docs.amplify.aws/react/frontend/auth/manage-user-sessions/)). On a 401, the frontend attempts one forced refresh; another 401 or refresh failure clears the authenticated view and asks for sign-in. A 403 stays an authorization error. Logout clears the SDK's local session and unmounts customer data. A valid copied JWT remains verifiable until expiry: local signature verification does not check server-side revocation on every request. Role/business changes also take effect as new tokens are issued; use short token lifetimes and reauthentication as appropriate.

### Required manual Cognito console checks

No AWS resource has been created or modified by this implementation. Confirm these settings on the existing `loyalty-platform-users` pool and `loyalty-platform-web` client:

1. Use the existing **public app client without a secret**. Copy its app client ID into both backend and frontend environment files. The client ID was not provided with the implementation request.
2. Enable `ALLOW_USER_SRP_AUTH` and token refresh (`ALLOW_REFRESH_TOKEN_AUTH`) for this direct login flow. Do not enable refresh-token rotation for this configuration unless its integration is separately tested.
3. Keep self-registration disabled and email sign-in enabled. Create business users administratively and give each person an individual account.
4. Permit the client to **read** `custom:business_id` so it is in the ID token, but **remove it from the client's writable attributes**. This is a mandatory tenant-security setting: users must never change their own business through Cognito self-service APIs. Administrators assign it through trusted admin operations. Do not rely on a hidden React field.
5. Confirm the Owner test user has a business attribute and membership in the `owner` group (case variants such as `Owner` are also accepted). Manager/Staff users require the corresponding group. Users missing either are denied.
6. MFA is disabled in the supplied development configuration. Temporary-password `NEW_PASSWORD_REQUIRED` is supported; other MFA/recovery challenges require administrator assistance in this MVP. Configure production MFA and recovery in a later hardening task.

## Local setup

### Prerequisites

- Python 3.10 or newer, with `pip` and `venv`.
- Node.js 22.12 or newer and npm. The installed Vite version also supports Node.js 20.19 or newer within the 20.x release line.
- An IANA timezone database containing `Europe/Dublin`. If Python cannot find it on your OS, install the `tzdata` package in the virtual environment.

Run the commands below from your local project checkout. DynamoDB mode requires AWS access to the existing table and AWS CLI v2 for local SSO login. Automated tests require no AWS account or credentials. Real application requests still require Cognito even when customer storage uses memory. No Twilio configuration is needed.

### Backend

Create the environment and install dependencies on a fresh checkout:

```sh
cd backend
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

If `backend/venv` already exists with dependencies installed, simply activate it. On Windows, use `venv\Scripts\activate` instead of `source venv/bin/activate`.

Configure DynamoDB in the current backend terminal:

```sh
export CUSTOMER_REPOSITORY=dynamodb
export AWS_REGION=eu-west-1
export DYNAMODB_CUSTOMERS_TABLE=loyalty-customer-dev
export AWS_PROFILE=loyalty-dev
aws sso login --profile loyalty-dev
```

If the `loyalty-dev` SSO profile is not configured, first run `aws configure sso --profile loyalty-dev` and provide your organization's SSO details, account and role. This stores configuration outside the repository; do not paste credentials or SSO tokens into project files. The role needs permission for the application's table reads and transactional write operations.

Verify the existing table's configuration without reading customer records:

```sh
aws dynamodb describe-table --table-name loyalty-customer-dev --region eu-west-1 --profile loyalty-dev --query 'Table.{Status:TableStatus,Keys:KeySchema,Types:AttributeDefinitions,Billing:BillingModeSummary.BillingMode}'
```

Expect `ACTIVE`, String keys `business_id` (HASH) and `customer_id` (RANGE), and `PAY_PER_REQUEST`. Do not create another table.

Start FastAPI from the `backend` directory:

```sh
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Alternatively, copy `backend/.env.example` to `backend/.env` if that file does not already exist, and review the settings before starting. The backend loads this file automatically; explicit process environment takes precedence. Never commit the real `.env` file.

| Backend variable | DynamoDB development value | Behaviour |
| --- | --- | --- |
| `CUSTOMER_REPOSITORY` | `dynamodb` | Selects persistence; unset defaults to `memory` |
| `AWS_REGION` | `eu-west-1` | Region; also the application default |
| `DYNAMODB_CUSTOMERS_TABLE` | `loyalty-customer-dev` | Required when using DynamoDB |
| `AWS_PROFILE` | `loyalty-dev` | Local SSO profile; optional, no hardcoded credentials |

For future AWS-hosted workloads, omit `AWS_PROFILE` and use IAM roles through boto3's standard credential chain. Do not store access keys in the repository or frontend.

To run offline using temporary memory storage, explicitly override the mode:

```sh
CUSTOMER_REPOSITORY=memory python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Memory is a separate development/test choice, not a fallback after DynamoDB failure.

- [API documentation](http://127.0.0.1:8000/docs)
- [Health endpoint](http://127.0.0.1:8000/health)

### Frontend

In a separate terminal, install dependencies from the lockfile and start Vite:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open [the manager dashboard](http://127.0.0.1:5173). Keep both terminals running. Press `Ctrl+C` in each terminal to stop the servers.

The backend allows frontend requests from `http://localhost:5173` and `http://127.0.0.1:5173`. Using a different frontend port requires updating the backend's local CORS configuration.

### Required Cognito and frontend configuration

From `frontend`, copy the provided example:

```sh
cp .env.example .env.local
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL |
| `VITE_COGNITO_USER_POOL_ID` | No default | Existing user pool ID; region is inferred from its prefix |
| `VITE_COGNITO_APP_CLIENT_ID` | No default | Existing public web client ID, matching the backend |

In `backend/.env`, also configure:

```dotenv
COGNITO_REGION=eu-west-1
COGNITO_USER_POOL_ID=replace-with-existing-user-pool-id
COGNITO_APP_CLIENT_ID=replace-with-existing-web-client-id
```

For the supplied development pool, set both user-pool variables to `eu-west-1_aZJWr8WKp`. Obtain the actual **client ID**, not its display name, from the existing `loyalty-platform-web` client. Never configure a client secret in the SPA. Missing backend configuration fails closed; it does not disable authentication. Memory mode still requires Cognito for real application requests; only tests inject a fake verifier.

Restart Vite and FastAPI after changing environment variables. Vite variables are public and included in the frontend bundle; never put secrets or credentials in them. `.env.local` is ignored by Git.

## Customer API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/customers` | Register a customer; returns HTTP 201 |
| `GET` | `/customers` | List customers in the selected business |
| `GET` | `/customers/{customer_id}` | Retrieve one customer |
| `PUT` | `/customers/{customer_id}` | Replace editable customer fields |

All customer endpoints require a verified Cognito ID token and use its `custom:business_id`. A legacy matching `business_id` query is optional; a different value is rejected. Missing or cross-business customer IDs return 404, duplicate normalized phones return 409 and invalid input returns 422.

Required editable fields are `first_name`, `last_name`, `phone` and `date_of_birth`. Optional contact fields are `email`, `address` and `eircode`; empty values become null. `marketing_consent` defaults to false and `status` defaults to active. `PUT` is a replacement operation: omitted optional contact fields are cleared and omitted consent/status values use these defaults.

Responses also contain the server-managed `business_id`, `customer_id`, `consent_timestamp`, `qr_token`, `created_at` and `updated_at`. Clients cannot supply those fields in a create/update body. Customer IDs, QR tokens and creation timestamps remain stable during updates.

`consent_timestamp` starts as null when consent is not given, records initial opt-in, and changes when consent is granted or withdrawn. Unrelated edits preserve it. This is the latest consent transition, not a complete consent or manager audit history.

## Testing and checks

From `backend`, with dependencies installed:

```sh
source venv/bin/activate
python -m unittest discover -s tests -v
python -m compileall -q app main.py tests
```

The backend includes tests covering customer creation/retrieval/updates, consent transitions, stable server-managed fields, business scoping, normalized duplicate phones, invalid input, concurrent duplicate creation and age boundaries including leap birthdays. Authentication tests generate local RSA keys and signed JWTs to test signature, expiry, issuer, audience, token type, groups and business validation. API tests check role permissions, cross-tenant denial and unauthenticated rejection. API integration tests explicitly force memory mode and inject a test-only verifier and start a temporary Uvicorn server on an available localhost port; localhost socket access is required. DynamoDB tests use an atomic in-process fake and boto3 Stubber, with dummy test credentials only. They cover serialization, business isolation, pagination (including empty filtered pages), lock exclusion, duplicate races, atomic phone changes, rollback, concurrency, metadata preservation and sanitized errors. Configuration tests mock AWS sessions. Automated tests neither access the real AWS account nor depend on the `loyalty-dev` profile.

From `frontend`:

```sh
npm run test
npm run lint
npm run build
```

Frontend tests cover phone/age validation, Ireland's calendar date, bearer attachment, token refresh, session expiry and 403 behaviour. Lint checks JavaScript/React code; the build writes production assets to `frontend/dist`. These checks do not replace browser interaction or accessibility testing.

## Current limitations

- **DynamoDB mode persists customer records across backend restarts/reloads.** The project owner has manually verified live DynamoDB persistence.
- **Memory mode only:** records are process-local, start empty and are lost on restart/reload. Use one worker in this mode; different workers have separate records. There is no automatic migration between memory and DynamoDB.
- Authentication and role/tenant checks are implemented, but this remains a local development application. The project owner has manually verified live Cognito login and tenant isolation. Browser sessions are JavaScript-readable, backend JWT validation does not immediately revoke already issued tokens, and production HTTPS, MFA, rate limiting and audit hardening remain outstanding.
- Customer data is not saved to browser storage. The customer directory does not display internal IDs or QR tokens, although the API returns them.
- SMS consent is recorded, but no messages are sent. QR lookup, confirmed visits and loyalty progress are implemented; voucher issuance/redemption and full historical audit logs remain planned.

## First real DynamoDB persistence test

After configuring backend DynamoDB and Cognito variables, logging in with AWS SSO, and starting both servers, sign in through Cognito first:

1. Open the dashboard and register a fictional adult customer with a test Irish mobile number. Use a number not already present in the selected development business. Do not commit any real customer information, request dumps or AWS output containing customer records.
2. Confirm the success notification, read-only profile and customer directory show the saved record.
3. Stop the backend with `Ctrl+C`, then restart with the same DynamoDB configuration. Reload the frontend and reopen the customer. The record, ID, QR token, timestamps and consent state should remain.
4. Try registering the same normalized phone in the alternate national/`+353` format. Expect a duplicate error and preserved form values.
5. Edit the customer's phone to a different unused test number. Confirm the updated profile and persistence after another backend restart. Register another fictional customer with the old phone: it should now be available. The new phone must remain protected from duplicates.
6. Confirm the directory contains only customers, never `PHONE#` rows. In API docs, test a `PHONE#` customer lookup: expect 404. Use a separately provisioned test user belonging to another business to confirm scoped lists/lookups; the same phone may belong to different businesses. Changing a query parameter cannot switch businesses.

The health endpoint checks application availability, not AWS connectivity. Customer API operations exercise storage. A 503 indicates a storage/configuration problem; check SSO expiry, table name/region and permissions rather than switching silently to memory.

The project owner has verified DynamoDB persistence manually. Automated tests still do not use the real AWS account. No new table or production deployment is part of Milestone 2.

## Manual Cognito Owner acceptance test

1. Configure the existing pool/client as above; fill both local environment files with the same public identifiers. Login to AWS SSO for the backend's DynamoDB access (this is separate from Cognito business-user login).
2. Start both servers using the commands above. Open the frontend; unauthenticated access should show the login page with no customer data and no sign-up option.
3. Enter the administratively created Owner test user's email/password. If Cognito requires a new permanent password, complete that screen. Do not paste passwords or tokens into commits, screenshots or chat logs.
4. Confirm the business workspace and Owner role appear, and existing DynamoDB customers load. Register/edit a fictional adult customer and confirm the existing validation and success/profile navigation.
5. Reload the page in the same tab: the session should restore. Sign out: customer pages should unmount and sign-in should reappear. Backend calls without a bearer token must return 401.
6. Repeat with test Manager and Staff users. All may manage customer details; Staff cannot change active/inactive status or gain Owner/Manager-only guard access.
7. For tenant isolation, use a separately provisioned user in another business. Check that lists stay scoped and a customer ID belonging to the first business returns 404. Requests with a mismatched `business_id` query return 403. Missing business/group membership must return 403.
8. Test expiry with short development token lifetimes or refresh expiration: valid refresh should renew the session; failed refresh should return to sign-in. Never expose a token in a URL.

Live Cognito acceptance has not been performed by the automated tests; no real user credentials were supplied or used.

## Planned development roadmap

Milestone 2 persistence has been manually verified by the project owner. Milestone 3 Cognito integration and current customer authorization are manually verified. Milestone 4 profile-photo storage/retrieval is manually verified. Milestone 5A QR lookup and visit tracking is implemented; live acceptance is pending. The following later milestones are **not implemented**, following `PROJECT_CONTEXT.md`:

- **Milestone 5B:** €10 voucher generation after five visits and single-use redemption.
- **Milestone 7:** Twilio messaging, consent-aware campaigns and scheduled birthday promotions.
- **Milestone 8:** audit/security/privacy hardening and production deployment, including future Lambda/API Gateway and hosting infrastructure.

Exact boundaries may evolve. No vouchers, Twilio, birthday automation or Lambda deployment is included in the current implementation.

### Retrying a temporary-password sign-in

The login form keeps `NEW_PASSWORD_REQUIRED` in the authentication provider
and uses Amplify v6 `confirmSignIn` within the original transaction. Password
policy failures allow retrying the permanent password; cancellation or an
expired transaction returns to the email/password form. Internal SDK error
text is not shown to users. No AWS configuration change is required.

After frontend authentication changes, stop Vite and run `npm run dev -- --force`
from `frontend`, then reload the login page once **before** signing in. Enter
the provisioned email and temporary password, submit the permanent password
without reloading the page, and verify the dashboard loads. Then sign out and
verify login with the permanent password. Cognito challenge expiry still applies.
Automated challenge tests use synthetic HTTP responses with the installed SDK;
they do not contact AWS. Real first-login acceptance was completed by the project owner; automated tests use only synthetic responses.

### Diagnosing local Cognito membership failures

`/auth/me` verifies Cognito ID tokens. Invalid signature, issuer, audience,
expiry or token type returns 401. A verified ID token without a valid
`custom:business_id` or recognized `cognito:groups` membership returns 403.
ASCII case-normalized group names `owner`, `manager`, and `staff` map to
application roles `OWNER`, `MANAGER`, and `STAFF`, with Owner taking precedence.
Title-case and uppercase variants are accepted. Whitespace, partial names,
non-ASCII lookalikes and other role names are not authorization aliases.

To diagnose locally, stop the backend and run from `backend`:

```bash
APP_ENV=development AUTH_DIAGNOSTICS=true venv/bin/python -m uvicorn main:app --reload
```

Then perform a fresh browser login. The backend logs an `Auth membership:` line
only after JWT verification. It includes a fixed reason code, business/group
claim presence and validity flags, and recognized role. It never includes the
JWT, signatures, password, subject, email, business value or group values.
Diagnostics require both explicit development mode and the opt-in flag; they
are disabled otherwise. Collect only this sanitized line and the `/auth/me`
HTTP status when reporting problems. Do not share authorization headers,
network exports, token storage, or complete token payloads. Restart without
`AUTH_DIAGNOSTICS=true` after troubleshooting.


## Milestone 4: private customer media

FastAPI controls uploads and proxies image bytes after Cognito authentication,
role authorization and a business-scoped customer lookup. No S3 keys, presigned
URLs, AWS credentials, document contents or audit subject IDs are returned in
ordinary customer/list responses. No bucket, policy, CORS, table or Cognito
configuration is changed by the application. Backend proxying requires no S3
browser CORS configuration.

| Category | Owner | Manager | Staff |
| --- | --- | --- | --- |
| Profile photo | View/upload/replace | View/upload/replace | View/upload/replace |
| ID document | View/upload/replace; verify/reject | View/upload/replace; verify/reject | No metadata, image or upload access |
| Signed consent evidence | View/upload/replace | View/upload/replace | No metadata, image or upload access |

Permissions are enforced on each backend operation, including direct image
requests. Staff controls are hidden as an additional UI measure. Tenant scope
comes exclusively from verified `custom:business_id`; a conflicting legacy
business query is denied. A cross-business or missing customer returns 404.
The browser's customer ID is only a lookup identifier, never authorization.

### Storage and replacement

Existing development bucket: **contactly-private-documents-dev**, **eu-west-1**.
Keep Block Public Access enabled, ACLs disabled and SSE-S3 enabled. Each put
explicitly requests `AES256` encryption and never sets an ACL. Conditional
creation prevents overwriting an existing object. Versioning is **disabled in
development to minimize cost**; deleting a replaced image is irreversible.

Keys follow `businesses/<business_id>/customers/<customer_id>/<category>/<random-uuid-hex>.<extension>`,
where category is `profile`, `identity` or `consent`. Names, phones, emails,
birth dates and document numbers are never included. The backend chooses the
key and refuses references outside the expected tenant/customer/category prefix.

DynamoDB stores private `media_profile`, `media_identity`, and `media_consent`
map attributes on the existing `CUSTOMER` item. No new table/item types or
schema migration are needed. Records without media attributes continue working.
Customer models exclude these attributes, and ordinary customer/phone updates
preserve them. The in-memory adapter implements the same interface for tests.
Use DynamoDB for real S3 tests: memory references are lost on restart and would
leave objects without metadata.

Metadata contains key, opaque revision, MIME type, encoded size, uploaded_at,
uploaded_by (Cognito subject), plus category fields. Dedicated authorized
metadata responses omit keys, cleanup references and user subject IDs.
ID metadata records document_type, verification_status, verified_at and
verified_by. Supported types are Passport, Driving Licence, National ID,
Residence Permit and Other. Every new/replaced ID starts **Pending**; Owner or
Manager may mark it **Verified** or **Rejected**. Verification requires the
current revision to prevent approving a concurrently replaced image.
Consent evidence records `signed_marketing_consent` and a snapshot of the
related consent timestamp; it never changes `marketing_consent` or replaces
structured consent. Subsequent consent changes do not rewrite the evidence
snapshot or erase the image; retention decisions remain a business policy.

Replacement stores a new object, conditionally updates the category's revision,
then deletes previous objects. A conflicting metadata write discards the new
object. A timed-out metadata write is read back before deletion so an image
referenced by a successful write is not deleted. Failed old-object cleanup is
retained privately as `cleanup_keys`, reported as `cleanup_pending`, and retried
on the next replacement. Generic logs contain no keys or identities. S3 and
DynamoDB cannot form one transaction: crashes, uncertain writes or cleanup
failures can still leave private orphans; operator reconciliation and a
production cleanup process are required. No background janitor is implemented.

### Validation and private viewing

Uploads use a **raw image body**, with matching Content-Type (`image/jpeg`,
`image/png`, `image/webp`), maximum **5 MiB (5,242,880 bytes)**, and at most
**20 million pixels**. No multipart parser or filename is required. FastAPI
bounds streamed input; Pillow verifies and fully decodes the actual format,
rejects corrupt/animated images and pixel bombs, corrects EXIF orientation,
and re-encodes fresh pixels without embedded EXIF/GPS/text/ICC metadata.
Re-encoded output must also fit the size limit. Filenames/extensions from the
browser are not used. Invalid content returns 422, unsupported MIME 415, size
violations 413, revision conflicts 409 and unavailable storage 503.

For each category (`profile-photo`, `id-document`, `consent-evidence`):

| Method | Path | Behaviour |
| --- | --- | --- |
| POST | `/customers/{id}/{category}` | Upload/replace; ID additionally requires `?document_type=Passport` (or another supported type) |
| GET | `/customers/{id}/{category}` | Safe authorized metadata; 404 if no image |
| GET | `/customers/{id}/{category}/image` | Authenticated image bytes; optional `revision` prevents stale viewing |
| PATCH | `/customers/{id}/id-document/verification` | JSON `{ "revision": "<current revision>", "status": "Verified" }` or Rejected |

Image/metadata responses use `Cache-Control: no-store`; images also use
`nosniff` and no-referrer. React fetches image bytes with the existing Bearer
transport, creates temporary local blob URLs and revokes them when hidden,
replaced or unmounted. No persistent document images are saved to browser
storage. Profile photos load automatically beside the customer’s name using the
authenticated image endpoint, with initials for missing photos and a retry
control for retrieval failures. Successful profile-photo replacement refreshes
the displayed avatar. Protected ID and consent images still require clicking
“View current image”. Customer-list/dashboard thumbnails retain initials: the
list API has no photo-presence flag or thumbnail endpoint, so fetching full
images per row would add avoidable requests and bandwidth. Authorized users can
still save or photograph what they view; browser controls cannot prevent this.

### Local configuration and acceptance test

Add to **backend/.env**, retaining your working Cognito/DynamoDB configuration:

```dotenv
S3_DOCUMENTS_BUCKET=contactly-private-documents-dev
S3_REGION=eu-west-1
AWS_PROFILE=loyalty-dev
```

Omit AWS_PROFILE in production; use IAM roles via the normal boto3 credential
chain. No frontend AWS variables are needed. Missing bucket configuration
leaves customer CRUD working and media operations unavailable (503).

From the project root, run in the backend terminal:

```bash
cd backend
source venv/bin/activate
python -m pip install -r requirements.txt
aws sso login --profile loyalty-dev
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

In the frontend terminal:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

1. Sign in as Owner. Open a fictional customer's profile. Select a test PNG,
   JPEG or WebP, review the preview, upload and click View current image.
2. Use the camera: allow permission, capture, retake, then upload. Confirm the
   camera stops on capture/cancel/navigation. Deny camera permission and verify
   file selection remains available. Camera requires localhost or HTTPS plus a
   supported browser; it is not available on ordinary remote HTTP.
3. Upload a fictional ID with a document type. Confirm Pending, mark Verified,
   then Rejected. Replace the image and confirm Pending with cleared verification.
4. Upload fictional signed consent evidence. Confirm existing consent is unchanged.
   Reload and restart the backend with DynamoDB selected; images should persist.
5. Repeat as Manager. As Staff, confirm only profile-photo controls appear and
   work. With Staff authorization in local API docs, protected metadata/image/
   upload/verification endpoints must return 403. Never share copied tokens.
6. With a separately provisioned other-business user, direct requests for the
   first customer's media must return 404 (or 403 for a conflicting business
   query). Requests without authentication must return 401.
7. Try a PDF/SVG, corrupted image and file over 5 MiB: reject without replacing
   the current image. Using console object listings (no content in screenshots),
   confirm replacement leaves the new object and deletes the old object after
   success. A cleanup warning requires investigation rather than declaring the
   old object deleted.

Automated media tests use FakeS3, the in-process DynamoDB fake and boto3 Stubber,
never real AWS. Frontend tests cover role categories, file validation, camera
permission/unmount cleanup and authenticated binary transport. Live S3/browser
acceptance remains a manual check.

No AWS console change was made. The existing local SSO role must have
`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on this bucket's `businesses/*`
objects, plus DynamoDB `GetItem`/`UpdateItem` and existing query/transaction
permissions. Verify these permissions only if AWS reports access denied;
any IAM change must be performed deliberately outside this application.
Keep the existing private bucket settings. A shared backend IAM identity spans
tenants; application authorization provides tenant isolation in this MVP.

Production work still required: HTTPS, request/concurrency/rate limits, malware
scanning policy, retention/deletion policy, orphan reconciliation, full audit
logs, operational monitoring, stronger token/session revocation controls and
privacy/GDPR review. Evaluate a production KMS encryption strategy later. There
is **no facial recognition, biometric matching, OCR or automated identity
verification**. Use fictional documents only; do not upload real customer ID
images during development. No permanent customer/document deletion workflow or
later milestone is implemented.


## Milestone 5A: QR lookup and confirmed visits

Owner, Manager and Staff can open **Loyalty visits**, scan/type an opaque QR token
as keyboard input, look up the active customer, and explicitly **Confirm visit**.
Lookup never records a visit. The profile photo uses the existing authenticated
binary transport; ID and consent images are not automatically displayed.
Customer profiles also display progress and retained visit history.

Authenticated endpoints (business comes exclusively from verified Cognito):

- `POST /loyalty/lookup` with `{"qr_token":"<opaque token>"}`.
- `POST /customers/{customer_id}/visits` with `{}`; server assigns UUID, UTC time
  and `recorded_by` from the authenticated Cognito `sub`.
- `GET /customers/{customer_id}/visits` returns customer, history and progress.

QR locks use `customer_id=QR#<token>`, `item_type=QR_LOCK` and `owner_customer_id`.
Immutable visit rows use `VISIT#<customer UUID>#<visit UUID>`, `item_type=VISIT`,
and `owner_customer_id`. The composite opaque prefix enables paginated,
customer-specific history Queries without a Scan or new GSI. Internal records
never appear as customers. New registrations atomically claim both indexes;
existing QR tokens are never rotated by migration.

One valid loyalty visit is allowed per customer per calendar date in the
server-owned business timezone, currently `Europe/Dublin`. Python zoneinfo
handles DST; this is not a rolling 24-hour restriction. New visit rows store
UTC `visited_at`, `local_visit_date` and `business_timezone`.

Before confirmation the repository reads the lifetime counter, then uses a
strongly consistent paginated Query of that customer's retained history to
check the Dublin date. The transaction checks active status and the expected
counter, updates only the lifetime count, and inserts the immutable visit.
If another request commits first, the counter condition fails and the repository
re-reads history. Thus simultaneous requests cannot accept the same local date.
This queries one customer's history, never a table Scan; read cost grows with
that customer's history and a future date index could improve scale.

Same-date confirmation returns 409 with
`A loyalty visit has already been recorded for this customer today.`
The frontend displays this message without success feedback. Rejection changes
neither the count nor history. Customer edits preserve loyalty/media metadata.
There is no cooldown setting. The date rule will also inform future Daily Raffle
eligibility, but no raffle entry or voucher is created here.

Threshold is five: `progress=total_visits % 5`, `visits_until_reward=5-progress`,
`reward_earned=total_visits > 0 and progress == 0`. Visit five returns 5/0/5/true;
visit six returns 6/1/4/false. History is never deleted. The UI shows **€10 reward
earned** at a completed cycle, but no voucher is created or issued in 5A.
History and counter are separate strongly consistent reads, so a concurrent
confirmation can briefly make their snapshots differ; refresh retrieves current data.
Memory mode supports the same workflow but loses customer/index/visit data on restart.

### Explicit QR-lock backfill for existing customers

No table/index/resource creation or automatic startup migration occurs. Run this
once per existing business using the normal backend environment and AWS SSO
profile. The script defaults to a read-only dry run, validates all candidates
before writing, and uses guarded transactions to preserve tokens and reject
conflicting ownership. It prints counts rather than customer data or QR tokens.
Use the existing table configuration below; commands run from `backend/`:

```bash
source venv/bin/activate
aws sso login --profile loyalty-dev
export CUSTOMER_REPOSITORY=dynamodb
export AWS_PROFILE=loyalty-dev
export AWS_REGION=eu-west-1
export DYNAMODB_CUSTOMERS_TABLE=loyalty-customer-dev
python scripts/backfill_qr_locks.py --business trumps
# Review counts; this next command deliberately writes QR_LOCK records.
python scripts/backfill_qr_locks.py --business trumps --apply
python scripts/backfill_qr_locks.py --business trumps
```

The final dry run should report zero missing locks. Rerunning is idempotent.
If interrupted or a concurrent change fails a guard, completed locks remain;
resolve the reported conflict and rerun. Do not edit or rotate existing tokens.
No migration of phone locks or media is performed. The IAM identity needs the
existing table's GetItem, Query and transactional write permissions; the script
never changes IAM or table settings.

Restart the backend/frontend, log in, and use a fictional active customer's
existing token in **Loyalty visits**. Confirm lookup leaves the count unchanged,
confirmation adds exactly one visit, an immediate retry is rejected, and visit
five displays the reward with all five history records retained. Wait until the next Dublin calendar date between valid confirmations. Verify an inactive
customer and a different-business user cannot record/access that customer's visits.
Automated loyalty tests use fakes/stubs and require no real AWS account.


### Existing visits and daily-rule acceptance

No visit backfill is required. Existing visit timestamps are converted to Dublin
calendar dates on read, including rows without the new local-date fields. An
existing visit today immediately prevents another visit today after the new
backend starts. Stored history and lifetime counts are preserved; historical
multiple visits permitted by the former rule are not deleted or reclassified.
Any obsolete timestamp metadata on customer rows is inert and can remain.
Remove the obsolete visit cooldown environment entry from your local `.env`.
Stop all old backend processes before restarting so they cannot accept visits
under the previous rule. No DynamoDB schema/IAM/resource changes are needed.

For live acceptance with the existing development customer:

1. Start the backend with the existing DynamoDB/Cognito/S3 environment and
   `aws sso login --profile loyalty-dev`; run `uvicorn main:app --reload` from
   `backend/` with its venv active. Run `npm run dev` from `frontend/`.
2. Log in, open the customer's profile and note count/history, then open
   **Loyalty visits** and scan/type the existing QR token. Lookup must leave
   count/history unchanged.
3. If today's Dublin visit already exists, **Confirm visit** must return the
   friendly duplicate message; reload the profile and verify unchanged values.
   Two tabs confirming concurrently must both reject if today's visit exists.
4. After the next Dublin midnight, look up and confirm once: count increases by
   one. An immediate retry must reject. On a date with no previous visit, two
   tabs confirming concurrently must produce exactly one successful visit.
5. Check UTC timestamp plus local date/timezone in the authenticated visit API
   response using the browser Network panel. Do not copy or expose tokens.
   A 23:55 visit followed by 00:05 on the next local date is allowed; automated
   tests cover that boundary and both DST transitions without changing clocks.
6. Across five distinct valid dates, progress reaches 0/5 with reward earned;
   the sixth reaches 1/5. All history remains and no voucher is issued.
