# Loyalty Platform

A local MVP for a future multi-business customer loyalty and SMS marketing platform. The project is designed to give managers a customer directory and, tools for recording visits and, in later milestones, issuing rewards and communicating with customers who have opted into marketing.

**Current status: Milestones 1–3 completed and manually verified against AWS by the project owner; Milestone 4 profile-photo storage/retrieval manually verified; Milestone 5A complete; Milestone 5B voucher engine implemented; Milestone 5B.1 QR management implemented; Milestone 5C Daily Raffle implemented; Milestone 5D.1 durable print queue and ticket generation implemented, awaiting live acceptance; Milestone 5D.2A Windows development agent implemented, awaiting production device provisioning and onsite printer acceptance; Milestone 5D.3 secure authentication/connectivity integration implemented with provisioning pending.** The application runs locally with a React manager dashboard and a FastAPI customer API. Customer persistence is configurable between DynamoDB and an optional in-memory repository. Cognito business-user login and server-side role/tenant authorization are implemented. Private customer images, camera capture and ID verification are implemented. QR lookup, explicit visit confirmation and loyalty progress are implemented. Automatic €10 loyalty/€20 birthday vouchers, redemption and atomic Daily Raffle entries are implemented; SMS sending remains planned. DynamoDB persistence was manually verified by the project owner.

## Implemented features

- Responsive dashboard, sidebar and customer-management pages for desktop, tablet and mobile.
- Dashboard counts from actual local records: total customers, marketing opted-in and birthdays this month. Birthday month uses the manager's browser date; there are no invented business analytics.
- Customer directory with name/phone search, date of birth, promotional SMS consent, status and profile actions.
- Customer registration, read-only profiles and a separate edit page.
- Irish mobile input with a visible Ireland `+353` indicator. National and international formats are normalized to E.164 by the backend before storage and per-business duplicate checks. Incomplete or malformed numbers are rejected. Validation checks format, not phone ownership or service availability.
- Minimum age of 18 enforced in frontend and backend using the full birth date and the current date in `Europe/Dublin`. Invalid and future dates are rejected. February 29 birthdays reach the age threshold on March 1 in non-leap years.
- Explicit promotional/marketing SMS consent, with a UTC timestamp for the most recent consent transition.
- Secure UUID4 customer IDs and separate random, opaque `qr_token` values containing no personal data. Keyboard scanner lookup and confirmed visit tracking are implemented; QR rendering, customer-facing links and protected regeneration are implemented; digital print queuing/ticket generation is implemented; Windows development printing adapter is implemented; production printing and onsite acceptance remain pending.
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
| Backend  | Python, FastAPI, Pydantic 2, Uvicorn, PyJWT with cryptography, Pillow, qrcode |
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
│   │   ├── voucher_rules.py    # Calendar reward policy and secure codes
│   │   ├── voucher_repository.py # Reward/code locks and conditional redemption
│   │   ├── voucher_service.py  # Effective expiry, listing and code lookup
│   │   ├── voucher_routes.py   # Authenticated voucher endpoints
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
- SMS consent is recorded, but no messages are sent. QR lookup, confirmed visits and loyalty progress are implemented; automatic vouchers and redemption are implemented; full historical audit logs remain planned.

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

Milestone 2 persistence has been manually verified by the project owner. Milestone 3 Cognito integration and current customer authorization are manually verified. Milestone 4 profile-photo storage/retrieval is manually verified. Milestone 5A QR lookup and visit tracking is complete. Milestone 5B automatic vouchers, Milestone 5B.1 customer QR management and Milestone 5C Daily Raffle entries are implemented; live acceptance of the new raffle workflow is pending. The following later milestones are **not implemented**, following `PROJECT_CONTEXT.md`:

- **Milestone 5D.2:** Windows Print Agent, printer transport and physical Epson printing.
- **Milestone 7:** Twilio messaging, consent-aware campaigns and scheduled birthday promotions.
- **Milestone 8:** audit/security/privacy hardening and production deployment, including future Lambda/API Gateway and hosting infrastructure.

Exact boundaries may evolve. No raffle winner selection, physical printing, Twilio, scheduled birthday SMS automation or Lambda deployment is included in the current implementation.

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
counter/customer update timestamp, updates only the lifetime count, and inserts
the immutable visit plus any qualifying 5B vouchers and locks.
If another request commits first, the counter condition fails and the repository
re-reads history. Thus simultaneous requests cannot accept the same local date.
This queries one customer's history, never a table Scan; read cost grows with
that customer's history and a future date index could improve scale.

Same-date confirmation returns 409 with
`A loyalty visit has already been recorded for this customer today.`
The frontend displays this message without success feedback. Rejection changes
neither the count nor history. Customer edits preserve loyalty/media metadata.
There is no cooldown setting. Milestone 5C now creates one Daily Raffle entry with every new valid visit using this same date rule. Milestone 5B now issues qualifying vouchers in the same visit transaction.

Threshold is five: `progress=total_visits % 5`, `visits_until_reward=5-progress`,
`reward_earned=total_visits > 0 and progress == 0`. Visit five returns 5/0/5/true;
visit six returns 6/1/4/false. History is never deleted. Milestone 5B now shows **€10 Loyalty Voucher earned** at a completed cycle and issues a real voucher.
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
five displays the issued loyalty voucher with all five history records retained. Wait until the next Dublin calendar date between valid confirmations. Verify an inactive
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
   the sixth reaches 1/5. All history remains; a loyalty voucher is now issued by 5B at each new fifth visit.


## Milestone 5B: Voucher and reward engine

Every new fifth valid visit (5, 10, 15, …) automatically issues exactly one
**€10 Loyalty Voucher**, using integer `value_cents=1000`. It is usable only on
its issue date in **Europe/Dublin**, expiring at the next local midnight.
A 23:50 issue expires ten minutes later, not after 24 hours.

A valid visit during the Monday–Sunday week containing the customer's birthday
issues a separate **€20 Birthday Voucher** (`value_cents=2000`), at most once
per customer per birthday year. Adjacent birthday years are checked to handle
weeks spanning December/January. February 29 birthdays use **March 1 in non-leap
years**. Birthday validity ends at the following Monday's Dublin midnight.
No birthday voucher is issued outside the birthday week or without a valid confirmed
visit. Both vouchers may be issued together; they remain separate records.

Vouchers retain business/customer UUIDs, type, value, random code, issue UTC
time and local date, timezone, issuer Cognito subject, qualifying visit UUID,
birthday year or loyalty milestone, UTC expiry, status and redemption identity/time.
Statuses are `ACTIVE`, `REDEEMED`, `EXPIRED`. Reads compute effective expiry
without a scheduled task or database write. A stored ACTIVE row past its
boundary is returned EXPIRED and cannot be redeemed. REDEEMED stays REDEEMED
for history. DST produces correctly shorter/longer days and weeks.

Owner, Manager and Staff may list, look up and redeem vouchers within their
verified business. The UI's **Vouchers** navigation opens a code lookup and
explicit redemption form; profiles list code, type, value, effective status,
issue/expiry and redemption dates. Display times use Dublin. Client rendering
also disables vouchers at their expiry boundary; backend enforcement is authoritative.
No internal DynamoDB lock keys are exposed. No arbitrary issuance endpoint exists.

Authenticated endpoints:

- `GET /customers/{customer_id}/vouchers`
- `POST /vouchers/lookup` with `{"voucher_code":"ABCDE-FGHJK-LMNPQ-RSTUV"}`
  (fictional formatting example; lowercase and ungrouped input are accepted)
- `POST /customers/{customer_id}/vouchers/{voucher_id}/redeem` with `{}`
- Valid visit responses additionally contain `vouchers`, containing only newly
  issued vouchers. QR lookup and rejected daily visits issue nothing.

### DynamoDB records and atomicity

All records retain `business_id` as the partition key in the existing table.

| Sort key `customer_id` | Type | Purpose |
| --- | --- | --- |
| `VOUCHER#<customer UUID>#<voucher UUID>` | `VOUCHER` | Permanent customer voucher history, efficiently queried by prefix |
| `REWARD#<customer UUID>#LOYALTY_10#<cycle number>` | `REWARD_LOCK` | At most one loyalty voucher per five-visit milestone |
| `REWARD#<customer UUID>#BIRTHDAY_20#<birthday year>` | `REWARD_LOCK` | At most one birthday voucher per year |
| `VCODE#<code>` | `VOUCHER_CODE` | Unique code-to-voucher lookup within the business |

Visit registration reads the persisted customer/counter and strongly consistent
history, evaluates reward policy, and commits a **single DynamoDB transaction**:
conditional customer counter update, visit insert, plus voucher/reward-lock/code-lock
inserts (5D.1 now adds raffle/date rows and print jobs, maximum thirteen actions for two rewards). All inserts require absence.
The customer update checks active status, expected lifetime count and expected
`updated_at`, so concurrent DOB edits cause policy re-evaluation. Reward locks
remain after redemption/expiry. Customer responses exclude every internal type.
Existing phone, QR, visit and private media attributes remain intact.

Codes contain 20 cryptographically random symbols from a 32-character alphabet
(100 bits), grouped in four blocks of five; no names, phones or DOBs. Code-lock
collisions roll back the entire transaction and retry with new codes, bounded
to three application attempts. Milestone/year locks prevent repeat issuance.
All SDK retries for an unchanged transaction share its client request token.

Redemption transactionally updates only an ACTIVE VOUCHER with a numeric expiry
boundary greater than the trusted request timestamp. It sets REDEEMED and the
server UTC timestamp/Cognito subject. Two requests can read ACTIVE, but only
one conditional update succeeds. The second returns a friendly 409. Reads are
scoped; cross-business code lookup/redemption returns no voucher. Expired and
already redeemed vouchers return 409. Authentication remains unchanged.

**Failure/retry:** a rejected transaction commits none of its visit/reward writes.
If a response is lost after AWS committed, the visit and rewards already exist
together. A retry hits the daily-visit guard; refresh customer history/vouchers
to inspect the committed result. Redemption with a lost response likewise
requires a status refresh; retry cannot redeem twice. There is no background
recovery queue because visit/reward persistence is one atomic transaction.
SDK/network failures remain sanitized; no raw AWS data is returned.

### Upgrade and live acceptance

No schema, GSI, AWS resource change, new environment variable or voucher backfill
is required. Existing 5A history/counts are preserved. **Past 5A milestones do
not retroactively receive vouchers**, and a duplicate of a prior visit cannot
issue one. Issuance starts with new valid visits; an existing count of five
reaches its next loyalty voucher at ten. Historical remediation, if wanted,
requires a separately authorized migration with its own expiry policy. Existing
QR locks remain required; the earlier explicit QR backfill applies only if still missing.

Stop every old backend process before restarting so older code cannot record
rewardless qualifying visits. With the existing backend `.env` unchanged:

```bash
cd /Users/jeffersonarcanjo/Desktop/Trumps/loyalty-platform/backend
source venv/bin/activate
aws sso login --profile loyalty-dev
uvicorn main:app --reload
```

In a second terminal:

```bash
cd /Users/jeffersonarcanjo/Desktop/Trumps/loyalty-platform/frontend
npm run dev
```

1. Log in with the existing Owner/Manager/Staff Cognito account. Open the
   existing fictional DynamoDB customer; note total visits, DOB and voucher list.
2. Use **Loyalty visits** with its unchanged token. Lookup alone must not create
   a visit/voucher. An already-recorded visit on today's Dublin date must reject
   without changing count/history/vouchers.
3. On each distinct available Dublin date confirm once. The next count divisible
   by five issues one €10 voucher, shows **€10 Loyalty Voucher earned**, and
   returns progress 0/5. Open the profile; refresh and verify one voucher and
   unchanged permanent visit history. Do not edit counters or system clocks.
4. For birthday acceptance, use only fictional data: before a new eligible visit,
   choose an adult DOB whose month/day lies in that visit's Dublin week. If the
   visit is also a fifth milestone, expect both reward messages and two records.
   Subsequent valid visits in that birthday week must not issue another birthday
   voucher. Once-per-year protection remains even if that voucher is redeemed.
5. Copy a displayed fictional voucher code into **Vouchers**, look it up, and
   redeem explicitly. Verify REDEEMED and redemption time. Retry (or use two tabs)
   and verify no second redemption succeeds. Authenticated API responses record
   the Cognito `sub`; never paste or expose JWTs to inspect this.
6. Leave another loyalty voucher unredeemed until the next Dublin midnight;
   refresh/lookup must show EXPIRED and reject redemption. Birthday vouchers
   expire on the following Monday. Use automated clock-controlled tests for
   midnight/DST/annual scenarios without altering the live clock.
7. Repeat access checks with the existing separate-business account: it cannot
   list/look up/redeem these vouchers. Check photos/ID/consent role permissions
   and QR lookup remain unchanged.

Automated tests use memory, an atomic paginated DynamoDB fake, local JWT keys
and SDK stubs; no real AWS account is needed. Real voucher acceptance has not
been run automatically. Known limitations: policy timezone is currently Dublin
for all configured businesses; per-business programme settings remain future
work. Customer history Queries grow with retained history; no global reporting
index, cancellation/refund workflow or full administrative audit log is added.
Effective EXPIRED is computed rather than persisted. Expiry is evaluated against
the server request timestamp; keep server clocks synchronized. Transactions
received just before midnight are judged at that trusted timestamp.

**Production Windows/Epson printing remains blocked pending device provisioning and onsite acceptance.**
5D.2A adds the isolated development agent below. No browser printing, raffle draw,
Twilio message, scheduled birthday automation or AWS deployment is added.


### Development-only four-visit acceptance seed

`scripts/seed_acceptance_visits.py` is standalone development/acceptance tooling,
never an application endpoint. Select an active **fictional** customer created
through the normal UI with zero visits and no vouchers/reward locks. It previews
four VISIT records at Dublin noon on the four dates before today and one
counter change from zero to four. Dry runs never write; `--apply` is required.
`--verify` is a separate read-only check after seeding and before normal visit #5.
The script uses the existing DynamoDB environment/profile, without table/account
constants or AWS resource changes. Run from `backend/` with the venv active:

```bash
python scripts/seed_acceptance_visits.py --business trumps --customer-id CUSTOMER_UUID
python scripts/seed_acceptance_visits.py --business trumps --customer-id CUSTOMER_UUID --apply
python scripts/seed_acceptance_visits.py --business trumps --customer-id CUSTOMER_UUID --verify
```

Replace CUSTOMER_UUID with the fictional customer's UUID. UUIDs in previews are
new random candidates each invocation. APPLY prints the records actually written.
All five writes commit together, guarded by active status, zero lifetime counter,
unchanged customer revision and absent visit keys. Concurrent normal writers
increment the counter and invalidate this transaction. No DynamoDB range lock
exists; do not concurrently modify records manually or run unrelated migrations.
No vouchers, reward locks or code locks are created, including birthday rewards.
Existing QR/phone/media attributes remain intact. Synthetic visits retain UTC
and Dublin dates, sequence 1–4, `acceptance_test_data=true` and
`recorded_by=development:milestone-5b-acceptance-seed`, deliberately not a claimed
Cognito identity. Reruns refuse existing history. The resulting progress is 4/5,
one visit until reward; record the fifth through the normal authenticated UI/API.
This tool must never be used with real customer data or production tables.


## Milestone 5B.1: Customer QR management

Authenticated Owner, Manager and Staff can search their existing business-scoped
customer directory by first/last/full name and equivalent Irish national or
`+353` mobile numbers. The profile's **Loyalty QR** renders the existing opaque
token as a locally generated PNG. No third-party QR service receives identifiers.
`qrcode==8.2` reuses Pillow; no npm dependency was added.

**Copy QR Link** recovers the stable `/q/<opaque-reference>` link. The public
mobile page displays generic Contactly branding, instructions and the QR only,
without login or customer information. **Send QR Link** explicitly reports SMS
is not configured (501); it never claims delivery. Owner/Manager regeneration
requires confirmation; Staff is denied by the backend. Regeneration atomically
replaces the customer token, QR lock and public pointer, invalidating both old
credentials while preserving customer information, media, visits and vouchers.
Concurrent stale requests return 409 rather than overwriting newer credentials.
Scanning still only identifies the customer; recording a visit requires confirmation.

| Endpoint | Access / purpose |
| --- | --- |
| `POST /customers/{id}/qr/link` with `{}` | All business roles; initialize/recover stable link reference |
| `GET /customers/{id}/qr/image` | All business roles; authenticated PNG |
| `POST /customers/{id}/qr/regenerate` | Owner/Manager; `confirmed: true` and current `expected_qr_token` |
| `POST /customers/{id}/qr/send` with `{}` | Authenticated placeholder; SMS not configured |
| `GET /public/qr/{reference}/image` | Minimal public PNG; current active customer only |

The private CUSTOMER attribute `public_qr_ref` is initialized lazily, without
rotating existing tokens. A same-table routing directory uses reserved partition
`!PUBLIC_QR`, sort key `PUBLIC#<reference>` and type `PUBLIC_QR`, mapping internally
to the business/customer. This reserved partition cannot be an authenticated
business ID. Customer resources and QR locks remain tenant-scoped. Strong point
reads and conditional transactions need no Scan, GSI or new AWS resources.
Public references and replacement tokens each have 256 bits of cryptographic
randomness. Directory records never appear in customer responses/list results.

No bulk migration is needed: first profile access creates the pointer. Existing
customers still need the earlier QR_LOCK backfill if their lookup lock is absent.
Existing DynamoDB IAM permissions must permit transactions/reads for this
reserved partition; review any tenant LeadingKeys restrictions manually. This
implementation does not change IAM or other AWS resources automatically.

Optional frontend `VITE_CUSTOMER_QR_BASE_URL` sets the customer-facing origin;
default is the current browser origin. No production domain is hardcoded. The
origin must serve the React app with an SPA fallback for `/q/*`; the existing
`VITE_API_URL` remains the backend origin. Install updated backend requirements
and restart the backend; restart Vite when changing environment variables.

Public links are bearer credentials: share only with the intended customer.
They do not authorize visits or access to private profiles/media. PNG responses
are no-store; pages/images suppress referrers. Production hosting must use HTTPS,
avoid logging public references and provide appropriate abuse controls. A QR
already downloaded cannot be erased; after regeneration its token no longer
resolves, and refreshing the old public link fails. Public pages intentionally
show no customer name. Real Honeywell hardware acceptance remains manual;
images encode the exact raw token accepted by the existing scanner workflow.

### Manual acceptance

1. Install `backend/requirements.txt` in the existing venv; start the backend
   with the existing Cognito/DynamoDB configuration. Start Vite with `npm run dev`.
2. Log in as Owner/Manager; search a fictional customer by first name, surname,
   full name, local phone and `+353` phone. Confirm only your business results.
3. Open their profile: see the name and QR without copying a DynamoDB token.
   Copy the link twice and reload the profile; the link and QR must stay stable.
4. Open the copied link in a logged-out/private browser. Confirm only Contactly,
   QR and instructions appear; inspect no private profile/history/voucher data.
5. Scan the displayed QR using the existing Loyalty visits input. Lookup must
   identify the customer without recording a visit. Confirm only if a real test
   visit is intended; all existing daily/reward rules still apply.
6. Click Send QR Link: confirm the unconfigured message and no delivery success.
7. Save the old link/token for testing. Cancel regeneration first (no change),
   then explicitly confirm as Owner/Manager. Old lookup/link must fail; the new
   link/QR must work. Check customer details, photos, visit counts and vouchers
   are preserved. Two tabs using the old token must not both regenerate.
8. Log in as Staff: search, view and copy work; regeneration is absent and direct
   regeneration API access returns 403. Repeat business-isolation checks with
   an existing separate-business account. Inactive customers' public links fail.

Milestone 5B.1 adds no Twilio, raffle, printing, scanner drivers or changes to reward rules. Milestone 5C below adds digital raffle entries.


## Milestone 5C: Daily Raffle

Every new successfully confirmed loyalty visit creates exactly one immutable
logical Daily Raffle entry. Creation is part of the same authoritative operation
as the visit, lifetime counter update and any €10 loyalty/€20 birthday vouchers.
The existing Dublin calendar-date, active-customer and reward rules are unchanged.
Lookup, duplicate/rejected visits, QR regeneration and redemption create no entries.

### Storage and transaction design

The existing table and business partition are reused. Each logical entry has two
physical rows, both written together:

| Sort key (`customer_id`) | Item type | Purpose |
| --- | --- | --- |
| `RAFFLE#<customer UUID>#<visit UUID>` | `RAFFLE_ENTRY` | Authoritative customer history and deterministic visit uniqueness |
| `RAFFLE_DATE#<YYYY-MM-DD>#<customer UUID>#<visit UUID>` | `RAFFLE_DATE_INDEX` | Immutable non-PII date projection for future business/date reporting |

`raffle_entry_id` is the existing random visit UUID, ensuring a deterministic
one-to-one relationship. Each row stores business, owner customer, visit,
visit number, Dublin raffle date/timezone, UTC creation time and authenticated
Cognito subject. It contains no name, phone, DOB, email, QR credential or media.
The projection repeats only these immutable fields, avoiding a read per entrant.
Customer name/phone can be resolved later when preparing a print job.

One conditional transaction commits the customer counter update, VISIT row,
RAFFLE_ENTRY row, date projection and any voucher/reward/code-lock rows. Both
raffle puts require absent keys. With 5D.1 print jobs, a normal visit uses five actions; a fifth visit
uses nine; a combined loyalty/birthday reward uses thirteen. Existing active status,
optimistic counter/revision, daily history and reward/code conditions remain.
Any failed condition/write rolls back the entire transaction. In-memory mode
mirrors the operation under its existing lock. Retries may return the existing
daily-duplicate error after an ambiguous committed response; refreshing history
shows the committed entry. Retrying never adds another entry or reward.

Customer and date retrieval use paginated strongly consistent `Query` with an
exact business partition and the relevant sort-key prefix. No Scan, GSI, new
table, IAM changes or other AWS resource creation is needed. Internal raffle
rows never appear in customer API/list results.

### API and interface

- Existing `POST /customers/{id}/visits` now includes `raffle_entry` alongside
  customer, visit, progress and vouchers. Its body remains `{}`; business,
  recorder, date and timestamp are server-owned.
- New authenticated `GET /customers/{id}/raffle-entries` returns newest-first
  immutable entry models, without storage keys. Owner, Manager and Staff may
  view their own business's customer history; missing/other-business customers
  return 404 and unauthenticated requests return 401. Responses are no-store.
- Repository `raffle_entries_for_date(business_id, date)` and internal service
  `for_date` prepare for reporting. No date-report/draw/public raffle endpoint
  or direct-create endpoint is added in 5C.

Loyalty visits displays separate checkmarked visit, Daily Raffle and eligible
voucher success messages, only after confirmation succeeds. The customer
profile adds a padded **Daily Raffle** card showing the ten most recent entries,
Dublin raffle date/time and associated visit number, with loading, empty, error
and refresh states. History uses the existing authenticated transport.

### Setup, history and limitations

No new dependency or environment variable is required. Restart the backend after
updating code; reload the frontend (Vite normally hot reloads). No migration or
backfill is required or run. Old visits remain untouched and have no raffle;
creation starts with new confirmed visits after 5C deployment. The explicit
four-visit acceptance seed remains historical test tooling and creates no raffle;
the next normal fifth visit creates its raffle and eligible rewards atomically.

The immutable date projection costs one additional small write/storage record
per entry. Queries scale with a customer's retained history or a single day's
entries, not the entire table. The current history endpoint follows DynamoDB
pagination internally but returns all entries; the UI shows ten. Public cursor
pagination/retention and large-volume reporting are future work. Existing
customer list Queries still consume reads for filtered internal business rows.
Milestone 5D.1 below adds the digital queue and immutable tickets. No winner
selection, exports, production printing, browser printing, Twilio or new public data access is implemented; the isolated 5D.2A agent is described below. Server clocks must remain
synchronized. Future business-specific timezone settings remain deferred.

### Exact live acceptance procedure

1. Restart FastAPI using the existing Cognito/DynamoDB/S3 configuration and
   `uvicorn main:app --reload` from `backend/` with the existing venv activated.
   Start/reload Vite from `frontend/` using `npm run dev`. Do not change AWS
   resources. Use fictional customers and existing business-user logins.
2. Select a fictional active customer who has not visited today in Dublin.
   Existing customers with old visits should initially show no raffle history.
   If already visited today before deployment, use a new fictional customer or
   wait for the next Dublin date; do not delete history or bypass the daily rule.
3. Open **Loyalty visits**, scan/type the existing QR, and look up the customer.
   Open their profile in another tab: lookup must create no visit or raffle.
4. Click **Confirm visit** once. Expect separate **Visit recorded successfully**
   and **Daily Raffle entry created** messages. Open the profile and refresh
   raffle history: one entry shows today's Dublin date and the visit number.
5. Repeat lookup/confirmation today, including two tabs. Expect the existing
   daily-duplicate error and no new entry, counter increment or voucher.
6. Read-only DynamoDB verification: in the existing table use Query, partition
   `business_id=trumps`, sort-key prefix `RAFFLE#<fictional-customer-UUID>#`.
   There must be exactly one RAFFLE_ENTRY per new valid visit. Query prefix
   `RAFFLE_DATE#<today-in-Dublin-YYYY-MM-DD>#` in the same partition: the matching
   RAFFLE_DATE_INDEX row has the same raffle/visit IDs and recorded_by Cognito
   subject. These two physical rows represent one logical entry. Do not expose
   JWTs or real customer records to inspect attribution.
7. For fifth-visit acceptance, use an eligible fictional customer with four
   historical visits (or the documented dry-run/apply acceptance seed on a new
   zero-visit fictional customer). Confirm normally: expect one raffle plus the
   €10 voucher, progress 0/5 and retained history. Seeded historical visits must
   not appear in raffle history.
8. With a separate fictional adult customer's birthday in this Dublin week,
   confirm a valid visit: expect one raffle and the €20 birthday voucher. With
   four historical visits and a birthday this week, expect one raffle and both
   vouchers; existing birthday/year and expiry rules still apply.
9. Redeem a voucher and regenerate QR as Owner/Manager; refresh raffle history:
   neither action adds an entry. Deactivate a separate fictional customer and
   verify confirmation is rejected without a raffle.
10. Repeat history access as Owner, Manager and Staff. Log out: history access
    must fail. Using an existing separate-business user, the original customer
    history must return 404; no internal raffle rows should appear in the directory.

Automated coverage uses memory/fake DynamoDB, deliberate conditional/storage
failures, concurrent attempts, DST clocks and SDK stubs. Real AWS/browser
acceptance is intentionally manual; no live raffle entries were created by tests.


### Milestone 5C acceptance improvement: manual visit lookup

**Loyalty visits** now offers **Scan customer QR** or **Find customer** by name
or phone. The manual search calls the existing authenticated `GET /customers`
directory only on Search submission, reusing the exact directory search helper
for first/last/full names, partial phones and equivalent Irish representations
(`0831234567`, `831234567`, `+353831234567`, `353831234567`). No extra backend
search or manual-visit endpoint is introduced. Form phone validation is unchanged.

Compact results display name, phone and active/inactive state. Selecting an
active result uses the existing read-only `GET /customers/{id}/visits` to load
fresh customer information and loyalty progress into the same confirmation panel
used by QR lookup, including the protected profile photo. Inactive results cannot
be selected; fresh deactivation and backend inactive checks remain enforced.
**Clear / change customer** and a new search allow correcting the selection.

Search and selection create no visits, raffle entries or vouchers. Both lookup
methods use the same **Confirm visit** action and existing
`POST /customers/{id}/visits` with `{}`. Daily Dublin eligibility, identity, tenant
checks, atomic visit/raffle/reward writes and success messages remain unchanged.
No frontend-supplied business or recorder is used. The current small-business MVP
queries the existing business directory for each explicit search; server-side
search/pagination can be added later if directory volume grows.

Manual acceptance: search a fictional customer by first/last/full name and each
phone format; choose among multiple matches; verify the panel's name, phone,
photo and progress. Check history is unchanged before confirmation. Confirm once,
expect visit/raffle and eligible reward messages, then repeat today and expect
the existing duplicate error. Clear/change selection and verify QR lookup still
works. Repeat with Owner, Manager and Staff; separate-business users must not
see/select the original customer. No migration, configuration or AWS changes
are needed; reload Vite for this frontend improvement.


## Milestone 5D.1: Durable print queue and immutable tickets

New confirmed visits automatically queue one Daily Raffle ticket, plus one ticket
for each €10 loyalty / €20 birthday voucher actually issued by the existing reward
engine. There can be one, two or three jobs. Print creation never issues a reward
or changes eligibility. QR/manual lookup, selection, rejected/duplicate visits,
redemption and QR regeneration do not create jobs. Production physical printing is
blocked; 5D.2A adds a separate development adapter below.

### Single-table keys and atomic creation

The existing PK `business_id` is always verified from Cognito. The canonical SK is:

```text
PRINT#<customer UUID>.<source visit UUID>.<DAILY_RAFFLE|LOYALTY_10|BIRTHDAY_20>
```

`print_job_id` is the portion after PRINT#. This deterministic source/type identity
is unique within the tenant and is conditionally inserted. Reprints append
`.R<client request UUID>` to the original ID. These are authenticated internal
identifiers; they are never public links. Owner customer is stored separately as
`owner_customer_id`, and `item_type=PRINT_JOB`. Jobs contain source visit, raffle
entry or voucher ID, timestamps, lifecycle/audit fields and a versioned snapshot.

Business queue, customer queue and customer/visit retrieval use paginated,
strongly consistent Queries with prefixes `PRINT#`, `PRINT#<customer UUID>.` and
`PRINT#<customer UUID>.<visit UUID>.`. There is no Scan, GSI, mutable queue index,
new table or automatic AWS/IAM resource change. Customer APIs exclude print rows.

Initial job puts join the existing authoritative visit transaction: counter,
VISIT, raffle entry/date projection, any vouchers/reward/code locks and all jobs.
Normal visits use five actions; one reward uses nine; both rewards use thirteen.
Customer revision is checked so concurrent edits cannot mix snapshot details with
an outdated reward decision. Job-generation or write failure leaves no partial
visit/reward/raffle/jobs. Memory mode mirrors atomic creation under the existing
lock but remains process-local; only DynamoDB mode is durable.

The adapter checks the 100-action and 4 MB aggregate limits before dispatch,
using a conservative serialized-size bound and reserving up to 400 KiB for each
existing update/check item. Put sizes are also bounded below 400 KiB. Maximum
current action count is thirteen, and snapshot text is capped at 8,000 characters.
See [AWS transaction limits](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html).

### Tickets and immutable PII

Template version 1 is a 42-column black-and-white, Unicode receipt-text snapshot.
It includes business name (Trumps for the existing trumps business, otherwise
generic Contactly until business settings exist), original customer name/phone,
required ticket message/heading, source reference or existing voucher code,
Europe/Dublin issue/expiry time and signature line. Expiry is exclusive, matching
the existing backend rules. No code is regenerated, including on reprint.

The complete bounded text and structured snapshot are stored when the visit
commits. Edits to customer details never rewrite historical tickets. Reprints use
that original snapshot with an explicit REPRINT banner. Control characters,
including printer-command escape characters, are stripped; previews render as
escaped text, never injected HTML. No ID/consent images, DOB, address, QR secret
or unrelated PII is copied. Print snapshots are private customer PII: production
retention/erasure policy must include these records and audit reasons.

### Lifecycle and paper-duplication safety

| State | Meaning / allowed next action |
| --- | --- |
| PENDING | Queued; may be atomically claimed |
| CLAIMED | Fenced 120-second lease; output has not started |
| PRINTING | Start accepted; outcome may include physical output |
| COMPLETED | Current holder acknowledged completion; UI says Printed |
| RETRYABLE | Failed/expired before start; may be claimed within attempt limit |
| FAILED | Three pre-output attempts exhausted; requires explicit reprint |
| UNCERTAIN | Started failure/expired printing; operator review/explicit reprint only |

Claim uses a random token, trusted subject, expiry and revision CAS; concurrent
claimers cannot both win. Start, complete and fail require both the current token
and matching authenticated holder with an unexpired lease. Only the claim response
returns the token. Lists/details/status responses never expose it. Every durable
transition records actor/time and a safe action/error code. Raw printer exception
text, JWTs, passwords or device credentials are not logged/stored by this feature.

A future agent MUST receive a successful start response before sending any bytes
to hardware. Expired CLAIMED jobs can safely retry because this protocol forbids
output before start. Expired/failed PRINTING jobs become effectively UNCERTAIN
and cannot be claimed automatically, even if acknowledgement was lost. GETs
calculate effective expired status without writes; operator review persists it
with CAS. The fixed lease is not renewed in 5D.1. Server clocks must be accurate.
Acknowledged completion is a trusted caller statement, not hardware verification.

Explicit reprints are allowed only for original COMPLETED, FAILED or UNCERTAIN
jobs, with confirmation and a meaningful audit reason. A deterministic request UUID
makes repeats of the same request idempotent. The original audit update and child
job insertion are one transaction. A child has its own attempt budget, original
source/codes/snapshot and REPRINT label. Reprint children cannot be recursively
reprinted: further explicit requests must reference the original. Nothing queues
additional paper automatically after uncertain output. After a lost response,
refresh/inspect the queue before another explicit decision. Do not change the
request UUID when retrying the same request.

### APIs and role boundaries

All routes verify the existing Cognito ID token and derive business exclusively
from it; mismatched business query parameters are rejected.

| Endpoint | Permission / purpose |
| --- | --- |
| `GET /customers/{id}/print-jobs` | Owner/Manager/Staff; summary status only |
| `GET /customers/{id}/visits/{visit_id}/print-jobs` | Owner/Manager/Staff; scoped summaries |
| `GET /print-jobs` | Owner/Manager business queue; `?review=true` filters failed/uncertain/retryable |
| `GET /print-jobs/{job_id}` | Owner/Manager; immutable ticket and audit detail, no claim token |
| `POST /print-jobs/{job_id}/claim` | Owner/Manager; `{}`; atomically lease job |
| `POST /print-jobs/{job_id}/start` | Owner/Manager; current `claim_token` |
| `POST /print-jobs/{job_id}/complete` | Owner/Manager; current `claim_token` |
| `POST /print-jobs/{job_id}/fail` | Owner/Manager; current `claim_token`; safe failure classification |
| `POST /print-jobs/{job_id}/review` | Owner/Manager; `{}`; persist expired lease classification |
| `POST /print-jobs/{job_id}/reprint` | Owner/Manager; UUID `request_id`, `reason`, `confirmed: true` |

Staff cannot administer the global queue, see ticket snapshots/audit reasons or
invoke lifecycle/reprint operations. Backend guards enforce this independently of
React. No unauthenticated queue/ticket route or generic create-print-job endpoint
exists. Visit responses contain queued summaries only; clients cannot choose jobs.

Contactly shows Queued ticket statuses after successful confirmation. Customer
profiles show the ten most recent job summaries with refresh. Owner/Manager have
**Print queue**, review filtering, private snapshot preview and an explicit reason
and confirmation for reprints. There are no UI controls that fabricate completion,
send bytes to hardware or call `window.print()`.

### Setup and live acceptance

No new dependency, environment variable, migration, startup backfill or AWS
resource change is needed. Use existing DynamoDB/Cognito configuration. Restart
FastAPI, reload Vite. Jobs begin with new visits after deployment; old rewards and
visits do not automatically gain jobs. The four-historical-visit development seed
still creates no jobs; the next normal fifth visit creates its two/three jobs.

1. With a fictional active customer eligible for a visit today, use either QR or
   name/phone identification. Lookup/selection must leave all job/history counts
   unchanged. Confirm once; see raffle job Queued, never Printed.
2. Open the profile and Owner/Manager Print queue. Inspect the immutable receipt;
   check name/phone, heading/message, signature, source reference and Dublin time.
3. With an eligible fictional customer at four historical visits, confirm: raffle
   plus loyalty jobs must use the issued voucher's existing code/expiry. Birthday
   eligibility adds the birthday ticket; both rewards produce exactly three jobs.
4. Retry the same day or use two tabs: no duplicate jobs/visit/rewards. Query the
   existing table using business partition and PRINT# customer/visit prefix to
   verify one canonical record per source/type. Never use a table Scan.
5. Change a fictional customer's name/phone and re-open the old ticket: original
   snapshot remains. Staff sees status summaries; global queue/detail/reprint APIs
   must return 403. Separate-business users cannot read these jobs (404 or empty
   own queue). Logged-out calls return 401.
6. All newly queued jobs remain pending in 5D.1 because no print agent is connected.
   Exercise claim/start/ack/failure/reprint through automated local tests. Do not
   mark live jobs completed just to simulate printing; no paper has been produced.
   Uncertain/reprint UI acceptance can use isolated test fixtures, not false live
   acknowledgements or DynamoDB edits.

### Milestone 5D.2 boundary and remaining decisions

The intended flow remains backend queue → Contactly Windows Print Agent → EPSON
TM-m30III → automatic cut. 5D.1 contains no executable agent, USB/network transport,
ESC/POS encoding, physical printing, spooler or driver integration. Unicode Euro
encoding/raster fallback, paper width/font, cutting, hardware status and offline
reconciliation must be tested on the actual Windows printer in 5D.2.

Current lifecycle endpoints are authenticated HUMAN Owner/Manager administration
boundaries, not a provisioned production device credential. The Windows agent
must receive its own revocable identity with explicit business/device binding and
narrow claim/start/ack scopes, enforced in a dedicated backend authorization guard.
Choose the real issuer/audience and enrollment/rotation mechanism in 5D.2; do not
reuse a staff login, embed credentials, add an auth bypass or accept a business ID
from the agent. Only that authenticated device plus its current fence may act as
holder. Existing Cognito verification must remain intact.

Exactly-once physical output cannot be guaranteed over printer/network crashes.
The lease/start protocol deliberately pauses ambiguous outcomes for operators.
5D.2A preserves that policy with lease renewal and a durable local output fence.
Production device deployment and onsite spool/ack acceptance remain pending.
Queue queries currently paginate internally but return retained jobs; global review
filters read the business's PRINT# range rather than a status index. For larger
volumes, add public cursor pagination/status work discovery after an explicit
architecture review; no expensive Scan or AWS index is silently introduced here.
Retention, device audit policy, rate limits and secure Windows credential storage
remain production work. No Twilio, raffle draw or new voucher rule is implemented.

### Milestone 5D.2A — Windows agent implementation

`print-agent/` contains an outbound worker, local-only default simulation,
Windows RAW Epson adapter, durable restart fence and mocked tests. See
[Windows setup and onsite acceptance](print-agent/README.md). No physical printing
was attempted. Spool acceptance records UNCERTAIN rather than claiming paper output.
An isolated, disabled-by-default loopback/in-memory device transport is implemented;
production device enrollment/authentication remains a deployment blocker. The worker
development transport cannot consume live DynamoDB jobs and never uses Owner/Manager
credentials. 5D.3 below adds HTTPS integration requiring explicit provider provisioning.

### Milestone 5D.3 — secure device authentication integration

Implemented: separate Cognito access-token validation for confidential M2M devices,
server-controlled device/client/business registry, Owner-only register/list/disable/
rotation-pending APIs, operator binding tool, HTTPS token acquisition/renewal and
Windows Credential Manager storage. Human authentication remains ID-token based;
agents cannot access customer/media/admin endpoints or acknowledge physical completion.
See [provisioning, configuration, permissions and acceptance](print-agent/README.md#milestone-5d3--secure-connectivity-integration-provisioning-pending).

Existing public SRP SPA configuration cannot supply client credentials. Future
provisioning requires a Cognito custom resource server/scope, token domain and a
unique confidential client-credentials-only client per device (recommended five-minute
tokens), plus a valid HTTPS backend. **None was provisioned or verified live.**
Backend variables: `PRINT_AGENT_ISSUER`, `PRINT_AGENT_SCOPE`; production secrets reside
only in the Windows vault. No permanent AWS credential is required on the agent.

Registry records use tenant `DEVICE#UUID`/`PRINT_DEVICE` items and a reserved
`!PRINT_DEVICES` partition with `CLIENT#client_id` bindings. New records use the
existing table, conditional/transactional writes and strongly consistent Get/Query;
no table/index/Scan or customer migration. Client IDs are never reassigned, including
rotation/revocation. Registry failures fail closed. Last-seen writes use revision CAS;
registration/revocation/rotation events live on device records, claim/start/spool-ack
history on existing print-job audits. Protect registry IAM access; do not expose its
reserved partition. Full centralized audit export/retention and last-seen write
throttling remain deployment/scaling work.

Owner API: GET/POST `/print-devices`; POST `/print-devices/{id}/disable|rotate`.
Machine API: GET `/print-agent/jobs`; POST `/print-agent/jobs/{id}/claim|start|renew|fail|submitted`.
No agent review/reprint/complete route. Owner-only Print devices UI is available at `#/print-devices`: list/register,
view returned device ID/status/last-seen, and explicitly confirm disable/rotation.
The existing API remains the authoritative role and tenant boundary. Provider creation, secret delivery
and provider revocation are explicit operator steps, never automatically performed.

New ticket template version 3 shows original issuance date (`DD/MM/YYYY`) and hour
(`HH:mm`, actual minutes) in Europe/Dublin on raffle, €10 and €20 tickets. Snapshots retain
server-issued UTC timestamps; retries/reprints never use processing time. Reprints
remain marked REPRINT. Legacy immutable snapshots retain their existing formatting;
no migration or physical printing is required. Updated simulation fixtures and
Windows timezone dependency are described in the Print Agent README.

Ticket time correction: new version 3 snapshots include actual original minutes (HH:mm).
Existing immutable version 1/2 snapshots remain supported without rewriting history.
