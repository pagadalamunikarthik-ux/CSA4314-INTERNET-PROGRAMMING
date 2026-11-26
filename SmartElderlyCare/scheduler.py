
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

from db import get_connection
from notifications import create_notification, notify_family


def check_missed_visits_automatically():
    connection = None
    cursor = None
    new_alerts = []

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # Detect scheduled visits whose date and time have passed.
        cursor.execute("""
            SELECT v.visit_id,
                   v.elderly_id,
                   e.full_name AS elderly_name,
                   v.scheduled_date,
                   v.scheduled_time
            FROM visits v
            JOIN elderly_profiles e
              ON v.elderly_id = e.elderly_id
            WHERE LOWER(v.visit_status) = 'scheduled'
              AND TIMESTAMP(
                    v.scheduled_date,
                    v.scheduled_time
                  ) < NOW()
        """)

        missed_visits = cursor.fetchall()

        for visit in missed_visits:
            title = "Missed Care Visit"
            message = (
                f"Scheduled visit on {visit['scheduled_date']} "
                f"at {visit['scheduled_time']} was not completed."
            )

            # Prevent duplicate notifications.
            cursor.execute("""
                SELECT notification_id
                FROM notifications
                WHERE elderly_id = %s
                  AND title = %s
                  AND message = %s
            """, (
                visit["elderly_id"],
                title,
                message
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

            new_alerts.append({
                "elderly_id": visit["elderly_id"],
                "elderly_name": visit["elderly_name"],
                "message": message
            })

        connection.commit()

    except Exception as error:
        if connection:
            connection.rollback()

        print("Automatic missed visit check failed:", error)
        return

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    # Send family emails after saving notifications.
    for alert in new_alerts:
        email_message = f"""
Dear Family Member,

A scheduled caregiver visit was missed.

Elderly Person: {alert['elderly_name']}

Details:
{alert['message']}

Please contact the care centre for further information.

Regards,
Elderly Care Management System
"""

        try:
            notify_family(
                alert["elderly_id"],
                "Alert: Missed Elderly Care Visit",
                email_message
            )
        except Exception as email_error:
            print("Missed visit email error:", email_error)

    print(
        f"[{datetime.now()}] Missed visit check completed. "
        f"{len(new_alerts)} new alert(s) created."
    )


scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(
        func=check_missed_visits_automatically,
        trigger="cron",
        hour=9,
        minute=0,
        id="missed_visit_alerts",
        replace_existing=True
    )

    scheduler.start()

    print("Automatic missed visit scheduler started.")
    print("Daily check time: 9:00 AM")
