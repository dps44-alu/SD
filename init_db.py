import sqlite3
import os

DB_NAME = "central.db"

def create_database():
    # Si la base de datos ya existe, la eliminamos
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print("Base de datos eliminada.")

    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS taxis (
                id INTEGER PRIMARY KEY,
                moving BOOL,
                destination TEXT,
                state TEXT
            )
     ''')

    taxis = [
        (1, False, '', ''),
        (2, False, '', ''),
        (3, False, '', ''),
        (4, False, '', '')
    ]

    cursor.executemany('''
        INSERT OR IGNORE INTO taxis (id, moving, destination, state) VALUES (?, ?, ?, ?)
    ''', taxis)

    connection.commit()
    connection.close()

if __name__ == '__main__':
    create_database()
    print("Database created successfully")