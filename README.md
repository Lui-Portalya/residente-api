# Residente API

Python 3.12 / FastAPI API over the existing Residente SQLite database (`data/residente.db`). No schema changes:
sessions, passwords (`scrypt$salt$hash`), charges, payments and reservations are read and written exactly as the
Next.js web app does, so both can share one database. Money is integer cents; dates are community-local `YYYY-MM-DDTHH:mm`.

## Run
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload      # docs at http://localhost:8000/docs
.venv/bin/python -m pytest                   # tests run on a temp copy of the database
```
Env: `DATABASE_PATH` (default `./data/residente.db`), `CORS_ORIGINS` (comma-separated, optional).

## Endpoints (`/api/v1`, `Authorization: Bearer <token>`)
| Area | Endpoint |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Resident | `GET /resident/dashboard`, `/resident/charges`, `/resident/payments` (read-only) |
| Reservations | `GET /resident/areas`, `GET /resident/areas/{id}/availability?from=&days=`, `GET/POST /resident/reservations`, `POST /resident/reservations/{id}/cancel` |
| Admin | `GET /admin/dashboard` |
| Payment review | `GET /admin/payments?status=`, `GET /admin/payments/{id}`, `POST /admin/payments/{id}/confirm`, `POST /admin/payments/{id}/reject` |

Seed users: `admin/admin123`, `resident/resident123`, `neighbour/neighbour123`, `gate/gate123` (gate can sign in but has no endpoints yet).

Notes: login locks out after 5 failures in 15 min (per email + IP). Confirming a payment also issues its receipt
(`R-00001`…) and writes audit rows; staff sign-ins and failed sign-ins are audited like in the web app.
