import os
import uuid
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename

from db import get_connection
from email_service import send_family_email

visits_bp = Blueprint("visits", __name__)

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def create_notification(elderly_id, title, message, notification_type):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO notifications
            (elderly_id, title, message, notification_type)
            VALUES (%s, %s, %s, %s)
        """, (elderly_id, title, message, notification_type))
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def get_visit_email_details(visit_id):
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                v.elderly_id,
                e.full_name AS elderly_name,
                u.full_name AS caregiver_name,
                v.scheduled_date,
                v.scheduled_time,
                v.check_in_time,
                v.check_out_time,
                v.notes,
                v.visit_photo,
                v.health_observations,
                v.medication_updates,
                v.visit_duration_minutes
            FROM visits v
            JOIN elderly_profiles e
                ON v.elderly_id = e.elderly_id
            JOIN caregivers c
                ON v.caregiver_id = c.caregiver_id
            JOIN users u
                ON c.user_id = u.user_id
            WHERE v.visit_id = %s
        """, (visit_id,))

        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


def notify_family(visit_id, event):
    details = get_visit_email_details(visit_id)

    if not details:
        return

    elderly_id = details["elderly_id"]
    elderly_name = details["elderly_name"]
    caregiver_name = details["caregiver_name"]

    scheduled_date = details["scheduled_date"]
    scheduled_time = details["scheduled_time"]

    attachment_path = None

    if details.get("visit_photo"):
        attachment_path = os.path.join(
            UPLOAD_FOLDER,
            details["visit_photo"]
        )

    if event == "scheduled":
        subject = "Elderly Care - Visit Scheduled"

        message = f"""
Dear Family Member,

A caregiver visit has been scheduled.

Elderly Person: {elderly_name}
Caregiver: {caregiver_name}
Date: {scheduled_date}
Time: {scheduled_time}

Regards,
Elderly Care Management System
"""

        title = "Visit Scheduled"
        notification_message = (
            f"{caregiver_name} is scheduled to visit "
            f"{elderly_name} on {scheduled_date} at {scheduled_time}."
        )

    elif event == "checkin":
        subject = "Elderly Care - Caregiver Checked In"

        message = f"""
Dear Family Member,

The caregiver has checked in for the visit.

Elderly Person: {elderly_name}
Caregiver: {caregiver_name}
Check-in Time: {details['check_in_time']}
Date: {scheduled_date}

Regards,
Elderly Care Management System
"""

        title = "Caregiver Checked In"
        notification_message = (
            f"{caregiver_name} has checked in to visit {elderly_name}."
        )

    elif event == "completed":
        subject = "Elderly Care - Visit Completed"

        message = f"""
Dear Family Member,

The caregiver has completed the visit.

Elderly Person: {elderly_name}
Caregiver: {caregiver_name}
Date: {scheduled_date}
Check-in Time: {details['check_in_time']}
Check-out Time: {details['check_out_time']}
Visit Duration: {details['visit_duration_minutes'] or 0} minutes

Health Observations:
{details['health_observations'] or 'No observations recorded.'}

Medication Updates:
{details['medication_updates'] or 'No medication updates recorded.'}

Additional Visit Notes:
{details['notes'] or 'No additional notes.'}

The visit photo is attached if available.

Regards,
Elderly Care Management System
"""

        title = "Visit Completed"
        notification_message = (
            f"The caregiver completed the visit for {elderly_name}. "
            f"Duration: {details['visit_duration_minutes'] or 0} minutes."
        )

    else:
        return

    create_notification(
        elderly_id,
        title,
        notification_message,
        "Visit Update"
    )

    send_family_email(
        elderly_id,
        subject,
        message,
        attachment_path if event == "completed" else None
    )


# =====================================
# CAREGIVER AVAILABILITY
# =====================================

@visits_bp.route("/caregiver-availability")
def caregiver_availability():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT c.caregiver_id, u.full_name, u.email,
                   c.phone, c.specialization, c.availability, c.status,
                   (
                       SELECT COUNT(*)
                       FROM visits v
                       WHERE v.caregiver_id = c.caregiver_id
                         AND v.visit_status = 'scheduled'
                         AND v.scheduled_date >= CURDATE()
                   ) AS upcoming_visits
            FROM caregivers c
            JOIN users u ON c.user_id = u.user_id
            ORDER BY u.full_name
        """)

        caregiver_list = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "caregiver_availability.html",
        caregiver_list=caregiver_list
    )


@visits_bp.route(
    "/caregiver-availability/<int:caregiver_id>",
    methods=["POST"]
)
def change_caregiver_status(caregiver_id):
    new_status = request.form.get("status")

    if new_status not in ["Available", "Absent"]:
        return "Invalid caregiver status.", 400

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    reassigned_count = 0
    pending_count = 0

    try:
        cursor.execute("""
            SELECT caregiver_id
            FROM caregivers
            WHERE caregiver_id = %s
        """, (caregiver_id,))

        if cursor.fetchone() is None:
            return "Caregiver not found.", 404

        cursor.execute("""
            UPDATE caregivers
            SET status = %s
            WHERE caregiver_id = %s
        """, (new_status, caregiver_id))

        if new_status == "Absent":
            cursor.execute("""
                SELECT visit_id, elderly_id, scheduled_date, scheduled_time
                FROM visits
                WHERE caregiver_id = %s
                  AND visit_status = 'scheduled'
                  AND scheduled_date >= CURDATE()
                ORDER BY scheduled_date, scheduled_time
            """, (caregiver_id,))

            affected_visits = cursor.fetchall()

            for visit in affected_visits:
                cursor.execute("""
                    SELECT c.caregiver_id,
                           COUNT(v.visit_id) AS workload
                    FROM caregivers c
                    LEFT JOIN visits v
                        ON c.caregiver_id = v.caregiver_id
                       AND v.visit_status = 'scheduled'
                       AND v.scheduled_date >= CURDATE()
                    WHERE c.status = 'Available'
                    GROUP BY c.caregiver_id
                    ORDER BY workload ASC, c.caregiver_id ASC
                """)

                candidates = cursor.fetchall()
                replacement_id = None

                for candidate in candidates:
                    candidate_id = candidate["caregiver_id"]

                    cursor.execute("""
                        SELECT visit_id
                        FROM visits
                        WHERE caregiver_id = %s
                          AND scheduled_date = %s
                          AND scheduled_time = %s
                          AND visit_status IN ('scheduled', 'in_progress')
                        LIMIT 1
                    """, (
                        candidate_id,
                        visit["scheduled_date"],
                        visit["scheduled_time"]
                    ))

                    if cursor.fetchone() is None:
                        replacement_id = candidate_id
                        break

                if replacement_id:
                    cursor.execute("""
                        UPDATE visits
                        SET caregiver_id = %s
                        WHERE visit_id = %s
                          AND visit_status = 'scheduled'
                    """, (replacement_id, visit["visit_id"]))

                    cursor.execute("""
                        INSERT INTO notifications
                        (elderly_id, title, message, notification_type)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        visit["elderly_id"],
                        "Caregiver Reassigned",
                        "Your scheduled caregiver is absent. Another available caregiver has been assigned.",
                        "Visit Update"
                    ))

                    reassigned_count += 1
                else:
                    pending_count += 1

        connection.commit()

    except Exception as error:
        connection.rollback()
        return f"Could not update caregiver status: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "caregiver_reassignment_result.html",
        status=new_status,
        reassigned_count=reassigned_count,
        pending_count=pending_count
    )


# =====================================
# VISIT MANAGEMENT
# =====================================

@visits_bp.route("/visits")
def visits_page():
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT v.visit_id, e.full_name, u.full_name,
                   v.scheduled_date, v.scheduled_time,
                   v.visit_status, v.check_in_time, v.check_out_time,
                   v.visit_photo, v.check_in_latitude,
                   v.check_in_longitude, v.visit_duration_minutes
            FROM visits v
            JOIN elderly_profiles e ON v.elderly_id = e.elderly_id
            JOIN caregivers c ON v.caregiver_id = c.caregiver_id
            JOIN users u ON c.user_id = u.user_id
            ORDER BY v.scheduled_date DESC, v.scheduled_time DESC
        """)

        visit_list = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    return render_template("visits.html", visit_list=visit_list)


@visits_bp.route("/visits/add", methods=["GET", "POST"])
def add_visit():
    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":
        try:
            cursor.execute("""
                INSERT INTO visits
                (elderly_id, caregiver_id, scheduled_date,
                 scheduled_time, notes)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                request.form["elderly_id"],
                request.form["caregiver_id"],
                request.form["scheduled_date"],
                request.form["scheduled_time"],
                request.form.get("notes", "")
            ))

            visit_id = cursor.lastrowid
            connection.commit()

        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

        notify_family(visit_id, "scheduled")
        return redirect(url_for("visits.visits_page"))

    try:
        cursor.execute("""
            SELECT elderly_id, full_name
            FROM elderly_profiles
            ORDER BY full_name
        """)
        elderly_list = cursor.fetchall()

        cursor.execute("""
            SELECT c.caregiver_id, u.full_name
            FROM caregivers c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.status = 'Available'
            ORDER BY u.full_name
        """)
        caregiver_list = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "visit_form.html",
        visit=None,
        elderly_list=elderly_list,
        caregiver_list=caregiver_list
    )


@visits_bp.route("/visits/edit/<int:visit_id>", methods=["GET", "POST"])
def edit_visit(visit_id):
    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "POST":
        try:
            cursor.execute("""
                UPDATE visits
                SET elderly_id=%s, caregiver_id=%s,
                    scheduled_date=%s, scheduled_time=%s, notes=%s
                WHERE visit_id=%s AND visit_status='scheduled'
            """, (
                request.form["elderly_id"],
                request.form["caregiver_id"],
                request.form["scheduled_date"],
                request.form["scheduled_time"],
                request.form.get("notes", ""),
                visit_id
            ))

            connection.commit()
        finally:
            cursor.close()
            connection.close()

        notify_family(visit_id, "scheduled")
        return redirect(url_for("visits.visits_page"))

    try:
        cursor.execute("""
            SELECT visit_id, elderly_id, caregiver_id,
                   scheduled_date, scheduled_time, notes
            FROM visits
            WHERE visit_id=%s
        """, (visit_id,))
        visit = cursor.fetchone()

        cursor.execute("""
            SELECT elderly_id, full_name
            FROM elderly_profiles
            ORDER BY full_name
        """)
        elderly_list = cursor.fetchall()

        cursor.execute("""
            SELECT c.caregiver_id, u.full_name
            FROM caregivers c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.status = 'Available'
            ORDER BY u.full_name
        """)
        caregiver_list = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    if visit is None:
        return "Visit not found", 404

    return render_template(
        "visit_form.html",
        visit=visit,
        elderly_list=elderly_list,
        caregiver_list=caregiver_list
    )


@visits_bp.route("/visits/delete/<int:visit_id>", methods=["POST"])
def delete_visit(visit_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            DELETE FROM visits
            WHERE visit_id=%s AND visit_status='scheduled'
        """, (visit_id,))
        connection.commit()
    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("visits.visits_page"))


# =====================================
# CAREGIVER CHECK-IN
# =====================================

@visits_bp.route("/visits/checkin/<int:visit_id>", methods=["POST"])
def checkin_visit(visit_id):
    latitude = request.form.get("latitude") or None
    longitude = request.form.get("longitude") or None

    photo = request.files.get("visit_photo")
    photo_name = None

    if not photo or not photo.filename:
        return "Please upload a visit photo.", 400

    if not allowed_file(photo.filename):
        return "Upload JPG, JPEG, PNG or WEBP only.", 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    safe_name = secure_filename(photo.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    photo_name = f"{uuid.uuid4().hex}.{extension}"
    photo.save(os.path.join(UPLOAD_FOLDER, photo_name))

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE visits
            SET check_in_time=NOW(),
                check_in_latitude=%s,
                check_in_longitude=%s,
                visit_photo=%s,
                visit_status='in_progress'
            WHERE visit_id=%s AND visit_status='scheduled'
        """, (latitude, longitude, photo_name, visit_id))

        if cursor.rowcount == 0:
            connection.rollback()
            return "Visit not found or already checked in.", 400

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    notify_family(visit_id, "checkin")
    return redirect(url_for("visits.visits_page"))


# =====================================
# CAREGIVER CHECK-OUT
# =====================================

@visits_bp.route("/visits/checkout/<int:visit_id>", methods=["POST"])
def checkout_visit(visit_id):
    health_observations = request.form.get(
        "health_observations", ""
    ).strip()

    medication_updates = request.form.get(
        "medication_updates", ""
    ).strip()

    additional_notes = request.form.get("notes", "").strip()

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE visits
            SET check_out_time=NOW(),
                visit_duration_minutes =
                    TIMESTAMPDIFF(MINUTE, check_in_time, NOW()),
                health_observations=%s,
                medication_updates=%s,
                notes=%s,
                visit_status='completed'
            WHERE visit_id=%s
              AND visit_status='in_progress'
              AND check_in_time IS NOT NULL
        """, (
            health_observations,
            medication_updates,
            additional_notes,
            visit_id
        ))

        if cursor.rowcount == 0:
            connection.rollback()
            return "Visit not found or not checked in.", 400

        connection.commit()

    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    notify_family(visit_id, "completed")
    return redirect(url_for("visits.visits_page"))


# =====================================
# AUTOMATIC VISIT SCHEDULING
# =====================================

@visits_bp.route("/visits/auto-schedule", methods=["POST"])
def auto_schedule_visits():
    tomorrow = date.today() + timedelta(days=1)

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    created_visit_ids = []

    try:
        cursor.execute("""
            SELECT elderly_id
            FROM elderly_profiles
            ORDER BY elderly_id
        """)
        elderly_list = cursor.fetchall()

        cursor.execute("""
            SELECT caregiver_id
            FROM caregivers
            WHERE status = 'Available'
            ORDER BY caregiver_id
        """)
        caregiver_list = cursor.fetchall()

        if not caregiver_list:
            return "No available caregivers found.", 400

        cursor.execute("""
            SELECT elderly_id
            FROM visits
            WHERE scheduled_date = %s
              AND visit_status IN ('scheduled', 'in_progress', 'completed')
        """, (tomorrow,))

        already_scheduled = {
            row["elderly_id"] for row in cursor.fetchall()
        }

        caregiver_count = len(caregiver_list)

        for index, elderly in enumerate(elderly_list):
            elderly_id = elderly["elderly_id"]

            if elderly_id in already_scheduled:
                continue

            caregiver = caregiver_list[index % caregiver_count]
            caregiver_id = caregiver["caregiver_id"]

            slot = index // caregiver_count
            hour = 9 + slot

            if hour >= 21:
                continue

            scheduled_time = f"{hour:02d}:00:00"

            cursor.execute("""
                INSERT INTO visits
                (elderly_id, caregiver_id, scheduled_date,
                 scheduled_time, visit_status, notes)
                VALUES (%s, %s, %s, %s, 'scheduled',
                        'Automatically scheduled visit')
            """, (
                elderly_id,
                caregiver_id,
                tomorrow,
                scheduled_time
            ))

            created_visit_ids.append(cursor.lastrowid)

        connection.commit()

    except Exception as error:
        connection.rollback()
        return f"Scheduling failed: {error}", 400

    finally:
        cursor.close()
        connection.close()

    for visit_id in created_visit_ids:
        try:
            notify_family(visit_id, "scheduled")
        except Exception as error:
            print("Family notification failed:", error)

    return redirect(url_for("visits.visits_page"))