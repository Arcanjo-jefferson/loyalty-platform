# Loyalty Platform

A local MVP for a future multi-business customer loyalty and SMS marketing platform. The project is designed to give managers a customer directory and, in later milestones, tools for recording visits, issuing rewards and communicating with customers who have opted into marketing.

**Current status: Milestones 1–2 completed; Milestone 3 authentication and authorization implemented, awaiting live Cognito acceptance testing.** The application runs locally with a React manager dashboard and a FastAPI customer API. Customer persistence is configurable between DynamoDB and an optional in-memory repository. Cognito business-user login and server-side role/tenant authorization are implemented. Document uploads, SMS sending and loyalty workflows remain planned. DynamoDB persistence was manually verified by the project owner.

## Implemented features

- Responsive dashboard, sidebar and customer-management pages for desktop, tablet and mobile.
- Dashboard counts from actual local records: total customers, marketing opted-in and birthdays this month. Birthday month uses the manager's browser date; there are no invented business analytics.
- Customer directory with name/phone search, date of birth, promotional SMS consent, status and profile actions.
- Customer registration, read-only profiles and a separate edit page.
- Irish mobile input with a visible Ireland `+353` indicator. National and international formats are normalized to E.164 by the backend before storage and per-business duplicate checks. Incomplete or malformed numbers are rejected. Validation checks format, not phone ownership or service availability.
- Minimum age of 18 enforced in frontend and backend using the full birth date and the current date in `Europe/Dublin`. Invalid and future dates are rejected. February 29 birthdays reach the age threshold on March 1 in non-leap years.
- Explicit promotional/marketing SMS consent, with a UTC timestamp for the most recent consent transition.
- Secure UUID4 customer IDs and separate random, opaque `qr_token` values containing no personal data. Token generation is a data-model foundation only; QR rendering, scanning and loyalty are not implemented.
- Server-managed UTC creation/update timestamps and active/inactive customer status.
- Successful registration and updates automatically open the customer's profile using the saved API response immediately. Reusable accessible notifications display `Customer registered successfully.` or `Customer details updated successfully.`
- Failed submissions remain on the form, preserve entered values and show an error without success feedback.
- Business-scoped storage and API queries use the verified Cognito user's `custom:business_id`; the frontend cannot choose another tenant.

- Configurable DynamoDB persistence through boto3, preserving the repository/service boundary and all Milestone 1 validation and UX.
- Atomic per-business phone-lock transactions, paginated business-scoped queries, optimistic concurrency checks and sanitized storage errors.

- Cognito email/password login, temporary-password completion, per-tab sessions, token refresh and logout; no public sign-up.
- Verified JWT authentication and reusable Owner/Manager/Staff guards on every customer endpoint.

## Technology stack

| Area     | Current technology |
| ---      | --- |
| Frontend | React 19, JavaScript, Vite 8, Amplify Auth, reusable components and CSS |
| Backend  | Python, FastAPI, Pydantic 2, Uvicorn, PyJWT with cryptography |
| Storage  | DynamoDB via boto3; optional process-local in-memory repository |
| Checks   | Python `unittest`, Node.js test runner, Oxlint, Vite production build |

No large UI framework or additional routing library is used. The backend uses the existing boto3 dependency for DynamoDB; no additional storage or test dependencies were added.

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
│   │   ├── models.py           # Customer models and input validation
│   │   ├── routes.py           # Customer HTTP endpoints
│   │   ├── service.py          # Customer IDs, consent and timestamp logic
│   │   └── repository.py       # Storage protocol and in-memory implementation
│   └── tests/
│       ├── test_customers.py
│       ├── test_age_validation.py
│       ├── test_auth.py
│       ├── auth_test_server.py # Test-only injected verifier; never deploy
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

- **Create:** one conditional transaction claims the phone lock and inserts the customer. A conflicting lock returns the existing user-friendly duplicate-phone error (409).
- **Update without a phone change:** a transaction verifies lock ownership and conditionally updates the customer.
- **Phone change:** one transaction claims the new phone, conditionally updates the customer and releases the old lock after verifying ownership. Failure rolls back every action. The old phone becomes reusable only after a successful change.
- **Concurrency:** the stored phone and expected update timestamp must match. A concurrent modification returns 409 rather than overwriting newer data. Transient transaction conflicts receive bounded retries with the same idempotency token.
- **Reads:** `GetItem` uses both keys; listing uses a strongly consistent, paginated `Query` for one business. No table scan is used for reads or phone uniqueness. Lists filter `item_type=CUSTOMER` and defensively exclude `PHONE#` keys; direct lookup of a phone-lock key returns no customer.
- **Serialization:** dates and UTC timestamps are ISO strings, consent is Boolean and optional empty fields are null. All existing customer fields are persisted. Storage-only fields are excluded from customer responses.
- **Failures:** AWS/credential/network errors become a generic 503 response; raw AWS messages and stack traces are not returned to the frontend. There is no automatic fallback to memory.

Updates modify only managed editable fields, consent timestamp and update timestamp. Immutable fields and unknown future metadata attributes remain intact. Future document references can use separate typed records in the same business partition (with a customer association) or additional metadata attributes. No document model, document API, S3 upload or webcam capture is implemented.

The adapter expects records created through this application, including their phone locks and type markers. It does not migrate old in-memory records or automatically adopt manually inserted customer rows. Treat pre-existing unmanaged rows as a separate migration task rather than bypassing lock ownership.

## Cognito authentication and authorization

Cognito authenticates business users, not loyalty customers. The frontend uses Amplify Auth with the existing public user-pool app client and `USER_SRP_AUTH` email/password flow. No Amplify deployment, identity pool, hosted-login domain or OAuth redirect URL is required by this flow. Tokens are persisted in session storage for reloads in the same tab, not localStorage or DynamoDB. Closing the tab normally ends local persistence. Browser storage is accessible to JavaScript; this is not HttpOnly cookie authentication.

Every customer operation requires an `Authorization: Bearer <ID token>` header. ID tokens are deliberately used because the standard Cognito ID token contains `custom:business_id`. The backend pins RS256, selects a key from the configured pool's cached JWKS, verifies signature, issuer, expiration, issued-at and exact app-client audience, and requires `token_use=id` plus subject. Access tokens, tokens from another client/pool and unsigned/invalid/expired tokens are rejected. This follows the [Cognito token verification guidance](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html); custom attributes are available in [Cognito ID tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html).

The verified user context contains subject, optional email, business, groups and effective role. An explicit allowlist recognizes `owner`, `manager` and `staff` after ASCII case normalization (also accepting `Owner`, `Manager` and `Staff`); precedence is **Owner > Manager > Staff**. Missing/invalid business membership or no recognized role returns 403. Authentication failure returns 401; unavailable configuration/JWKS returns 503. No tokens or passwords are logged by application code.

`GET /auth/me` returns the authenticated user's minimal context to initialize the UI. All customer routes derive storage scope from that identity. A legacy `business_id` query is allowed only if it matches the verified business; it never selects the tenant, and a mismatch returns 403. Cross-tenant customer IDs return 404. No frontend role or permission value is trusted. Owner privileges apply to one business, not across businesses.

| Role | Current customer permissions | Future authorization helpers |
| --- | --- | --- |
| Owner | Create, list/search, view, edit and change active/inactive status | `require_owner` for owner-only administration |
| Manager | Create, list/search, view, edit and change active/inactive status | `require_management` for Owner/Manager, including future sensitive documents |
| Staff | Create active customers, list/search, view and edit details; cannot change status | `require_customer_access` for all three roles |

The full finalized role model remains in `PROJECT_CONTEXT.md`. Guards for future sensitive operations are available; no staff-management, document, SMS or report endpoints have been implemented. Hiding UI controls is supplementary; the backend is authoritative. Staff edit auditing remains a future requirement, not an implemented audit log.

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
- Authentication and role/tenant checks are implemented, but this remains a local development application. Live Cognito login requires acceptance testing. Browser sessions are JavaScript-readable, backend JWT validation does not immediately revoke already issued tokens, and production HTTPS, MFA, rate limiting and audit hardening remain outstanding.
- Customer data is not saved to browser storage. The customer directory does not display internal IDs or QR tokens, although the API returns them.
- SMS consent is recorded, but no messages are sent. There is no QR scanning, visit recording, loyalty counter, reward issuance, voucher redemption or historical audit workflow.

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

Milestone 2 persistence has been manually verified by the project owner. Milestone 3 Cognito integration and current customer authorization are implemented, pending live login acceptance testing. The following later milestones are **not implemented**, following `PROJECT_CONTEXT.md`:

- **Milestone 4:** private S3 customer documents and webcam capture; no facial recognition.
- **Milestone 5:** QR scanning and confirmed visit tracking with preserved visit history.
- **Milestone 6:** unique €10 vouchers after five visits, progress reset to 0/5 without deleting historical visits, and single-use redemption.
- **Milestone 7:** Twilio messaging, consent-aware campaigns and scheduled birthday promotions.
- **Milestone 8:** audit/security/privacy hardening and production deployment, including future Lambda/API Gateway and hosting infrastructure.

Exact boundaries may evolve. No S3 upload, QR loyalty, vouchers, Twilio, birthday automation or Lambda deployment is included in the current implementation.

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
they do not contact AWS. Real first-login acceptance remains a manual check.

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
