# Intellegam Sales Coaching

## Overview

A local, single-user web application that imports sales transcripts, combines them with customer context and saves structured coaching with exact source evidence and history.
Stack: **React/TypeScript + Vite, FastAPI/Pydantic, SQLite and GPT-4.1 mini**.
**Path A (native Notion Meeting Notes import) is implemented. Path B is proposed only.**
No Intellegam internal system, CRM, login, telephony or meeting bot is required.

## Demo Video



**Demo link:** (https://github.com/Spoorthy-Siddannaiah/sales_coaching/releases/download/v1.0.0/sales-coaching-demo.mov)

## Implemented Features

- Native Notion full-transcript retrieval with source IDs, raw metadata, pagination,
  bounded retries and duplicate/version detection. Ordinary Notion pages are unsupported.
- Editable company, relevant needs, previous interactions and conversation objective;
  context is persisted, passed to analysis and snapshotted with each report.
- One authorized OpenAI request, structured output, exact quotation/role validation,
  five coaching dimensions, summary, outcome, questions, next steps and improvements.
- Full mode for verified roles; limited mode with unknown salesperson scores otherwise.
  Complete attributed input requires two practical improvements with suggested wording.
- SQLite transcript/report persistence, processing states, failures and immutable history.
- React import/list/context/report workflow. Evidence opens and highlights original text
  in Transcript; prior analyses and input snapshots remain accessible through History.

## Architecture

### Path A — Notion Meeting Import (Implemented)

![Implemented Path A](docs/architecture/path-a-implemented.png)

React calls FastAPI, which retrieves authorized Notion Meeting Notes through the Notion
API. Transcript normalization preserves original content and available metadata. SQLite
stores the source; customer context feeds GPT-4.1 mini through the coaching service.
JSON schema, Pydantic and source-evidence validation gate saved reports and history.
Notion and OpenAI are external providers. Normalization does not invent roles or timestamps.

### Path B — Salesperson-first Phone Call (Proposed, Not Implemented)

![Proposed Path B](docs/architecture/path-b-proposed.png)

FastAPI would validate number authorization and the caller-ID route, call the salesperson
first and confirm availability, then call the customer. A telephony provider would create
**two outbound legs**, bridge them into a conference and record with participant consent.
Signed, deduplicated webhooks would drive call state and recording/transcription processing. No answer, cancellation, partial recordings and processing failures would be handled; stopping must account for both legs. Calls outside the supported route are not captured.

Twilio supports outbound calls and conferencing. German carrier CLIP no screening,
BYOC and SIP trunking are candidate approaches for an authorized existing German mobile
number, not a verified combined solution. Twilio IE1 does not support external Verified
Caller IDs. Verification alone does not prove carrier display: **block customer dialing
if the required caller-ID route cannot be verified**, and test the displayed number on
the receiving device. Never silently substitute another number. Path B is not implemented,
integrated or tested. Next step: approved two-handset caller-ID and two-sided-audio tests.
Source: [Twilio regional availability](https://www.twilio.com/docs/global-infrastructure/regional-product-and-feature-availability).

### Shared Analysis and Storage Pipeline

![Shared pipeline](docs/architecture/shared-pipeline.png)

Both paths would provide normalized transcripts, source metadata and reliable speaker
roles where available, then reuse the implemented coaching, GPT-4.1 mini, validation, SQLite and React reporting. Path B acquisition/transcription is future work. Diagram
labels are conditional: tested native Notion responses lacked utterance attribution.
“Clean text” means extraction, not rewriting dialogue. Missing metrics remain unknown.

## Design Decisions and Trade-offs

Path A delivers one narrow pipeline using authorized existing artifacts; phone acquisition
and German caller-ID feasibility remain bounded research. FastAPI and npm/Vite reuse the
working backend and React stack rather than introducing Next.js/Bun. SQLite and one local
async task avoid database/queue infrastructure. PostgreSQL, durable workers and deployment
are future production choices; one backend worker is required for this prototype.

Transcript versions remain separate from generated reports. Model-selected source IDs
are bound to the transcript fingerprint; Python extracts exact quotations and roles.
Invalid IDs, wrong attribution, fabricated quotations and malformed reports fail rather
than being silently repaired. These checks establish provenance, not semantic truth.
Transcript/customer-context text is untrusted data, never instructions to the model.
Scores use independent 1–5 behavioral anchors; talk-time/timing metrics are not fabricated.

Analysis returns HTTP 202, persists pending/analyzing/completed/failed and is polled by React.
Repeating the same analysis request UUID reuses its job; a deliberately new UUID creates
another report. Interrupted jobs become failed on restart without automatic paid retry.
Context/transcript changes feed new analyses; prior reports keep their original snapshots.
Changed-output behavior and restart persistence are mock-tested; no live controlled
before/after comparison is claimed.

### Ten-minute cost estimate

**US domestic pricing example**, checked 10 October 2026; not a German telephony quote or a new paid test. The assignment requests a sourced ten-minute estimate, not a
specific German tariff:

- Analysis: 5,000 input tokens including prompt/schema + 2,000 output tokens at
  $0.40/$1.60 per million = **$0.0052**. [GPT-4.1 mini pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
- US domestic callback: two 10-minute outbound legs × $0.014/min = **$0.28**;
  10-minute recording × $0.0025/min = **$0.025**. [Twilio US pricing](https://www.twilio.com/en-us/voice/pricing/us).
- Two isolated 10-minute channels × $0.003/min mini-transcribe = **$0.06**.
  [OpenAI pricing](https://platform.openai.com/pricing/).
- Illustrative total: **$0.3702**, excluding rental, storage, taxes, ringing, rounding,
  setup and carrier/BYOC charges. This is not a Germany/IE1 tariff or caller-ID guarantee.
  Destination, region, account and route pricing must be checked before real calls.

Existing Notion import needs no new transcription request; subscription/AI entitlement
is separate. Local controls default to a $5 allowance and $1 reserve and require explicit
paid authorization. They are not a provider-level cap or a record of outside spending;
configure actual remaining credit and preserve existing accounting files.

### Privacy and permissions

Use fictional or consented tests and bind the unauthenticated app to localhost. Integration
permissions and participant consent still matter; request approved test access if unavailable,
without buying services for this challenge. Never use real production customers for testing.
Credentials remain server-side. SQLite/backups contain source text, snapshots, context and
reports; the app acquires no underlying audio. Notion retains its own data. Authorized
OpenAI analysis sends text/context; provider copies depend on account retention controls.
Data remains local until deliberately removed. Stop the app before consistent deletion of
related rows or the whole database; handle backups/exports and provider copies separately.
Preserve the spending ledger. No deletion API/scheduler is built. Production requires access
control, protected storage and a formal retention policy; login is outside this exercise.

## How to Run

Prerequisites: Python 3.11+ and Node supported by Vite 7. Verified with Python 3.11.13
and Node 24.3.0. **Fresh dependency installation was not tested** during package checks.
From the project root:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp -n .env.example .env
```

Edit [.env.example](.env.example)'s local `.env` copy; preserve an existing file. Set
`NOTION_API_TOKEN`, `NOTION_VERSION=2026-03-11`, `OPENAI_API_KEY` and `LLM_PROVIDER=openai`.
Other settings include `DATABASE_PATH`, model/timeouts/token limits and ledger/budget paths.
The backend reads project-root `.env`; environment variables override it. Never commit keys. Optional Ollama needs its configured local server/model; earlier live inference timed out.

Terminal 1:

```sh
LLM_PROVIDER=openai .venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

Terminal 2, from project root:

```sh
cd frontend
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>; API docs: <http://127.0.0.1:8000/docs>.
Startup initializes SQLite automatically. The submitted source contains no local reports.

### Native Notion setup and offline fixture

A user starts native transcription or uploads approved audio in Notion, with appropriate
account entitlement/settings and consent. An integration connection does not start recording.
Create an internal connection with Read content, grant the meeting page access and configure
the token locally. Import one native page with a ready full transcript, review warnings,
then save fictional context. Revoking access stops new imports, not local report reading.
Source: [Notion prerequisites](https://www.notion.com/help/ai-meeting-notes) and
[Meeting Notes API](https://developers.notion.com/reference/block#meeting-notes).

Choose **Load offline demo** for `kapibala-sim:mstate:S46_standard`, a licensed synthetic
OmniSupport conversation with source-defined a=salesperson/b=customer roles, no timestamps.
[Attribution/CC BY 4.0](backend/tests/fixtures/external/ATTRIBUTION.md) and the original
[dataset card](backend/tests/fixtures/external/dataset-card.md) are included. Original message
content/order is preserved, including one upstream merged message. Edit/save context, then
explicitly authorize one paid analysis. Imports/reading are free; OpenAI generation is not.
There is no automatic paid retry/repair. Historical live-evaluation scripts invoke providers;
do not run them as setup commands. The rejected synthetic test report is a regression fixture.

## Testing and Limitations

```sh
.venv/bin/python -m pytest backend/tests -c backend/pytest.ini
cd frontend
npm run typecheck
npm run build
node tests/evidence-navigation.mjs
node tests/api-errors.mjs
```

**256 backend tests passed**; frontend typecheck/build passed. Tests use temporary storage and mocked providers, never real paid calls. Extracted
package verification reuses installed dependencies, not a fresh install. Browser acceptance
was previously tested using mocked providers, covering import, reports, evidence navigation,
history, errors and mobile layout. These checks do not verify live provider integrations.

Native Notion transcript retrieval and persistence were verified. However, the tested transcript did not provide reliable speaker attribution, so full salesperson scoring could not be validated. Complete scored reports were successfully demonstrated using an attributed synthetic fixture.
Block and Markdown responses matched all 31 paragraphs, without truncation; neither
exposed verified utterance timestamps. API agreement does not prove universal UI completeness.
An accepted native limited report has not been demonstrated; unavailable roles require
null salesperson scores. This limitation does not affect the verified fixture workflow.

Coaching accepts 80–16,000 characters; longer imports remain complete in storage and analysis
rejects them before paid calls, without truncation. Scores, question inventories, commitments
and recommendations remain model judgments. Exact evidence does not guarantee score
calibration, correct commitment interpretation or independent certification. Next work: accepted native limited coaching and live quality review,
then longer-transcript handling and production safeguards. No additional source or phone
integration is claimed.

## Development Time and AI Usage

Development time (candidate estimate, not independently audited): Approximately **8–9 hours** of active development, including architecture,
implementation, debugging, testing and documentation; this estimate may exceed the eight-hour
challenge timebox. OpenAI Codex assisted implementation, review, debugging, test generation,
mocked browser acceptance and explanations. Architectural decisions, integration boundaries,
evidence-validation requirements and final verification were reviewed and directed by the developer.
