# SentinelPay

Trust every transaction.

## Current status

The repository includes a Next.js App Router dashboard, FastAPI service, PostgreSQL/Redis configuration, merchant authentication, merchant settings, payment request APIs, and a public checkout page. The checkout can connect to an injected wallet and read its network, but it does not send funds. The escrow contract and lifecycle tests are authored but have not been compiled or run because Hardhat/OpenZeppelin could not be installed in this environment. AI assessment, on-chain event monitoring, settlement authorization service, WebSockets, email verification, password reset, and live deployment remain incomplete. No managed service or testnet deployment has been performed.

## Local API

Requires Python 3.12+, PostgreSQL, and Redis. From the repository root:

```powershell
Copy-Item .env.example .env
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

The API listens on `http://localhost:8000`. `GET /health/live` checks that the process responds; `GET /health/ready` checks PostgreSQL and Redis and returns HTTP 503 if either dependency is unavailable. The readiness check intentionally does not report simulated dependency success.

Start PostgreSQL, Redis, and the backend with Docker Compose:

```powershell
docker compose up --build postgres redis backend
```

In a second terminal, start the frontend:

```powershell
Copy-Item apps/web/.env.example apps/web/.env.local
npm run dev --prefix apps/web
```

Open `http://localhost:3000`. To build and run the current local stack in containers, use `docker compose up --build`. Local Compose credentials are for development only. Payment settlement remains disabled until the contract and event monitor have been validated.

Frontend dependencies are locked in `apps/web/package-lock.json`. The scaffold and checked-in TypeScript source use strict TypeScript settings.

## Environment configuration

| Variable | Purpose | Production value |
| --- | --- | --- |
| `APP_ENV` | Runtime environment | `production` |
| `APP_NAME` | FastAPI title | `SentinelPay API` |
| `API_BASE_URL` | Public API origin for clients | Railway public HTTPS URL |
| `CORS_ORIGINS` | Comma-separated allowed browser origins | Exact frontend HTTPS origin(s), no wildcard |
| `DATABASE_URL` | Managed PostgreSQL connection | Railway PostgreSQL `DATABASE_URL` reference |
| `REDIS_URL` | Managed Redis connection | Railway Redis `REDIS_URL` reference |
| `EVM_RPC_URL` | Selected EVM network RPC endpoint | Sepolia RPC URL from your provider |
| `EVM_CHAIN_ID` | EVM network ID | `11155111` for Sepolia |
| `ESCROW_CONTRACT_ADDRESS` | Deployed escrow address | Set after verified deployment |
| `JWT_SECRET` | Access-token signing key | Random secret, at least 32 characters |
| `JWT_REFRESH_SECRET` | Refresh-token signing key | A different random secret, at least 32 characters |

Do not commit `.env`, `.env.local`, provider credentials, wallet private keys, or signing secrets. The API does not need a deployer private key; contract deployment should be run separately from a controlled deployment environment. Separate current-stack templates are provided at `backend/.env.example` and `apps/web/.env.example`.

## Merchant authentication (Phase 2)

The API now supports merchant registration, login, refresh-token rotation, logout, current-user lookup, merchant profile updates, and per-merchant risk/settlement settings. Passwords are Argon2-hashed. Access and refresh JWTs are set as separate HttpOnly cookies; refresh token identifiers are hashed in PostgreSQL and rotated on each refresh. Production startup rejects missing, reused, or development-only JWT signing secrets. Browser mutation requests with an `Origin` header are restricted to configured `CORS_ORIGINS`.

Apply the initial identity/settings schema from `backend/` after PostgreSQL is available:

```powershell
alembic upgrade head
```

The API routes are under `/api/v1/auth` and `/api/v1/merchants`. Registration creates a merchant and conservative default settings; it does not verify email ownership or wallet control yet. Set `APP_ENV=production` and separate strong `JWT_SECRET` and `JWT_REFRESH_SECRET` values before production use.

Run the auth and payment integration tests from the repository root with:

```powershell
backend/.venv/Scripts/python -m pytest backend/tests -q
```

## Payment requests (Phase 3)

Authenticated merchants can create, list, inspect, and cancel payment requests through `/api/v1/payments`. A public checkout summary is available at `/api/v1/payments/checkout/{reference}` using an unguessable reference. Requests are limited to the configured chain and native `ETH`. The checkout can request a MetaMask account and show the wallet network; deposit and settlement controls remain disabled until escrow deployment and monitoring are verified.

## Database migrations

Run migrations from `backend/` with the production `DATABASE_URL` available in the environment:

```powershell
alembic upgrade head
```

After adding SQLAlchemy models under `app/` and importing their metadata from `migrations/env.py`, create a revision with:

```powershell
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

The current revision chain is `0001_identity` then `0002_payments`. Review every migration before applying it to production. Run migrations as a release/deploy step, not independently in every web worker. These migrations have not been applied to a live PostgreSQL database.

## Railway production setup

1. Create a Railway project and add managed PostgreSQL and Redis services.
2. Deploy this repository as a service. Railway uses the root `railway.json` and `backend/Dockerfile`.
3. Configure the API service variables using Railway service references for `DATABASE_URL` and `REDIS_URL`; set `APP_ENV=production`, `API_BASE_URL`, and exact `CORS_ORIGINS`.
4. Configure the frontend origin only after the frontend is deployed. Keep browser origins explicit; do not use `*` with credentials.
5. Apply Alembic migrations from a controlled release step before routing production traffic.
6. Confirm Railway's `/health/live` health check and manually verify `/health/ready` after database and Redis references are connected.

The production image is built with:

```powershell
docker build -f backend/Dockerfile -t sentinelpay-api .
docker run --env-file .env -p 8000:8000 sentinelpay-api
```

## Escrow contract status

`contracts/contracts/SentinelEscrow.sol` contains native ETH and allowlisted ERC-20 escrow, risk holds, an EIP-712 release authorization, refund/expiry paths, and pause controls. `contracts/test/SentinelEscrow.test.ts` covers the intended lifecycle/security cases. **The contract is not verified yet:** Hardhat/OpenZeppelin installation stalled, so compilation and tests have not run. Do not deploy or use it for real funds until compilation, all tests, and an independent security review pass.

After npm registry access is available, from `contracts/`:

```powershell
npm install
Copy-Item .env.example .env
npm run compile
npm test
npm run deploy:sepolia
```

Set `RPC_URL`, `DEPLOYER_PRIVATE_KEY`, and `AUTHORIZER_ADDRESS` in the local contract environment. The deploy script rejects networks other than Sepolia. Only after a verified deployment should `ESCROW_CONTRACT_ADDRESS` and `EVM_RPC_URL` be configured for the backend and `NEXT_PUBLIC_ESCROW_ADDRESS` for the frontend. A funded Sepolia deployer and RPC credentials are required; neither is present here.