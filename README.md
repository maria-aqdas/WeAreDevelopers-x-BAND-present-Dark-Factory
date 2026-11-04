# 👑 Aurum Reserve                     

**A smart reservation command center with a concurrency-safe booking engine.**

Aurum Reserve is a restaurant reservation management application built with **Python, Streamlit, and SQLite**. It demonstrates how to prevent double-bookings when multiple requests attempt to reserve the same table at the same time.

🔗 **[Live Demo](https://aurum reserve.streamlit.app)** · 💻 **[Source Code](https://github.com/maria-aqdas/aurum-reserve)**

<!-- Add a screenshot or GIF of the Kill Demo here -->
<!-- ![Aurum Reserve Screenshot](docs/screenshot.png) -->

---

## 🎯 Why This Project Exists

Imagine two customers trying to book the last available table at exactly the same time. If the system checks availability before saving either reservation, both customers might receive a confirmation.

This problem is known as a **race condition**.

Aurum Reserve demonstrates how database transactions, overlap checks, and idempotency keys can help prevent duplicate or conflicting reservations. Its built-in **Kill Demo** and **Integrity Lab** allow users to test the booking engine directly.

## ✨ Features

| Feature | Description |
|---|---|
| 🪑 **Floor Command** | View restaurant tables with Ready/Occupied status, filter by zone, and add or remove tables. |
| 📅 **Smart Booking** | Assign the smallest available table that can accommodate the party. |
| ⚡ **Kill Demo** | Launch 2 to 50 concurrent threads against a single table and inspect the booking results. |
| 🧪 **Integrity Lab** | Test overlapping reservations, duplicate retries, oversized parties, and concurrent booking attempts. |
| 📒 **Reservation Ledger** | Browse reservation history, cancel bookings, export CSV files, and view guests-per-day charts. |
| 🗃️ **SQL Console** | Inspect the database using read-only `SELECT` queries. |
| 🌍 **Multi-Venue Support** | Manage multiple venues with separate timezones while storing timestamps in UTC. |

## ⚙️ How the Booking Engine Works

Aurum Reserve uses several techniques to protect reservation integrity.

### 1. 🔒 Database Transactions

SQLite's `BEGIN IMMEDIATE` starts a write transaction and acquires the write reservation before the availability check. This serializes competing writers, preventing them from simultaneously executing the critical check-and-insert sequence.

### 2. ⏱️ Reservation Overlap Detection

A table is available for a requested time interval only if no confirmed reservation overlaps with it.

For a requested interval `[s, e)`, an existing reservation conflicts when:

```python
existing_start < requested_end and existing_end > requested_start
```

The half-open interval allows one reservation to end exactly when the next begins, without treating them as overlapping.

### 3. 🔁 Idempotency Keys

Each booking request carries a unique idempotency key. If a client retries the same request, such as after a network timeout, the engine can return the original reservation instead of creating a duplicate.

### 4. 🌐 UTC-Based Timezone Handling

All timestamps are stored in UTC and converted to each venue's local timezone for display. This helps maintain consistent reservation times across venues in different timezones.

### 5. 📖 Write-Ahead Logging (WAL)

SQLite's WAL mode allows readers to continue reading a consistent database snapshot while a writer is active, subject to SQLite's locking and checkpointing rules.

### 📌 Booking Result Codes

| Code | Meaning |
|---|---|
| `201` | Reservation created successfully |
| `200` | Duplicate request returned the existing reservation |
| `409` | No suitable table is available for the requested time |

## 🛠️ Tech Stack

- **Python 3.9+**: Application logic and booking engine
- **Streamlit**: Interactive web interface
- **SQLite**: Database storage and transaction management
- **pandas**: Data tables, CSV exports, and charts
- **zoneinfo**: Timezone conversion
- **tzdata**: Timezone database support where required

## 🚀 Getting Started

Follow these steps to run Aurum Reserve locally.

### 1. Clone the repository

```bash
git clone https://github.com/your-username/aurum-reserve.git
cd aurum-reserve
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the application

```bash
streamlit run aurum_reserve.py
```

The application initializes the SQLite database (`aurum.db`) and demo venues on first run, as implemented in the project.

### 📦 Requirements

Your `requirements.txt` should contain:

```text
streamlit
pandas
tzdata
```

## 📁 Project Structure

```text
aurum-reserve/
├── aurum_reserve.py     # Database, booking engine, and UI
├── requirements.txt    # Python dependencies
├── README.md           # Project documentation
└── .streamlit/
    └── config.toml      # Optional Streamlit theme configuration
```

## ☁️ Deploying to Streamlit Community Cloud

1. Push your project to GitHub.
2. Visit [Streamlit Community Cloud](https://share.streamlit.io/) and sign in with GitHub.
3. Click **Create app** and select your repository and branch.
4. Set the main application file to `aurum_reserve.py`.
5. Click **Deploy**.

**Important:** Streamlit Community Cloud's local filesystem should not be treated as permanent database storage. Use persistent external storage if reservations must survive app restarts and redeployments.

## 🧪 How to Test the Booking Guarantees

You can verify the booking engine using the app's built-in tools.

### Test 1: Run the Kill Demo

1. Open the **Kill Demo** tab.
2. Select 50 concurrent requests.
3. Click **Fire**.
4. Inspect the results.

For a test where all 50 requests compete for the same exclusive time slot and table, the expected outcome is one successful creation (`201`) and 49 rejected requests (`409`), assuming no pre-existing reservation or other condition changes the outcome.

### Test 2: Run the Integrity Lab

1. Open the **Integrity Lab** tab.
2. Click **Run all integrity checks**.
3. Review the results for overlap detection, idempotent retries, oversized parties, and concurrent requests.

### Test 3: Check for Overlapping Reservations

Open the **SQL Console** and run:

```sql
SELECT COUNT(*)
FROM reservations a
JOIN reservations b
  ON a.table_id = b.table_id
 AND a.id < b.id
WHERE a.status = 'confirmed'
  AND b.status = 'confirmed'
  AND a.start_utc < b.end_utc
  AND a.end_utc > b.start_utc;
```

A result of `0` means the query found no overlapping confirmed reservations for the same table in the current database.

## ⚠️ Known Limitations

- **Temporary cloud storage:** The SQLite database may reset when the hosted app restarts or is redeployed.
- **Single-writer architecture:** SQLite serializes writes. It is suitable for this demonstration and many small applications, but a high-traffic production service may benefit from PostgreSQL.
- **Fixed booking duration:** Reservations use a 90-minute duration by default, configurable through the `book()` call.
- **No authentication:** Anyone with access to the app can create or cancel reservations.
- **Deployment considerations:** Concurrent database access, persistence, and scaling should be evaluated before using the application for real restaurant bookings.

## 🗺️ Future Improvements

- [ ] Migrate to PostgreSQL with appropriate constraints or locking for reservation conflicts.
- [ ] Add authentication and role-based permissions for hosts and managers.
- [ ] Support configurable booking durations and restaurant opening hours.
- [ ] Build an automated test suite using `pytest`.
- [ ] Add a waitlist for fully booked time slots.
- [ ] Introduce persistent production-ready database hosting.

## 📚 What I Learned

Building Aurum Reserve helped explore several important software engineering concepts:

- 🔒 Why check-then-insert logic can fail under concurrent requests.
- 🔁 How idempotency keys help make request retries safe.
- 🕒 Why storing timestamps in UTC simplifies timezone handling.
- 🧪 How concurrent tests can help validate database integrity.
- 🗃️ How SQLite transactions and WAL mode support reliable data access.

## 📄 License

This project is licensed under the **MIT License**. You can use and modify it according to the terms of the license.

---

### 👩‍💻 Author

**Maria Aqdas**

🔗 [LinkedIn](https://linkedin.com/in/maria-aqdas-ds) · [GitHub](https://github.com/maria-aqdas)

