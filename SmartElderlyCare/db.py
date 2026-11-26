import mysql.connector

def get_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="elderly_care_db"
    )
    return connection