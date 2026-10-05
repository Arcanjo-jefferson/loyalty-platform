# Loyalty Platform

A local MVP for a future multi-business customer loyalty and SMS marketing platform. The project is designed to give managers a customer directory and, in later milestones, tools for recording visits, issuing rewards and communicating with customers who have opted into marketing.

**Current status: Milestone 1 completed; Milestone 2 DynamoDB implementation available, with live AWS persistence verification pending.** The application runs locally with a React manager dashboard and a FastAPI customer API. Customer persistence is configurable between DynamoDB and an optional in-memory repository. Authentication, document uploads, SMS sending and loyalty workflows remain planned.

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
- Business-scoped storage and API queries. Development defaults to `business_id=trumps`; the application is not permanently tied to one business.

- Configurable DynamoDB persistence through boto3, preserving the repository/service boundary and all Milestone 1 validation and UX.
- Atomic per-business phone-lock transactions, paginated business-scoped queries, optimistic concurrency checks and sanitized storage errors.

## Technology stack

| Area     | Current technology |
| ---      | --- |
| Frontend | React 19, JavaScript, Vite 8, reusable components and CSS |
| Backend  | Python, FastAPI, Pydantic 2, Uvicorn |
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
│   │   ├── config.py           # Environment loading and repository selection
│   │   ├── dynamodb_repository.py # DynamoDB mapping, queries and transactions
│   │   ├── models.py           # Customer models and input validation
│   │   ├── routes.py           # Customer HTTP endpoints
│   │   ├── service.py          # Customer IDs, consent and timestamp logic
│   │   └── repository.py       # Storage protocol and in-memory implementation
│   └── tests/
│       ├── test_customers.py
│       ├── test_age_validation.py
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

These are the required target settings, not a claim that this implementation has inspected the live AWS table. Verify its schema with the command below before the first live test.

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

## Local setup

### Prerequisites

- Python 3.10 or newer, with `pip` and `venv`.
- Node.js 22.12 or newer and npm. The installed Vite version also supports Node.js 20.19 or newer within the 20.x release line.
- An IANA timezone database containing `Europe/Dublin`. If Python cannot find it on your OS, install the `tzdata` package in the virtual environment.

Run the commands below from your local project checkout. DynamoDB mode requires AWS access to the existing table and AWS CLI v2 for local SSO login. Offline memory mode and automated tests require no AWS account or credentials. No Twilio configuration is needed.

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

### Optional frontend configuration

From `frontend`, copy the provided example:

```sh
cp .env.example .env.local
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL |
| `VITE_BUSINESS_ID` | `trumps` | Development business scope |

Restart Vite after changing environment variables. Vite variables are public and included in the frontend bundle; never put secrets or credentials in them. `.env.local` is ignored by Git.

## Customer API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/customers` | Register a customer; returns HTTP 201 |
| `GET` | `/customers` | List customers in the selected business |
| `GET` | `/customers/{customer_id}` | Retrieve one customer |
| `PUT` | `/customers/{customer_id}` | Replace editable customer fields |

All customer endpoints accept a `business_id` query parameter, defaulting to `trumps`. Missing or cross-business customer IDs return 404, duplicate normalized phones return 409 and invalid input returns 422.

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

The backend includes tests covering customer creation/retrieval/updates, consent transitions, stable server-managed fields, business scoping, normalized duplicate phones, invalid input, concurrent duplicate creation and age boundaries including leap birthdays. API integration tests explicitly force memory mode and start a temporary Uvicorn server on an available localhost port; localhost socket access is required. DynamoDB tests use an atomic in-process fake and boto3 Stubber, with dummy test credentials only. They cover serialization, business isolation, pagination (including empty filtered pages), lock exclusion, duplicate races, atomic phone changes, rollback, concurrency, metadata preservation and sanitized errors. Configuration tests mock AWS sessions. Automated tests neither access the real AWS account nor depend on the `loyalty-dev` profile.

From `frontend`:

```sh
npm run test
npm run lint
npm run build
```

The three frontend tests cover phone normalization, birth-date/age validation and Ireland's calendar date. Lint checks JavaScript/React code; the build writes production assets to `frontend/dist`. These checks do not replace browser interaction or accessibility testing.

## Current limitations

- **DynamoDB mode persists customer records across backend restarts/reloads.** Live persistence still needs verification against the existing table using the procedure below.
- **Memory mode only:** records are process-local, start empty and are lost on restart/reload. Use one worker in this mode; different workers have separate records. There is no automatic migration between memory and DynamoDB.
- Manager authentication and authorization are not implemented. `business_id` is development scoping, not a security boundary. Anyone who can reach the API can request customer records. Keep this MVP local until authentication and trusted business context are implemented.
- Customer data is not saved to browser storage. The customer directory does not display internal IDs or QR tokens, although the API returns them.
- SMS consent is recorded, but no messages are sent. There is no QR scanning, visit recording, loyalty counter, reward issuance, voucher redemption or historical audit workflow.

## First real DynamoDB persistence test

After activating the backend environment, exporting the four variables above, logging in with SSO, checking the table schema and starting both servers:

1. Open the dashboard and register a fictional adult customer with a test Irish mobile number. Use a number not already present in the selected development business. Do not commit any real customer information, request dumps or AWS output containing customer records.
2. Confirm the success notification, read-only profile and customer directory show the saved record.
3. Stop the backend with `Ctrl+C`, then restart with the same DynamoDB configuration. Reload the frontend and reopen the customer. The record, ID, QR token, timestamps and consent state should remain.
4. Try registering the same normalized phone in the alternate national/`+353` format. Expect a duplicate error and preserved form values.
5. Edit the customer's phone to a different unused test number. Confirm the updated profile and persistence after another backend restart. Register another fictional customer with the old phone: it should now be available. The new phone must remain protected from duplicates.
6. Confirm the directory contains only customers, never `PHONE#` rows. In API docs, test a `PHONE#` customer lookup: expect 404. Repeat with another test business to confirm scoped lists/lookups; the same phone may belong to different businesses.

The health endpoint checks application availability, not AWS connectivity. Customer API operations exercise storage. A 503 indicates a storage/configuration problem; check SSO expiry, table name/region and permissions rather than switching silently to memory.

This manual test has not been run against the real AWS account by the automated suite. No new table or production deployment is part of Milestone 2.

## Planned development roadmap

Milestone 2 implements configurable DynamoDB customer persistence. Its live AWS acceptance test remains pending. The following later milestones are **not implemented**, following `PROJECT_CONTEXT.md`:

- **Milestone 3:** Cognito authentication, individual staff accounts, roles and trusted tenant authorization.
- **Milestone 4:** private S3 customer documents and webcam capture; no facial recognition.
- **Milestone 5:** QR scanning and confirmed visit tracking with preserved visit history.
- **Milestone 6:** unique €10 vouchers after five visits, progress reset to 0/5 without deleting historical visits, and single-use redemption.
- **Milestone 7:** Twilio messaging, consent-aware campaigns and scheduled birthday promotions.
- **Milestone 8:** audit/security/privacy hardening and production deployment, including future Lambda/API Gateway and hosting infrastructure.

Exact boundaries may evolve. No Cognito, S3 upload, QR loyalty, vouchers, Twilio, birthday automation or Lambda deployment is included in the current implementation.
