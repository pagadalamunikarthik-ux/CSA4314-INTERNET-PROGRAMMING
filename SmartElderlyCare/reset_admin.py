from werkzeug.security import generate_password_hash
from db import get_connection

connection = get_connection()
cursor = connection.cursor()

new_password = generate_password_hash("Admin@123")

cursor.execute("""
    UPDATE users
    SET password = %s
    WHERE email = %s AND role = 'admin'
""", (new_password, "admin@gmail.com"))

connection.commit()

print("Admin password reset successfully!" if cursor.rowcount > 0
      else "Admin account not found!")

cursor.close()
connection.close()