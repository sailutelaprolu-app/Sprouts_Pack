"""
Your Sprouts - sprout packet delivery management.

Three levels:
  * Administrator  - creates vendors
  * Vendors        - create customers, set price per packet, record deliveries, track payments
  * Customers      - record packets received, see monthly statement, send requests

Everything lives in one flat folder (no sub-folders), as requested.
"""
import hashlib
import os
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)

from translations import TEXT

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "sprouts.db"))
IST = timezone(timedelta(hours=5, minutes=30))
APP_NAME = "Your Sprouts"

# Only these files may be downloaded from the folder (so app.py and the database stay private).
PUBLIC_FILES = {"style.css", "app.js", "icon-192.png", "icon-512.png", "favicon.png"}



def compute_version():
    """A fingerprint of all app files. It changes automatically whenever you upload new files,
    which makes installed phones show the 'New version available' message."""
    h = hashlib.sha256()
    for name in sorted(os.listdir(HERE)):
        if name.endswith((".py", ".html", ".css", ".js", ".json", ".png")):
            with open(os.path.join(HERE, name), "rb") as f:
                h.update(name.encode() + f.read())
    return h.hexdigest()[:10]


APP_VERSION = compute_version()

app = Flask(__name__, template_folder=HERE, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or "dev-only-change-me",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") is not None,
)


# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, mobile TEXT,
    secret_hash TEXT UNIQUE NOT NULL, active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY, vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    name TEXT NOT NULL, mobile TEXT, email TEXT,
    secret_hash TEXT UNIQUE NOT NULL, active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
    paise INTEGER NOT NULL, effective_from TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS price_changes (
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
    old_paise INTEGER, new_paise INTEGER NOT NULL, effective_from TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', created_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS entries (
    customer_id INTEGER NOT NULL REFERENCES customers(id), day TEXT NOT NULL,
    cust_packets INTEGER, cust_comment TEXT, cust_at TEXT,
    vendor_packets INTEGER, vendor_at TEXT,
    PRIMARY KEY (customer_id, day));
CREATE TABLE IF NOT EXISTS payments (
    customer_id INTEGER NOT NULL REFERENCES customers(id), month TEXT NOT NULL,
    paid INTEGER DEFAULT 0, paid_on TEXT, PRIMARY KEY (customer_id, month));
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
    text TEXT NOT NULL, status TEXT DEFAULT 'open', reply TEXT,
    created_at TEXT, closed_at TEXT);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, at TEXT, role TEXT, actor_id INTEGER, actor_name TEXT,
    vendor_id INTEGER, action TEXT, details TEXT);
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    env_secret = os.environ.get("ADMIN_SECRET", "").strip()
    if env_secret:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('admin_hash', ?)",
                     (hash_secret(env_secret),))
    elif not conn.execute("SELECT 1 FROM settings WHERE key='admin_hash'").fetchone():
        new_id = make_secret(conn) + make_secret(conn)  # administrator's own ID stays longer for safety
        conn.execute("INSERT INTO settings VALUES ('admin_hash', ?)", (hash_secret(new_id),))
        print("=" * 50, flush=True)
        print(f"  ADMINISTRATOR SECRET ID: {new_id}", flush=True)
        print("  Write this down. It is shown only once.", flush=True)
        print("=" * 50, flush=True)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- helpers
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I to avoid confusion


SECRET_LENGTH = 5  # Secret IDs for vendors and customers are 5 characters, e.g. K7MP2


def make_secret(conn=None):
    """Make a new random Secret ID that nobody else is using."""
    conn = conn or db()
    while True:
        new_id = "".join(secrets.choice(ALPHABET) for _ in range(SECRET_LENGTH))
        h = hash_secret(new_id)
        taken = (conn.execute("SELECT 1 FROM vendors WHERE secret_hash=?", (h,)).fetchone()
                 or conn.execute("SELECT 1 FROM customers WHERE secret_hash=?", (h,)).fetchone()
                 or conn.execute("SELECT 1 FROM settings WHERE key='admin_hash' AND value=?", (h,)).fetchone())
        if not taken:
            return new_id


def clean_secret(value):
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def hash_secret(value):
    return hashlib.sha256(clean_secret(value).encode()).hexdigest()


def now_ist():
    return datetime.now(IST)


def today():
    return now_ist().date()


def stamp():
    return now_ist().strftime("%Y-%m-%d %H:%M")


def parse_day(value, default=None):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def parse_month(value):
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
    except (TypeError, ValueError):
        return today().strftime("%Y-%m")


def month_days(month):
    first = datetime.strptime(month, "%Y-%m").date()
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, nxt - timedelta(days=1)


def to_paise(value):
    try:
        rupees = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    if rupees <= 0 or rupees > 100000:
        return None
    return int(round(rupees * 100))


def rupees(paise):
    """Format paise as Indian rupees, e.g. 123456 -> '₹1,234.56'."""
    paise = int(paise or 0)
    whole, frac = divmod(abs(paise), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{s}.{frac:02d}"


def audit(action, details="", vendor_id=None):
    role = session.get("role")
    actor_id = session.get("uid")
    if vendor_id is None:
        vendor_id = session.get("vendor_id")
    db().execute(
        "INSERT INTO audit (at, role, actor_id, actor_name, vendor_id, action, details) "
        "VALUES (?,?,?,?,?,?,?)",
        (stamp(), role, actor_id, session.get("name"), vendor_id, action, details))


def price_on(customer_id, day_str):
    row = db().execute(
        "SELECT paise FROM prices WHERE customer_id=? AND effective_from<=? "
        "ORDER BY effective_from DESC, id DESC LIMIT 1", (customer_id, day_str)).fetchone()
    return row["paise"] if row else 0


def current_price(customer_id):
    return price_on(customer_id, today().isoformat())


def billed(entry):
    """Packets that count for the bill: the customer's count, or the vendor's if the customer did not enter."""
    if entry["cust_packets"] is not None:
        return entry["cust_packets"]
    return entry["vendor_packets"] or 0


def entry_status(entry):
    c, v = entry["cust_packets"], entry["vendor_packets"]
    if c is None and v is None:
        return "none"
    if c is None:
        return "vendor_only"
    if v is None:
        return "customer_only"
    return "match" if c == v else "mismatch"


def month_statement(customer_id, month):
    first, last = month_days(month)
    rows = db().execute(
        "SELECT * FROM entries WHERE customer_id=? AND day BETWEEN ? AND ? ORDER BY day",
        (customer_id, first.isoformat(), last.isoformat())).fetchall()
    lines, total_packets, total_paise, mismatches = [], 0, 0, 0
    for r in rows:
        packets = billed(r)
        price = price_on(customer_id, r["day"])
        amount = packets * price
        status = entry_status(r)
        mismatches += status == "mismatch"
        total_packets += packets
        total_paise += amount
        lines.append({"day": r["day"], "cust": r["cust_packets"], "vendor": r["vendor_packets"],
                      "comment": r["cust_comment"], "packets": packets, "price": price,
                      "amount": amount, "status": status})
    pay = db().execute("SELECT * FROM payments WHERE customer_id=? AND month=?",
                       (customer_id, month)).fetchone()
    return {"lines": lines, "packets": total_packets, "amount": total_paise,
            "mismatches": mismatches, "paid": bool(pay and pay["paid"]),
            "paid_on": pay["paid_on"] if pay else None}


def month_is_paid(customer_id, day_str):
    row = db().execute("SELECT paid FROM payments WHERE customer_id=? AND month=?",
                       (customer_id, day_str[:7])).fetchone()
    return bool(row and row["paid"])


# ---------------------------------------------------------------- language
def lang():
    code = request.cookies.get("lang") or session.get("lang")
    return code if code in ("en", "te") else None


def t(key, **kwargs):
    entry = TEXT.get(key)
    if entry is None:
        return key
    text = entry.get(lang() or "en") or entry["en"]
    return text.format(**kwargs) if kwargs else text


@app.context_processor
def inject():
    return {"t": t, "lang": lang() or "en", "rupees": rupees, "APP_NAME": APP_NAME,
            "role": session.get("role"), "me": session.get("name"),
            "csrf": csrf_token(), "today": today().isoformat(), "version": APP_VERSION}


@app.route("/lang/<code>")
def set_lang(code):
    if code not in ("en", "te"):
        abort(404)
    target = request.args.get("next") or url_for("home")
    if not target.startswith("/"):
        target = url_for("home")
    resp = redirect(target)
    resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


# ---------------------------------------------------------------- security
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def guard():
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            abort(400)
    # make sure a logged-in user is still active
    role, uid = session.get("role"), session.get("uid")
    if role == "vendor":
        row = db().execute("SELECT active FROM vendors WHERE id=?", (uid,)).fetchone()
        if not row or not row["active"]:
            session.clear()
    elif role == "customer":
        row = db().execute(
            "SELECT c.active, v.active AS vactive FROM customers c JOIN vendors v ON v.id=c.vendor_id "
            "WHERE c.id=?", (uid,)).fetchone()
        if not row or not row["active"] or not row["vactive"]:
            session.clear()


def login_required(role):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                return redirect(url_for("login"))
            return fn(*args, **kwargs)
        return wrapper
    return deco


FAILED = {}  # ip -> list of failure times


def too_many_attempts(ip):
    recent = [x for x in FAILED.get(ip, []) if time.time() - x < 900]
    FAILED[ip] = recent
    return len(recent) >= 10


# ---------------------------------------------------------------- public pages
@app.route("/")
def home():
    if not lang():
        return render_template("language.html")
    role = session.get("role")
    if role == "admin":
        return redirect(url_for("admin_home"))
    if role == "vendor":
        return redirect(url_for("vendor_daily"))
    if role == "customer":
        return redirect(url_for("customer_home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not lang():
        return render_template("language.html")
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]
        if too_many_attempts(ip):
            flash(t("too_many_attempts"), "error")
            return render_template("login.html")
        h = hash_secret(request.form.get("secret"))
        conn = db()
        admin = conn.execute("SELECT 1 FROM settings WHERE key='admin_hash' AND value=?", (h,)).fetchone()
        vendor = conn.execute("SELECT * FROM vendors WHERE secret_hash=?", (h,)).fetchone()
        cust = conn.execute(
            "SELECT c.*, v.active AS vactive, v.name AS vname FROM customers c "
            "JOIN vendors v ON v.id=c.vendor_id WHERE c.secret_hash=?", (h,)).fetchone()
        keep_csrf = session.get("csrf")
        session.clear()
        session["csrf"] = keep_csrf
        session.permanent = True
        if admin:
            session.update(role="admin", uid=0, name=t("administrator"))
            return redirect(url_for("admin_home"))
        if vendor and vendor["active"]:
            session.update(role="vendor", uid=vendor["id"], vendor_id=vendor["id"], name=vendor["name"])
            return redirect(url_for("vendor_daily"))
        if cust and cust["active"] and cust["vactive"]:
            session.update(role="customer", uid=cust["id"], vendor_id=cust["vendor_id"], name=cust["name"])
            return redirect(url_for("customer_home"))
        FAILED.setdefault(ip, []).append(time.time())
        if vendor or cust:
            flash(t("account_inactive"), "error")
        else:
            flash(t("wrong_secret"), "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- administrator
@app.route("/admin")
@login_required("admin")
def admin_home():
    vendors = db().execute(
        "SELECT v.*, (SELECT COUNT(*) FROM customers c WHERE c.vendor_id=v.id AND c.active=1) AS ncust "
        "FROM vendors v ORDER BY v.active DESC, v.name").fetchall()
    return render_template("admin.html", vendors=vendors)


@app.route("/admin/vendor/add", methods=["POST"])
@login_required("admin")
def admin_add_vendor():
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    if not name:
        flash(t("name_required"), "error")
        return redirect(url_for("admin_home"))
    secret = make_secret()
    conn = db()
    cur = conn.execute("INSERT INTO vendors (name, mobile, secret_hash, created_at) VALUES (?,?,?,?)",
                       (name, mobile, hash_secret(secret), stamp()))
    audit("vendor_added", f"{name} ({mobile})", vendor_id=cur.lastrowid)
    conn.commit()
    return render_template("secret.html", who=name, secret=secret, back=url_for("admin_home"))


@app.route("/admin/vendor/<int:vid>/edit", methods=["POST"])
@login_required("admin")
def admin_edit_vendor(vid):
    conn = db()
    v = conn.execute("SELECT * FROM vendors WHERE id=?", (vid,)).fetchone() or abort(404)
    name = request.form.get("name", "").strip() or v["name"]
    mobile = request.form.get("mobile", "").strip()
    conn.execute("UPDATE vendors SET name=?, mobile=? WHERE id=?", (name, mobile, vid))
    audit("vendor_edited", f"{name} ({mobile})", vendor_id=vid)
    conn.commit()
    flash(t("saved"), "ok")
    return redirect(url_for("admin_home"))


@app.route("/admin/vendor/<int:vid>/reset", methods=["POST"])
@login_required("admin")
def admin_reset_vendor(vid):
    conn = db()
    v = conn.execute("SELECT * FROM vendors WHERE id=?", (vid,)).fetchone() or abort(404)
    secret = make_secret()
    conn.execute("UPDATE vendors SET secret_hash=? WHERE id=?", (hash_secret(secret), vid))
    audit("vendor_secret_reset", v["name"], vendor_id=vid)
    conn.commit()
    return render_template("secret.html", who=v["name"], secret=secret, back=url_for("admin_home"))


@app.route("/admin/vendor/<int:vid>/toggle", methods=["POST"])
@login_required("admin")
def admin_toggle_vendor(vid):
    conn = db()
    v = conn.execute("SELECT * FROM vendors WHERE id=?", (vid,)).fetchone() or abort(404)
    new = 0 if v["active"] else 1
    conn.execute("UPDATE vendors SET active=? WHERE id=?", (new, vid))
    audit("vendor_activated" if new else "vendor_deactivated", v["name"], vendor_id=vid)
    conn.commit()
    return redirect(url_for("admin_home"))


@app.route("/admin/audit")
@login_required("admin")
def admin_audit():
    vid = request.args.get("vendor", type=int)
    sql = "SELECT a.*, v.name AS vname FROM audit a LEFT JOIN vendors v ON v.id=a.vendor_id"
    args = ()
    if vid:
        sql += " WHERE a.vendor_id=?"
        args = (vid,)
    rows = db().execute(sql + " ORDER BY a.id DESC LIMIT 300", args).fetchall()
    vendors = db().execute("SELECT id, name FROM vendors ORDER BY name").fetchall()
    return render_template("audit.html", rows=rows, vendors=vendors, vid=vid)


# ---------------------------------------------------------------- vendor
def own_customer(cid):
    row = db().execute("SELECT * FROM customers WHERE id=? AND vendor_id=?",
                       (cid, session["uid"])).fetchone()
    if not row:
        abort(404)
    return row


def counts_for_badges():
    vid = session.get("uid")
    conn = db()
    open_req = conn.execute(
        "SELECT COUNT(*) FROM requests r JOIN customers c ON c.id=r.customer_id "
        "WHERE c.vendor_id=? AND r.status='open'", (vid,)).fetchone()[0]
    return {"open_requests": open_req}


@app.route("/vendor")
@login_required("vendor")
def vendor_daily():
    day = parse_day(request.args.get("day"), today())
    if day > today():
        day = today()
    ds = day.isoformat()
    conn = db()
    customers = conn.execute(
        "SELECT * FROM customers WHERE vendor_id=? AND active=1 ORDER BY name", (session["uid"],)).fetchall()
    rows, tot_packets, tot_amount = [], 0, 0
    for c in customers:
        e = conn.execute("SELECT * FROM entries WHERE customer_id=? AND day=?", (c["id"], ds)).fetchone()
        e = e or {"cust_packets": None, "vendor_packets": None, "cust_comment": None}
        packets = billed(e)
        price = price_on(c["id"], ds)
        tot_packets += packets
        tot_amount += packets * price
        rows.append({"c": c, "e": e, "status": entry_status(e), "packets": packets,
                     "amount": packets * price, "locked": month_is_paid(c["id"], ds)})
    return render_template("vendor_daily.html", day=ds, rows=rows, tot_packets=tot_packets,
                           tot_amount=tot_amount, prev=(day - timedelta(days=1)).isoformat(),
                           next=(day + timedelta(days=1)).isoformat() if day < today() else None,
                           **counts_for_badges())


@app.route("/vendor/deliveries", methods=["POST"])
@login_required("vendor")
def vendor_save_deliveries():
    day = parse_day(request.form.get("day"))
    if not day or day > today():
        abort(400)
    ds = day.isoformat()
    conn = db()
    changed = 0
    for c in conn.execute("SELECT id, name FROM customers WHERE vendor_id=? AND active=1",
                          (session["uid"],)).fetchall():
        raw = request.form.get(f"p{c['id']}", "").strip()
        if raw == "" or month_is_paid(c["id"], ds):
            continue
        if not raw.isdigit() or int(raw) > 999:
            continue
        val = int(raw)
        old = conn.execute("SELECT vendor_packets FROM entries WHERE customer_id=? AND day=?",
                           (c["id"], ds)).fetchone()
        if old and old["vendor_packets"] == val:
            continue
        conn.execute(
            "INSERT INTO entries (customer_id, day, vendor_packets, vendor_at) VALUES (?,?,?,?) "
            "ON CONFLICT(customer_id, day) DO UPDATE SET vendor_packets=excluded.vendor_packets, "
            "vendor_at=excluded.vendor_at", (c["id"], ds, val, stamp()))
        audit("vendor_delivery", f"{c['name']}: {ds} = {val}")
        changed += 1
    conn.commit()
    flash(t("deliveries_saved", n=changed), "ok")
    return redirect(url_for("vendor_daily", day=ds))


@app.route("/vendor/customers")
@login_required("vendor")
def vendor_customers():
    conn = db()
    rows = conn.execute("SELECT * FROM customers WHERE vendor_id=? ORDER BY active DESC, name",
                        (session["uid"],)).fetchall()
    customers = [{"c": c, "price": current_price(c["id"]),
                  "pending": conn.execute("SELECT 1 FROM price_changes WHERE customer_id=? AND status='pending'",
                                          (c["id"],)).fetchone() is not None} for c in rows]
    return render_template("vendor_customers.html", customers=customers, **counts_for_badges())


@app.route("/vendor/customers/add", methods=["POST"])
@login_required("vendor")
def vendor_add_customer():
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    paise = to_paise(request.form.get("price"))
    if not name:
        flash(t("name_required"), "error")
        return redirect(url_for("vendor_customers"))
    if paise is None:
        flash(t("price_invalid"), "error")
        return redirect(url_for("vendor_customers"))
    secret = make_secret()
    conn = db()
    cur = conn.execute(
        "INSERT INTO customers (vendor_id, name, mobile, secret_hash, created_at) VALUES (?,?,?,?,?)",
        (session["uid"], name, mobile, hash_secret(secret), stamp()))
    conn.execute("INSERT INTO prices (customer_id, paise, effective_from) VALUES (?,?,?)",
                 (cur.lastrowid, paise, "2000-01-01"))
    audit("customer_added", f"{name} @ {rupees(paise)}/packet")
    conn.commit()
    return render_template("secret.html", who=name, secret=secret, back=url_for("vendor_customers"))


@app.route("/vendor/customer/<int:cid>")
@login_required("vendor")
def vendor_customer(cid):
    c = own_customer(cid)
    conn = db()
    prices = conn.execute("SELECT * FROM prices WHERE customer_id=? ORDER BY effective_from DESC, id DESC",
                          (cid,)).fetchall()
    changes = conn.execute("SELECT * FROM price_changes WHERE customer_id=? ORDER BY id DESC LIMIT 10",
                           (cid,)).fetchall()
    return render_template("vendor_customer.html", c=c, price=current_price(cid), prices=prices,
                           changes=changes, **counts_for_badges())


@app.route("/vendor/customer/<int:cid>/edit", methods=["POST"])
@login_required("vendor")
def vendor_edit_customer(cid):
    c = own_customer(cid)
    name = request.form.get("name", "").strip() or c["name"]
    mobile = request.form.get("mobile", "").strip()
    db().execute("UPDATE customers SET name=?, mobile=? WHERE id=?", (name, mobile, cid))
    audit("customer_edited", name)
    db().commit()
    flash(t("saved"), "ok")
    return redirect(url_for("vendor_customer", cid=cid))


@app.route("/vendor/customer/<int:cid>/price", methods=["POST"])
@login_required("vendor")
def vendor_propose_price(cid):
    c = own_customer(cid)
    paise = to_paise(request.form.get("price"))
    eff = parse_day(request.form.get("effective_from"))
    if paise is None:
        flash(t("price_invalid"), "error")
        return redirect(url_for("vendor_customer", cid=cid))
    if not eff or eff < today():
        flash(t("date_not_past"), "error")
        return redirect(url_for("vendor_customer", cid=cid))
    conn = db()
    conn.execute("UPDATE price_changes SET status='cancelled', decided_at=? "
                 "WHERE customer_id=? AND status='pending'", (stamp(), cid))
    conn.execute("INSERT INTO price_changes (customer_id, old_paise, new_paise, effective_from, created_at) "
                 "VALUES (?,?,?,?,?)", (cid, current_price(cid), paise, eff.isoformat(), stamp()))
    audit("price_proposed", f"{c['name']}: {rupees(current_price(cid))} → {rupees(paise)} from {eff}")
    conn.commit()
    flash(t("price_sent"), "ok")
    return redirect(url_for("vendor_customer", cid=cid))


@app.route("/vendor/customer/<int:cid>/price/cancel", methods=["POST"])
@login_required("vendor")
def vendor_cancel_price(cid):
    c = own_customer(cid)
    db().execute("UPDATE price_changes SET status='cancelled', decided_at=? "
                 "WHERE customer_id=? AND status='pending'", (stamp(), cid))
    audit("price_cancelled", c["name"])
    db().commit()
    return redirect(url_for("vendor_customer", cid=cid))


@app.route("/vendor/customer/<int:cid>/reset", methods=["POST"])
@login_required("vendor")
def vendor_reset_customer(cid):
    c = own_customer(cid)
    secret = make_secret()
    db().execute("UPDATE customers SET secret_hash=? WHERE id=?", (hash_secret(secret), cid))
    audit("customer_secret_reset", c["name"])
    db().commit()
    return render_template("secret.html", who=c["name"], secret=secret,
                           back=url_for("vendor_customer", cid=cid))


@app.route("/vendor/customer/<int:cid>/toggle", methods=["POST"])
@login_required("vendor")
def vendor_toggle_customer(cid):
    c = own_customer(cid)
    new = 0 if c["active"] else 1
    db().execute("UPDATE customers SET active=? WHERE id=?", (new, cid))
    audit("customer_activated" if new else "customer_deactivated", c["name"])
    db().commit()
    return redirect(url_for("vendor_customer", cid=cid))


@app.route("/vendor/month")
@login_required("vendor")
def vendor_month():
    month = parse_month(request.args.get("month"))
    conn = db()
    customers = conn.execute("SELECT * FROM customers WHERE vendor_id=? ORDER BY active DESC, name",
                             (session["uid"],)).fetchall()
    rows, due, collected = [], 0, 0
    for c in customers:
        s = month_statement(c["id"], month)
        if not c["active"] and not s["lines"]:
            continue
        rows.append({"c": c, "s": s})
        if s["paid"]:
            collected += s["amount"]
        else:
            due += s["amount"]
    first, _ = month_days(month)
    prev_m = (first - timedelta(days=1)).strftime("%Y-%m")
    next_m = (first + timedelta(days=32)).strftime("%Y-%m")
    if next_m > today().strftime("%Y-%m"):
        next_m = None
    return render_template("vendor_month.html", month=month, rows=rows, due=due, collected=collected,
                           prev=prev_m, next=next_m, **counts_for_badges())


@app.route("/vendor/month/paid", methods=["POST"])
@login_required("vendor")
def vendor_mark_paid():
    cid = request.form.get("customer_id", type=int)
    month = parse_month(request.form.get("month"))
    c = own_customer(cid)
    paid = 1 if request.form.get("paid") == "1" else 0
    db().execute(
        "INSERT INTO payments (customer_id, month, paid, paid_on) VALUES (?,?,?,?) "
        "ON CONFLICT(customer_id, month) DO UPDATE SET paid=excluded.paid, paid_on=excluded.paid_on",
        (cid, month, paid, stamp() if paid else None))
    audit("marked_paid" if paid else "marked_unpaid", f"{c['name']}: {month}")
    db().commit()
    return redirect(url_for("vendor_month", month=month))


@app.route("/vendor/statement/<int:cid>")
@login_required("vendor")
def vendor_statement(cid):
    c = own_customer(cid)
    month = parse_month(request.args.get("month"))
    first, _ = month_days(month)
    return render_template("statement.html", c=c, month=month, s=month_statement(cid, month),
                           price=current_price(cid),
                           prev=(first - timedelta(days=1)).strftime("%Y-%m"),
                           next=None if month >= today().strftime("%Y-%m")
                           else (first + timedelta(days=32)).strftime("%Y-%m"),
                           base=url_for("vendor_statement", cid=cid), **counts_for_badges())


@app.route("/vendor/requests")
@login_required("vendor")
def vendor_requests():
    rows = db().execute(
        "SELECT r.*, c.name AS cname FROM requests r JOIN customers c ON c.id=r.customer_id "
        "WHERE c.vendor_id=? ORDER BY r.status='done', r.id DESC LIMIT 200", (session["uid"],)).fetchall()
    return render_template("vendor_requests.html", rows=rows, **counts_for_badges())


@app.route("/vendor/requests/<int:rid>/reply", methods=["POST"])
@login_required("vendor")
def vendor_reply_request(rid):
    conn = db()
    r = conn.execute("SELECT r.*, c.name AS cname FROM requests r JOIN customers c ON c.id=r.customer_id "
                     "WHERE r.id=? AND c.vendor_id=?", (rid, session["uid"])).fetchone() or abort(404)
    reply = request.form.get("reply", "").strip()[:1000]
    conn.execute("UPDATE requests SET reply=?, status='done', closed_at=? WHERE id=?", (reply, stamp(), rid))
    audit("request_closed", f"{r['cname']}: {reply[:80]}")
    conn.commit()
    flash(t("saved"), "ok")
    return redirect(url_for("vendor_requests"))


# ---------------------------------------------------------------- customer
@app.route("/me")
@login_required("customer")
def customer_home():
    cid = session["uid"]
    conn = db()
    td = today().isoformat()
    pending = conn.execute("SELECT * FROM price_changes WHERE customer_id=? AND status='pending'",
                           (cid,)).fetchone()
    today_entry = conn.execute("SELECT * FROM entries WHERE customer_id=? AND day=?", (cid, td)).fetchone()
    # days where the customer's and vendor's counts differ: the only past days the customer may correct
    disputes = [e for e in conn.execute(
        "SELECT * FROM entries WHERE customer_id=? AND day<? AND cust_packets IS NOT NULL "
        "AND vendor_packets IS NOT NULL AND cust_packets<>vendor_packets ORDER BY day DESC LIMIT 31",
        (cid, td)).fetchall() if not month_is_paid(cid, e["day"])]
    recent = conn.execute("SELECT * FROM entries WHERE customer_id=? AND day<? ORDER BY day DESC LIMIT 7",
                          (cid, td)).fetchall()
    recent = [{"e": e, "status": entry_status(e)} for e in recent]
    s = month_statement(cid, today().strftime("%Y-%m"))
    return render_template("customer_home.html", pending=pending, price=current_price(cid), s=s,
                           today_entry=today_entry, today_status=entry_status(today_entry) if today_entry else "none",
                           today_open=customer_can_edit(cid, td, today_entry),
                           today_paid=month_is_paid(cid, td), disputes=disputes, recent=recent)


def customer_can_edit(cid, day_str, entry):
    """Rules for the customer:
    - today: can enter once; after saving it is locked
    - any day where vendor and customer counts differ (dispute): can update
    - a missed day: the vendor's count is final, the customer cannot enter it
    - a paid month: nothing can change"""
    if month_is_paid(cid, day_str):
        return False
    if entry is not None and entry_status(entry) == "mismatch":
        return True
    return day_str == today().isoformat() and (entry is None or entry["cust_packets"] is None)


@app.route("/me/entry", methods=["POST"])
@login_required("customer")
def customer_save_entry():
    cid = session["uid"]
    day = parse_day(request.form.get("day"))
    raw = request.form.get("packets", "").strip()
    comment = request.form.get("comment", "").strip()[:2000]
    if not day or day > today():
        flash(t("date_not_future"), "error")
        return redirect(url_for("customer_home"))
    ds = day.isoformat()
    existing = db().execute("SELECT * FROM entries WHERE customer_id=? AND day=?", (cid, ds)).fetchone()
    if not customer_can_edit(cid, ds, existing):
        flash(t("month_locked") if month_is_paid(cid, ds) else t("entry_locked"), "error")
        return redirect(url_for("customer_home"))
    if not raw.isdigit() or int(raw) > 999:
        flash(t("packets_invalid"), "error")
        return redirect(url_for("customer_home"))
    db().execute(
        "INSERT INTO entries (customer_id, day, cust_packets, cust_comment, cust_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(customer_id, day) DO UPDATE SET cust_packets=excluded.cust_packets, "
        "cust_comment=COALESCE(excluded.cust_comment, entries.cust_comment), cust_at=excluded.cust_at",
        (cid, ds, int(raw), comment or None, stamp()))
    was_dispute = existing is not None and entry_status(existing) == "mismatch"
    audit("customer_entry", f"{session['name']}: {ds} = {raw}" + (" (dispute update)" if was_dispute else ""))
    db().commit()
    flash(t("entry_saved"), "ok")
    return redirect(url_for("customer_home"))


@app.route("/me/price/<int:pid>", methods=["POST"])
@login_required("customer")
def customer_decide_price(pid):
    cid = session["uid"]
    conn = db()
    pc = conn.execute("SELECT * FROM price_changes WHERE id=? AND customer_id=? AND status='pending'",
                      (pid, cid)).fetchone() or abort(404)
    accept = request.form.get("decision") == "accept"
    conn.execute("UPDATE price_changes SET status=?, decided_at=? WHERE id=?",
                 ("accepted" if accept else "rejected", stamp(), pid))
    if accept:
        conn.execute("INSERT INTO prices (customer_id, paise, effective_from) VALUES (?,?,?)",
                     (cid, pc["new_paise"], pc["effective_from"]))
    audit("price_accepted" if accept else "price_rejected",
          f"{session['name']}: {rupees(pc['new_paise'])} from {pc['effective_from']}")
    conn.commit()
    flash(t("price_accepted_msg") if accept else t("price_rejected_msg"), "ok")
    return redirect(url_for("customer_home"))


@app.route("/me/statement")
@login_required("customer")
def customer_statement():
    cid = session["uid"]
    c = db().execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    month = parse_month(request.args.get("month"))
    first, _ = month_days(month)
    return render_template("statement.html", c=c, month=month, s=month_statement(cid, month),
                           price=current_price(cid),
                           prev=(first - timedelta(days=1)).strftime("%Y-%m"),
                           next=None if month >= today().strftime("%Y-%m")
                           else (first + timedelta(days=32)).strftime("%Y-%m"),
                           base=url_for("customer_statement"))


@app.route("/me/requests", methods=["GET", "POST"])
@login_required("customer")
def customer_requests():
    cid = session["uid"]
    conn = db()
    if request.method == "POST":
        text = request.form.get("text", "").strip()[:1000]
        if text:
            conn.execute("INSERT INTO requests (customer_id, text, created_at) VALUES (?,?,?)",
                         (cid, text, stamp()))
            audit("request_sent", f"{session['name']}: {text[:80]}")
            conn.commit()
            flash(t("request_sent_msg"), "ok")
        return redirect(url_for("customer_requests"))
    rows = conn.execute("SELECT * FROM requests WHERE customer_id=? ORDER BY id DESC LIMIT 50", (cid,)).fetchall()
    return render_template("customer_requests.html", rows=rows)


# ---------------------------------------------------------------- phone-app files
@app.route("/static/<name>")
def static_file(name):
    if name not in PUBLIC_FILES:
        abort(404)
    return send_from_directory(HERE, name, max_age=60 * 60 * 24)


@app.route("/manifest.json")
def manifest():
    return send_from_directory(HERE, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    with open(os.path.join(HERE, "sw.js"), encoding="utf-8") as f:
        code = f.read().replace("__VERSION__", APP_VERSION)
    resp = app.response_class(code, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/offline")
def offline():
    return render_template("offline.html")


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title=t("not_found"), body=""), 404


@app.errorhandler(400)
def bad_request(_e):
    return render_template("message.html", title=t("try_again"), body=t("session_expired")), 400


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
