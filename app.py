from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import pg8000.native
import os
from datetime import date, timedelta
from functools import wraps
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = "wird_tracker_secret_key_2026"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

START_DATE = date(2026, 6, 27)
END_DATE   = date(2026, 7, 3)

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


# ────────────────────────────────────────────────────────────────
# قاعدة البيانات - pg8000.native
# ────────────────────────────────────────────────────────────────

def get_db():
    p = urlparse(DATABASE_URL)
    conn = pg8000.native.Connection(
        host=p.hostname,
        port=p.port or 5432,
        database=p.path.lstrip("/"),
        user=p.username,
        password=p.password,
        ssl_context=True,
    )
    return conn

def qone(conn, sql, params=None):
    """تنفيذ query وإرجاع صف واحد كـ dict"""
    if params:
        rows = conn.run(sql, **{f"p{i+1}": v for i, v in enumerate(params)})
    else:
        rows = conn.run(sql)
    if not rows:
        return None
    cols = [c["name"] for c in conn.columns]
    return dict(zip(cols, rows[0]))

def qall(conn, sql, params=None):
    """تنفيذ query وإرجاع كل الصفوف كـ list of dicts"""
    if params:
        rows = conn.run(sql, **{f"p{i+1}": v for i, v in enumerate(params)})
    else:
        rows = conn.run(sql)
    if not rows:
        return []
    cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]

def qrun(conn, sql, params=None):
    """تنفيذ query بدون إرجاع نتيجة"""
    if params:
        conn.run(sql, **{f"p{i+1}": v for i, v in enumerate(params)})
    else:
        conn.run(sql)

# تحويل placeholders من :1,:2 لـ $p1,$p2
def ph(sql):
    """بدّل :1 :2 :3 ... بـ :p1 :p2 :p3 ..."""
    import re
    return re.sub(r':(\d+)', lambda m: f':p{m.group(1)}', sql)


def init_db():
    conn = get_db()

    conn.run("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            plain_password TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS wirds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            order_num INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.run("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            wird_id INTEGER NOT NULL,
            record_date TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(user_id, wird_id, record_date)
        )
    """)

    try:
        conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS plain_password TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    rows = conn.run("SELECT COUNT(*) as cnt FROM wirds")
    cnt = rows[0][0] if rows else 0
    if cnt == 0:
        for i, w in enumerate(DEFAULT_WIRDS):
            conn.run(
                "INSERT INTO wirds (name, order_num) VALUES (:p1, :p2)",
                p1=w, p2=i
            )

    rows = conn.run("SELECT COUNT(*) as cnt FROM users WHERE role='owner'")
    cnt = rows[0][0] if rows else 0
    if cnt == 0:
        conn.run(
            "INSERT INTO users (username, password, plain_password, role) VALUES (:p1,:p2,:p3,:p4)",
            p1="owner",
            p2=generate_password_hash("owner123"),
            p3="owner123",
            p4="owner"
        )

    conn.close()


# ────────────────────────────────────────────────────────────────
# Decorators
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
# Helpers
# ────────────────────────────────────────────────────────────────

def get_period_days():
    days = []
    current = START_DATE
    while current <= END_DATE:
        days.append(current)
        current += timedelta(days=1)
    return days


# ────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" in session:
        role = session.get("role")
        if role == "owner":   return redirect(url_for("owner_dashboard"))
        elif role == "admin": return redirect(url_for("admin_dashboard"))
        else:                 return redirect(url_for("user_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = qone(conn, "SELECT * FROM users WHERE username=:p1", (username,))
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
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
    today       = date.today()
    period_days = get_period_days()

    selected_str = request.args.get("date", "")
    try:
        selected_date = date.fromisoformat(selected_str)
        if not (START_DATE <= selected_date <= END_DATE):
            raise ValueError
    except ValueError:
        selected_date = max(START_DATE, min(today, END_DATE))

    conn  = get_db()
    wirds = qall(conn, "SELECT * FROM wirds WHERE active=1 ORDER BY order_num")

    if request.method == "POST":
        action = request.form.get("action", "save_wirds")

        if action == "change_password":
            old_pw  = request.form.get("old_password", "")
            new_pw  = request.form.get("new_password", "")
            new_pw2 = request.form.get("new_password2", "")
            user = qone(conn, "SELECT * FROM users WHERE id=:p1", (session["user_id"],))
            if not check_password_hash(user["password"], old_pw):
                flash("كلمة السر القديمة غلط ❌", "error")
            elif new_pw != new_pw2:
                flash("كلمة السر الجديدة مش متطابقة ❌", "error")
            elif len(new_pw) < 4:
                flash("كلمة السر لازم تكون 4 حروف على الأقل", "error")
            else:
                qrun(conn,
                    "UPDATE users SET password=:p1, plain_password=:p2 WHERE id=:p3",
                    (generate_password_hash(new_pw), new_pw, session["user_id"])
                )
                flash("تم تغيير كلمة السر بنجاح ✅", "success")

        else:
            rec_date_str = request.form.get("record_date", selected_date.isoformat())
            try:
                rec_date = date.fromisoformat(rec_date_str)
                if not (START_DATE <= rec_date <= END_DATE):
                    raise ValueError
            except ValueError:
                rec_date = selected_date

            for wird in wirds:
                status = request.form.get(f"wird_{wird['id']}")
                if status in ("ada2", "qadaa", "gharama"):
                    qrun(conn, """
                        INSERT INTO records (user_id, wird_id, record_date, status)
                        VALUES (:p1, :p2, :p3, :p4)
                        ON CONFLICT (user_id, wird_id, record_date)
                        DO UPDATE SET status=EXCLUDED.status
                    """, (session["user_id"], wird["id"], rec_date.isoformat(), status))
            flash(f"تم حفظ أوراد {rec_date.strftime('%d/%m')} ✅", "success")
            conn.close()
            return redirect(url_for("user_dashboard", date=rec_date.isoformat()))

    records_rows = qall(conn,
        "SELECT wird_id, status FROM records WHERE user_id=:p1 AND record_date=:p2",
        (session["user_id"], selected_date.isoformat()))
    records_selected = {r["wird_id"]: r["status"] for r in records_rows}

    stats = []
    for d in period_days:
        day_rows = qall(conn,
            "SELECT wird_id, status FROM records WHERE user_id=:p1 AND record_date=:p2",
            (session["user_id"], d.isoformat()))
        day_rec = {r["wird_id"]: r["status"] for r in day_rows}
        stats.append({
            "date":    d,
            "records": day_rec,
            "ada2":    sum(1 for v in day_rec.values() if v == "ada2"),
            "qadaa":   sum(1 for v in day_rec.values() if v == "qadaa"),
            "gharama": sum(1 for v in day_rec.values() if v == "gharama"),
            "missing": len(wirds) - len(day_rec),
        })

    conn.close()
    return render_template("user_dashboard.html",
                           wirds=wirds, records_selected=records_selected,
                           selected_date=selected_date, today=today,
                           stats=stats, START_DATE=START_DATE, END_DATE=END_DATE)


# ──── صفحة الأدمن ────

@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    conn        = get_db()
    users       = qall(conn, "SELECT * FROM users WHERE role='user'")
    wirds       = qall(conn, "SELECT * FROM wirds WHERE active=1 ORDER BY order_num")
    period_days = get_period_days()

    report = []
    for user in users:
        user_data = {"username": user["username"], "days": []}
        total_ada2 = total_qadaa = total_gharama = total_missing = 0
        for d in period_days:
            rows = qall(conn,
                "SELECT wird_id, status FROM records WHERE user_id=:p1 AND record_date=:p2",
                (user["id"], d.isoformat()))
            day_rec = {r["wird_id"]: r["status"] for r in rows}
            ada2    = sum(1 for v in day_rec.values() if v == "ada2")
            qadaa   = sum(1 for v in day_rec.values() if v == "qadaa")
            gharama = sum(1 for v in day_rec.values() if v == "gharama")
            missing = len(wirds) - len(day_rec)
            total_ada2 += ada2; total_qadaa += qadaa
            total_gharama += gharama; total_missing += missing
            user_data["days"].append({
                "date": d, "records": day_rec,
                "ada2": ada2, "qadaa": qadaa,
                "gharama": gharama, "missing": missing,
            })
        total_wirds = len(wirds) * len(period_days)
        user_data.update({
            "total_ada2": total_ada2, "total_qadaa": total_qadaa,
            "total_gharama": total_gharama, "total_missing": total_missing,
            "completion_pct": round(total_ada2 / total_wirds * 100) if total_wirds else 0,
        })
        report.append(user_data)

    daily_reports = []
    for d in period_days:
        day_data = {"date": d, "users": [],
                    "total_ada2": 0, "total_qadaa": 0,
                    "total_gharama": 0, "total_missing": 0}
        for user in users:
            rows = qall(conn,
                "SELECT wird_id, status FROM records WHERE user_id=:p1 AND record_date=:p2",
                (user["id"], d.isoformat()))
            day_rec = {r["wird_id"]: r["status"] for r in rows}
            ada2    = sum(1 for v in day_rec.values() if v == "ada2")
            qadaa   = sum(1 for v in day_rec.values() if v == "qadaa")
            gharama = sum(1 for v in day_rec.values() if v == "gharama")
            missing = len(wirds) - len(day_rec)
            day_data["users"].append({
                "username": user["username"], "records": day_rec,
                "ada2": ada2, "qadaa": qadaa,
                "gharama": gharama, "missing": missing,
            })
            day_data["total_ada2"]    += ada2
            day_data["total_qadaa"]   += qadaa
            day_data["total_gharama"] += gharama
            day_data["total_missing"] += missing
        daily_reports.append(day_data)

    conn.close()
    return render_template("admin_dashboard.html",
                           report=report, daily_reports=daily_reports,
                           wirds=wirds, START_DATE=START_DATE, END_DATE=END_DATE)


# ──── صفحة صاحب النظام ────

@app.route("/owner", methods=["GET", "POST"])
@login_required
@role_required("owner")
def owner_dashboard():
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_user":
            uname = request.form.get("username", "").strip()
            pw    = request.form.get("password", "")
            role  = request.form.get("role", "user")
            if uname and pw and role in ("user", "admin"):
                try:
                    qrun(conn,
                        "INSERT INTO users (username, password, plain_password, role) VALUES (:p1,:p2,:p3,:p4)",
                        (uname, generate_password_hash(pw), pw, role)
                    )
                    flash(f"تم إضافة '{uname}' ✅", "success")
                except Exception:
                    flash("الاسم ده موجود بالفعل", "error")

        elif action == "delete_user":
            uid = request.form.get("user_id")
            qrun(conn, "DELETE FROM users WHERE id=:p1 AND role != 'owner'", (uid,))
            flash("تم حذف المستخدم", "success")

        elif action == "reset_password":
            uid    = request.form.get("user_id")
            new_pw = request.form.get("new_password", "").strip()
            if new_pw and len(new_pw) >= 4:
                qrun(conn,
                    "UPDATE users SET password=:p1, plain_password=:p2 WHERE id=:p3 AND role != 'owner'",
                    (generate_password_hash(new_pw), new_pw, uid)
                )
                flash("تم تغيير كلمة السر ✅", "success")
            else:
                flash("كلمة السر لازم تكون 4 حروف على الأقل", "error")

        elif action == "add_wird":
            wname = request.form.get("wird_name", "").strip()
            if wname:
                r  = qone(conn, "SELECT MAX(order_num) as mx FROM wirds")
                mx = r["mx"] if r and r["mx"] is not None else 0
                qrun(conn, "INSERT INTO wirds (name, order_num) VALUES (:p1,:p2)", (wname, mx + 1))
                flash("تم إضافة الورد ✅", "success")

        elif action == "delete_wird":
            wid = request.form.get("wird_id")
            qrun(conn, "UPDATE wirds SET active=0 WHERE id=:p1", (wid,))
            flash("تم حذف الورد", "success")

        elif action == "edit_wird":
            wid   = request.form.get("wird_id")
            wname = request.form.get("wird_name", "").strip()
            if wid and wname:
                qrun(conn, "UPDATE wirds SET name=:p1 WHERE id=:p2", (wname, wid))
                flash("تم تعديل الورد ✅", "success")

        conn.close()
        return redirect(url_for("owner_dashboard"))

    users = qall(conn, "SELECT * FROM users WHERE role != 'owner' ORDER BY role, username")
    wirds = qall(conn, "SELECT * FROM wirds WHERE active=1 ORDER BY order_num")
    conn.close()
    return render_template("owner_dashboard.html", users=users, wirds=wirds)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
