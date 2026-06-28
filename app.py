from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import pg8000
import pg8000.native
import os
from datetime import date, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = "wird_tracker_secret_key_2026"

DATABASE_URL = os.environ.get("DATABASE_URL")

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
# قاعدة البيانات
# ────────────────────────────────────────────────────────────────

def get_db():
    conn = pg8000.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            plain_password TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS wirds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            order_num INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            wird_id INTEGER NOT NULL,
            record_date TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(user_id, wird_id, record_date)
        )
    """)

    # أضف عمود plain_password لو مش موجود (للترقية)
    c.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS plain_password TEXT NOT NULL DEFAULT ''
    """)

    # أضف الأوراد الافتراضية لو مفيش
    c.execute("SELECT COUNT(*) as cnt FROM wirds")
    if c.fetchone()["cnt"] == 0:
        for i, w in enumerate(DEFAULT_WIRDS):
            c.execute("INSERT INTO wirds (name, order_num) VALUES (%s, %s)", (w, i))

    # أضف الـ owner لو مش موجود
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE role='owner'")
    if c.fetchone()["cnt"] == 0:
        c.execute(
            "INSERT INTO users (username, password, plain_password, role) VALUES (%s, %s, %s, %s)",
            ("owner", generate_password_hash("owner123"), "owner123", "owner")
        )

    conn.commit()
    c.close()
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
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = c.fetchone()
        c.close()
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
    today        = date.today()
    period_days  = get_period_days()

    # اليوم المختار
    selected_str = request.args.get("date", "")
    try:
        selected_date = date.fromisoformat(selected_str)
        if not (START_DATE <= selected_date <= END_DATE):
            raise ValueError
    except ValueError:
        selected_date = max(START_DATE, min(today, END_DATE))

    conn = get_db()
    c    = conn.cursor()
    c.execute("SELECT * FROM wirds WHERE active=1 ORDER BY order_num")
    wirds = c.fetchall()

    # حفظ الأوراد
    if request.method == "POST":
        action = request.form.get("action", "save_wirds")

        if action == "change_password":
            old_pw  = request.form.get("old_password", "")
            new_pw  = request.form.get("new_password", "")
            new_pw2 = request.form.get("new_password2", "")
            c.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
            user = c.fetchone()
            if not check_password_hash(user["password"], old_pw):
                flash("كلمة السر القديمة غلط ❌", "error")
            elif new_pw != new_pw2:
                flash("كلمة السر الجديدة مش متطابقة ❌", "error")
            elif len(new_pw) < 4:
                flash("كلمة السر لازم تكون 4 حروف على الأقل", "error")
            else:
                c.execute(
                    "UPDATE users SET password=%s, plain_password=%s WHERE id=%s",
                    (generate_password_hash(new_pw), new_pw, session["user_id"])
                )
                conn.commit()
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
                    c.execute("""
                        INSERT INTO records (user_id, wird_id, record_date, status)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id, wird_id, record_date)
                        DO UPDATE SET status=EXCLUDED.status
                    """, (session["user_id"], wird["id"], rec_date.isoformat(), status))
            conn.commit()
            flash(f"تم حفظ أوراد {rec_date.strftime('%d/%m')} ✅", "success")
            c.close()
            conn.close()
            return redirect(url_for("user_dashboard", date=rec_date.isoformat()))

    # سجلات اليوم المختار
    c.execute("""
        SELECT wird_id, status FROM records
        WHERE user_id=%s AND record_date=%s
    """, (session["user_id"], selected_date.isoformat()))
    records_selected = {r["wird_id"]: r["status"] for r in c.fetchall()}

    # إحصائيات الأسبوع
    stats = []
    for d in period_days:
        c.execute("""
            SELECT wird_id, status FROM records
            WHERE user_id=%s AND record_date=%s
        """, (session["user_id"], d.isoformat()))
        day_rec = {r["wird_id"]: r["status"] for r in c.fetchall()}
        stats.append({
            "date":    d,
            "records": day_rec,
            "ada2":    sum(1 for v in day_rec.values() if v == "ada2"),
            "qadaa":   sum(1 for v in day_rec.values() if v == "qadaa"),
            "gharama": sum(1 for v in day_rec.values() if v == "gharama"),
            "missing": len(wirds) - len(day_rec),
        })

    c.close()
    conn.close()
    return render_template("user_dashboard.html",
                           wirds=wirds,
                           records_selected=records_selected,
                           selected_date=selected_date,
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
    c    = conn.cursor()
    c.execute("SELECT * FROM users WHERE role='user'")
    users = c.fetchall()
    c.execute("SELECT * FROM wirds WHERE active=1 ORDER BY order_num")
    wirds = c.fetchall()
    period_days = get_period_days()

    # التقرير الإجمالي
    report = []
    for user in users:
        user_data = {"username": user["username"], "days": []}
        total_ada2 = total_qadaa = total_gharama = total_missing = 0
        for d in period_days:
            c.execute("""
                SELECT wird_id, status FROM records
                WHERE user_id=%s AND record_date=%s
            """, (user["id"], d.isoformat()))
            day_rec = {r["wird_id"]: r["status"] for r in c.fetchall()}
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

    # التقارير اليومية
    daily_reports = []
    for d in period_days:
        day_data = {"date": d, "users": [],
                    "total_ada2": 0, "total_qadaa": 0,
                    "total_gharama": 0, "total_missing": 0}
        for user in users:
            c.execute("""
                SELECT wird_id, status FROM records
                WHERE user_id=%s AND record_date=%s
            """, (user["id"], d.isoformat()))
            day_rec = {r["wird_id"]: r["status"] for r in c.fetchall()}
            ada2    = sum(1 for v in day_rec.values() if v == "ada2")
            qadaa   = sum(1 for v in day_rec.values() if v == "qadaa")
            gharama = sum(1 for v in day_rec.values() if v == "gharama")
            missing = len(wirds) - len(day_rec)
            day_data["users"].append({
                "username": user["username"], "records": day_rec,
                "ada2": ada2, "qadaa": qadaa,
                "gharama": gharama, "missing": missing,
            })
            day_data["total_ada2"] += ada2
            day_data["total_qadaa"] += qadaa
            day_data["total_gharama"] += gharama
            day_data["total_missing"] += missing
        daily_reports.append(day_data)

    c.close()
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
    c    = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_user":
            uname = request.form.get("username", "").strip()
            pw    = request.form.get("password", "")
            role  = request.form.get("role", "user")
            if uname and pw and role in ("user", "admin"):
                try:
                    c.execute(
                        "INSERT INTO users (username, password, plain_password, role) VALUES (%s,%s,%s,%s)",
                        (uname, generate_password_hash(pw), pw, role)
                    )
                    conn.commit()
                    flash(f"تم إضافة '{uname}' ✅", "success")
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    flash("الاسم ده موجود بالفعل", "error")

        elif action == "delete_user":
            uid = request.form.get("user_id")
            c.execute("DELETE FROM users WHERE id=%s AND role != 'owner'", (uid,))
            conn.commit()
            flash("تم حذف المستخدم", "success")

        elif action == "reset_password":
            uid    = request.form.get("user_id")
            new_pw = request.form.get("new_password", "").strip()
            if new_pw and len(new_pw) >= 4:
                c.execute(
                    "UPDATE users SET password=%s, plain_password=%s WHERE id=%s AND role != 'owner'",
                    (generate_password_hash(new_pw), new_pw, uid)
                )
                conn.commit()
                flash("تم تغيير كلمة السر ✅", "success")
            else:
                flash("كلمة السر لازم تكون 4 حروف على الأقل", "error")

        elif action == "add_wird":
            wname = request.form.get("wird_name", "").strip()
            if wname:
                c.execute("SELECT MAX(order_num) as mx FROM wirds")
                mx = c.fetchone()["mx"] or 0
                c.execute("INSERT INTO wirds (name, order_num) VALUES (%s,%s)", (wname, mx + 1))
                conn.commit()
                flash(f"تم إضافة الورد ✅", "success")

        elif action == "delete_wird":
            wid = request.form.get("wird_id")
            c.execute("UPDATE wirds SET active=0 WHERE id=%s", (wid,))
            conn.commit()
            flash("تم حذف الورد", "success")

        elif action == "edit_wird":
            wid   = request.form.get("wird_id")
            wname = request.form.get("wird_name", "").strip()
            if wid and wname:
                c.execute("UPDATE wirds SET name=%s WHERE id=%s", (wname, wid))
                conn.commit()
                flash("تم تعديل الورد ✅", "success")

        c.close()
        conn.close()
        return redirect(url_for("owner_dashboard"))

    c.execute("SELECT * FROM users WHERE role != 'owner' ORDER BY role, username")
    users = c.fetchall()
    c.execute("SELECT * FROM wirds WHERE active=1 ORDER BY order_num")
    wirds = c.fetchall()
    c.close()
    conn.close()
    return render_template("owner_dashboard.html", users=users, wirds=wirds)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
