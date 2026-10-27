# Serverless preparation — Milestone 6.1, phase 1

This is application compatibility work, **not a deployable production stack**.
No AWS infrastructure, scheduler, resource provisioning or deployment is included.
Real SMS delivery remains disabled. Existing customer, reward, raffle, print and
media behaviour is unchanged.

## Entry points

From `backend/`, local development is unchanged:

```sh
./venv/bin/python -m pip install -r requirements.txt
./venv/bin/python -m uvicorn main:app --reload
```

`main:app` creates the local ASGI application from `app.application.create_app`.
Uvicorn lifespan starts the existing SMS simulation worker and stops it on shutdown.
Keep lifespan enabled for local automatic simulation. Importing the module alone
constructs services but does not start a thread.

The future Lambda handler setting is:

```text
lambda_function.handler
```

The deployment package root must contain `lambda_function.py` and `app/`.
Mangum 0.22.0, pinned in requirements.txt, translates API Gateway HTTP API payload
format 2.0 requests to ASGI. The application and adapter initialize at module import
and are reused on warm invocations. The handler does not trust API Gateway claims
as a replacement for the existing backend Cognito bearer verification.

`lambda_function.py` imports the shared factory directly; it does not import or
construct the local `main.app`. It explicitly uses `start_sms_worker=False` and
Mangum `lifespan='off'`. The disabled factory flag also prevents SMS worker startup
if a future caller enters that app's lifespan explicitly. The flag is server-side
application construction, not a request parameter or authentication override.

Existing SMS routes can register an authenticated business in the worker's
in-memory notification set, but no background thread runs in the Lambda API app.
Confirmed campaigns remain durably queued. The existing authorized manual
simulation endpoint is unchanged. **Automatic scheduled processing is not yet
implemented**; do not present this phase as production-ready SMS processing.

## Packaging and future configuration

- Build dependencies for the selected Linux Lambda Python runtime/architecture.
  Do not copy macOS `venv/`: Pillow, cryptography and pydantic-core include native
  components. Validate ZIP size; an image package remains a future alternative.
- Package application source and installed requirements only. Exclude `.env`, AWS
  profiles/credentials, local configuration, virtual environments, tests, test-data
  scripts, caches and Git metadata. No packaging or deployment automation is added.
- Use an execution IAM role, not permanent keys or the local `loyalty-dev` profile.
- Explicitly select `CUSTOMER_REPOSITORY=dynamodb` and separate production table,
  private-media bucket and Cognito configuration. The existing memory default is
  retained for local compatibility; production startup validation is still pending.
- Keep `SMS_PROVIDER=simulation`, `SMS_REAL_DELIVERY_ENABLED=false` and no live SMS
  event bindings. No incoming provider webhook routes are introduced.
- Preserve bearer headers, paths and JSON responses. A root custom-domain mapping
  or HTTP API `$default` stage avoids adding a prefix to `/print-agent` URLs.
- CORS currently allows only localhost. Exact production-origin configuration,
  IAM policies, API throttles, concurrency limits, TLS and custom domains are later
  phases. Do not expose this initial configuration as a finished production API.

## Known limits and remaining work

1. Replace local worker lifecycle notifications with bounded scheduled Lambda
   processing, preserving outbox, consent, budget, idempotency and UNKNOWN rules.
2. Resolve 5 MiB private image transport against Lambda's buffered payload limits
   and binary encoding overhead. This phase does not reduce limits or redesign
   uploads/downloads, and does not claim full-size images work through Lambda.
3. Bound print/SMS history polling and device heartbeat writes without changing
   physical output fences or immutable tickets. Windows integration is untouched.
4. Add production environment validation and resource isolation, CORS, timeouts,
   API response-size controls and cold-start/native-dependency benchmarks.
5. Prepare reviewed infrastructure definitions for private frontend S3/CloudFront,
   HTTP API/Lambda, scheduled processing, DNS/TLS, monitoring and backups.
6. Verify deployment using fictional data before approved live acceptance. Do not
   copy development customers, print jobs or media automatically into production.

`/health` remains the existing liveness response, not a dependency-readiness check.
The $6–20/month target remains a planning estimate, not a verified deployment cost.

## Offline verification

From `backend/`:

```sh
./venv/bin/python -m pytest tests/test_lambda.py tests/test_sms_worker.py -q
./venv/bin/python -m pytest tests -q
./venv/bin/python -m compileall -q app main.py lambda_function.py scripts
```

Tests use synthetic HTTP API events, injected identity verifiers and local
repositories; no AWS, real messages or physical printer jobs are required.
The tests exercise the installed Mangum adapter rather than mocking translation.
They cover initialization, warm requests, base64 request decoding, authentication,
role/tenant denial, durable queuing without automatic dispatch, explicit Lambda
lifespan protection and local Uvicorn import/startup compatibility.

Adapter references: [Mangum](https://mangum.fastapiexpert.com/adapter/) and
[lifespan configuration](https://mangum.fastapiexpert.com/lifespan/).
