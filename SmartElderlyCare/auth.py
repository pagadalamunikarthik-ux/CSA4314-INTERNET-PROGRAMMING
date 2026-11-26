from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_connection

auth_bp = Blueprint("auth", __name__)


def verify_password(stored_password, entered_password):
    if not stored_password:
        return False

    try:
        if check_password_hash(stored_password, entered_password):
            return True
    except Exception:
        pass

    # Support old plain-text passwords and upgrade them
    if stored_password == entered_password:
        return True

    return False


@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT user_id, full_name, email, password, role
            FROM users
            WHERE email=%s
        """, (email,))

        user = cursor.fetchone()

        if not user or not verify_password(user["password"], password):
            cursor.close()
            connection.close()
            return render_template(
                "login.html",
                error="Invalid email or password"
            )

        # Upgrade plain-text passwords to secure hashes
        if user["password"] == password:
            new_hash = generate_password_hash(password)
            cursor.execute("""
                UPDATE users SET password=%s
                WHERE user_id=%s
            """, (new_hash, user["user_id"]))
            connection.commit()

        role = user["role"].lower().strip()

        if role not in ["admin", "caregiver", "family", "elder"]:
            cursor.close()
            connection.close()
            return render_template(
                "login.html",
                error="This account has an unsupported role."
            )

        session.clear()
        session["user_id"] = user["user_id"]
        session["name"] = user["full_name"]
        session["email"] = user["email"]
        session["role"] = role

        if role == "caregiver":
            cursor.execute("""
                SELECT caregiver_id
                FROM caregivers
                WHERE user_id=%s
            """, (user["user_id"],))
            caregiver = cursor.fetchone()

            if not caregiver:
                cursor.close()
                connection.close()
                session.clear()
                return render_template(
                    "login.html",
                    error="No caregiver profile is linked to this account."
                )

            session["caregiver_id"] = caregiver["caregiver_id"]

        elif role == "elder":
            cursor.execute("""
                SELECT elderly_id
                FROM elderly_profiles
                WHERE user_id=%s
            """, (user["user_id"],))
            elder = cursor.fetchone()

            if not elder:
                cursor.close()
                connection.close()
                session.clear()
                return render_template(
                    "login.html",
                    error="No elderly profile is linked to this account."
                )

            session["elderly_id"] = elder["elderly_id"]

        elif role == "family":
            cursor.execute("""
                SELECT family_id, elderly_id
                FROM family_members
                WHERE user_id=%s
            """, (user["user_id"],))
            family = cursor.fetchone()

            if not family:
                cursor.close()
                connection.close()
                session.clear()
                return render_template(
                    "login.html",
                    error="No family profile is linked to this account."
                )

            session["family_id"] = family["family_id"]
            session["elderly_id"] = family["elderly_id"]

        cursor.close()
        connection.close()

        if role == "admin":
            return redirect("/")
        elif role == "caregiver":
            return redirect("/caregiver-dashboard")
        elif role == "elder":
            return redirect("/elder-dashboard")
        else:
            return redirect("/family-dashboard")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/caregiver-dashboard")
def caregiver_dashboard():

    if session.get("role") != "caregiver":
        return redirect("/login")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT v.visit_id, e.full_name, v.scheduled_date,
               v.scheduled_time, v.visit_status, v.notes
        FROM visits v
        JOIN elderly_profiles e ON v.elderly_id=e.elderly_id
        WHERE v.caregiver_id=%s
        ORDER BY v.scheduled_date DESC, v.scheduled_time DESC
    """, (session["caregiver_id"],))

    visits = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "caregiver_dashboard.html",
        visits=visits
    )


@auth_bp.route("/elder-dashboard")
def elder_dashboard():

    if session.get("role") != "elder":
        return redirect("/login")

    elderly_id = session["elderly_id"]

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM elderly_profiles
        WHERE elderly_id=%s
    """, (elderly_id,))
    elder = cursor.fetchone()

    cursor.execute("""
        SELECT * FROM medications
        WHERE elderly_id=%s
    """, (elderly_id,))
    medications = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM vital_records
        WHERE elderly_id=%s
        ORDER BY recorded_at DESC
    """, (elderly_id,))
    health_records = cursor.fetchall()

    cursor.execute("""
        SELECT v.visit_id, v.scheduled_date, v.scheduled_time,
               v.visit_status, u.full_name AS caregiver_name
        FROM visits v
        JOIN caregivers c ON v.caregiver_id=c.caregiver_id
        JOIN users u ON c.user_id=u.user_id
        WHERE v.elderly_id=%s
        ORDER BY v.scheduled_date DESC
    """, (elderly_id,))
    visits = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "elder_dashboard.html",
        elder=elder,
        medications=medications,
        health_records=health_records,
        visits=visits
    )


@auth_bp.route("/family-dashboard")
def family_dashboard():

    if session.get("role") != "family":
        return redirect("/login")

    elderly_id = session["elderly_id"]

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM elderly_profiles
        WHERE elderly_id=%s
    """, (elderly_id,))
    elder = cursor.fetchone()

    cursor.execute("""
        SELECT * FROM medications
        WHERE elderly_id=%s
    """, (elderly_id,))
    medications = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM medication_logs
        WHERE elderly_id=%s
        ORDER BY administered_at DESC
    """, (elderly_id,))
    medication_logs = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM vital_records
        WHERE elderly_id=%s
        ORDER BY recorded_at DESC
    """, (elderly_id,))
    health_records = cursor.fetchall()

    cursor.execute("""
        SELECT v.visit_id, v.scheduled_date, v.scheduled_time,
               v.visit_status, u.full_name AS caregiver_name
        FROM visits v
        LEFT JOIN caregivers c ON v.caregiver_id=c.caregiver_id
        LEFT JOIN users u ON c.user_id=u.user_id
        WHERE v.elderly_id=%s
        ORDER BY v.scheduled_date DESC
    """, (elderly_id,))
    visits = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM emergency_incidents
        WHERE elderly_id=%s
        ORDER BY reported_at DESC
    """, (elderly_id,))
    incidents = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM notifications
        WHERE elderly_id=%s
        ORDER BY created_at DESC
    """, (elderly_id,))
    notifications = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "family_dashboard.html",
        elder=elder,
        medications=medications,
        medication_logs=medication_logs,
        health_records=health_records,
        visits=visits,
        incidents=incidents,
        notifications=notifications
    )