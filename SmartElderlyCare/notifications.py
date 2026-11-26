
from io import BytesIO
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, session

from db import get_connection
from email_service import send_family_email

notifications_bp = Blueprint("notifications", __name__)


def create_notification(cursor, elderly_id, title, message, notification_type):
    cursor.execute("""
        INSERT INTO notifications
        (elderly_id, title, message, notification_type)
        VALUES (%s, %s, %s, %s)
    """, (elderly_id, title, message, notification_type))


def notify_family(elderly_id, subject, message, attachment=None):
    attachments = [attachment] if attachment else None
    return send_family_email(
        elderly_id, subject, message, attachments=attachments
    )


# VIEW NOTIFICATIONS
@notifications_bp.route("/notifications")
def notifications_page():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if session.get("role") == "family":
            cursor.execute("""
                SELECT n.notification_id, n.elderly_id,
                       e.full_name AS elderly_name,
                       n.title, n.message, n.notification_type,
                       n.is_read, n.created_at
                FROM notifications n
                JOIN elderly_profiles e
                  ON n.elderly_id = e.elderly_id
                WHERE n.elderly_id = %s
                ORDER BY n.created_at DESC
            """, (session["elderly_id"],))
        else:
            cursor.execute("""
                SELECT n.notification_id, n.elderly_id,
                       e.full_name AS elderly_name,
                       n.title, n.message, n.notification_type,
                       n.is_read, n.created_at
                FROM notifications n
                JOIN elderly_profiles e
                  ON n.elderly_id = e.elderly_id
                ORDER BY n.created_at DESC
            """)

        notifications = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "notifications.html",
        notifications=notifications
    )


# ADD NOTIFICATION
@notifications_bp.route("/notifications/add", methods=["GET", "POST"])
def add_notification():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if request.method == "POST":
            create_notification(
                cursor,
                request.form["elderly_id"],
                request.form["title"],
                request.form["message"],
                request.form["notification_type"]
            )
            connection.commit()
            return redirect("/notifications")

        cursor.execute("""
            SELECT elderly_id, full_name
            FROM elderly_profiles
            ORDER BY full_name
        """)
        elderly_list = cursor.fetchall()

    except Exception as error:
        connection.rollback()
        return f"Could not create notification: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "notification_form.html",
        elderly_list=elderly_list
    )


# MARK NOTIFICATION AS READ
@notifications_bp.route(
    "/notifications/read/<int:notification_id>",
    methods=["POST"]
)
def mark_notification_read(notification_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        if session.get("role") == "family":
            cursor.execute("""
                UPDATE notifications
                SET is_read = TRUE
                WHERE notification_id = %s
                  AND elderly_id = %s
            """, (notification_id, session["elderly_id"]))
        else:
            cursor.execute("""
                UPDATE notifications
                SET is_read = TRUE
                WHERE notification_id = %s
            """, (notification_id,))

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    return redirect("/notifications")


# DELETE NOTIFICATION
@notifications_bp.route(
    "/notifications/delete/<int:notification_id>",
    methods=["POST"]
)
def delete_notification(notification_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        if session.get("role") == "family":
            cursor.execute("""
                DELETE FROM notifications
                WHERE notification_id = %s
                  AND elderly_id = %s
            """, (notification_id, session["elderly_id"]))
        else:
            cursor.execute("""
                DELETE FROM notifications
                WHERE notification_id = %s
            """, (notification_id,))

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    return redirect("/notifications")


# EMERGENCY INCIDENT MANAGEMENT
@notifications_bp.route("/emergency-incidents")
def emergency_incidents():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT i.*, e.full_name AS elderly_name
            FROM emergency_incidents i
            JOIN elderly_profiles e
              ON i.elderly_id = e.elderly_id
            ORDER BY i.reported_at DESC
        """)
        incidents = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "emergency_incidents.html",
        incidents=incidents
    )


@notifications_bp.route(
    "/emergency-incidents/add", methods=["GET", "POST"]
)
def add_emergency_incident():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if request.method == "POST":
            elderly_id = request.form["elderly_id"]
            incident_type = request.form["incident_type"]
            severity = request.form["severity"]
            description = request.form["description"]
            action_taken = request.form.get("action_taken", "")

            cursor.execute("""
                INSERT INTO emergency_incidents
                (elderly_id, incident_type, severity,
                 description, action_taken)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                elderly_id, incident_type, severity,
                description, action_taken
            ))

            create_notification(
                cursor,
                elderly_id,
                "Emergency Incident: " + incident_type,
                description,
                "Emergency"
            )

            connection.commit()

        else:
            cursor.execute("""
                SELECT elderly_id, full_name
                FROM elderly_profiles
                ORDER BY full_name
            """)
            elderly_list = cursor.fetchall()

    except Exception as error:
        connection.rollback()
        return f"Could not save emergency incident: {error}", 400

    finally:
        cursor.close()
        connection.close()

    if request.method == "POST":
        email_message = (
            "An emergency incident has been reported.\n\n"
            f"Incident: {incident_type}\n"
            f"Severity: {severity}\n"
            f"Description: {description}\n"
            f"Action taken: {action_taken}\n\n"
            "Please contact the care team immediately."
        )

        notify_family(
            elderly_id,
            "URGENT: Elderly Care Emergency Alert",
            email_message
        )

        return redirect("/emergency-incidents")

    return render_template(
        "emergency_form.html",
        elderly_list=elderly_list
    )


@notifications_bp.route(
    "/emergency-incidents/close/<int:incident_id>",
    methods=["POST"]
)
def close_emergency_incident(incident_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE emergency_incidents
            SET incident_status = 'Closed'
            WHERE incident_id = %s
        """, (incident_id,))
        connection.commit()

    finally:
        cursor.close()
        connection.close()

    return redirect("/emergency-incidents")


# MEDICATION LOGS
@notifications_bp.route("/medication-logs")
def medication_logs():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT l.*, e.full_name AS elderly_name
            FROM medication_logs l
            JOIN elderly_profiles e
              ON l.elderly_id = e.elderly_id
            ORDER BY l.administered_at DESC
        """)
        logs = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    return render_template("medication_logs.html", logs=logs)


@notifications_bp.route(
    "/medication-logs/add", methods=["GET", "POST"]
)
def add_medication_log():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if request.method == "POST":
            elderly_id = request.form["elderly_id"]
            medication_id = request.form.get("medication_id") or None
            medicine_name = request.form["medicine_name"]
            status = request.form["medication_status"]
            notes = request.form.get("notes", "")

            if status not in ["Taken", "Missed", "Skipped"]:
                return "Invalid medication status", 400

            cursor.execute("""
                INSERT INTO medication_logs
                (elderly_id, medication_id, medicine_name,
                 medication_status, notes)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                elderly_id, medication_id, medicine_name,
                status, notes
            ))

            if status in ["Missed", "Skipped"]:
                create_notification(
                    cursor,
                    elderly_id,
                    "Medication " + status,
                    f"{medicine_name}: {notes}",
                    "Medication"
                )

            connection.commit()

        else:
            cursor.execute("""
                SELECT elderly_id, full_name
                FROM elderly_profiles
                ORDER BY full_name
            """)
            elderly_list = cursor.fetchall()

            cursor.execute("""
                SELECT m.medication_id, m.elderly_id,
                       m.medicine_name, m.dosage,
                       e.full_name AS elderly_name
                FROM medications m
                JOIN elderly_profiles e
                  ON m.elderly_id = e.elderly_id
                ORDER BY e.full_name, m.medicine_name
            """)
            medication_list = cursor.fetchall()

    except Exception as error:
        connection.rollback()
        return f"Could not save medication log: {error}", 400

    finally:
        cursor.close()
        connection.close()

    if request.method == "POST":
        if status in ["Missed", "Skipped"]:
            notify_family(
                elderly_id,
                "Medication Alert: " + medicine_name,
                f"The medication {medicine_name} was marked "
                f"{status}.\nNotes: {notes}"
            )

        return redirect("/medication-logs")

    return render_template(
        "medication_log_form.html",
        elderly_list=elderly_list,
        medication_list=medication_list
    )


# MISSED VISIT ALERTS WITH FAMILY EMAIL
@notifications_bp.route(
    "/alerts/check-missed-visits", methods=["POST"]
)
def check_missed_visits():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    alerts_created = 0
    emails_sent = 0

    try:
        cursor.execute("""
            SELECT v.visit_id, v.elderly_id,
                   e.full_name AS elderly_name,
                   v.scheduled_date, v.scheduled_time
            FROM visits v
            JOIN elderly_profiles e
              ON v.elderly_id = e.elderly_id
            WHERE LOWER(v.visit_status) = 'scheduled'
              AND TIMESTAMP(v.scheduled_date, v.scheduled_time) < NOW()
        """)

        missed_visits = cursor.fetchall()

        for visit in missed_visits:
            title = "Missed Care Visit"
            message = (
                f"Scheduled visit on {visit['scheduled_date']} "
                f"at {visit['scheduled_time']} was not completed."
            )

            cursor.execute("""
                SELECT notification_id
                FROM notifications
                WHERE elderly_id = %s
                  AND title = %s
                  AND message = %s
            """, (
                visit["elderly_id"], title, message
            ))

            if cursor.fetchone():
                continue

            create_notification(
                cursor,
                visit["elderly_id"],
                title,
                message,
                "Missed Visit"
            )

            connection.commit()
            alerts_created += 1

            email_message = (
                f"Dear Family,\n\n"
                f"A scheduled care visit for "
                f"{visit['elderly_name']} was missed.\n\n"
                f"Date: {visit['scheduled_date']}\n"
                f"Time: {visit['scheduled_time']}\n\n"
                "Please contact the care team.\n\n"
                "Elderly Care Management System"
            )

            try:
                if notify_family(
                    visit["elderly_id"],
                    "Missed Care Visit Alert",
                    email_message
                ):
                    emails_sent += 1

            except Exception as email_error:
                print("Missed visit email error:", email_error)

    except Exception as error:
        connection.rollback()
        return f"Could not check missed visits: {error}", 400

    finally:
        cursor.close()
        connection.close()

    return (
        f"Missed visit check completed. "
        f"{alerts_created} notification(s) created. "
        f"{emails_sent} family email(s) sent."
    )


# WEEKLY PDF HEALTH REPORT
@notifications_bp.route(
    "/reports/weekly", methods=["GET", "POST"]
)
def weekly_report():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if request.method == "GET":
            cursor.execute("""
                SELECT elderly_id, full_name
                FROM elderly_profiles
                ORDER BY full_name
            """)
            elderly_list = cursor.fetchall()

            return render_template(
                "weekly_report.html",
                elderly_list=elderly_list
            )

        elderly_id = request.form.get("elderly_id")

        cursor.execute("""
            SELECT full_name, age, medical_conditions
            FROM elderly_profiles
            WHERE elderly_id = %s
        """, (elderly_id,))
        person = cursor.fetchone()

        if not person:
            return "Elderly profile not found", 404

        start_date = date.today() - timedelta(days=7)

        cursor.execute("""
            SELECT blood_pressure, heart_rate, temperature,
                   oxygen_level, notes, recorded_at
            FROM vital_records
            WHERE elderly_id = %s
              AND recorded_at >= %s
            ORDER BY recorded_at DESC
        """, (elderly_id, start_date))
        health_records = cursor.fetchall()

        cursor.execute("""
            SELECT scheduled_date, scheduled_time,
                   check_in_time, check_out_time,
                   visit_status, notes
            FROM visits
            WHERE elderly_id = %s
              AND scheduled_date >= %s
            ORDER BY scheduled_date DESC
        """, (elderly_id, start_date))
        visit_records = cursor.fetchall()

        cursor.execute("""
            SELECT medicine_name, medication_status,
                   administered_at, notes
            FROM medication_logs
            WHERE elderly_id = %s
              AND administered_at >= %s
            ORDER BY administered_at DESC
        """, (elderly_id, start_date))
        medication_records = cursor.fetchall()

    except Exception as error:
        return f"Could not retrieve report data: {error}", 400

    finally:
        cursor.close()
        connection.close()

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
            Table, TableStyle
        )
        from reportlab.lib.styles import getSampleStyleSheet

        pdf_buffer = BytesIO()

        document = SimpleDocTemplate(
            pdf_buffer,
            pagesize=A4,
            rightMargin=35,
            leftMargin=35,
            topMargin=35,
            bottomMargin=35
        )

        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(
            "Weekly Elderly Health Report", styles["Title"]
        ))
        story.append(Spacer(1, 12))

        story.append(Paragraph(
            f"Name: {person['full_name']}", styles["Normal"]
        ))
        story.append(Paragraph(
            f"Age: {person['age'] or 'Not recorded'}",
            styles["Normal"]
        ))
        story.append(Paragraph(
            "Medical conditions: "
            f"{person['medical_conditions'] or 'None recorded'}",
            styles["Normal"]
        ))
        story.append(Paragraph(
            f"Report period: {start_date} to {date.today()}",
            styles["Normal"]
        ))
        story.append(Spacer(1, 15))

        def add_section(title, rows):
            story.append(Paragraph(title, styles["Heading2"]))

            if not rows:
                story.append(Paragraph(
                    "No records available for this period.",
                    styles["Normal"]
                ))
                story.append(Spacer(1, 10))
                return

            table = Table(rows, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6)
            ]))
            story.append(table)
            story.append(Spacer(1, 12))

        add_section("Health Records", [
            ["BP", "Heart Rate", "Temp", "Oxygen", "Date"]
        ] + [
            [
                str(r["blood_pressure"] or "-"),
                str(r["heart_rate"] or "-"),
                str(r["temperature"] or "-"),
                str(r["oxygen_level"] or "-"),
                str(r["recorded_at"])
            ]
            for r in health_records
        ])

        add_section("Care Visits", [
            ["Date", "Time", "Check-in", "Check-out", "Status"]
        ] + [
            [
                str(r["scheduled_date"]),
                str(r["scheduled_time"]),
                str(r["check_in_time"] or "-"),
                str(r["check_out_time"] or "-"),
                str(r["visit_status"])
            ]
            for r in visit_records
        ])

        add_section("Medication Records", [
            ["Medicine", "Status", "Date", "Notes"]
        ] + [
            [
                str(r["medicine_name"]),
                str(r["medication_status"]),
                str(r["administered_at"]),
                str(r["notes"] or "-")
            ]
            for r in medication_records
        ])

        document.build(story)
        pdf_buffer.seek(0)

        attachment = (
            f"Weekly_Health_Report_{elderly_id}.pdf",
            pdf_buffer.getvalue(),
            "application",
            "pdf"
        )

        email_message = (
            "Dear Family,\n\n"
            f"Please find attached the weekly health report for "
            f"{person['full_name']}.\n\n"
            f"Report period: {start_date} to {date.today()}.\n\n"
            "Regards,\nElderly Care Management System"
        )

        sent = notify_family(
            elderly_id,
            "Weekly Elderly Health Report",
            email_message,
            attachment
        )

        if sent:
            return (
                "Weekly PDF report generated and emailed successfully. "
                '<a href="/reports/weekly">Go back</a>'
            )

        return (
            "PDF was generated, but the email could not be sent. "
            "Check the family email address and terminal."
        ), 500

    except Exception as error:
        return f"Could not generate weekly report: {error}", 400
