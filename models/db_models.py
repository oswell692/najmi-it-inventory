# models/db_models.py
from config import get_db_connection
from werkzeug.security import generate_password_hash

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Stations (if not already created elsewhere)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stations (
        id SERIAL PRIMARY KEY,
        name VARCHAR(150) NOT NULL UNIQUE,
        location VARCHAR(200)
    );
    """)

    # Users (if not already created elsewhere)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL,
        station_id INTEGER REFERENCES stations(id) ON DELETE SET NULL
    );
    """)

    # Computers table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS computers (
        id SERIAL PRIMARY KEY,
        station_id INTEGER REFERENCES stations(id) ON DELETE CASCADE,
        computer_name VARCHAR(200),
        assigned_user VARCHAR(200),
        year_purchased VARCHAR(20),
        processor VARCHAR(255),
        installed_ram VARCHAR(100),
        device_id VARCHAR(255),
        product_id VARCHAR(255),
        system_type VARCHAR(255),
        pen_touch VARCHAR(100),
        last_serviced DATE,
        history TEXT,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Printers table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS printers (
        id SERIAL PRIMARY KEY,
        station_id INTEGER REFERENCES stations(id) ON DELETE CASCADE,
        printer_name VARCHAR(200),
        serial_number VARCHAR(200),
        year_purchased VARCHAR(20),
        status VARCHAR(50),
        notes TEXT,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Maintenance table (optional if you want separate)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS maintenance (
        id SERIAL PRIMARY KEY,
        equipment_type VARCHAR(20) NOT NULL,
        equipment_id INTEGER NOT NULL,
        station_id INTEGER REFERENCES stations(id) ON DELETE CASCADE,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        description TEXT,
        performed_by INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

