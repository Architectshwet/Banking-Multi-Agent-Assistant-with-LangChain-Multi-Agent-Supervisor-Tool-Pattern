# Banking Multi-Agent Assistant with LangChain Multi-Agent Supervisor Tool Pattern

This project is a digital banking assistant built with the LangChain multi-agent supervisor pattern.
The `BankingSupervisor` is the main user-facing agent with custom tools: `authentication`, `account_agent_tool`, and `payments_agent_tool`.
The supervisor uses parent-thread checkpointing, while `account_agent_tool` and `payments_agent_tool` are tool-wrapped sub-agents with isolated specialist checkpoints for account and payments domains.
It supports authentication workflows, account workflows (profile, balances, transactions, cards), and payment workflows (saved payees, fund transfer, bill payment) with multi-turn memory and streaming responses.

## Features

- Single supervisor agent with custom tools for authentication and domain delegation.
- The single supervisor uses a parent-thread checkpointer, while two custom tools are tool-wrapped sub-agents with isolated specialist checkpointing: `account_agent_tool` and `payments_agent_tool`.
- Supervisor handles flow/routing; sub-agents handle domain reasoning and internal tool calls.
- Two specialist agents:
  - `AccountAgent`: profile, account details, transactions, card portfolio.
  - `PaymentsAgent`: saved payees, fund transfer flow, bill payments.
- SSE streaming chat API (`/chat/stream`) plus built-in web UI (`/web`).
- PostgreSQL-backed checkpoint persistence for conversation memory.
- Session store persistence by parent thread (optionally mirrored to PostgreSQL).
- Automatic schema setup and demo data seed during startup.

## Architecture

1. `BankingSupervisor` is the single user-facing orchestrator.
2. For domain requests, supervisor calls specialist tools that internally invoke sub-agents.
3. Specialist tools act as the contract boundary between orchestration and domain logic.
4. Checkpoint isolation is implemented with specialist thread IDs:
   - Account specialist: `<parent_thread_id>:account`
   - Payments specialist: `<parent_thread_id>:payments`
5. Shared session context (for example `customer_id`) is read via `parent_thread_id`.

This design keeps specialist memory isolated while preserving shared session variables for the full conversation.

## Use Cases

- Authenticated digital banking assistant across account and payments domains.
- Profile inquiries (name/email/phone/segment/relationship) and account balance lookups.
- Recent transaction and spending-history follow-ups in multi-turn conversations.
- Card portfolio checks (status, limits, due details, card metadata).
- Saved-payee exploration plus guided fund-transfer execution.
- Bill payment creation with account, biller, amount, and category capture.
- End-to-end supervisor-driven banking assistant with isolated specialist memory and shared session context.

## API Endpoints

- `GET /health` - service health.
- `GET /admin/data-summary` - demo table row counts.
- `POST /chat/stream` - streaming chat endpoint (SSE).
- `GET /web` - browser test UI.

## Run (Docker)

1. Create environment file:

```bash
cp .env.example .env
```

2. Set required values in `.env`:
   - `OPENAI_API_KEY`
   - `POSTGRESQL_URL`
   - Optional: `LANGFUSE_*`, `ENABLE_SESSION_SYNC`, `BANKING_DEFAULT_CUSTOMER_ID`

3. Start dev stack:

```bash
docker-compose -f docker-compose.dev.yml up --build
```

4. Access:
   - Web UI: `http://localhost:8000/web`
   - Health: `http://localhost:8000/health`
   - Data summary: `http://localhost:8000/admin/data-summary`

## Docker Lifecycle

```bash
docker-compose -f docker-compose.dev.yml down
docker-compose -f docker-compose.dev.yml up
docker-compose -f docker-compose.dev.yml up --build
docker-compose -f docker-compose.dev.yml down -v
```
