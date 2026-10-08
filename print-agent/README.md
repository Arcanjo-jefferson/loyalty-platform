# Contactly Windows Print Agent — Milestone 5D.2A

Independent outbound-only worker. **Simulation is the default. Production device
identity is not provisioned; live DynamoDB printing is deliberately blocked.**
No AWS resources, Windows tasks, drivers or printer settings are installed by this
repository. No physical output has been tested. This agent never calls visit,
raffle creation, voucher issuance or public QR endpoints.

## Windows setup and safe simulation

Use Python 3.11+ in PowerShell, from `print-agent`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe -m contactly_agent --config config.local.json --once
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Simulation reads only the local JSON fixture and writes exact UTF-8 ticket text
into `state/simulated/*.txt`, one file per immutable job identity. Re-running
preserves files without duplicating output. It does not construct HTTP transport,
import win32print, claim real jobs or acknowledge them. The example contains only
fictional test content. To inspect real snapshot rendering, an authorized manager
may separately export an approved fictional ticket into a local fixture; the
agent does not fetch production jobs in simulation. Keep snapshots and state
files private: ticket content contains customer names/phones.

## Isolated development authentication and Windows mode

The backend `/development/print-agent` transport is disabled by default. It
requires all of these process environment variables and **in-memory repository**:

- `APP_ENV=development`
- `CUSTOMER_REPOSITORY=memory`
- `PRINT_AGENT_DEV_ENABLED=true`
- `PRINT_AGENT_DEV_BUSINESS` — explicit test business binding
- `PRINT_AGENT_DEV_ID` — explicit device identity
- `PRINT_AGENT_DEV_SECRET` — independently generated random secret, at least 32 characters

Only loopback callers are accepted. DynamoDB repositories are categorically
rejected, even when enabled. The secret authenticates one configured development
device; the server supplies its business and audit identity. No submitted business
or actor is trusted. This device can list eligible jobs, claim, renew, start,
report pre-output failure or unconfirmed spool acceptance. It cannot access human
customer/media/admin APIs, reprints or completion acknowledgement. No Cognito human
token is accepted. Do not reuse an Owner password, JWT, AWS key or QR link.

On the **same Windows machine** run a separate in-memory development backend,
create fictional data through its normal authenticated visit workflow, and set
`CONTACTLY_AGENT_DEV_SECRET` in the worker environment to the matching secret.
Do not print or commit that value. Development shared-secret transport is not
production enrollment. For explicit onsite development output set:

```json
{
  "mode": "development-windows",
  "allow_development_printing": true,
  "backend_url": "http://127.0.0.1:8000/development/print-agent",
  "printer_name": "EXACT EXISTING WINDOWS QUEUE NAME",
  "poll_seconds": 3,
  "timeout_seconds": 10,
  "state_directory": "state"
}
```

Discover names without modifying configuration:

```powershell
Get-Printer | Select-Object Name, DriverName, PortName
```

Only the explicitly selected queue is opened. No default printer, driver, port or
other application's configuration is changed. RAW spool documents contain Epson
ESC/POS initialization, PC858 selection (ESC t 19), original 42-column snapshot,
feed and GS V 66 0 partial-cut request. Each job is a separate spool document and
cut request, ordered by visit timestamp then raffle, loyalty, birthday. Unsupported
characters or widths fail preflight; text is never silently truncated/replaced.
PC858 support, font width, paper width, RAW passthrough and actual cutting must be
verified for this installed Epson driver/model. Unicode raster rendering is future
work; unsupported customer names are a documented preflight limitation.

Microsoft documents RAW submission as spooler acceptance, not paper delivery:
[StartDocPrinter](https://learn.microsoft.com/windows/win32/printdocs/startdocprinter).
Cut command reference: [Epson GS V](https://download4.epson.biz/sec_pubs/pos/reference_en/escpos/gs_cv.html).

## Reliability and honest output status

Claims remain atomic, tenant-scoped and fenced by token/device/expiry. A renewal
occurs after preflight, then every 30 seconds during submission. An expired/stale
fence cannot start output. Pre-output failures use the existing maximum of three
attempts; reconnect backoff doubles up to 30 seconds. HTTP timeouts are bounded.
No auth response bodies, secrets, tokens or ticket PII appear in structured logs.
401/invalid credentials stops processing that poll; fix/rotate environment secret
and restart. No hidden human login or token-refresh shortcut exists.

SQLite (`synchronous=FULL`) writes START_INTENT before requesting PRINTING. The
agent sends no bytes unless the start response succeeds. After any started attempt,
the local job fence permanently prevents automatic output again, including crashes
between spool submission and acknowledgement. Keep this database across restarts;
do not delete it to retry. Multiple instances sharing a state directory also use
its unique job fence; separate agents rely on backend atomic claims. Explicit
manager reprints have new identities and retain original code/text with REPRINT.

Successful EndDocPrinter/complete byte acceptance reports `submitted`, transitioning
the backend to **UNCERTAIN**, with
`SPOOL_ACCEPTED_PHYSICAL_OUTPUT_UNCONFIRMED` and no `printed_at`. This conservative
policy requires operator review even for spool-accepted jobs. It never asserts
physical completion. Failed/ambiguous started output and expired PRINTING also
require review; never auto-reprint. Lost start replies can leave a local fence
without paper: inspect backend state and use an explicit audited reprint if needed.

Windows native spool APIs can block despite network HTTP timeouts; lease heartbeats
continue during submission. Ctrl+C stops future polling and waits for the current
native call. A hung native call may require operator termination; the durable fence
and expired PRINTING protect against automatic replay. Disk failures stop output.
Structured JSON logs are in `state/agent.log` and stdout. Establish log rotation,
protected file ACLs and backup of state before unattended production deployment.

## Production blocker and Task Scheduler preparation

Production requires an independently provisioned, revocable device identity with
short-lived tokens, verified issuer/audience/signature/expiry, bound business/device
claims and narrow queue scopes. Device enrollment, secure Windows credential vault,
rotation/revocation and TLS are deployment work; no resources were created here.
Production URLs/modes are rejected. Existing Cognito Owner/Manager APIs remain
unchanged. Do not enable this development transport against production or reverse
proxy it. A real DynamoDB customer cannot be printed through this release's worker.

After device auth and onsite acceptance are approved, prepare (but do not create
now) a Task Scheduler task under a dedicated least-privilege Windows account:
program absolute `.venv\Scripts\python.exe`, arguments `-m contactly_agent --config
<absolute config.local.json>`, Start in absolute `print-agent` directory, daily
startup/logon trigger, restart on failure, **do not start a new instance** policy.
Use persistent protected state and explicit queue access; no administrator role
needed. Do not use execution time limits that routinely kill active spool calls.

## Exact onsite acceptance procedure

1. Preserve existing printer/application settings; discover the current queue name.
2. Run simulation above and inspect three independent files and original codes.
3. Start the isolated memory backend with explicit device variables; never point it
   at DynamoDB. Create fictional customers/visits via normal UI to queue 1–3 jobs.
4. With staff approval and paper available, opt into development-windows and run
   `python -m contactly_agent --config config.local.json --once`.
5. Check one physical ticket/cut per job, order, € glyph, names, 42 columns and codes.
   Check existing loyalty application still prints using its unchanged settings.
6. Confirm backend jobs report UNCERTAIN/spool-accepted, not physical Printed. Inspect
   paper and spool queue before approving any additional explicit REPRINT.
7. Test offline preflight: no paper/start; reconnect only within bounded attempts.
8. Test network outage, two instances, restart after start/spool, expired fence and
   explicit manager reprint. Never delete local state or auto-retry uncertain output.
9. Stop with Ctrl+C; no startup task is installed. Record results. Production
   DynamoDB acceptance waits for dedicated device identity deployment.
