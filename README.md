# Loyalty Platform

A local MVP for a future multi-business customer loyalty and SMS marketing platform. The project is designed to give managers a customer directory and, in later milestones, tools for recording visits, issuing rewards and communicating with customers who have opted into marketing.

**Current status: Milestone 1 — customer-management foundation completed.** The application runs locally with a React manager dashboard and a FastAPI customer API. Persistent storage, authentication, SMS sending and loyalty workflows are planned, not implemented.

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

## Technology stack

| Area | Current technology |
| --- | --- |
| Frontend | React 19, JavaScript, Vite 8, reusable components and CSS |
| Backend | Python, FastAPI, Pydantic 2, Uvicorn |
| Storage | Process-local, in-memory repository |
| Checks | Python `unittest`, Node.js test runner, Oxlint, Vite production build |

No large UI framework or additional routing library is used. AWS SDK packages remain in the existing backend dependency file but are unused; their presence does not indicate an AWS integration.

## Project structure

```text
loyalty-platform/
├── README.md
├── .gitignore
├── backend/
│   ├── main.py                 # Application factory, CORS, errors, health endpoints
│   ├── requirements.txt
│   ├── app/
│   │   ├── models.py           # Customer models and input validation
│   │   ├── routes.py           # Customer HTTP endpoints
│   │   ├── service.py          # Customer IDs, consent and timestamp logic
│   │   └── repository.py       # Storage protocol and in-memory implementation
│   └── tests/
│       ├── test_customers.py
│       └── test_age_validation.py
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

HTTP handling, validation, business logic and storage are separate. The `CustomerRepository` protocol allows a future storage adapter to replace the in-memory implementation while retaining the API and service layer. Any persistent adapter must preserve atomic phone uniqueness within each business.

## Local setup

### Prerequisites

- Python 3.10 or newer, with `pip` and `venv`.
- Node.js 22.12 or newer and npm. The installed Vite version also supports Node.js 20.19 or newer within the 20.x release line.
- An IANA timezone database containing `Europe/Dublin`. If Python cannot find it on your OS, install the `tzdata` package in the virtual environment.

Run the commands below from your local project checkout. No AWS account, Twilio account or credentials are needed.

### Backend

Create the environment and install dependencies on a fresh checkout:

```sh
cd backend
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

If `backend/venv` already exists with dependencies installed, simply activate it. On Windows, use `venv\Scripts\activate` instead of `source venv/bin/activate`.

Start FastAPI from the `backend` directory:

```sh
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

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
python -m compileall -q app main.py
```

The backend currently has 12 tests covering customer creation/retrieval/updates, consent transitions, stable server-managed fields, business scoping, normalized duplicate phones, invalid input, concurrent duplicate creation and age boundaries including leap birthdays. Integration tests start a temporary Uvicorn server on an available localhost port and use fresh in-memory storage; localhost socket access is required.

From `frontend`:

```sh
npm run test
npm run lint
npm run build
```

The three frontend tests cover phone normalization, birth-date/age validation and Ireland's calendar date. Lint checks JavaScript/React code; the build writes production assets to `frontend/dist`. These checks do not replace browser interaction or accessibility testing.

## Current limitations

- **Customer records are lost whenever the backend process restarts**, including reloads caused by code changes. There is no database or durable backup, and the directory starts empty.
- Storage is local to one process. Run one backend worker; separate workers would have separate records and uniqueness checks.
- Manager authentication and authorization are not implemented. `business_id` is development scoping, not a security boundary. Anyone who can reach the API can request customer records. Keep this MVP local until authentication and trusted business context are implemented.
- Customer data is not saved to browser storage. The customer directory does not display internal IDs or QR tokens, although the API returns them.
- SMS consent is recorded, but no messages are sent. There is no QR scanning, visit recording, loyalty counter, reward issuance, voucher redemption or historical audit workflow.

## Planned development roadmap

The following work is **planned and not implemented**. Sequencing may change as requirements are refined.

1. **Persistent customer storage:** add a DynamoDB repository adapter while preserving business scoping, validation and atomic per-business phone uniqueness.
2. **Manager authentication and tenant authorization:** integrate Amazon Cognito and derive trusted business access from authenticated manager identity.
3. **SMS marketing:** integrate Twilio for individual and bulk promotional SMS, consent enforcement and SMS history.
4. **Birthday campaigns:** schedule birthday promotional SMS and generate unique promotional codes.
5. **QR loyalty and visits:** add customer QR generation/scanning and visit recording with retained visit history.
6. **Rewards and vouchers:** generate a unique €10 voucher after five visits, reset progress to 0/5 without deleting historical visits, and allow each voucher to be redeemed once.
7. **History and auditing:** provide voucher history, manager/action audit history and the remaining operational history views.
8. **Cloud deployment:** evaluate AWS API Gateway, Lambda, EventBridge, and S3 with CloudFront for hosting and scheduled workflows.

DynamoDB, Cognito, Twilio, AWS deployment, QR loyalty and vouchers are future milestones. The completed implementation remains the local customer-management foundation.
