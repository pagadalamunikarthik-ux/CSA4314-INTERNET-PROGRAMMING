
import os
from flask import Flask, render_template, request, redirect, url_for, session, abort
from db import get_connection
from werkzeug.security import generate_password_hash
from visits import visits_bp
from notifications import notifications_bp
from scheduler import start_scheduler
from auth import auth_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

# Change the key to invalidate old login sessions.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "elderly-care-new-login-key-2026"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.register_blueprint(visits_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(auth_bp)


# ==========================================
# ROLE-BASED LOGIN PROTECTION
# ==========================================

@app.before_request
def check_user_access():

    # Login, logout and static files are public.
    if request.endpoint in ("auth.login", "auth.logout", "static"):
        return None

    # Both user_id and role must exist.
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id or not role:
        session.clear()
        return redirect(url_for("auth.login"))

    role = str(role).lower().strip()

    # Admin dashboard.
    if request.path == "/":
        if role == "admin":
            return None

        if role == "caregiver":
            return redirect(url_for("auth.caregiver_dashboard"))

        if role == "elder":
            return redirect(url_for("auth.elder_dashboard"))

        if role == "family":
            return redirect(url_for("auth.family_dashboard"))

    # Admin can access management pages.
    if role == "admin":
        return None

    path = request.path
    method = request.method

    # Caregiver permissions.
    if role == "caregiver":

        if path == "/caregiver-dashboard":
            return None

        if path == "/visits" or path.startswith("/visits/"):
            return None

    # Elder permissions.
    if role == "elder":

        if path == "/elder-dashboard":
            return None

    # Family permissions.
    if role == "family":

        if path == "/family-dashboard":
            return None

        if path == "/notifications" and method == "GET":
            return None

        if path.startswith("/notifications/read/") and method == "POST":
            return None

    abort(403)


# ==========================================
# ADMIN DASHBOARD
# ==========================================

@app.route("/")
def home():

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM elderly_profiles")
        elderly_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM caregivers")
        caregiver_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE scheduled_date=CURDATE()
        """)
        today_visits = cursor.fetchone()[0]

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "index.html",
        elderly_count=elderly_count,
        caregiver_count=caregiver_count,
        today_visits=today_visits
    )


# ==========================================
# ELDERLY MANAGEMENT
# ==========================================

@app.route("/elderly")
def elderly_page():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT elderly_id, full_name, age, gender, address,
               medical_conditions, emergency_contact
        FROM elderly_profiles
    """)

    elderly_list = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("elderly.html", elderly_list=elderly_list)


@app.route("/elderly/add", methods=["GET", "POST"])
def add_elderly():

    if request.method == "POST":

        connection = get_connection()
        cursor = connection.cursor()

        try:
            cursor.execute("""
                INSERT INTO elderly_profiles
                (full_name, age, gender, address,
                 medical_conditions, emergency_contact)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                request.form["full_name"],
                request.form["age"] or None,
                request.form["gender"],
                request.form["address"],
                request.form["medical_conditions"],
                request.form["emergency_contact"]
            ))

            elderly_id = cursor.lastrowid

            names = request.form.getlist("family_name[]")
            relationships = request.form.getlist("relationship[]")
            phones = request.form.getlist("family_phone[]")
            emails = request.form.getlist("family_email[]")
            primary = request.form.get("primary_family")

            for i, name in enumerate(names):

                name = name.strip()
                phone = phones[i].strip() if i < len(phones) else ""

                if name and phone:
                    cursor.execute("""
                        INSERT INTO family_members
                        (elderly_id, full_name, relationship,
                         phone, email, is_primary)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (
                        elderly_id,
                        name,
                        relationships[i] if i < len(relationships) else "",
                        phone,
                        emails[i] if i < len(emails) else "",
                        i == int(primary)
                        if primary and primary.isdigit()
                        else False
                    ))

            connection.commit()

        except Exception as error:
            connection.rollback()
            return f"Could not add elderly profile: {error}", 400

        finally:
            cursor.close()
            connection.close()

        return redirect("/elderly")

    return render_template("add_elderly.html")


@app.route("/elderly/view/<int:elderly_id>")
def view_elderly(elderly_id):

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM elderly_profiles
        WHERE elderly_id=%s
    """, (elderly_id,))

    person = cursor.fetchone()

    if person is None:
        cursor.close()
        connection.close()
        return "Profile not found", 404

    cursor.execute("""
        SELECT *
        FROM family_members
        WHERE elderly_id=%s
        ORDER BY is_primary DESC, family_id ASC
    """, (elderly_id,))

    family_members = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "elderly_detail.html",
        person=person,
        elderly=person,
        family_members=family_members
    )


@app.route("/elderly/edit/<int:elderly_id>", methods=["GET", "POST"])
def edit_elderly(elderly_id):

    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":

        cursor.execute("""
            UPDATE elderly_profiles
            SET full_name=%s, age=%s, gender=%s,
                address=%s, medical_conditions=%s,
                emergency_contact=%s
            WHERE elderly_id=%s
        """, (
            request.form["full_name"],
            request.form["age"] or None,
            request.form["gender"],
            request.form["address"],
            request.form["medical_conditions"],
            request.form["emergency_contact"],
            elderly_id
        ))

        connection.commit()
        cursor.close()
        connection.close()

        return redirect("/elderly")

    cursor.execute("""
        SELECT *
        FROM elderly_profiles
        WHERE elderly_id=%s
    """, (elderly_id,))

    person = cursor.fetchone()

    if person is None:
        cursor.close()
        connection.close()
        return "Profile not found", 404

    cursor.execute("""
        SELECT family_id, elderly_id, full_name,
               relationship, phone, email, is_primary
        FROM family_members
        WHERE elderly_id=%s
        ORDER BY is_primary DESC, family_id ASC
    """, (elderly_id,))

    family_members = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "edit_elderly.html",
        person=person,
        family_members=family_members
    )


@app.route("/elderly/delete/<int:elderly_id>", methods=["POST"])
def delete_elderly(elderly_id):

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            DELETE FROM elderly_profiles
            WHERE elderly_id=%s
        """, (elderly_id,))

        connection.commit()

    except Exception as error:
        connection.rollback()
        return f"Cannot delete profile: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return redirect("/elderly")


# ==========================================
# FAMILY MEMBER MANAGEMENT
# ==========================================

@app.route("/family/edit/<int:family_id>", methods=["POST"])
def edit_family_member(family_id):

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT elderly_id
            FROM family_members
            WHERE family_id=%s
        """, (family_id,))

        result = cursor.fetchone()

        if result is None:
            return "Family member not found", 404

        elderly_id = result[0]
        is_primary = 1 if request.form.get("is_primary") else 0

        if is_primary:
            cursor.execute("""
                UPDATE family_members
                SET is_primary=0
                WHERE elderly_id=%s
            """, (elderly_id,))

        cursor.execute("""
            UPDATE family_members
            SET full_name=%s, relationship=%s,
                phone=%s, email=%s, is_primary=%s
            WHERE family_id=%s
        """, (
            request.form["full_name"],
            request.form.get("relationship", ""),
            request.form["phone"],
            request.form.get("email", ""),
            is_primary,
            family_id
        ))

        connection.commit()

    except Exception as error:
        connection.rollback()
        return f"Could not update family member: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return redirect(f"/elderly/edit/{elderly_id}")


@app.route("/family/delete/<int:family_id>", methods=["POST"])
def delete_family_member(family_id):

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT elderly_id
            FROM family_members
            WHERE family_id=%s
        """, (family_id,))

        result = cursor.fetchone()

        if result is None:
            return "Family member not found", 404

        elderly_id = result[0]

        cursor.execute("""
            DELETE FROM family_members
            WHERE family_id=%s
        """, (family_id,))

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    return redirect(f"/elderly/edit/{elderly_id}")


# ==========================================
# CAREGIVER MANAGEMENT
# ==========================================

@app.route("/caregivers")
def caregivers_page():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT c.caregiver_id, u.full_name, u.email, c.phone,
               c.specialization, c.availability, c.status
        FROM caregivers c
        JOIN users u ON c.user_id=u.user_id
        ORDER BY c.caregiver_id DESC
    """)

    caregiver_list = cursor.fetchall()

    cursor.execute("""
        SELECT COUNT(*)
        FROM caregivers
        WHERE status='Available'
    """)
    available_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM caregivers
        WHERE status='Absent'
    """)
    absent_count = cursor.fetchone()[0]

    cursor.close()
    connection.close()

    return render_template(
        "caregivers.html",
        caregiver_list=caregiver_list,
        available_count=available_count,
        absent_count=absent_count,
        message=request.args.get("message"),
        warning=request.args.get("warning")
    )


@app.route("/caregivers/add", methods=["GET", "POST"])
def add_caregiver():

    if request.method == "POST":

        connection = get_connection()
        cursor = connection.cursor()

        try:
            password_hash = generate_password_hash(
                request.form["password"]
            )

            cursor.execute("""
                INSERT INTO users (full_name, email, password, role)
                VALUES (%s, %s, %s, 'caregiver')
            """, (
                request.form["full_name"],
                request.form["email"],
                password_hash
            ))

            user_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO caregivers
                (user_id, phone, specialization, availability, status)
                VALUES (%s, %s, %s, %s, 'Available')
            """, (
                user_id,
                request.form["phone"],
                request.form["specialization"],
                request.form["availability"]
            ))

            connection.commit()

        except Exception as error:
            connection.rollback()
            return f"Could not add caregiver: {error}", 400

        finally:
            cursor.close()
            connection.close()

        return redirect(url_for("caregivers_page"))

    return render_template("caregiver_form.html", caregiver=None)


@app.route("/caregivers/edit/<int:caregiver_id>", methods=["GET", "POST"])
def edit_caregiver(caregiver_id):

    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":

        cursor.execute("""
            UPDATE users u
            JOIN caregivers c ON u.user_id=c.user_id
            SET u.full_name=%s,
                c.phone=%s,
                c.specialization=%s,
                c.availability=%s
            WHERE c.caregiver_id=%s
        """, (
            request.form["full_name"],
            request.form["phone"],
            request.form["specialization"],
            request.form["availability"],
            caregiver_id
        ))

        connection.commit()
        cursor.close()
        connection.close()

        return redirect(url_for("caregivers_page"))

    cursor.execute("""
        SELECT c.caregiver_id, u.full_name, u.email, c.phone,
               c.specialization, c.availability
        FROM caregivers c
        JOIN users u ON c.user_id=u.user_id
        WHERE c.caregiver_id=%s
    """, (caregiver_id,))

    caregiver = cursor.fetchone()

    cursor.close()
    connection.close()

    if caregiver is None:
        return "Caregiver not found", 404

    return render_template("caregiver_form.html", caregiver=caregiver)


@app.route("/caregivers/status/<int:caregiver_id>", methods=["POST"])
def update_caregiver_status(caregiver_id):

    new_status = request.form.get("status")

    if new_status not in ["Available", "Absent"]:
        return "Invalid caregiver status", 400

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE caregivers
            SET status=%s
            WHERE caregiver_id=%s
        """, (new_status, caregiver_id))

        connection.commit()

    except Exception as error:
        connection.rollback()
        return f"Could not update caregiver status: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("caregivers_page"))


@app.route("/caregivers/delete/<int:caregiver_id>", methods=["POST"])
def delete_caregiver(caregiver_id):

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE caregiver_id=%s
            AND visit_status IN ('scheduled', 'in_progress')
        """, (caregiver_id,))

        if cursor.fetchone()[0] > 0:
            return "Reassign active visits before deleting this caregiver.", 400

        cursor.execute("""
            DELETE FROM caregivers
            WHERE caregiver_id=%s
        """, (caregiver_id,))

        connection.commit()

    except Exception as error:
        connection.rollback()
        return f"Could not delete caregiver: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("caregivers_page"))


# ==========================================
# MEDICATION MANAGEMENT
# ==========================================

@app.route("/medications")
def medications_page():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT m.medication_id, m.elderly_id, e.full_name,
               m.medicine_name, m.dosage, m.schedule, m.instructions
        FROM medications m
        JOIN elderly_profiles e ON m.elderly_id=e.elderly_id
        ORDER BY m.medication_id DESC
    """)

    medication_list = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "medications.html",
        medication_list=medication_list
    )


@app.route("/medications/add", methods=["GET", "POST"])
def add_medication():

    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":

        cursor.execute("""
            INSERT INTO medications
            (elderly_id, medicine_name, dosage, schedule, instructions)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            request.form["elderly_id"],
            request.form["medicine_name"],
            request.form["dosage"],
            request.form["schedule"],
            request.form["instructions"]
        ))

        connection.commit()
        cursor.close()
        connection.close()

        return redirect("/medications")

    cursor.execute("""
        SELECT elderly_id, full_name
        FROM elderly_profiles
    """)

    elderly_list = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "medication_form.html",
        medication=None,
        elderly_list=elderly_list
    )


@app.route("/medications/edit/<int:medication_id>", methods=["GET", "POST"])
def edit_medication(medication_id):

    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":

        cursor.execute("""
            UPDATE medications
            SET elderly_id=%s, medicine_name=%s, dosage=%s,
                schedule=%s, instructions=%s
            WHERE medication_id=%s
        """, (
            request.form["elderly_id"],
            request.form["medicine_name"],
            request.form["dosage"],
            request.form["schedule"],
            request.form["instructions"],
            medication_id
        ))

        connection.commit()
        cursor.close()
        connection.close()

        return redirect("/medications")

    cursor.execute("""
        SELECT medication_id, elderly_id, medicine_name,
               dosage, schedule, instructions
        FROM medications
        WHERE medication_id=%s
    """, (medication_id,))

    medication = cursor.fetchone()

    cursor.execute("""
        SELECT elderly_id, full_name
        FROM elderly_profiles
    """)

    elderly_list = cursor.fetchall()

    cursor.close()
    connection.close()

    if medication is None:
        return "Medication not found", 404

    return render_template(
        "medication_form.html",
        medication=medication,
        elderly_list=elderly_list
    )


@app.route("/medications/delete/<int:medication_id>", methods=["POST"])
def delete_medication(medication_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM medications
        WHERE medication_id=%s
    """, (medication_id,))

    connection.commit()
    cursor.close()
    connection.close()

    return redirect("/medications")


# ==========================================
# HEALTH MONITORING
# ==========================================

@app.route("/health")
def health_page():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT v.record_id, e.full_name, v.blood_pressure,
               v.heart_rate, v.temperature, v.oxygen_level,
               v.notes, v.recorded_at
        FROM vital_records v
        JOIN elderly_profiles e ON v.elderly_id=e.elderly_id
        ORDER BY v.recorded_at DESC
    """)

    records = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("health.html", records=records)


@app.route("/health/add", methods=["GET", "POST"])
def add_health():

    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":

        cursor.execute("""
            INSERT INTO vital_records
            (elderly_id, recorded_by, blood_pressure,
             heart_rate, temperature, oxygen_level, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            request.form["elderly_id"],
            request.form.get("recorded_by") or None,
            request.form["blood_pressure"],
            request.form["heart_rate"] or None,
            request.form["temperature"] or None,
            request.form["oxygen_level"] or None,
            request.form["notes"]
        ))

        connection.commit()
        cursor.close()
        connection.close()

        return redirect("/health")

    cursor.execute("""
        SELECT elderly_id, full_name
        FROM elderly_profiles
    """)

    elderly_list = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "health_form.html",
        elderly_list=elderly_list
    )


# ==========================================
# APPLICATION START
# ==========================================

if __name__ == "__main__":

    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler()

    app.run(debug=True)
