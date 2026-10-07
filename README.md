# 👑 Aurum Reserve

**A reservation command center with a concurrency-safe booking engine.**
Built with Streamlit and SQLite. Guarantees zero double-bookings, even when dozens of requests hit the same table at the same instant.

**[Live Demo](https://your-app-name.streamlit.app)** · **[Source Code](https://github.com/your-username/aurum-reserve)**

<!-- Add a screenshot or GIF of the Kill Demo here -->
<!-- ![Aurum Reserve screenshot](docs/screenshot.png) -->

---

## Why this project exists

Booking systems have a classic bug: two people try to reserve the last table at the same moment, both checks pass, and both bookings are saved. This is a **race condition**.

Aurum Reserve demonstrates a clean solution and **proves it live** inside the app, instead of just claiming it works.

## Features

| Area | What it does |
|---|---|
| **Floor Command** | Live station grid with Ready/Occupied status, zone filters, and add/remove stations |
| **Smart Booking** | Assigns the smallest table that fits the party, so large tables are not wasted |
| **Kill Demo** | Fires 2 to 50 concurrent threads at a single table and shows exactly one winner (`201`) and the rest rejected (`409`) |
| **Integrity Lab** | Runs real checks against the database: overlap audit, idempotent retry, oversized party rejection, and a concurrency race |
| **Ledger** | Filterable reservation history in each venue's local timezone, cancellation, CSV export, and a guests-per-day chart |
| **SQL Console** | Read-only `SELECT` queries for inspecting the database |
| **Multi-venue and timezones** | Each venue has its own timezone; all times are stored in UTC |

## How the booking engine works

1. **`BEGIN IMMEDIATE`** takes SQLite's write lock at the start of the transaction. Two bookers can never be inside the "check, then insert" section at the same time, which removes the race window.
2. **Overlap check:** a table is free for a new booking `[s, e)` only if no confirmed booking satisfies `start < e AND end > s`.
3. **Idempotency keys:** every booking carries a unique key. If a client retries the same request (for example after a network timeout), the engine returns the original reservation (`200`) instead of creating a duplicate.
4. **UTC storage:** all timestamps are stored in UTC and converted to the venue's timezone only for display.
5. **WAL mode** lets reads continue while a write is in progress.

Result codes: `201` created, `200` duplicate retry (same reservation returned), `409` no table available.

## Tech stack

- **Python 3.9+** (uses `zoneinfo`)
- **Streamlit** for the UI
- **SQLite** (WAL mode) for storage
- **pandas** for tables, exports, and charts

## Getting started

```bash
# 1. Clone
git clone https://github.com/your-username/aurum-reserve.git
cd aurum-reserve

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
streamlit run aurum_reserve.py
```

The database (`aurum.db`) and the demo venues are created automatically on first run.

### `requirements.txt`

```
streamlit
pandas
tzdata
```

## Project structure

```
aurum-reserve/
├── aurum_reserve.py     # Database layer, booking engine, and UI
├── requirements.txt
├── README.md
└── .streamlit/
    └── config.toml      # Optional: forces the dark theme
```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **Create app**, select the repo and branch, and set the main file to `aurum_reserve.py`.
4. Click **Deploy**.

## How to verify the guarantees yourself

1. Open the **Kill Demo** tab, select **50** racers, and click Fire. Expect `1 × 201` and `49 × 409`.
2. Open the **Integrity Lab** tab and click **Run all integrity checks**. All checks should pass.
3. Open the **SQL Console** and run:
   ```sql
   SELECT COUNT(*) FROM reservations a JOIN reservations b
   ON a.table_id=b.table_id AND a.id<b.id
   WHERE a.status='confirmed' AND b.status='confirmed'
   AND a.start_utc<b.end_utc AND a.end_utc>b.start_utc;
   ```
   The result should be `0`.

## Known limitations

- **Ephemeral storage on Streamlit Community Cloud:** the SQLite file resets when the app restarts, so demo data does not persist between restarts.
- **Single-writer database:** SQLite serializes writes. This is perfect for a demo and small venues, but a high-traffic production system would need a server database.
- **Bookings use a fixed 90-minute duration** (configurable in the `book()` call).
- **No authentication:** anyone with the link can create or cancel reservations.

## Roadmap

- [ ] Move to PostgreSQL (row-level locking or an exclusion constraint on time ranges)
- [ ] User authentication and roles (host, manager)
- [ ] Configurable booking duration and opening hours
- [ ] Automated test suite with `pytest`
- [ ] Waitlist when a slot is full

## What I learned

- Why check-then-insert logic is unsafe without a lock or constraint
- How idempotency keys make retries safe
- Handling timezones correctly by storing UTC and converting at the edge
- Verifying concurrency claims with real multi-threaded tests

## License

MIT. Free to use and modify.

---

Built by **Your Name** · [LinkedIn](https://linkedin.com/in/your-profile) · [GitHub](https://github.com/your-username)
