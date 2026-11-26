
import os
import mimetypes
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

from db import get_connection

load_dotenv()


def _prepare_attachments(attachments):
    if not attachments:
        return []

    if isinstance(attachments, (str, os.PathLike)):
        items = [attachments]
    elif isinstance(attachments, tuple) and len(attachments) == 4:
        items = [attachments]
    else:
        items = list(attachments)

    prepared = []

    for item in items:
        if isinstance(item, tuple) and len(item) == 4:
            filename, content, maintype, subtype = item
            prepared.append((filename, content, maintype, subtype))
            continue

        if isinstance(item, (str, os.PathLike)):
            file_path = os.fspath(item)

            if not os.path.isfile(file_path):
                print("Attachment not found:", file_path)
                continue

            filename = os.path.basename(file_path)
            content_type, _ = mimetypes.guess_type(filename)

            if content_type:
                maintype, subtype = content_type.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"

            with open(file_path, "rb") as file:
                content = file.read()

            prepared.append((
                filename, content, maintype, subtype
            ))
            continue

        raise ValueError("Unsupported attachment format.")

    return prepared


def send_family_email(elderly_id, subject, message, attachments=None):
    connection = None
    cursor = None

    try:
        email_address = os.getenv("EMAIL_ADDRESS", "").strip()
        app_password = os.getenv(
            "EMAIL_APP_PASSWORD", ""
        ).replace(" ", "").strip()

        if not email_address or not app_password:
            print("Email credentials missing in .env")
            return False

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT email
            FROM family_members
            WHERE elderly_id = %s
              AND email IS NOT NULL
              AND TRIM(email) != ''
        """, (elderly_id,))

        recipients = []
        for row in cursor.fetchall():
            address = (row[0] or "").strip()
            if address and address not in recipients:
                recipients.append(address)

        if not recipients:
            print("No family email address found.")
            return False

        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = email_address
        email["To"] = ", ".join(recipients)
        email.set_content(message)

        for filename, content, maintype, subtype in _prepare_attachments(attachments):
            email.add_attachment(
                content,
                maintype=maintype,
                subtype=subtype,
                filename=filename
            )

        with smtplib.SMTP(
            "smtp.gmail.com", 587, timeout=20
        ) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_address, app_password)
            server.send_message(email)

        print("Family email sent successfully.")
        return True

    except Exception as error:
        print("Email sending failed:", repr(error))
        return False

    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
