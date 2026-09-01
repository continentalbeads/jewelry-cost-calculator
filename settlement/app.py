"""CBS Consignment Settlement — local single-user Flask app.

Run:  pip install flask && python app.py  ->  http://127.0.0.1:5111
"""
import calendar
import csv
import io
import json
import os
import secrets
import time
import uuid
from datetime import date, timedelta

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import fees as feemod
import importer
import matching
from util import (apply_bps, fmt_bps, fmt_money, parse_cents, parse_date,
                  parse_int, today)

app = Flask(__name__)

db.init_db()


def _load_secret_key():
    """Persistent random signing key so sessions survive restarts and cookies
    can't be forged with a known constant."""
    conn = db.connect()
    key = db.get_setting(conn, "secret_key")
    if not key:
        key = secrets.token_hex(32)
        db.set_setting(conn, "secret_key", key)
        conn.commit()
    conn.close()
    return key


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",  # blocks cross-site form posts to the app
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
if os.environ.get("CBS_HTTPS"):
    # set CBS_HTTPS=1 when serving through HTTPS (tunnel/reverse proxy) so the
    # session cookie is never sent over plain HTTP
    app.config["SESSION_COOKIE_SECURE"] = True

app.jinja_env.filters["money"] = fmt_money
app.jinja_env.filters["bps"] = fmt_bps


def get_conn():
    return db.connect()


# ---------------------------------------------------------------- auth

PUBLIC_ENDPOINTS = {"login", "setup", "static", "invite_accept"}
# The ONLY endpoints a consignor account can reach — everything else redirects
# to their portal (or 403s for API paths). Default-deny.
PORTAL_ENDPOINTS = {"portal_home", "logout", "account"}


@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    conn = get_conn()
    n_users = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE role='owner'").fetchone()["c"]
    uid = session.get("uid")
    user = None
    if uid:
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not n_users:
        return redirect(url_for("setup"))
    if user is None:
        session.clear()
        if request.path.startswith("/api/"):
            abort(401)
        nxt = request.path if request.method == "GET" else None
        return redirect(url_for("login", next=nxt))
    if user["role"] == "consignor" and request.endpoint not in PORTAL_ENDPOINTS:
        if request.path.startswith("/api/"):
            abort(403)
        return redirect(url_for("portal_home"))
    return None


@app.context_processor
def auth_ctx():
    uid = session.get("uid")
    email = role = None
    if uid:
        conn = get_conn()
        row = conn.execute("SELECT email, role FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        if row:
            email, role = row["email"], row["role"]
    return {"logged_in": email is not None, "current_user_email": email,
            "is_owner": role == "owner"}


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


@app.route("/setup", methods=["GET", "POST"])
def setup():
    conn = get_conn()
    if conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]:
        conn.close()
        return redirect(url_for("login"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if "@" not in email:
            error = "Enter a valid email address."
        elif len(pw) < 8:
            error = "Password must be at least 8 characters."
        elif pw != pw2:
            error = "Passwords don't match."
        else:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?,?)",
                (email, generate_password_hash(pw)))
            db.audit(conn, "users", cur.lastrowid, "created", None, email,
                     "login account created")
            conn.commit()
            conn.close()
            session.clear()
            session["uid"] = cur.lastrowid
            session.permanent = True
            flash("Account created — you're signed in.", "ok")
            return redirect(url_for("dashboard"))
    conn.close()
    return render_template("setup.html", error=error,
                           email=request.form.get("email", "dean@continentalbeads.com"))


# Simple in-memory login throttle (the portal faces the internet):
# after MAX_FAILS bad attempts for an email, lock that email out for LOCK_SECS.
_login_fails = {}
_LOGIN_MAX_FAILS = 8
_LOGIN_LOCK_SECS = 300


@app.route("/login", methods=["GET", "POST"])
def login():
    conn = get_conn()
    if not conn.execute("SELECT COUNT(*) c FROM users WHERE role='owner'").fetchone()["c"]:
        conn.close()
        return redirect(url_for("setup"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pw = request.form.get("password", "")
        key = email.lower()
        fails, locked_until = _login_fails.get(key, (0, 0))
        if time.time() < locked_until:
            conn.close()
            return render_template("login.html", next="", error=
                "Too many failed attempts — try again in a few minutes."), 429
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], pw):
            _login_fails.pop(key, None)
            conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?",
                         (user["id"],))
            db.audit(conn, "users", user["id"], "login", None, user["email"], "signed in")
            conn.commit()
            conn.close()
            session.clear()
            session["uid"] = user["id"]
            session.permanent = bool(request.form.get("remember"))
            if user["role"] == "consignor":
                return redirect(url_for("portal_home"))
            return redirect(_safe_next(request.form.get("next")) or url_for("dashboard"))
        fails += 1
        _login_fails[key] = (fails, time.time() + _LOGIN_LOCK_SECS
                             if fails >= _LOGIN_MAX_FAILS else 0)
        db.audit(conn, "users", None, "login_failed", None, email, "bad credentials")
        conn.commit()
        error = "Wrong email or password."
    conn.close()
    return render_template("login.html", error=error,
                           next=_safe_next(request.args.get("next")) or "")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "ok")
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
def account():
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if not check_password_hash(user["password_hash"], current):
            flash("Current password is wrong.", "error")
        elif len(pw) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif pw != pw2:
            flash("New passwords don't match.", "error")
        else:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (generate_password_hash(pw), user["id"]))
            db.audit(conn, "users", user["id"], "password", None, "(changed)",
                     "password changed")
            conn.commit()
            flash("Password changed.", "ok")
        conn.close()
        return redirect(url_for("account"))
    conn.close()
    return render_template("account.html", user=user)


@app.context_processor
def nav_counts():
    uid = session.get("uid")
    if not uid:
        return {"nav_pending_review": 0, "nav_unverified_fees": 0}
    conn = get_conn()
    row = conn.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    if not row or row["role"] != "owner":
        conn.close()
        return {"nav_pending_review": 0, "nav_unverified_fees": 0}
    pending = conn.execute(
        """SELECT COUNT(*) c FROM import_lines
           WHERE match_status IN ('fuzzy','unmatched') AND settled_run_id IS NULL"""
    ).fetchone()["c"]
    unverified = conn.execute(
        "SELECT COUNT(*) c FROM fee_schedule WHERE verified=0"
    ).fetchone()["c"]
    conn.close()
    return {"nav_pending_review": pending, "nav_unverified_fees": unverified}


# ---------------------------------------------------------------- dashboard

@app.route("/")
def dashboard():
    conn = get_conn()
    consignors = conn.execute(
        """SELECT c.*, COALESCE(SUM(l.amount_cents), 0) AS balance
           FROM consignors c LEFT JOIN ledger l ON l.consignor_id = c.id
           WHERE c.active = 1 GROUP BY c.id ORDER BY c.name"""
    ).fetchall()
    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5").fetchall()
    conn.close()
    return render_template("index.html", consignors=consignors, runs=runs)


# ------------------------------------------------- consignor portal & invites

@app.route("/consignors/<int:cid>/invite", methods=["POST"])
def consignor_invite(cid):
    conn = get_conn()
    c = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
    if not c:
        abort(404)
    token = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO invites (token, consignor_id, expires_at) "
        "VALUES (?,?, datetime('now', '+14 days'))", (token, cid))
    db.audit(conn, "invites", cid, "invite", None, "portal invite created",
             f"for {c['name']}")
    conn.commit()
    conn.close()
    flash(f"Invite link for {c['name']} created — copy it from their card below "
          f"and send it to them. It expires in 14 days and works once.", "ok")
    return redirect(url_for("consignors"))


@app.route("/invite/<int:iid>/revoke", methods=["POST"])
def invite_revoke(iid):
    conn = get_conn()
    conn.execute("UPDATE invites SET used_at=datetime('now') WHERE id=? AND used_at IS NULL",
                 (iid,))
    db.audit(conn, "invites", iid, "invite", None, "revoked", "portal invite revoked")
    conn.commit()
    conn.close()
    return redirect(url_for("consignors"))


@app.route("/portal-user/<int:uid>/delete", methods=["POST"])
def portal_user_delete(uid):
    conn = get_conn()
    u = conn.execute("SELECT * FROM users WHERE id=? AND role='consignor'", (uid,)).fetchone()
    if u:
        db.audit(conn, "users", uid, "deleted", u["email"], None, "portal access removed")
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        flash(f"Portal access removed for {u['email']}.", "ok")
    conn.close()
    return redirect(url_for("consignors"))


@app.route("/invite/<token>", methods=["GET", "POST"])
def invite_accept(token):
    conn = get_conn()
    inv = conn.execute(
        """SELECT i.*, c.name AS consignor_name FROM invites i
           JOIN consignors c ON c.id = i.consignor_id
           WHERE i.token=? AND i.used_at IS NULL AND i.expires_at > datetime('now')""",
        (token,)).fetchone()
    if not inv:
        conn.close()
        return render_template("invite.html", invalid=True), 404
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        if "@" not in email:
            error = "Enter a valid email address."
        elif len(pw) < 8:
            error = "Password must be at least 8 characters."
        elif pw != pw2:
            error = "Passwords don't match."
        elif conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            error = "That email already has an account — sign in instead."
        else:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, consignor_id) "
                "VALUES (?,?, 'consignor', ?)",
                (email, generate_password_hash(pw), inv["consignor_id"]))
            conn.execute("UPDATE invites SET used_at=datetime('now') WHERE id=?",
                         (inv["id"],))
            db.audit(conn, "users", cur.lastrowid, "created", None, email,
                     f"portal account for {inv['consignor_name']}")
            conn.commit()
            conn.close()
            session.clear()
            session["uid"] = cur.lastrowid
            session.permanent = True
            return redirect(url_for("portal_home"))
    conn.close()
    return render_template("invite.html", invalid=False, error=error,
                           consignor_name=inv["consignor_name"], token=token)


PORTAL_TYPE_LABELS = {
    "SALE": "Sale — your share",
    "REFUND": "Refund",
    "PAYOUT": "Payment to you",
    "CHARGE": "Charge",
    "ADJUSTMENT": "Adjustment",
}


@app.route("/portal")
def portal_home():
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    if user["role"] == "consignor":
        cid = user["consignor_id"]
    else:
        cid = request.args.get("as", type=int)  # owner preview
        if not cid:
            conn.close()
            flash("To preview the portal, use the Preview link on a consignor's card.", "error")
            return redirect(url_for("consignors"))
    consignor = conn.execute("SELECT id, name, business_name FROM consignors WHERE id=?",
                             (cid,)).fetchone()
    if not consignor:
        conn.close()
        abort(404)
    # Only net, consignor-facing columns leave the database here — never fees,
    # gross, or the shop's share.
    entries = conn.execute(
        """SELECT entry_date, type, description, amount_cents FROM ledger
           WHERE consignor_id=? ORDER BY entry_date DESC, id DESC""", (cid,)).fetchall()
    balance = sum(e["amount_cents"] for e in entries)
    months = {}
    for e in entries:
        m = e["entry_date"][:7]
        g = months.setdefault(m, {"month": m, "entries": [], "credited": 0, "paid": 0})
        g["entries"].append(dict(e))
        if e["type"] in ("SALE", "REFUND"):
            g["credited"] += e["amount_cents"]
        elif e["type"] == "PAYOUT":
            g["paid"] += -e["amount_cents"]
    conn.close()
    return render_template("portal.html", consignor=consignor, balance=balance,
                           months=list(months.values()), labels=PORTAL_TYPE_LABELS,
                           preview=(user["role"] != "consignor"))


# ---------------------------------------------------------------- consignors

@app.route("/consignors")
def consignors():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM consignors ORDER BY active DESC, name").fetchall()
    aliases = {}
    for a in conn.execute("SELECT * FROM aliases ORDER BY kind, text").fetchall():
        aliases.setdefault(a["consignor_id"], []).append(a)
    portal_users = {}
    for u in conn.execute(
            "SELECT * FROM users WHERE role='consignor' ORDER BY email").fetchall():
        portal_users.setdefault(u["consignor_id"], []).append(u)
    open_invites = {}
    for i in conn.execute(
            """SELECT * FROM invites WHERE used_at IS NULL
               AND expires_at > datetime('now') ORDER BY id""").fetchall():
        open_invites.setdefault(i["consignor_id"], []).append(i)
    conn.close()
    return render_template("consignors.html", consignors=rows, aliases=aliases,
                           portal_users=portal_users, open_invites=open_invites)


@app.route("/consignors/save", methods=["POST"])
def consignor_save():
    f = request.form
    cid = f.get("id")
    split_bps = int(round(float(f.get("split_pct") or 40) * 100))
    charge = f.get("recurring_charge")
    charge_cents = parse_cents(charge) if charge else None
    vals = dict(
        name=f.get("name", "").strip(),
        business_name=f.get("business_name", "").strip() or None,
        split_bps=split_bps,
        zelle_contact=f.get("zelle_contact", "").strip() or None,
        w9_on_file=1 if f.get("w9_on_file") else 0,
        active=1 if f.get("active") else 0,
        recurring_charge_cents=charge_cents,
        recurring_charge_start=f.get("recurring_charge_start") or None,
        recurring_charge_end=f.get("recurring_charge_end") or None,
        recurring_charge_note=f.get("recurring_charge_note", "").strip() or None,
    )
    if not vals["name"]:
        flash("Name is required.", "error")
        return redirect(url_for("consignors"))
    conn = get_conn()
    if cid:
        old = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
        for k, v in vals.items():
            if old[k] != v:
                db.audit(conn, "consignors", cid, k, old[k], v, "consignor edit")
        conn.execute(
            """UPDATE consignors SET name=:name, business_name=:business_name,
               split_bps=:split_bps, zelle_contact=:zelle_contact, w9_on_file=:w9_on_file,
               active=:active, recurring_charge_cents=:recurring_charge_cents,
               recurring_charge_start=:recurring_charge_start,
               recurring_charge_end=:recurring_charge_end,
               recurring_charge_note=:recurring_charge_note WHERE id=:id""",
            {**vals, "id": cid})
    else:
        cur = conn.execute(
            """INSERT INTO consignors (name, business_name, split_bps, zelle_contact,
               w9_on_file, active, recurring_charge_cents, recurring_charge_start,
               recurring_charge_end, recurring_charge_note)
               VALUES (:name,:business_name,:split_bps,:zelle_contact,:w9_on_file,
                       :active,:recurring_charge_cents,:recurring_charge_start,
                       :recurring_charge_end,:recurring_charge_note)""", vals)
        cid = cur.lastrowid
        db.audit(conn, "consignors", cid, None, None, vals["name"], "consignor created")
        prefix = f.get("initial_prefix", "").strip()
        if prefix:
            conn.execute("INSERT OR IGNORE INTO aliases (consignor_id, text, kind) VALUES (?,?,'prefix')",
                         (cid, prefix))
    conn.commit()
    conn.close()
    flash("Consignor saved.", "ok")
    return redirect(url_for("consignors"))


@app.route("/consignors/<int:cid>/alias/add", methods=["POST"])
def alias_add(cid):
    text = request.form.get("text", "").strip()
    kind = request.form.get("kind", "prefix")
    if text:
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO aliases (consignor_id, text, kind) VALUES (?,?,?)",
                     (cid, text, kind if kind in ("prefix", "alias", "tag") else "alias"))
        db.audit(conn, "aliases", cid, kind, None, text, "alias added")
        conn.commit()
        conn.close()
    return redirect(request.referrer or url_for("consignors"))


@app.route("/alias/<int:aid>/delete", methods=["POST"])
def alias_delete(aid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM aliases WHERE id=?", (aid,)).fetchone()
    if row:
        db.audit(conn, "aliases", row["consignor_id"], row["kind"], row["text"], None, "alias deleted")
        conn.execute("DELETE FROM aliases WHERE id=?", (aid,))
        conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("consignors"))


# ---------------------------------------------------------------- fee schedule

@app.route("/fees")
def fee_schedule():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM fee_schedule ORDER BY channel, deductible DESC, effective_from, id"
    ).fetchall()
    conn.close()
    return render_template("fees.html", fees=rows, today=today())


@app.route("/fees/add", methods=["POST"])
def fee_add():
    f = request.form
    channel = f.get("channel", "").strip()
    name = f.get("fee_name", "").strip()
    if not channel or not name:
        flash("Channel and fee name are required.", "error")
        return redirect(url_for("fee_schedule"))
    percent_bps = int(round(float(f.get("percent") or 0) * 100))
    fixed_cents = parse_cents(f.get("fixed") or "0")
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO fee_schedule (channel, fee_name, percent_bps, fixed_cents,
           effective_from, effective_to, deductible, verified)
           VALUES (?,?,?,?,?,?,?,1)""",
        (channel, name, percent_bps, fixed_cents,
         f.get("effective_from") or today(), f.get("effective_to") or None,
         1 if f.get("deductible") else 0))
    db.audit(conn, "fee_schedule", cur.lastrowid, None, None,
             f"{channel}/{name} {percent_bps}bps+{fixed_cents}c", "fee row added")
    conn.commit()
    conn.close()
    flash("Fee row added.", "ok")
    return redirect(url_for("fee_schedule"))


@app.route("/fees/<int:fid>/update", methods=["POST"])
def fee_update(fid):
    f = request.form
    conn = get_conn()
    old = conn.execute("SELECT * FROM fee_schedule WHERE id=?", (fid,)).fetchone()
    if not old:
        abort(404)
    vals = dict(
        percent_bps=int(round(float(f.get("percent") or 0) * 100)),
        fixed_cents=parse_cents(f.get("fixed") or "0"),
        effective_from=f.get("effective_from") or old["effective_from"],
        effective_to=f.get("effective_to") or None,
        deductible=1 if f.get("deductible") else 0,
        verified=1 if f.get("verified") else 0,
    )
    for k, v in vals.items():
        if old[k] != v:
            db.audit(conn, "fee_schedule", fid, k, old[k], v, "fee row edit")
    conn.execute(
        """UPDATE fee_schedule SET percent_bps=:percent_bps, fixed_cents=:fixed_cents,
           effective_from=:effective_from, effective_to=:effective_to,
           deductible=:deductible, verified=:verified WHERE id=:id""",
        {**vals, "id": fid})
    conn.commit()
    conn.close()
    flash("Fee row updated.", "ok")
    return redirect(url_for("fee_schedule"))


@app.route("/fees/<int:fid>/verify", methods=["POST"])
def fee_verify(fid):
    conn = get_conn()
    conn.execute("UPDATE fee_schedule SET verified=1 WHERE id=?", (fid,))
    db.audit(conn, "fee_schedule", fid, "verified", 0, 1, "rate confirmed by user")
    conn.commit()
    conn.close()
    return redirect(url_for("fee_schedule"))


# ---------------------------------------------------------------- import

@app.route("/import")
def import_page():
    conn = get_conn()
    imports = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 20").fetchall()
    catalog = conn.execute(
        "SELECT COUNT(*) c, MAX(updated_at) t FROM catalog_items").fetchone()
    tag_aliases = conn.execute(
        """SELECT a.text, c.name FROM aliases a JOIN consignors c ON c.id=a.consignor_id
           WHERE a.kind='tag' ORDER BY c.name""").fetchall()
    conn.close()
    return render_template("import.html", imports=imports,
                           catalog_count=catalog["c"], catalog_updated=catalog["t"],
                           tag_aliases=tag_aliases)


def _read_csv_source():
    """The upload forms accept either a browsed file or a typed path to a CSV
    on this computer (for when the native file dialog can't be used, e.g.
    driving the Mac remotely). Returns (bytes, filename) or (None, error)."""
    f = request.files.get("csv_file")
    if f and f.filename:
        return f.read(), f.filename
    path = os.path.expanduser(request.form.get("server_path", "").strip().strip("'\""))
    if not path:
        return None, "Choose a CSV file or type its path on this computer."
    if not os.path.isfile(path):
        return None, f"No file found at {path} — check the path (e.g. ~/Downloads/orders_export.csv)."
    if os.path.getsize(path) > 50 * 1024 * 1024:
        return None, f"{path} is over 50 MB — that doesn't look like an order export."
    try:
        with open(path, "rb") as fh:
            return fh.read(), os.path.basename(path)
    except OSError as e:
        return None, f"Couldn't read {path}: {e}"


@app.route("/import/upload", methods=["POST"])
def import_upload():
    data, name_or_err = _read_csv_source()
    if data is None:
        flash(name_or_err, "error")
        return redirect(url_for("import_page"))
    filename = name_or_err
    headers = importer.read_headers(data)
    if not headers:
        flash("Could not read any header row from that file.", "error")
        return redirect(url_for("import_page"))
    token = uuid.uuid4().hex
    path = os.path.join(db.UPLOAD_DIR, f"{token}.csv")
    with open(path, "wb") as out:
        out.write(data)
    conn = get_conn()
    saved = db.get_setting(conn, "csv_mapping")
    conn.close()
    saved_mapping = json.loads(saved) if saved else {}
    # saved mapping only counts where its headers exist in this file
    mapping = {k: v for k, v in saved_mapping.items() if v in headers}
    if not mapping:
        mapping = importer.guess_mapping(headers)
    return render_template("mapping.html", headers=headers, mapping=mapping,
                           fields=importer.MAP_FIELDS, token=token,
                           filename=filename,
                           heading="Map CSV columns",
                           action_url=url_for("import_process"))


@app.route("/import/process", methods=["POST"])
def import_process():
    token = request.form.get("token", "")
    filename = request.form.get("filename", "orders.csv")
    if not token.isalnum():
        abort(400)
    path = os.path.join(db.UPLOAD_DIR, f"{token}.csv")
    if not os.path.exists(path):
        flash("Upload expired — please re-upload the file.", "error")
        return redirect(url_for("import_page"))
    mapping = {}
    for field, _label, required in importer.MAP_FIELDS:
        col = request.form.get(f"map_{field}", "")
        if col:
            mapping[field] = col
        elif required:
            flash(f"A column for '{_label}' is required.", "error")
            return redirect(url_for("import_page"))
    with open(path, "rb") as fh:
        data = fh.read()
    conn = get_conn()
    if request.form.get("remember"):
        db.set_setting(conn, "csv_mapping", json.dumps(mapping))
    import_id = importer.run_import(conn, data, filename, mapping)
    info = conn.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone()
    conn.commit()
    conn.close()
    os.remove(path)
    flash(f"Imported {info['rows_new']} new lines "
          f"({info['rows_dup']} duplicates skipped, {info['rows_total']} rows total). "
          f"Now clear the review queue.", "ok")
    return redirect(url_for("review"))


# ------------------- product catalog import (tag matching) -------------------

@app.route("/catalog/upload", methods=["POST"])
def catalog_upload():
    data, name_or_err = _read_csv_source()
    if data is None:
        flash(name_or_err, "error")
        return redirect(url_for("import_page"))
    filename = name_or_err
    headers = importer.read_headers(data)
    if not headers:
        flash("Could not read any header row from that file.", "error")
        return redirect(url_for("import_page"))
    token = uuid.uuid4().hex
    with open(os.path.join(db.UPLOAD_DIR, f"{token}.csv"), "wb") as out:
        out.write(data)
    conn = get_conn()
    saved = db.get_setting(conn, "catalog_csv_mapping")
    conn.close()
    saved_mapping = json.loads(saved) if saved else {}
    mapping = {k: v for k, v in saved_mapping.items() if v in headers}
    if not mapping:
        mapping = importer.guess_catalog_mapping(headers)
    return render_template("mapping.html", headers=headers, mapping=mapping,
                           fields=importer.CATALOG_FIELDS, token=token,
                           filename=filename,
                           heading="Map product catalog columns",
                           action_url=url_for("catalog_process"))


@app.route("/catalog/process", methods=["POST"])
def catalog_process():
    token = request.form.get("token", "")
    filename = request.form.get("filename", "products.csv")
    if not token.isalnum():
        abort(400)
    path = os.path.join(db.UPLOAD_DIR, f"{token}.csv")
    if not os.path.exists(path):
        flash("Upload expired — please re-upload the file.", "error")
        return redirect(url_for("import_page"))
    mapping = {}
    for field, label, required in importer.CATALOG_FIELDS:
        col = request.form.get(f"map_{field}", "")
        if col:
            mapping[field] = col
        elif required:
            flash(f"A column for '{label}' is required.", "error")
            return redirect(url_for("import_page"))
    with open(path, "rb") as fh:
        data = fh.read()
    conn = get_conn()
    if request.form.get("remember"):
        db.set_setting(conn, "catalog_csv_mapping", json.dumps(mapping))
    count = importer.run_catalog_import(conn, data, filename, mapping)
    rematched = matching.rematch_pending(conn)
    conn.commit()
    conn.close()
    os.remove(path)
    flash(f"Catalog updated: {count} products/variants stored. "
          f"Pending lines re-matched — {rematched} now have a match.", "ok")
    return redirect(url_for("import_page"))


# ---------------------------------------------------------------- review queue

@app.route("/review")
def review():
    conn = get_conn()
    def bucket(status):
        return conn.execute(
            """SELECT il.*, c.name AS consignor_name FROM import_lines il
               LEFT JOIN consignors c ON c.id = il.consignor_id
               WHERE il.match_status = ? AND il.settled_run_id IS NULL
               ORDER BY il.order_date, il.id""", (status,)).fetchall()
    consignor_rows = conn.execute(
        "SELECT id, name FROM consignors WHERE active=1 ORDER BY name").fetchall()
    channels = feemod.channel_list(conn)
    fee_channels = feemod.fee_channels(conn)
    buckets = {
        "confident": bucket("confident") + bucket("confirmed"),
        "fuzzy": bucket("fuzzy"),
        "unmatched": bucket("unmatched"),
        "dismissed": bucket("dismissed"),
    }
    no_fee_count = sum(1 for l in buckets["confident"] + buckets["fuzzy"]
                       if l["channel"] not in fee_channels)
    conn.close()
    return render_template("review.html", consignors=consignor_rows,
                           channels=channels, fee_channels=fee_channels,
                           no_fee_count=no_fee_count, **buckets)


@app.route("/line/<int:lid>/assign", methods=["POST"])
def line_assign(lid):
    cid = request.form.get("consignor_id")
    if not cid:
        flash("Pick a consignor first.", "error")
        return redirect(url_for("review"))
    conn = get_conn()
    line = conn.execute("SELECT * FROM import_lines WHERE id=?", (lid,)).fetchone()
    if not line or line["settled_run_id"]:
        conn.close()
        abort(404)
    db.audit(conn, "import_lines", lid, "consignor_id", line["consignor_id"], cid,
             f"manual assign (was {line['match_status']})")
    conn.execute(
        """UPDATE import_lines SET consignor_id=?, match_status='confirmed',
           match_method='manual', match_score=NULL WHERE id=?""", (cid, lid))
    if request.form.get("save_alias"):
        alias_text = request.form.get("alias_text", "").strip()
        if alias_text:
            conn.execute(
                "INSERT OR IGNORE INTO aliases (consignor_id, text, kind) VALUES (?,?,'alias')",
                (cid, alias_text))
            db.audit(conn, "aliases", int(cid), "alias", None, alias_text,
                     "saved from review queue")
    conn.commit()
    conn.close()
    return redirect(url_for("review"))


@app.route("/line/<int:lid>/confirm", methods=["POST"])
def line_confirm(lid):
    conn = get_conn()
    line = conn.execute("SELECT * FROM import_lines WHERE id=?", (lid,)).fetchone()
    if not line or not line["consignor_id"]:
        conn.close()
        abort(404)
    db.audit(conn, "import_lines", lid, "match_status", line["match_status"], "confirmed",
             f"fuzzy match confirmed ({line['match_method']}, score {line['match_score']})")
    conn.execute("UPDATE import_lines SET match_status='confirmed' WHERE id=?", (lid,))
    conn.commit()
    conn.close()
    return redirect(url_for("review"))


@app.route("/line/<int:lid>/dismiss", methods=["POST"])
def line_dismiss(lid):
    conn = get_conn()
    line = conn.execute("SELECT * FROM import_lines WHERE id=?", (lid,)).fetchone()
    if line and not line["settled_run_id"]:
        db.audit(conn, "import_lines", lid, "match_status", line["match_status"],
                 "dismissed", "dismissed as not-consignment")
        conn.execute(
            "UPDATE import_lines SET match_status='dismissed', consignor_id=NULL WHERE id=?",
            (lid,))
        conn.commit()
    conn.close()
    return redirect(url_for("review"))


@app.route("/line/<int:lid>/restore", methods=["POST"])
def line_restore(lid):
    conn = get_conn()
    line = conn.execute("SELECT * FROM import_lines WHERE id=?", (lid,)).fetchone()
    if line and not line["settled_run_id"]:
        db.audit(conn, "import_lines", lid, "match_status", line["match_status"],
                 "unmatched", "restored to queue")
        conn.execute(
            """UPDATE import_lines SET match_status='unmatched', consignor_id=NULL,
               match_method=NULL, match_score=NULL WHERE id=?""", (lid,))
        conn.commit()
    conn.close()
    return redirect(url_for("review"))


@app.route("/line/<int:lid>/channel", methods=["POST"])
def line_channel(lid):
    channel = request.form.get("channel", "").strip()
    conn = get_conn()
    line = conn.execute("SELECT * FROM import_lines WHERE id=?", (lid,)).fetchone()
    if line and channel and not line["settled_run_id"]:
        db.audit(conn, "import_lines", lid, "channel", line["channel"], channel,
                 "channel override")
        conn.execute("UPDATE import_lines SET channel=? WHERE id=?", (channel, lid))
        conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("review"))


@app.route("/review/dismiss-unmatched", methods=["POST"])
def dismiss_unmatched():
    conn = get_conn()
    n = conn.execute(
        """UPDATE import_lines SET match_status='dismissed'
           WHERE match_status='unmatched' AND settled_run_id IS NULL""").rowcount
    db.audit(conn, "import_lines", None, "match_status", "unmatched", "dismissed",
             f"bulk dismiss of {n} unmatched lines")
    conn.commit()
    conn.close()
    flash(f"Dismissed {n} unmatched lines as not-consignment.", "ok")
    return redirect(url_for("review"))


@app.route("/review/redetect-channels", methods=["POST"])
def redetect_channels():
    """Re-run channel detection from each line's raw source value — for lines
    imported before a source variant (e.g. Shopify POS's '580111') was known.
    Only touches unsettled lines, and resets any manual channel overrides."""
    conn = get_conn()
    lines = conn.execute(
        "SELECT id, channel, channel_raw FROM import_lines WHERE settled_run_id IS NULL"
    ).fetchall()
    changed = 0
    for l in lines:
        new = importer.resolve_channel(l["channel_raw"])
        if new != l["channel"]:
            db.audit(conn, "import_lines", l["id"], "channel", l["channel"], new,
                     "bulk channel re-detect")
            conn.execute("UPDATE import_lines SET channel=? WHERE id=?", (new, l["id"]))
            changed += 1
    conn.commit()
    conn.close()
    flash(f"Re-detected channels on unsettled lines: {changed} changed. "
          f"If a draft run already exists, delete it and recreate so fees recompute.",
          "ok")
    return redirect(url_for("review"))


@app.route("/review/rematch", methods=["POST"])
def rematch():
    conn = get_conn()
    n = matching.rematch_pending(conn)
    conn.commit()
    conn.close()
    flash(f"Re-ran matching: {n} pending lines now have a match.", "ok")
    return redirect(url_for("review"))


# ---------------------------------------------------------------- runs

def _run_line_view(conn, line):
    fee_rows = conn.execute(
        "SELECT * FROM run_line_fees WHERE run_line_id=? ORDER BY id", (line["id"],)
    ).fetchall()
    fee_total = sum(fr["amount_cents"] for fr in fee_rows if not fr["removed"])
    net = line["gross_cents"] - fee_total
    share = apply_bps(net, line["split_bps"])
    return {**dict(line), "fees": [dict(fr) for fr in fee_rows],
            "fee_total": fee_total, "net_cents": net,
            "consignor_share_cents": share, "my_share_cents": net - share}


def _run_lines(conn, run_id):
    rows = conn.execute(
        """SELECT rl.*, c.name AS consignor_name FROM run_lines rl
           JOIN consignors c ON c.id = rl.consignor_id
           WHERE rl.run_id=? ORDER BY c.name, rl.order_date, rl.id""", (run_id,)
    ).fetchall()
    return [_run_line_view(conn, r) for r in rows]


@app.route("/runs")
def runs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    eligible = conn.execute(
        """SELECT COUNT(*) c FROM import_lines
           WHERE match_status IN ('confident','confirmed') AND settled_run_id IS NULL
             AND id NOT IN (SELECT rl.import_line_id FROM run_lines rl
                            JOIN runs r ON r.id = rl.run_id
                            WHERE r.status = 'draft' AND rl.import_line_id IS NOT NULL)"""
    ).fetchone()["c"]
    conn.close()
    return render_template("runs.html", runs=rows, eligible=eligible,
                           default_period=today()[:7])


@app.route("/runs/create", methods=["POST"])
def run_create():
    period = request.form.get("period") or today()[:7]
    label = request.form.get("label", "").strip() or f"Settlement {period}"
    conn = get_conn()
    pending = conn.execute(
        """SELECT COUNT(*) c FROM import_lines
           WHERE match_status IN ('fuzzy','unmatched') AND settled_run_id IS NULL"""
    ).fetchone()["c"]
    if pending:
        conn.close()
        flash(f"{pending} lines still need review. Confirm, assign, or dismiss them "
              f"before creating a run — nothing gets settled silently.", "error")
        return redirect(url_for("review"))
    cur = conn.execute("INSERT INTO runs (label, period) VALUES (?,?)", (label, period))
    run_id = cur.lastrowid
    lines = conn.execute(
        """SELECT il.*, c.split_bps FROM import_lines il
           JOIN consignors c ON c.id = il.consignor_id
           WHERE il.match_status IN ('confident','confirmed') AND il.settled_run_id IS NULL
             AND il.id NOT IN (SELECT rl.import_line_id FROM run_lines rl
                               JOIN runs r ON r.id = rl.run_id
                               WHERE r.status = 'draft' AND rl.import_line_id IS NOT NULL)
           ORDER BY il.id"""
    ).fetchall()
    for il in lines:
        entry_type = "REFUND" if il["is_refund"] else "SALE"
        rl = conn.execute(
            """INSERT INTO run_lines (run_id, import_line_id, consignor_id, entry_type,
               order_ref, order_date, channel, description, gross_cents, split_bps)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, il["id"], il["consignor_id"], entry_type, il["order_ref"],
             il["order_date"], il["channel"], il["title"], il["gross_cents"],
             il["split_bps"]))
        for fee in feemod.compute_fees(conn, il["channel"], il["order_date"],
                                       il["gross_cents"]):
            conn.execute(
                """INSERT INTO run_line_fees (run_line_id, fee_schedule_id, fee_name,
                   amount_cents) VALUES (?,?,?,?)""",
                (rl.lastrowid, fee["fee_schedule_id"], fee["fee_name"],
                 fee["amount_cents"]))
    db.audit(conn, "runs", run_id, None, None,
             f"draft created with {len(lines)} lines", "run created")
    conn.commit()
    conn.close()
    flash(f"Draft run created with {len(lines)} lines. Review and edit before committing.", "ok")
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/runs/<int:run_id>")
def run_detail(run_id):
    conn = get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run:
        abort(404)
    lines = _run_lines(conn, run_id)
    consignor_rows = conn.execute(
        "SELECT id, name FROM consignors WHERE active=1 ORDER BY name").fetchall()
    channels = feemod.channel_list(conn)
    statement_consignors = []
    if run["status"] == "committed":
        statement_consignors = conn.execute(
            """SELECT DISTINCT c.id, c.name FROM ledger l
               JOIN consignors c ON c.id = l.consignor_id
               WHERE l.run_id=? ORDER BY c.name""", (run_id,)).fetchall()
    conn.close()
    no_fee_count = sum(1 for l in lines if not l["excluded"] and not l["fees"])
    return render_template("run_detail.html", run=run, lines=lines,
                           consignors=consignor_rows, channels=channels,
                           statement_consignors=statement_consignors, today=today(),
                           no_fee_count=no_fee_count)


@app.route("/runs/<int:run_id>/delete", methods=["POST"])
def run_delete(run_id):
    conn = get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run or run["status"] != "draft":
        conn.close()
        flash("Only draft runs can be deleted.", "error")
        return redirect(url_for("runs"))
    conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
    db.audit(conn, "runs", run_id, "status", "draft", None, "draft run deleted")
    conn.commit()
    conn.close()
    flash("Draft run deleted. Its lines are back in the pool.", "ok")
    return redirect(url_for("runs"))


@app.route("/runs/<int:run_id>/add-line", methods=["POST"])
def run_add_line(run_id):
    f = request.form
    conn = get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run or run["status"] != "draft":
        conn.close()
        abort(400)
    cid = f.get("consignor_id")
    try:
        gross = parse_cents(f.get("gross"))
    except ValueError:
        conn.close()
        flash("Gross amount not understood.", "error")
        return redirect(url_for("run_detail", run_id=run_id))
    entry_type = f.get("entry_type", "SALE")
    if entry_type == "REFUND" and gross > 0:
        gross = -gross
    consignor = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
    if not consignor:
        conn.close()
        flash("Pick a consignor.", "error")
        return redirect(url_for("run_detail", run_id=run_id))
    channel = f.get("channel") or None
    order_date = f.get("order_date") or today()
    rl = conn.execute(
        """INSERT INTO run_lines (run_id, consignor_id, entry_type, order_ref, order_date,
           channel, description, gross_cents, split_bps, manual, note)
           VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
        (run_id, cid, entry_type if entry_type in ("SALE", "REFUND") else "SALE",
         f.get("order_ref", "").strip() or None, order_date, channel,
         f.get("description", "").strip() or "(manual line)", gross,
         consignor["split_bps"], f.get("note", "").strip() or None))
    if f.get("apply_fees") and channel:
        for fee in feemod.compute_fees(conn, channel, order_date, gross):
            conn.execute(
                """INSERT INTO run_line_fees (run_line_id, fee_schedule_id, fee_name,
                   amount_cents) VALUES (?,?,?,?)""",
                (rl.lastrowid, fee["fee_schedule_id"], fee["fee_name"],
                 fee["amount_cents"]))
    db.audit(conn, "run_lines", rl.lastrowid, None, None,
             f"manual line added: {fmt_money(gross)}", f"run {run_id}")
    conn.commit()
    conn.close()
    return redirect(url_for("run_detail", run_id=run_id))


# ------------- editable review-table API (draft runs only) -------------

def _api_line_response(conn, line_id):
    line = conn.execute(
        """SELECT rl.*, c.name AS consignor_name FROM run_lines rl
           JOIN consignors c ON c.id=rl.consignor_id WHERE rl.id=?""", (line_id,)
    ).fetchone()
    v = _run_line_view(conn, line)
    return {
        "id": v["id"],
        "gross_cents": v["gross_cents"],
        "fee_total": v["fee_total"],
        "net_cents": v["net_cents"],
        "consignor_share_cents": v["consignor_share_cents"],
        "my_share_cents": v["my_share_cents"],
        "split_bps": v["split_bps"],
        "excluded": v["excluded"],
        "edited": v["edited"],
        "fees": [{"id": fr["id"], "fee_name": fr["fee_name"],
                  "amount_cents": fr["amount_cents"], "removed": fr["removed"],
                  "edited": fr["edited"],
                  "original_amount_cents": fr["original_amount_cents"]}
                 for fr in v["fees"]],
        "fmt": {"gross": fmt_money(v["gross_cents"]), "fee_total": fmt_money(v["fee_total"]),
                "net": fmt_money(v["net_cents"]),
                "share": fmt_money(v["consignor_share_cents"]),
                "mine": fmt_money(v["my_share_cents"])},
    }


def _require_draft_line(conn, line_id):
    line = conn.execute(
        """SELECT rl.*, r.status FROM run_lines rl JOIN runs r ON r.id=rl.run_id
           WHERE rl.id=?""", (line_id,)).fetchone()
    if not line or line["status"] != "draft":
        abort(400, "line not editable (missing or run already committed)")
    return line


@app.route("/api/run-line/<int:line_id>", methods=["POST"])
def api_run_line(line_id):
    data = request.get_json(force=True)
    field = data.get("field")
    value = data.get("value")
    conn = get_conn()
    line = _require_draft_line(conn, line_id)
    ctx = f"run {line['run_id']} review edit"
    if field == "gross":
        new = parse_cents(value)
        if new != line["gross_cents"]:
            if line["original_gross_cents"] is None:
                conn.execute("UPDATE run_lines SET original_gross_cents=? WHERE id=?",
                             (line["gross_cents"], line_id))
            db.audit(conn, "run_lines", line_id, "gross_cents",
                     line["gross_cents"], new, ctx)
            conn.execute("UPDATE run_lines SET gross_cents=?, edited=1 WHERE id=?",
                         (new, line_id))
    elif field == "split_pct":
        new = int(round(float(value or 0) * 100))
        if new != line["split_bps"]:
            if line["original_split_bps"] is None:
                conn.execute("UPDATE run_lines SET original_split_bps=? WHERE id=?",
                             (line["split_bps"], line_id))
            db.audit(conn, "run_lines", line_id, "split_bps",
                     line["split_bps"], new, ctx)
            conn.execute("UPDATE run_lines SET split_bps=?, edited=1 WHERE id=?",
                         (new, line_id))
    elif field == "excluded":
        new = 1 if value else 0
        db.audit(conn, "run_lines", line_id, "excluded", line["excluded"], new, ctx)
        conn.execute("UPDATE run_lines SET excluded=? WHERE id=?", (new, line_id))
    elif field == "note":
        conn.execute("UPDATE run_lines SET note=? WHERE id=?",
                     (str(value or "").strip() or None, line_id))
    elif field == "channel":
        db.audit(conn, "run_lines", line_id, "channel", line["channel"], value, ctx)
        conn.execute("UPDATE run_lines SET channel=? WHERE id=?", (value, line_id))
    else:
        abort(400, f"unknown field {field}")
    conn.commit()
    resp = _api_line_response(conn, line_id)
    conn.close()
    return jsonify(resp)


@app.route("/api/run-line/<int:line_id>/fee/add", methods=["POST"])
def api_fee_add(line_id):
    data = request.get_json(force=True)
    conn = get_conn()
    line = _require_draft_line(conn, line_id)
    name = str(data.get("name") or "Ad-hoc fee").strip()
    amount = parse_cents(data.get("amount"))
    conn.execute(
        """INSERT INTO run_line_fees (run_line_id, fee_name, amount_cents, source)
           VALUES (?,?,?,'manual')""", (line_id, name, amount))
    db.audit(conn, "run_line_fees", line_id, "add", None, f"{name}: {fmt_money(amount)}",
             f"run {line['run_id']} ad-hoc fee")
    conn.execute("UPDATE run_lines SET edited=1 WHERE id=?", (line_id,))
    conn.commit()
    resp = _api_line_response(conn, line_id)
    conn.close()
    return jsonify(resp)


@app.route("/api/run-line/<int:line_id>/reset-fees", methods=["POST"])
def api_reset_fees(line_id):
    conn = get_conn()
    line = _require_draft_line(conn, line_id)
    db.audit(conn, "run_line_fees", line_id, "reset", None,
             "fees recomputed from schedule", f"run {line['run_id']}")
    conn.execute("DELETE FROM run_line_fees WHERE run_line_id=?", (line_id,))
    for fee in feemod.compute_fees(conn, line["channel"], line["order_date"],
                                   line["gross_cents"]):
        conn.execute(
            """INSERT INTO run_line_fees (run_line_id, fee_schedule_id, fee_name,
               amount_cents) VALUES (?,?,?,?)""",
            (line_id, fee["fee_schedule_id"], fee["fee_name"], fee["amount_cents"]))
    conn.commit()
    resp = _api_line_response(conn, line_id)
    conn.close()
    return jsonify(resp)


@app.route("/api/fee/<int:fee_id>", methods=["POST"])
def api_fee(fee_id):
    data = request.get_json(force=True)
    conn = get_conn()
    fee = conn.execute("SELECT * FROM run_line_fees WHERE id=?", (fee_id,)).fetchone()
    if not fee:
        abort(404)
    line = _require_draft_line(conn, fee["run_line_id"])
    ctx = f"run {line['run_id']} fee edit"
    if "amount" in data:
        new = parse_cents(data["amount"])
        if new != fee["amount_cents"]:
            if fee["original_amount_cents"] is None:
                conn.execute("UPDATE run_line_fees SET original_amount_cents=? WHERE id=?",
                             (fee["amount_cents"], fee_id))
            db.audit(conn, "run_line_fees", fee_id, "amount_cents",
                     fee["amount_cents"], new, ctx)
            conn.execute("UPDATE run_line_fees SET amount_cents=?, edited=1 WHERE id=?",
                         (new, fee_id))
            conn.execute("UPDATE run_lines SET edited=1 WHERE id=?", (fee["run_line_id"],))
    if "removed" in data:
        new = 1 if data["removed"] else 0
        db.audit(conn, "run_line_fees", fee_id, "removed", fee["removed"], new, ctx)
        conn.execute("UPDATE run_line_fees SET removed=?, edited=1 WHERE id=?",
                     (new, fee_id))
        conn.execute("UPDATE run_lines SET edited=1 WHERE id=?", (fee["run_line_id"],))
    conn.commit()
    resp = _api_line_response(conn, fee["run_line_id"])
    conn.close()
    return jsonify(resp)


# ---------------------------------------------------------------- commit

@app.route("/runs/<int:run_id>/commit", methods=["POST"])
def run_commit(run_id):
    conn = get_conn()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run or run["status"] != "draft":
        conn.close()
        flash("Run is not a draft.", "error")
        return redirect(url_for("runs"))

    backup_path = db.backup_db(conn, f"pre-run{run_id}")

    lines = _run_lines(conn, run_id)
    committed = 0
    for v in lines:
        if v["excluded"]:
            continue
        kept_fees = [{"name": fr["fee_name"], "amount_cents": fr["amount_cents"]}
                     for fr in v["fees"] if not fr["removed"]]
        source_ref = v["order_ref"] or (f"manual line {v['id']}" if v["manual"] else None)
        conn.execute(
            """INSERT INTO ledger (consignor_id, entry_date, type, run_id, source_ref,
               channel, description, gross_cents, fee_cents, fee_detail, net_cents,
               consignor_share_cents, my_share_cents, amount_cents, note,
               manually_edited)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (v["consignor_id"], v["order_date"] or today(), v["entry_type"], run_id,
             source_ref, v["channel"], v["description"], v["gross_cents"], v["fee_total"],
             json.dumps(kept_fees), v["net_cents"], v["consignor_share_cents"],
             v["my_share_cents"], v["consignor_share_cents"], v["note"], v["edited"]))
        committed += 1
        if v["import_line_id"]:
            conn.execute("UPDATE import_lines SET settled_run_id=? WHERE id=?",
                         (run_id, v["import_line_id"]))

    # Recurring monthly charges for this period (deduped per consignor per month).
    period = run["period"]
    year, month = int(period[:4]), int(period[5:7])
    month_start = f"{period}-01"
    month_end = f"{period}-{calendar.monthrange(year, month)[1]:02d}"
    charges = 0
    for c in conn.execute(
        """SELECT * FROM consignors WHERE active=1 AND recurring_charge_cents > 0
           AND recurring_charge_start <= ?
           AND (recurring_charge_end IS NULL OR recurring_charge_end >= ?)""",
            (month_end, month_start)).fetchall():
        exists = conn.execute(
            """SELECT 1 FROM ledger WHERE consignor_id=? AND type='CHARGE'
               AND source_ref=?""", (c["id"], f"recurring:{period}")).fetchone()
        if exists:
            continue
        conn.execute(
            """INSERT INTO ledger (consignor_id, entry_date, type, run_id, source_ref,
               description, amount_cents, note)
               VALUES (?,?, 'CHARGE', ?, ?, ?, ?, ?)""",
            (c["id"], month_start, run_id, f"recurring:{period}",
             c["recurring_charge_note"] or "Monthly charge",
             -c["recurring_charge_cents"], f"recurring charge for {period}"))
        charges += 1

    conn.execute(
        "UPDATE runs SET status='committed', committed_at=datetime('now'), backup_path=? WHERE id=?",
        (backup_path, run_id))
    db.audit(conn, "runs", run_id, "status", "draft", "committed",
             f"{committed} ledger entries, {charges} recurring charges; backup {backup_path}")
    conn.commit()
    conn.close()
    flash(f"Run committed: {committed} ledger entries written"
          + (f", {charges} recurring charge(s) posted" if charges else "")
          + f". DB backed up to {os.path.basename(backup_path)}.", "ok")
    return redirect(url_for("payouts"))


# ---------------------------------------------------------------- payouts

def _balances(conn):
    return conn.execute(
        """SELECT c.*, COALESCE(SUM(l.amount_cents),0) AS balance
           FROM consignors c LEFT JOIN ledger l ON l.consignor_id=c.id
           WHERE c.active=1 GROUP BY c.id ORDER BY c.name"""
    ).fetchall()


@app.route("/payouts")
def payouts():
    conn = get_conn()
    rows = _balances(conn)
    conn.close()
    return render_template("payouts.html", rows=rows, today=today())


@app.route("/payouts/pay", methods=["POST"])
def payout_pay():
    f = request.form
    cid = f.get("consignor_id")
    try:
        amount = parse_cents(f.get("amount"))
    except ValueError:
        flash("Payout amount not understood.", "error")
        return redirect(url_for("payouts"))
    if amount <= 0:
        flash("Payout amount must be positive.", "error")
        return redirect(url_for("payouts"))
    conn = get_conn()
    c = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
    if not c:
        conn.close()
        abort(404)
    if not c["w9_on_file"] and not f.get("override_w9"):
        conn.close()
        flash(f"{c['name']} has no W-9 on file — flagged do-not-pay. "
              f"Tick the override box to pay anyway.", "error")
        return redirect(url_for("payouts"))
    method = f.get("method", "Zelle").strip() or "Zelle"
    date = f.get("date") or today()
    conn.execute(
        """INSERT INTO ledger (consignor_id, entry_date, type, description,
           amount_cents, payout_method, note)
           VALUES (?,?, 'PAYOUT', ?, ?, ?, ?)""",
        (cid, date, f"Payout via {method}" + (f" to {c['zelle_contact']}" if c["zelle_contact"] else ""),
         -amount, method, f.get("note", "").strip() or None))
    db.audit(conn, "ledger", int(cid), "payout", None,
             f"{fmt_money(amount)} via {method} on {date}", "payout recorded")
    conn.commit()
    conn.close()
    flash(f"Recorded {fmt_money(amount)} payout to {c['name']}.", "ok")
    return redirect(url_for("payouts"))


# ---------------------------------------------------------------- statements

def _statement_data(conn, run_id, cid):
    run = conn.execute("SELECT * FROM runs WHERE id=? AND status='committed'",
                       (run_id,)).fetchone()
    consignor = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
    if not run or not consignor:
        return None
    entries = conn.execute(
        """SELECT * FROM ledger WHERE run_id=? AND consignor_id=? ORDER BY entry_date, id""",
        (run_id, cid)).fetchall()
    if entries:
        first_id = min(e["id"] for e in entries)
        prior = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) b FROM ledger WHERE consignor_id=? AND id<?",
            (cid, first_id)).fetchone()["b"]
    else:
        prior = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) b FROM ledger WHERE consignor_id=?",
            (cid,)).fetchone()["b"]
    parsed = []
    for e in entries:
        parsed.append({**dict(e),
                       "fee_items": json.loads(e["fee_detail"]) if e["fee_detail"] else []})
    activity = sum(e["amount_cents"] for e in entries)
    balance_after = prior + activity
    return {"run": run, "consignor": consignor, "entries": parsed,
            "prior_balance": prior, "activity": activity,
            "balance_after": balance_after,
            "amount_due": max(0, balance_after)}


@app.route("/runs/<int:run_id>/statement/<int:cid>")
def statement(run_id, cid):
    conn = get_conn()
    data = _statement_data(conn, run_id, cid)
    conn.close()
    if not data:
        abort(404)
    if request.args.get("fmt") == "csv" and request.args.get("view") == "net":
        # Consignor-facing export: net amounts only — no fees, no gross,
        # matching what the portal shows.
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Continental Bead Suppliers - Consignment Statement"])
        w.writerow(["Consignor", data["consignor"]["name"],
                    data["consignor"]["business_name"] or ""])
        w.writerow(["Period", data["run"]["period"]])
        w.writerow([])
        w.writerow(["Date", "Activity", "Order/Ref", "Item", "Amount"])
        labels = {"SALE": "Sale - your share", "REFUND": "Refund",
                  "PAYOUT": "Payment to you", "CHARGE": "Charge",
                  "ADJUSTMENT": "Adjustment"}
        for e in data["entries"]:
            w.writerow([e["entry_date"], labels.get(e["type"], e["type"]),
                        e["source_ref"] or "", e["description"] or "",
                        f"{e['amount_cents']/100:.2f}"])
        w.writerow([])
        w.writerow(["Prior balance carried forward", f"{data['prior_balance']/100:.2f}"])
        w.writerow(["This period", f"{data['activity']/100:.2f}"])
        w.writerow(["Balance", f"{data['balance_after']/100:.2f}"])
        w.writerow(["Amount due this period", f"{data['amount_due']/100:.2f}"])
        buf.seek(0)
        return send_file(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                         mimetype="text/csv", as_attachment=True,
                         download_name=f"statement-{data['run']['period']}-{data['consignor']['name']}-net.csv")
    if request.args.get("fmt") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Continental Bead Suppliers - Consignment Statement"])
        w.writerow(["Consignor", data["consignor"]["name"],
                    data["consignor"]["business_name"] or ""])
        w.writerow(["Period", data["run"]["period"], "Run", run_id])
        w.writerow([])
        w.writerow(["Date", "Type", "Order/Ref", "Description", "Fee name",
                    "Gross", "Fee", "Net", "Your share", "Amount"])
        for e in data["entries"]:
            w.writerow([e["entry_date"], e["type"], e["source_ref"] or "",
                        e["description"] or "", "",
                        f"{e['gross_cents']/100:.2f}", "",
                        f"{e['net_cents']/100:.2f}",
                        f"{e['consignor_share_cents']/100:.2f}",
                        f"{e['amount_cents']/100:.2f}"])
            for fi in e["fee_items"]:
                w.writerow(["", "", "", "", fi["name"], "",
                            f"{fi['amount_cents']/100:.2f}", "", "", ""])
        w.writerow([])
        w.writerow(["Prior balance carried forward", f"{data['prior_balance']/100:.2f}"])
        w.writerow(["This period activity", f"{data['activity']/100:.2f}"])
        w.writerow(["Balance", f"{data['balance_after']/100:.2f}"])
        w.writerow(["Amount due this period", f"{data['amount_due']/100:.2f}"])
        buf.seek(0)
        return send_file(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                         mimetype="text/csv", as_attachment=True,
                         download_name=f"statement-{data['run']['period']}-{data['consignor']['name']}.csv")
    return render_template("statement.html", **data)


# ---------------------------------------------------------------- sales report

def _report_data(conn, cid, d_from, d_to):
    consignor = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
    if not consignor:
        return None
    entries = conn.execute(
        """SELECT * FROM ledger WHERE consignor_id=? AND type IN ('SALE','REFUND')
           AND entry_date >= ? AND entry_date <= ?
           ORDER BY channel, entry_date, id""", (cid, d_from, d_to)).fetchall()
    groups = {}
    for e in entries:
        ch = e["channel"] or "(no channel recorded)"
        g = groups.setdefault(ch, {"channel": ch, "entries": [], "totals":
                                   {"gross": 0, "fees": 0, "net": 0, "share": 0}})
        g["entries"].append({**dict(e),
                             "fee_items": json.loads(e["fee_detail"]) if e["fee_detail"] else []})
        g["totals"]["gross"] += e["gross_cents"]
        g["totals"]["fees"] += e["fee_cents"]
        g["totals"]["net"] += e["net_cents"]
        g["totals"]["share"] += e["amount_cents"]
    grand = {"gross": 0, "fees": 0, "net": 0, "share": 0, "count": len(entries)}
    for g in groups.values():
        for k in ("gross", "fees", "net", "share"):
            grand[k] += g["totals"][k]
    other = [dict(e) for e in conn.execute(
        """SELECT * FROM ledger WHERE consignor_id=? AND type NOT IN ('SALE','REFUND')
           AND entry_date >= ? AND entry_date <= ? ORDER BY entry_date, id""",
        (cid, d_from, d_to)).fetchall()]
    return {"consignor": consignor, "groups": list(groups.values()), "grand": grand,
            "other": other, "other_total": sum(e["amount_cents"] for e in other),
            "d_from": d_from, "d_to": d_to}


@app.route("/report")
def report():
    conn = get_conn()
    consignor_rows = conn.execute(
        "SELECT id, name FROM consignors ORDER BY active DESC, name").fetchall()
    # default to the previous calendar month (what you're paying out for)
    this_month_first = date.today().replace(day=1)
    prev_end = this_month_first - timedelta(days=1)
    d_from = request.args.get("from") or prev_end.replace(day=1).isoformat()
    d_to = request.args.get("to") or prev_end.isoformat()
    cid = request.args.get("consignor_id", type=int)
    data = _report_data(conn, cid, d_from, d_to) if cid else None
    conn.close()
    if data and request.args.get("fmt") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Continental Bead Suppliers - Sales report"])
        w.writerow(["Consignor", data["consignor"]["name"], "From", d_from, "To", d_to])
        w.writerow([])
        w.writerow(["Channel", "Date", "Type", "Order/Ref", "Item",
                    "Gross", "Fees", "Net", "Consignor share"])
        for g in data["groups"]:
            for e in g["entries"]:
                w.writerow([g["channel"], e["entry_date"], e["type"],
                            e["source_ref"] or "", e["description"] or "",
                            f"{e['gross_cents']/100:.2f}", f"{e['fee_cents']/100:.2f}",
                            f"{e['net_cents']/100:.2f}", f"{e['amount_cents']/100:.2f}"])
            t = g["totals"]
            w.writerow([f"{g['channel']} subtotal", "", "", "", "",
                        f"{t['gross']/100:.2f}", f"{t['fees']/100:.2f}",
                        f"{t['net']/100:.2f}", f"{t['share']/100:.2f}"])
        gr = data["grand"]
        w.writerow(["TOTAL", "", "", "", "", f"{gr['gross']/100:.2f}",
                    f"{gr['fees']/100:.2f}", f"{gr['net']/100:.2f}",
                    f"{gr['share']/100:.2f}"])
        for e in data["other"]:
            w.writerow([e["type"], e["entry_date"], "", e["source_ref"] or "",
                        e["description"] or "", "", "", "",
                        f"{e['amount_cents']/100:.2f}"])
        buf.seek(0)
        return send_file(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                         mimetype="text/csv", as_attachment=True,
                         download_name=f"sales-{data['consignor']['name']}-{d_from}-to-{d_to}.csv")
    return render_template("report.html", consignors=consignor_rows, cid=cid,
                           d_from=d_from, d_to=d_to, data=data)


# ---------------------------------------------------------------- 1099 / aging / ledger

@app.route("/1099")
def ten99():
    conn = get_conn()
    rows = conn.execute(
        """SELECT c.id, c.name, c.business_name, c.w9_on_file,
                  substr(l.entry_date,1,4) AS year,
                  SUM(-l.amount_cents) AS paid
           FROM ledger l JOIN consignors c ON c.id=l.consignor_id
           WHERE l.type='PAYOUT'
           GROUP BY c.id, year ORDER BY year DESC, c.name"""
    ).fetchall()
    conn.close()
    return render_template("ten99.html", rows=rows, threshold=60000)


@app.route("/aging")
def aging():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) c FROM inventory_items").fetchone()["c"]
    items = conn.execute(
        """SELECT i.*, c.name AS consignor_name,
                  CAST(julianday('now') - julianday(listed_date) AS INTEGER) AS days_listed
           FROM inventory_items i LEFT JOIN consignors c ON c.id=i.consignor_id
           WHERE i.sold=0 ORDER BY days_listed DESC"""
    ).fetchall() if count else []
    conn.close()
    return render_template("aging.html", items=items, count=count)


@app.route("/ledger/<int:cid>")
def ledger_view(cid):
    conn = get_conn()
    consignor = conn.execute("SELECT * FROM consignors WHERE id=?", (cid,)).fetchone()
    if not consignor:
        abort(404)
    entries = conn.execute(
        "SELECT * FROM ledger WHERE consignor_id=? ORDER BY id", (cid,)).fetchall()
    running = 0
    rows = []
    for e in entries:
        running += e["amount_cents"]
        rows.append({**dict(e), "running": running})
    rows.reverse()
    conn.close()
    return render_template("ledger.html", consignor=consignor, rows=rows,
                           balance=running, today=today())


@app.route("/ledger/<int:cid>/adjust", methods=["POST"])
def ledger_adjust(cid):
    f = request.form
    note = f.get("note", "").strip()
    if not note:
        flash("Adjustments require a note.", "error")
        return redirect(url_for("ledger_view", cid=cid))
    try:
        amount = parse_cents(f.get("amount"))
    except ValueError:
        flash("Adjustment amount not understood.", "error")
        return redirect(url_for("ledger_view", cid=cid))
    if amount == 0:
        flash("Adjustment amount can't be zero.", "error")
        return redirect(url_for("ledger_view", cid=cid))
    conn = get_conn()
    conn.execute(
        """INSERT INTO ledger (consignor_id, entry_date, type, description,
           amount_cents, note, manually_edited)
           VALUES (?,?, 'ADJUSTMENT', ?, ?, ?, 1)""",
        (cid, f.get("date") or today(), f.get("description", "").strip() or "Manual adjustment",
         amount, note))
    db.audit(conn, "ledger", cid, "adjustment", None,
             f"{fmt_money(amount)}: {note}", "manual adjustment")
    conn.commit()
    conn.close()
    flash("Adjustment recorded.", "ok")
    return redirect(url_for("ledger_view", cid=cid))


@app.route("/audit")
def audit_view():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
    conn.close()
    return render_template("audit.html", rows=rows)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5111, debug=False)
