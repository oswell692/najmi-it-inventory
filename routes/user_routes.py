from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from config import get_db_connection

user_bp = Blueprint('user', __name__)

# ---------------- USER DASHBOARD ----------------
@user_bp.route('/user/dashboard')
def user_dashboard():
    role = session.get('role')
    if role not in ['user', 'admin']:
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    station_id = session.get('station_id') if role == 'user' else None

    conn = get_db_connection()
    cur = conn.cursor()

    # For admin, show all stations
    if role == 'admin':
        cur.execute("SELECT * FROM stations")
        stations = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('admin_dashboard.html', stations=stations)

    # For user, show only assigned station
    if not station_id:
        flash("No station assigned.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('auth.login'))

    cur.execute("SELECT * FROM stations WHERE id=%s", (station_id,))
    station = cur.fetchone()
    if not station:
        flash("Station not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('auth.login'))

    cur.execute("SELECT * FROM equipment WHERE station_id=%s AND type='computer'", (station_id,))
    computers = cur.fetchall()
    cur.execute("SELECT * FROM equipment WHERE station_id=%s AND type='printer'", (station_id,))
    printers = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('station_dashboard.html', station=station, computers=computers, printers=printers)


# ---------------- COMPUTERS ----------------
@user_bp.route('/user/station/<int:station_id>/add_computer', methods=['GET', 'POST'])
def add_computer(station_id):
    role = session.get('role')
    if role not in ['user', 'admin']:
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if role == 'user' and station_id != session.get('station_id'):
        flash("You can only add computers to your assigned station.", "danger")
        return redirect(url_for('user.user_dashboard'))

    if request.method == 'POST':
        data = (
            station_id,
            'computer',
            request.form.get('computer_name'),
            request.form.get('assigned_user'),
            request.form.get('year_purchased'),
            request.form.get('processor'),
            request.form.get('installed_ram'),
            request.form.get('device_id'),
            request.form.get('product_id'),
            request.form.get('system_type'),
            request.form.get('pen_touch')
        )
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO equipment
            (station_id, type, name, assigned_user, year_purchased, processor, ram, device_id, product_id, system_type, pen_touch)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, data)
        conn.commit()
        cur.close()
        conn.close()
        flash("Computer added successfully.", "success")
        return redirect(url_for('user.user_dashboard'))

    return render_template('add_edit_equipment.html', kind='computer', action='Add', station_id=station_id, item=None)


@user_bp.route('/user/equipment/<int:equipment_id>/edit_computer', methods=['GET', 'POST'])
def edit_computer(equipment_id):
    role = session.get('role')
    if role not in ['user', 'admin']:
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM equipment WHERE id=%s AND type='computer'", (equipment_id,))
    computer = cur.fetchone()

    if not computer:
        flash("Computer not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    if role == 'user' and computer['station_id'] != session.get('station_id'):
        flash("You can only edit computers from your assigned station.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    if request.method == 'POST':
        cur.execute("""
            UPDATE equipment SET name=%s, assigned_user=%s, year_purchased=%s, processor=%s, ram=%s,
            device_id=%s, product_id=%s, system_type=%s, pen_touch=%s WHERE id=%s
        """, (
            request.form.get('computer_name'),
            request.form.get('assigned_user'),
            request.form.get('year_purchased'),
            request.form.get('processor'),
            request.form.get('installed_ram'),
            request.form.get('device_id'),
            request.form.get('product_id'),
            request.form.get('system_type'),
            request.form.get('pen_touch'),
            equipment_id
        ))
        conn.commit()
        flash("Computer updated successfully.", "success")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    cur.close()
    conn.close()
    return render_template('add_edit_equipment.html', kind='computer', action='Edit', item=computer)


# ---------------- PRINTERS ----------------
@user_bp.route('/user/station/<int:station_id>/add_printer', methods=['GET', 'POST'])
def add_printer(station_id):
    role = session.get('role')
    if role not in ['user', 'admin']:
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if role == 'user' and station_id != session.get('station_id'):
        flash("You can only add printers to your assigned station.", "danger")
        return redirect(url_for('user.user_dashboard'))

    if request.method == 'POST':
        data = (
            station_id,
            'printer',
            request.form.get('printer_name'),
            request.form.get('serial_number'),
            request.form.get('year_purchased'),
            request.form.get('status')
        )
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO equipment
            (station_id, type, name, serial_number, year_purchased, status)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, data)
        conn.commit()
        cur.close()
        conn.close()
        flash("Printer added successfully.", "success")
        return redirect(url_for('user.user_dashboard'))

    return render_template('add_edit_equipment.html', kind='printer', action='Add', station_id=station_id, item=None)


@user_bp.route('/user/equipment/<int:equipment_id>/edit_printer', methods=['GET', 'POST'])
def edit_printer(equipment_id):
    role = session.get('role')
    if role not in ['user', 'admin']:
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM equipment WHERE id=%s AND type='printer'", (equipment_id,))
    printer = cur.fetchone()

    if not printer:
        flash("Printer not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    if role == 'user' and printer['station_id'] != session.get('station_id'):
        flash("You can only edit printers from your assigned station.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    if request.method == 'POST':
        cur.execute("""
            UPDATE equipment SET name=%s, serial_number=%s, year_purchased=%s, status=%s
            WHERE id=%s
        """, (
            request.form.get('printer_name'),
            request.form.get('serial_number'),
            request.form.get('year_purchased'),
            request.form.get('status'),
            equipment_id
        ))
        conn.commit()
        flash("Printer updated successfully.", "success")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    cur.close()
    conn.close()
    return render_template('add_edit_equipment.html', kind='printer', action='Edit', item=printer)


# ---------------- DELETE ----------------
@user_bp.route('/user/equipment/<int:equipment_id>/delete', methods=['POST'])
def delete_equipment(equipment_id):
    role = session.get('role')
    if role not in ['user', 'admin']:
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT station_id FROM equipment WHERE id=%s", (equipment_id,))
    station_data = cur.fetchone()

    if not station_data:
        flash("Equipment not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    if role == 'user' and station_data['station_id'] != session.get('station_id'):
        flash("You can only delete equipment from your assigned station.", "danger")
        cur.close()
        conn.close()
        return redirect(url_for('user.user_dashboard'))

    cur.execute("DELETE FROM equipment WHERE id=%s", (equipment_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Equipment deleted successfully.", "success")
    return redirect(url_for('user.user_dashboard'))

