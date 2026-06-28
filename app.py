from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os
from datetime import date, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = "wird_tracker_secret_key_2026"

DB = "wird.db"

# قائمة الأوراد اليومية
DEFAULT_WIRDS = [
    "سنة المغرب البعدية ركعتان",
    "سنة العشاء البعدية ركعتان",
    "قيام الليل بعشر آيات",
    "خمس دقائق دعاء",
    "100 صلاة على النبي ﷺ",
    "100 استغفار",
    "ركعتا الضحى",
    "قراءة جزء من القرآن",
    "سنة الظهر القبلية 4 ركعات",
    "سنة الظهر البعدية ركعتان",
]

START_DATE = date(2026, 6, 27)
END_DATE   = date(2026, 7, 3)


# ────────────────────────────────────────────────────────────────
# قاعدة البيانات
# ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS wirds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            order_num INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            wird_id INTEGER NOT NULL,
            record_date TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(user_id, wird_id, record_date),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(wird_id) REFERENCES wirds(id)
        )
    """)

    # أضف الأوراد الافتراضية إذا مفيش
    count = c.execute("SELECT COUNT(*) FROM wirds").fetchone()[0]
    if count == 0:
        for i, w in enumerate(DEFAULT_WIRDS):
            c.execute("INSERT INTO wirds (name, order_num) VALUES (?, ?)", (w, i))

    # أضف حساب صاحب النظام إذا مفيش
    count = c.execute("SELECT COUNT(*) FROM users WHERE role='owner'").fetchone()[0]
    if count == 0:
        pw = generate_password_hash("owner123")
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ("owner", pw, "owner"))

    conn.commit()
    conn.close()


# ────────────────────────────────────────────────────────────────
# Decorators للصلاحيات
# ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("role") not in roles:
                flash("مش عندك صلاحية تدخل هنا", "error")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ────────────────────────────────────────────────────────────────
# المسارات (Routes)
# ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" in session:
        role = session.get("role")
        if role == "owner":
            return redirect(url_for("owner_dashboard"))
        elif role == "admin":
            return redirect(url_for("admin_dashboard"))
        else:
            return redirect(url_for("user_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("index"))
        flash("اسم المستخدم أو كلمة السر غلط", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ──── صفحة المستخدم ────

@app.route("/user", methods=["GET", "POST"])
@login_required
@role_required("user")
def user_dashboard():
    today = date.today()

    # لو خارج فترة الأوراد
    in_period = START_DATE <= today <= END_DATE

    conn = get_db()
    wirds = conn.execute("SELECT * FROM wirds WHERE active=1 ORDER BY order_num").fetchall()

    if request.method == "POST" and in_period:
        for wird in wirds:
            status = request.form.get(f"wird_{wird['id']}")
            if status in ("ada2", "qadaa", "gharama"):
                conn.execute("""
                    INSERT INTO records (user_id, wird_id, record_date, status)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, wird_id, record_date)
                    DO UPDATE SET status=excluded.status
                """, (session["user_id"], wird["id"], today.isoformat(), status))
        conn.commit()
        flash("تم حفظ الأوراد بنجاح ✅", "success")

    # اجيب السجلات الحالية لليوم ده
    records_today = {}
    rows = conn.execute("""
        SELECT wird_id, status FROM records
        WHERE user_id=? AND record_date=?
    """, (session["user_id"], today.isoformat())).fetchall()
    for r in rows:
        records_today[r["wird_id"]] = r["status"]

    # إحصائيات الأسبوع
    stats = []
    current = START_DATE
    while current <= END_DATE:
        day_records = conn.execute("""
            SELECT w.name, r.status FROM records r
            JOIN wirds w ON w.id=r.wird_id
            WHERE r.user_id=? AND r.record_date=?
        """, (session["user_id"], current.isoformat())).fetchall()
        stats.append({"date": current, "records": day_records})
        current += timedelta(days=1)

    conn.close()
    return render_template("user_dashboard.html",
                           wirds=wirds,
                           records_today=records_today,
                           in_period=in_period,
                           today=today,
                           stats=stats,
                           START_DATE=START_DATE,
                           END_DATE=END_DATE)


# ──── صفحة الأدمن ────

@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    conn = get_db()
    users = conn.execute("SELECT * FROM users WHERE role='user'").fetchall()
    wirds = conn.execute("SELECT * FROM wirds WHERE active=1 ORDER BY order_num").fetchall()

    report = []
    for user in users:
        user_data = {"username": user["username"], "days": []}
        current = START_DATE
        total_ada2 = total_qadaa = total_gharama = total_missing = 0

        while current <= END_DATE:
            day_records = {}
            rows = conn.execute("""
                SELECT wird_id, status FROM records
                WHERE user_id=? AND record_date=?
            """, (user["id"], current.isoformat())).fetchall()
            for r in rows:
                day_records[r["wird_id"]] = r["status"]

            day_ada2 = sum(1 for v in day_records.values() if v == "ada2")
            day_qadaa = sum(1 for v in day_records.values() if v == "qadaa")
            day_gharama = sum(1 for v in day_records.values() if v == "gharama")
            day_missing = len(wirds) - len(day_records)

            total_ada2 += day_ada2
            total_qadaa += day_qadaa
            total_gharama += day_gharama
            total_missing += day_missing

            user_data["days"].append({
                "date": current,
                "records": day_records,
                "ada2": day_ada2,
                "qadaa": day_qadaa,
                "gharama": day_gharama,
                "missing": day_missing,
            })
            current += timedelta(days=1)

        total_wirds = len(wirds) * 7
        user_data["total_ada2"] = total_ada2
        user_data["total_qadaa"] = total_qadaa
        user_data["total_gharama"] = total_gharama
        user_data["total_missing"] = total_missing
        user_data["completion_pct"] = round(total_ada2 / total_wirds * 100) if total_wirds else 0
        report.append(user_data)

    conn.close()
    return render_template("admin_dashboard.html",
                           report=report, wirds=wirds,
                           START_DATE=START_DATE, END_DATE=END_DATE)


# ──── صفحة صاحب النظام ────

@app.route("/owner", methods=["GET", "POST"])
@login_required
@role_required("owner")
def owner_dashboard():
    conn = get_db()

    # إضافة مستخدم
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_user":
            uname = request.form.get("username", "").strip()
            pw    = request.form.get("password", "")
            role  = request.form.get("role", "user")
            if uname and pw and role in ("user", "admin"):
                try:
                    conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                                 (uname, generate_password_hash(pw), role))
                    conn.commit()
                    flash(f"تم إضافة المستخدم '{uname}' بنجاح ✅", "success")
                except sqlite3.IntegrityError:
                    flash("اسم المستخدم ده موجود بالفعل", "error")

        elif action == "delete_user":
            uid = request.form.get("user_id")
            conn.execute("DELETE FROM users WHERE id=? AND role != 'owner'", (uid,))
            conn.commit()
            flash("تم حذف المستخدم", "success")

        elif action == "add_wird":
            wname = request.form.get("wird_name", "").strip()
            if wname:
                max_order = conn.execute("SELECT MAX(order_num) FROM wirds").fetchone()[0] or 0
                conn.execute("INSERT INTO wirds (name, order_num) VALUES (?, ?)", (wname, max_order + 1))
                conn.commit()
                flash(f"تم إضافة الورد '{wname}' ✅", "success")

        elif action == "delete_wird":
            wid = request.form.get("wird_id")
            conn.execute("UPDATE wirds SET active=0 WHERE id=?", (wid,))
            conn.commit()
            flash("تم حذف الورد", "success")

        elif action == "edit_wird":
            wid   = request.form.get("wird_id")
            wname = request.form.get("wird_name", "").strip()
            if wid and wname:
                conn.execute("UPDATE wirds SET name=? WHERE id=?", (wname, wid))
                conn.commit()
                flash("تم تعديل الورد ✅", "success")

        conn.close()
        return redirect(url_for("owner_dashboard"))

    users = conn.execute("SELECT * FROM users WHERE role != 'owner' ORDER BY role, username").fetchall()
    wirds = conn.execute("SELECT * FROM wirds WHERE active=1 ORDER BY order_num").fetchall()
    conn.close()
    return render_template("owner_dashboard.html", users=users, wirds=wirds)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)