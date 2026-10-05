"""
AURUM RESERVE - Reservation Command Center
------------------------------------------
Offline SQLite engine with atomic bookings (BEGIN IMMEDIATE), idempotency keys,
a live concurrency arena, and a real integrity lab (no fake status badges).

Run:  streamlit run aurum_reserve.py
"""
import sqlite3
import threading
import uuid
import random
import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

APP_NAME = "Aurum Reserve"
DB = "aurum.db"
UTC = ZoneInfo("UTC")
FMT = "%Y-%m-%dT%H:%M:%S"
ARENA_NAME = "The Chef's Counter (Arena)"

ZONE_ICONS = {
    "Drive-Thru": "🚗", "Counter": "🛎️", "Kiosks": "📱",
    "Delivery": "🛵", "VIP": "🥂", "Main Floor": "🍽️",
}


# ============================================================ Database layer
def conn():
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    c = conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS restaurants(
            id INTEGER PRIMARY KEY, name TEXT UNIQUE, tz TEXT);
        CREATE TABLE IF NOT EXISTS tables_(
            id INTEGER PRIMARY KEY, restaurant_id INTEGER, label TEXT, seats INTEGER,
            zone TEXT DEFAULT 'Main Floor', code TEXT);
        CREATE TABLE IF NOT EXISTS reservations(
            id INTEGER PRIMARY KEY, table_id INTEGER, guest TEXT, phone TEXT, party INTEGER,
            start_utc TEXT, end_utc TEXT, status TEXT DEFAULT 'confirmed',
            idem_key TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """
    )
    if c.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0] == 0:
        seed = {
            "L'Étoile Noire & Grand Gastronomy": ("America/New_York", [
                ("Drive-Thru Lane 1", 4, "Drive-Thru", "DT-01"),
                ("Drive-Thru Lane 2", 4, "Drive-Thru", "DT-02"),
                ("Front Counter A", 2, "Counter", "FC-101"),
                ("Front Counter B", 2, "Counter", "FC-102"),
                ("Self-Order Kiosk Alpha", 1, "Kiosks", "KS-01"),
                ("Self-Order Kiosk Beta", 1, "Kiosks", "KS-02"),
                ("Dispatch Hub 1", 6, "Delivery", "DL-201"),
                ("Executive Lounge", 8, "VIP", "VIP-01"),
            ]),
            ARENA_NAME: ("America/New_York", [("The Sole Table", 2, "VIP", "CHEF-01")]),
            "Lahore Bites": ("Asia/Karachi", [
                ("Garden 1", 2, "Main Floor", "LHR-01"),
                ("Garden 2", 4, "Main Floor", "LHR-02"),
                ("Rooftop 1", 6, "VIP", "LHR-03"),
            ]),
        }
        for name, (tz, items) in seed.items():
            rid = c.execute("INSERT INTO restaurants(name,tz) VALUES(?,?)", (name, tz)).lastrowid
            for label, seats, zone, code in items:
                c.execute(
                    "INSERT INTO tables_(restaurant_id,label,seats,zone,code) VALUES(?,?,?,?,?)",
                    (rid, label, seats, zone, code),
                )
    c.close()


def to_utc(tz_name, date_val, time_val):
    local = dt.datetime.combine(date_val, time_val).replace(tzinfo=ZoneInfo(tz_name))
    return local.astimezone(UTC)


def book(restaurant_id, guest, party, start_utc, minutes=90, idem_key=None, phone=""):
    """Atomic booking. Returns (http_code, status, reservation_id, table_label)."""
    idem_key = idem_key or str(uuid.uuid4())
    end_utc = start_utc + dt.timedelta(minutes=minutes)
    s, e = start_utc.strftime(FMT), end_utc.strftime(FMT)
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")  # takes the write lock up front -> no race window
        prev = c.execute(
            "SELECT r.id, t.label FROM reservations r JOIN tables_ t ON t.id=r.table_id "
            "WHERE r.idem_key=?", (idem_key,)).fetchone()
        if prev:
            c.execute("COMMIT")
            return 200, "duplicate_retry", prev["id"], prev["label"]

        tables = c.execute(
            "SELECT id, label FROM tables_ WHERE restaurant_id=? AND seats>=? "
            "ORDER BY seats ASC, id ASC", (restaurant_id, party)).fetchall()
        for t in tables:
            clash = c.execute(
                "SELECT 1 FROM reservations WHERE table_id=? AND status='confirmed' "
                "AND start_utc<? AND end_utc>?", (t["id"], e, s)).fetchone()
            if not clash:
                rid = c.execute(
                    "INSERT INTO reservations(table_id,guest,phone,party,start_utc,end_utc,idem_key) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (t["id"], guest, phone, party, s, e, idem_key)).lastrowid
                c.execute("COMMIT")
                return 201, "confirmed", rid, t["label"]
        c.execute("ROLLBACK")
        return 409, "no_table", None, None
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()


def cancel_reservation(rid):
    c = conn()
    c.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (rid,))
    c.close()


def list_reservations(restaurant_id):
    c = conn()
    rows = c.execute(
        """SELECT r.id, t.label AS station, t.code, t.zone, r.guest, r.phone, r.party,
                  r.start_utc, r.end_utc, r.status, r.created_at
           FROM reservations r JOIN tables_ t ON t.id=r.table_id
           WHERE t.restaurant_id=? ORDER BY r.start_utc DESC""", (restaurant_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_tables(restaurant_id):
    c = conn()
    rows = c.execute("SELECT * FROM tables_ WHERE restaurant_id=? ORDER BY id", (restaurant_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_station(restaurant_id, code, name, seats, zone):
    c = conn()
    c.execute("INSERT INTO tables_(restaurant_id,label,seats,zone,code) VALUES(?,?,?,?,?)",
              (restaurant_id, name, seats, zone, code))
    c.close()


def delete_table(table_id):
    c = conn()
    c.execute("DELETE FROM tables_ WHERE id=?", (table_id,))
    c.close()


def audit_overlaps():
    c = conn()
    n = c.execute(
        """SELECT COUNT(*) FROM reservations a JOIN reservations b
           ON a.table_id=b.table_id AND a.id<b.id
           WHERE a.status='confirmed' AND b.status='confirmed'
           AND a.start_utc<b.end_utc AND a.end_utc>b.start_utc""").fetchone()[0]
    c.close()
    return n


def run_race(restaurant_id, n_racers):
    """Fire n threads at the same instant, all wanting the same slot."""
    target = dt.datetime.now(UTC) + dt.timedelta(days=random.randint(10, 400),
                                                 minutes=random.randint(0, 1000))
    barrier = threading.Barrier(n_racers)
    log, lock = [], threading.Lock()

    def worker(i):
        barrier.wait()
        token = f"racer-{uuid.uuid4()}"
        code, status, rid, tbl = book(restaurant_id, f"Racer-{i:02d}", 1, target, 60, token)
        with lock:
            log.append({"racer": f"Racer-{i:02d}", "http": code, "outcome": status,
                        "reservation": rid, "table": tbl})

    threads = [threading.Thread(target=worker, args=(i + 1,)) for i in range(n_racers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return log


# ============================================================ UI helpers
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Playfair+Display:wght@600;700&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; }
.stApp { background: radial-gradient(1200px 600px at 10% -10%, #2a1b4d 0%, transparent 60%),
                     radial-gradient(1000px 500px at 100% 0%, #3b2a10 0%, transparent 55%), #0a0b12; color: #e8e9f0; }
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
.block-container { padding-top: 1.4rem; max-width: 1400px; }
section[data-testid="stSidebar"] { background: #0d0e17; border-right: 1px solid #23253a; }

.hero { position: relative; overflow: hidden; border-radius: 22px; padding: 30px 34px; margin-bottom: 22px;
        background: linear-gradient(120deg, rgba(212,175,55,.16), rgba(124,92,255,.18) 55%, rgba(34,211,238,.10));
        border: 1px solid rgba(255,255,255,.10); box-shadow: 0 20px 60px rgba(0,0,0,.45); }
.hero:after { content:""; position:absolute; inset:-40% -10% auto auto; width:420px; height:420px;
              background: radial-gradient(circle, rgba(212,175,55,.25), transparent 65%); filter: blur(10px); }
.hero h1 { font-family:'Playfair Display',serif; font-size:40px; margin:0; letter-spacing:.5px;
           background: linear-gradient(90deg,#f6e27a,#d4af37 40%,#fff 100%); -webkit-background-clip:text; color:transparent; }
.hero .sub { color:#a9acc6; font-size:13px; letter-spacing:2.5px; text-transform:uppercase; margin-top:6px; }
.pill { display:inline-block; padding:5px 12px; border-radius:999px; font-size:12px; font-weight:600; margin:12px 8px 0 0;
        background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.12); color:#d9dbef; }
.pill.live:before { content:""; display:inline-block; width:8px; height:8px; border-radius:50%; background:#22c55e;
                    margin-right:7px; box-shadow:0 0 0 0 rgba(34,197,94,.7); animation:pulse 1.8s infinite; }
@keyframes pulse { 70% { box-shadow:0 0 0 9px rgba(34,197,94,0);} 100% { box-shadow:0 0 0 0 rgba(34,197,94,0);} }

.kpi { background:linear-gradient(160deg,rgba(255,255,255,.07),rgba(255,255,255,.02)); border:1px solid rgba(255,255,255,.09);
       border-radius:18px; padding:18px 20px; backdrop-filter: blur(8px); transition:.25s; }
.kpi:hover { transform:translateY(-3px); border-color:rgba(212,175,55,.5); }
.kpi .lbl { color:#9a9dbb; font-size:11px; letter-spacing:1.8px; font-weight:700; }
.kpi .val { font-size:34px; font-weight:800; margin-top:4px; color:#fff; }
.kpi .ico { float:right; font-size:22px; opacity:.85; }

.card { background:linear-gradient(160deg,rgba(255,255,255,.06),rgba(255,255,255,.015)); border:1px solid rgba(255,255,255,.09);
        border-radius:16px; padding:16px; margin-bottom:8px; transition:.25s; }
.card:hover { transform:translateY(-3px); box-shadow:0 12px 30px rgba(0,0,0,.45); border-color:rgba(124,92,255,.55); }
.card h4 { margin:10px 0 2px; color:#fff; font-size:15px; }
.card .meta { color:#8f93b3; font-size:11px; font-weight:600; letter-spacing:1.2px; }
.card .foot { display:flex; justify-content:space-between; margin-top:12px; font-size:12px; color:#b7bad3; }
.badge { font-size:10.5px; font-weight:800; padding:3px 9px; border-radius:999px; letter-spacing:.8px; }
.ready { background:rgba(34,197,94,.14); color:#4ade80; border:1px solid rgba(34,197,94,.4); }
.busy  { background:rgba(239,68,68,.14); color:#f87171; border:1px solid rgba(239,68,68,.4); }

.stat { border-radius:16px; padding:20px; text-align:center; border:1px solid rgba(255,255,255,.1); }
.stat .n { font-size:46px; font-weight:800; line-height:1; }
.stat .t { font-size:11px; letter-spacing:2px; font-weight:700; margin-top:6px; color:#c4c7de; }
.verdict { border-radius:14px; padding:16px 20px; border:1px solid rgba(34,197,94,.5);
           background:linear-gradient(90deg,rgba(34,197,94,.14),transparent); color:#86efac; font-weight:600; }
.arena { border-radius:18px; padding:26px; border:1px solid rgba(212,175,55,.35);
         background:linear-gradient(135deg,rgba(212,175,55,.12),rgba(124,92,255,.08)); }
.arena h2 { font-family:'Playfair Display',serif; margin:0 0 6px; color:#f6e27a; font-size:30px; }

.stTabs [data-baseweb="tab-list"] { gap:6px; background:rgba(255,255,255,.04); padding:6px; border-radius:14px; }
.stTabs [data-baseweb="tab"] { border-radius:10px; padding:9px 16px; color:#a9acc6; font-weight:600; }
.stTabs [aria-selected="true"] { background:linear-gradient(90deg,#d4af37,#b8892b); color:#10101a !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
div.stButton > button, div[data-testid="stFormSubmitButton"] > button { border-radius:12px; font-weight:700; border:1px solid rgba(255,255,255,.15); }
div.stButton > button[kind="primary"], div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background:linear-gradient(90deg,#d4af37,#f0cf63); color:#14141f; border:none; }
div[data-testid="stForm"] { border:1px solid rgba(255,255,255,.1); border-radius:16px; background:rgba(255,255,255,.03); }
</style>
"""


def kpi(col, label, value, icon):
    col.markdown(f'<div class="kpi"><span class="ico">{icon}</span><div class="lbl">{label}</div>'
                 f'<div class="val">{value}</div></div>', unsafe_allow_html=True)


def stat(col, n, text, color, bg):
    col.markdown(f'<div class="stat" style="background:{bg}"><div class="n" style="color:{color}">{n}</div>'
                 f'<div class="t">{text}</div></div>', unsafe_allow_html=True)


def localize(df, tz):
    """Show UTC timestamps in the venue's own timezone."""
    for col in ("start_utc", "end_utc"):
        df[col.replace("_utc", "_local")] = (
            pd.to_datetime(df[col]).dt.tz_localize("UTC").dt.tz_convert(tz).dt.strftime("%d %b %Y, %H:%M"))
    return df.drop(columns=["start_utc", "end_utc"])


# ============================================================ Main UI
def run_ui():
    st.set_page_config(page_title=f"{APP_NAME} · Command Center", page_icon="👑", layout="wide")
    init_db()
    st.markdown(CSS, unsafe_allow_html=True)

    c = conn()
    rests = {r["name"]: dict(r) for r in c.execute("SELECT * FROM restaurants").fetchall()}
    c.close()

    st.sidebar.markdown("### 👑 Aurum Reserve")
    st.sidebar.caption("Reservation Command Center")
    name = st.sidebar.selectbox("Venue", list(rests))
    venue = rests[name]
    st.sidebar.divider()
    st.sidebar.caption("Engine: SQLite · WAL · BEGIN IMMEDIATE")

    tables = get_tables(venue["id"])
    all_res = list_reservations(venue["id"])
    active = [r for r in all_res if r["status"] == "confirmed"]
    now_iso = dt.datetime.now(UTC).strftime(FMT)
    busy_now = {r["station"] for r in active if r["start_utc"] <= now_iso < r["end_utc"]}
    util = len(busy_now) / len(tables) * 100 if tables else 0.0
    upcoming = [r for r in active if r["start_utc"] >= now_iso]

    # ---- Hero
    st.markdown(f"""
    <div class="hero">
      <h1>{venue['name']}</h1>
      <div class="sub">Aurum Reserve · Reservation Command Center</div>
      <span class="pill live">Live · Atomic Engine</span>
      <span class="pill">🌍 {venue['tz']}</span>
      <span class="pill">🛡️ Zero double-bookings guaranteed</span>
    </div>""", unsafe_allow_html=True)

    k = st.columns(4)
    kpi(k[0], "STATIONS", len(tables), "🏛️")
    kpi(k[1], "LIVE UTILIZATION", f"{util:.0f}%", "⚡")
    kpi(k[2], "UPCOMING BOOKINGS", len(upcoming), "📅")
    kpi(k[3], "GUESTS EXPECTED", sum(r["party"] for r in upcoming), "👥")
    st.write("")

    tabs = st.tabs(["🏢 Floor Command", "🎯 Kill Demo", "🧪 Integrity Lab", "📑 Ledger", "🔍 SQL Console"])

    # ---------------- Floor Command
    with tabs[0]:
        left, right = st.columns([1.7, 1])
        with left:
            zones = ["All"] + sorted({t["zone"] for t in tables})
            zf = st.radio("Zone", zones, horizontal=True, label_visibility="collapsed")
            shown = tables if zf == "All" else [t for t in tables if t["zone"] == zf]
            grid = st.columns(3)
            for i, t in enumerate(shown):
                is_busy = t["label"] in busy_now
                with grid[i % 3]:
                    st.markdown(f"""
                    <div class="card">
                      <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="font-size:24px">{ZONE_ICONS.get(t['zone'], '🍽️')}</span>
                        <span class="badge {'busy' if is_busy else 'ready'}">{'OCCUPIED' if is_busy else 'READY'}</span>
                      </div>
                      <h4>{t['label']}</h4>
                      <div class="meta">{t['zone'].upper()}</div>
                      <div class="foot"><span>Code <b>{t['code']}</b></span><span>👥 <b>{t['seats']}</b> seats</span></div>
                    </div>""", unsafe_allow_html=True)
                    if st.button("Remove", key=f"del_{t['id']}", use_container_width=True):
                        delete_table(t["id"])
                        st.rerun()
            if not shown:
                st.info("No stations in this zone yet.")

        with right:
            st.markdown("#### ✨ New Reservation")
            with st.form("book_form"):
                guest = st.text_input("Guest name", placeholder="e.g. Ayesha Khan")
                phone = st.text_input("Phone", placeholder="+92-300-0000000")
                party = st.number_input("Party size", 1, 50, 2)
                d = st.date_input("Date", dt.date.today())
                tm = st.time_input("Time", dt.time(19, 0))
                if st.form_submit_button("Reserve best-fit table", type="primary", use_container_width=True):
                    if not guest.strip():
                        st.error("Please enter a guest name.")
                    else:
                        code, _, rid, tbl = book(venue["id"], guest.strip(), int(party),
                                                 to_utc(venue["tz"], d, tm), 90, phone=phone.strip())
                        if code == 201:
                            st.success(f"Confirmed on **{tbl}** · Ref #{rid}")
                            st.balloons()
                        else:
                            st.error("No table is free for that party size and time.")

            st.markdown("#### ➕ Register Station")
            with st.form("station_form"):
                code_in = st.text_input("Code", "APX-03")
                name_in = st.text_input("Name", "Express Counter 3")
                zone_in = st.selectbox("Zone", list(ZONE_ICONS))
                seats_in = st.number_input("Seats", 1, 20, 4)
                if st.form_submit_button("Add station", use_container_width=True):
                    add_station(venue["id"], code_in, name_in, int(seats_in), zone_in)
                    st.rerun()

    # ---------------- Kill Demo
    with tabs[1]:
        st.markdown("""<div class="arena"><h2>The Kill Demo</h2>
        One table. N racers. The same instant. Every thread fights for the same slot —
        the database lets exactly one win and answers the rest with a clean <b>409 Conflict</b>.</div>""",
                    unsafe_allow_html=True)
        st.write("")
        arena = next((r for r in rests.values() if r["name"] == ARENA_NAME), venue)
        a1, a2 = st.columns([1, 2])
        with a1:
            n = st.select_slider("Racers", [2, 8, 12, 24, 50], value=24)
            fire = st.button(f"▶  Fire {n} concurrent bookers", type="primary", use_container_width=True)
            st.caption(f"Arena venue: {arena['name']}")
        if fire:
            with st.spinner("Releasing the barrier..."):
                log = run_race(arena["id"], n)
            created = [r for r in log if r["http"] == 201]
            rejected = [r for r in log if r["http"] == 409]
            other = len(log) - len(created) - len(rejected)
            s = st.columns(3)
            stat(s[0], len(created), "201 CREATED", "#4ade80", "rgba(34,197,94,.10)")
            stat(s[1], len(rejected), "409 REJECTED", "#f87171", "rgba(239,68,68,.10)")
            stat(s[2], other, "OTHER", "#94a3b8", "rgba(148,163,184,.08)")
            st.write("")
            overlaps = audit_overlaps()
            ok = len(created) == 1 and overlaps == 0
            st.markdown(f'<div class="verdict">{"PASS" if ok else "FAIL"} — {len(created)}×201, '
                        f'{len(rejected)}×409, overlaps in database: {overlaps}.</div>', unsafe_allow_html=True)
            for r in created:  # keep the ledger clean between runs
                cancel_reservation(r["reservation"])
            st.write("")
            st.dataframe(pd.DataFrame(log).sort_values("http"), use_container_width=True, hide_index=True)

    # ---------------- Integrity Lab (real checks, computed live)
    with tabs[2]:
        st.markdown("#### 🧪 Integrity Lab")
        st.caption("These checks run against the real database right now. Nothing here is hard-coded.")
        if st.button("Run all integrity checks", type="primary"):
            results = []
            overlaps = audit_overlaps()
            results.append(("Zero overlapping confirmed bookings", overlaps == 0, f"{overlaps} overlaps found"))

            t0 = dt.datetime.now(UTC) + dt.timedelta(days=700, minutes=random.randint(0, 5000))
            key = f"idem-{uuid.uuid4()}"
            c1, _, id1, _ = book(venue["id"], "Idem Test", 1, t0, 30, key)
            c2, st2, id2, _ = book(venue["id"], "Idem Test", 1, t0, 30, key)
            results.append(("Idempotent retry returns same reservation",
                            c1 == 201 and c2 == 200 and id1 == id2, f"first={c1}, retry={c2} ({st2})"))
            if id1:
                cancel_reservation(id1)

            max_seats = max((t["seats"] for t in tables), default=0)
            c3, _, _, _ = book(venue["id"], "Too Big", max_seats + 1, t0, 30)
            results.append(("Oversized party is rejected", c3 == 409, f"returned {c3}"))

            log = run_race(arena["id"], 12)
            wins = [r for r in log if r["http"] == 201]
            results.append(("12-thread race has exactly one winner", len(wins) == 1, f"{len(wins)} winners"))
            for r in wins:
                cancel_reservation(r["reservation"])
            results.append(("Still zero overlaps after the race", audit_overlaps() == 0, "re-audited"))

            for label, passed, detail in results:
                st.markdown(f"{'✅' if passed else '❌'} **{label}** — <span style='color:#9a9dbb'>{detail}</span>",
                            unsafe_allow_html=True)
            if all(p for _, p, _ in results):
                st.markdown('<div class="verdict">All invariants hold.</div>', unsafe_allow_html=True)

    # ---------------- Ledger
    with tabs[3]:
        st.markdown("#### 📑 Operations Ledger")
        if all_res:
            df = localize(pd.DataFrame(all_res), venue["tz"])
            fcol, _ = st.columns([1, 2])
            status = fcol.selectbox("Status", ["all", "confirmed", "cancelled"])
            view = df if status == "all" else df[df["status"] == status]
            st.dataframe(view, use_container_width=True, hide_index=True)

            conf = pd.DataFrame(active)
            if not conf.empty:
                conf["day"] = pd.to_datetime(conf["start_utc"]).dt.date
                st.markdown("##### Guests per day")
                st.bar_chart(conf.groupby("day")["party"].sum(), color="#d4af37")

            cc1, cc2 = st.columns([1, 1])
            cancel_id = cc1.selectbox("Cancel a reservation", [r["id"] for r in active] or [None])
            if cc1.button("Cancel selected") and cancel_id:
                cancel_reservation(cancel_id)
                st.rerun()
            cc2.download_button("📥 Export CSV", df.to_csv(index=False).encode(), "aurum_ledger.csv", "text/csv")
        else:
            st.info("No reservations yet. Create one from Floor Command.")

    # ---------------- SQL Console (read-only)
    with tabs[4]:
        st.markdown("#### 🔍 SQL Console (read-only)")
        sql = st.text_area("Query", "SELECT id, label, seats, zone FROM tables_ LIMIT 20;", height=110)
        if st.button("Run query"):
            if not sql.strip().lower().startswith("select"):
                st.error("Only SELECT statements are allowed here.")
            else:
                try:
                    cx = conn()
                    rows = [dict(r) for r in cx.execute(sql).fetchall()]
                    cx.close()
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                except Exception as ex:
                    st.error(f"Execution error: {ex}")


if __name__ == "__main__":
    run_ui()
else:
    run_ui()
