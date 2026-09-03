# Flux — LLM Credit Monitor

Standalone dashboard for real-time LLM API credit levels and Supabase user-registration alerts.

> This project is self-contained. To publish it as its own GitHub repository, copy the `llm-credit-monitor/` folder to a new repo root (or use this directory as the repo root).

## What it shows

- **OpenAI / GPT** — month-to-date spend via Admin Costs API; remaining estimated from `OPENAI_MONTHLY_BUDGET`
- **xAI / Grok** — prepaid balance via Management API
- **DeepSeek** — live `/user/balance`
- **Qwen / DashScope** — available balance + period spend from `/quotas`
- **Supabase users** — total row count + latest signup; dashboard alert when count increases

## Quick start

```bash
cd llm-credit-monitor
cp .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

With no keys configured (or `DEMO_MODE=true`), the UI runs on realistic demo data so you can validate the dashboard immediately.

## Configure live providers

Edit `.env.local`:

| Variable | Purpose |
|---|---|
| `DEMO_MODE` | `true` forces mock data; `false` uses live keys |
| `OPENAI_ADMIN_KEY` | OpenAI **Admin** API key (not a project secret key) |
| `OPENAI_MONTHLY_BUDGET` | USD budget used to compute remaining |
| `XAI_MANAGEMENT_KEY` | xAI Management API key |
| `XAI_TEAM_ID` | Optional team id (auto-resolved when omitted) |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `DASHSCOPE_API_KEY` | Alibaba Cloud Model Studio / DashScope key |
| `DASHSCOPE_BASE_URL` | Intl or China DashScope base URL |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (server-only) |
| `SUPABASE_USERS_TABLE` | Table to count (default `profiles`) |
| `LOW_BALANCE_THRESHOLD` | USD threshold for warnings (default `10`) |

## Supabase setup

1. Ensure a users/profiles table exists (default name `profiles`) with at least `id` and `created_at`. Optional `email` improves alert text.
2. Put the **service role** key in `SUPABASE_SERVICE_ROLE_KEY` (never expose it to the browser).
3. The dashboard polls `/api/monitor` every 30s. When `totalUsers` increases, a **New user registered** alert appears.

Example minimal table:

```sql
create table public.profiles (
  id uuid primary key default gen_random_uuid(),
  email text,
  created_at timestamptz not null default now()
);
```

## API

`GET /api/monitor` — JSON snapshot of all providers + user stats. Keys stay server-side.

## Notes on provider APIs

- OpenAI does **not** expose prepaid remaining balance on standard API keys. Flux uses Admin costs + your configured monthly budget.
- xAI prepaid ledger can lag live console remaining by current-cycle unposted spend.
- DeepSeek returns granted vs topped-up balance explicitly.
- DashScope `/quotas` shape varies by region/account; Flux reads `available` / `credits` / spend fields when present.

## Scripts

```bash
npm run dev      # local dashboard
npm run build    # production build
npm run start    # serve production build
npm run lint
```
