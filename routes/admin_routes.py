from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from config import get_db_connection
from datetime import datetime
admin_bp = Blueprint('admin', __name__)

import os
import uuid
from werkzeug.utils import secure_filename

# Add configuration for file uploads
UPLOAD_FOLDER = 'static/uploads/send_items'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route('/admin/send-items', methods=['GET', 'POST'])
def send_items():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        from_station_id = request.form.get('from_station_id')
        to_station_id = request.form.get('to_station_id')
        sent_by = request.form.get('sent_by')
        received_by = request.form.get('received_by')
        send_date = request.form.get('send_date')
        expected_delivery_date = request.form.get('expected_delivery_date') or None
        notes = request.form.get('notes')
        
        # Get items data
        item_names = request.form.getlist('item_names[]')
        item_quantities = request.form.getlist('item_quantities[]')
        item_conditions = request.form.getlist('item_conditions[]')
        
        # Handle file uploads
        photo_paths = []
        if 'item_photos' in request.files:
            files = request.files.getlist('item_photos')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    # Create unique filename
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    
                    # Ensure upload directory exists
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    
                    # Save file
                    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
                    file.save(file_path)
                    photo_paths.append(unique_filename)
        
        # Create send record
        cur.execute("""
            INSERT INTO send_items 
            (from_station_id, to_station_id, sent_by, received_by, send_date, 
             expected_delivery_date, notes, photo_paths, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'sent')
            RETURNING id
        """, (from_station_id, to_station_id, sent_by, received_by, send_date, 
              expected_delivery_date, notes, photo_paths))
        
        send_id = cur.fetchone()['id']
        
        # Insert items
        for i in range(len(item_names)):
            cur.execute("""
                INSERT INTO send_items_details 
                (send_id, item_name, quantity, condition)
                VALUES (%s, %s, %s, %s)
            """, (send_id, item_names[i], item_quantities[i], item_conditions[i]))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash("Items sent successfully! Status: In Transit", "success")
        return redirect(url_for('admin.send_items_history'))
    
    # GET request - load form data
    cur.execute("SELECT * FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('send_items.html',
                         stations=stations,
                         today=datetime.now().strftime('%Y-%m-%d'))


@admin_bp.route('/admin/send-items/history')
def send_items_history():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT s.*, 
               s1.name as from_station_name, 
               s2.name as to_station_name,
               (SELECT COUNT(*) FROM send_items_details WHERE send_id = s.id) as item_count
        FROM send_items s
        LEFT JOIN stations s1 ON s.from_station_id = s1.id
        LEFT JOIN stations s2 ON s.to_station_id = s2.id
        ORDER BY s.send_date DESC, s.created_at DESC
    """)
    send_history = cur.fetchall()
    
    # Get stations for the filter dropdown
    cur.execute("SELECT id, name FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('send_items_history.html', 
                         send_history=send_history,
                         stations=stations,
                         now=datetime.now())
@admin_bp.route('/admin/send-items/<int:send_id>/update-expected-date', methods=['POST'])
def update_expected_date(send_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get the form data
    expected_date = request.form.get('expected_date')
    date_notes = request.form.get('date_notes', '')
    
    if not expected_date:
        flash("Expected date is required.", "danger")
        return redirect(url_for('admin.send_items_details', send_id=send_id))
    
    try:
        # Update the expected delivery date
        cur.execute("""
            UPDATE send_items 
            SET expected_delivery_date = %s,
                notes = CASE 
                    WHEN notes IS NOT NULL AND notes != '' THEN notes || '\n\nDate Update: ' || %s || ' - ' || %s
                    ELSE 'Date Update: ' || %s || ' - ' || %s
                END
            WHERE id = %s
        """, (expected_date, expected_date, date_notes, expected_date, date_notes, send_id))
        
        conn.commit()
        flash("Expected delivery date updated successfully!", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error updating expected date: {str(e)}", "danger")
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.send_items_details', send_id=send_id))

@admin_bp.route('/admin/send-items/<int:send_id>/mark-received', methods=['POST'])
def mark_items_received(send_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get the form data
    received_by = request.form.get('received_by')
    received_date = request.form.get('received_date')
    receive_notes = request.form.get('receive_notes', '')
    
    if not received_by or not received_date:
        flash("Received by and received date are required.", "danger")
        return redirect(url_for('admin.send_items_details', send_id=send_id))
    
    try:
        # Update the send record to mark as received
        cur.execute("""
            UPDATE send_items 
            SET status = 'received',
                received_by = %s,
                received_date = %s,
                notes = CASE 
                    WHEN notes IS NOT NULL AND notes != '' THEN notes || '\n\nReceived: ' || %s || ' by ' || %s || ' - ' || %s
                    ELSE 'Received: ' || %s || ' by ' || %s || ' - ' || %s
                END
            WHERE id = %s
        """, (received_by, received_date, received_date, received_by, receive_notes, 
              received_date, received_by, receive_notes, send_id))
        
        conn.commit()
        flash("Items marked as received successfully!", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error marking items as received: {str(e)}", "danger")
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.send_items_details', send_id=send_id))

@admin_bp.route('/admin/send-items/<int:send_id>')
def send_items_details(send_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get the send record
    cur.execute("""
        SELECT s.*, 
               s1.name as from_station_name, 
               s2.name as to_station_name
        FROM send_items s
        LEFT JOIN stations s1 ON s.from_station_id = s1.id
        LEFT JOIN stations s2 ON s.to_station_id = s2.id
        WHERE s.id = %s
    """, (send_id,))
    send_record = cur.fetchone()
    
    if not send_record:
        flash("Send record not found.", "danger")
        return redirect(url_for('admin.send_items_history'))
    
    # Get the items for this send
    cur.execute("""
        SELECT * FROM send_items_details 
        WHERE send_id = %s
    """, (send_id,))
    items = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('send_items_details.html',
                         send_record=send_record,
                         items=items)

# ---------------- ADMIN DASHBOARD ----------------
@admin_bp.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get stations (keep this as is)
    cur.execute("SELECT * FROM stations")
    stations = cur.fetchall()
    
    # Get computers count from equipment table
    cur.execute("SELECT COUNT(*) as count FROM equipment WHERE type='computer'")
    computers_count = cur.fetchone()['count']
    
    # Get printers count from printers table
    cur.execute("SELECT COUNT(*) as count FROM printers")
    printers_count = cur.fetchone()['count']
    
    total_devices = computers_count + printers_count
    
    cur.close()
    conn.close()

    return render_template('admin_dashboard.html', 
                         stations=stations,
                         computers_count=computers_count,
                         printers_count=printers_count,
                         total_devices=total_devices)

@admin_bp.route('/station/add', methods=['GET', 'POST'])
def add_station():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO stations (name, location) VALUES (%s, %s)", (name, location))
        conn.commit()
        cur.close()
        conn.close()
        flash("Station added successfully.", "success")
        return redirect(url_for('admin.admin_dashboard'))

    return render_template('add_edit_station.html', action='Add', station=None)

# ---------------- VIEW STATION ----------------
@admin_bp.route('/admin/station/<int:station_id>')
def view_station(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stations WHERE id=%s", (station_id,))
    station = cur.fetchone()
    
    if not station:
        flash("Station not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    cur.execute("SELECT * FROM equipment WHERE station_id=%s AND type='computer'", (station_id,))
    computers = cur.fetchall()

    # <-- changed: fetch printers from 'printers' table, not equipment
    cur.execute("SELECT * FROM printers WHERE station_id=%s", (station_id,))
    printers = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('station_dashboard.html', station=station, computers=computers, printers=printers)


# ---------------- COMPUTERS ----------------
@admin_bp.route('/admin/station/<int:station_id>/add_computer', methods=['GET', 'POST'])
def add_computer(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        data = (
            station_id,
            'computer',
            request.form.get('computer_name'),
            request.form.get('assigned_user'),
            request.form.get('status', 'active'),  # Default to 'active' if not provided
            request.form.get('year_purchased'),
            request.form.get('processor'),
            request.form.get('installed_ram'),
            request.form.get('device_id'),
            request.form.get('product_id'),
            request.form.get('system_type'),
            request.form.get('pen_touch'),
            request.form.get('windows'),
            request.form.get('notes'),
            request.form.get('last_serviced'),
            request.form.get('history')
        )
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO equipment
            (station_id, type, name, assigned_user, status, year_purchased, processor, ram, device_id, product_id, system_type, pen_touch, windows, notes, last_serviced, history)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, data)
        conn.commit()
        cur.close()
        conn.close()
        flash("Computer added successfully.", "success")
        return redirect(url_for('admin.view_station', station_id=station_id))

    return render_template('add_edit_equipment.html', kind='computer', action='Add', station_id=station_id, item=None)


@admin_bp.route('/admin/equipment/<int:equipment_id>/edit_computer', methods=['GET', 'POST'])
def edit_computer(equipment_id):
    if session.get('role') != 'admin':
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
        return redirect(url_for('admin.admin_dashboard'))

    if request.method == 'POST':
        cur.execute("""
            UPDATE equipment SET name=%s, assigned_user=%s, status=%s, year_purchased=%s, processor=%s, ram=%s,
            device_id=%s, product_id=%s, system_type=%s, pen_touch=%s, windows=%s, notes=%s,
            last_serviced=%s, history=%s WHERE id=%s
        """, (
            request.form.get('computer_name'),
            request.form.get('assigned_user'),
            request.form.get('status'),
            request.form.get('year_purchased'),
            request.form.get('processor'),
            request.form.get('installed_ram'),
            request.form.get('device_id'),
            request.form.get('product_id'),
            request.form.get('system_type'),
            request.form.get('pen_touch'),
            request.form.get('windows'),
            request.form.get('notes'),
            request.form.get('last_serviced'),
            request.form.get('history'),
            equipment_id
        ))
        conn.commit()
        cur.close()
        conn.close()
        flash("Computer updated successfully.", "success")
        return redirect(url_for('admin.view_station', station_id=computer['station_id']))

    cur.close()
    conn.close()
    return render_template('add_edit_equipment.html', kind='computer', action='Edit', item=computer)


# ---------------- PRINTERS ----------------
# ---------------- VIEW ALL PRINTERS ----------------
@admin_bp.route('/admin/printers')
def view_printers():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # UPDATE THIS QUERY to include station information
    cur.execute("""
        SELECT p.*, s.name as station_name, s.location 
        FROM printers p 
        LEFT JOIN stations s ON p.station_id = s.id 
        ORDER BY p.id DESC
    """)
    printers = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('view_printer.html', printers=printers)


@admin_bp.route('/admin/station/<int:station_id>/add_printer', methods=['GET', 'POST'])
def add_printer(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        # <-- changed: data no longer includes 'type'; match printers table columns
        data = (
            station_id,
            request.form.get('printer_name'),
            request.form.get('serial_number'),
            request.form.get('year_purchased'),
            request.form.get('status'),
            request.form.get('notes')
        )
        conn = get_db_connection()
        cur = conn.cursor()
        # <-- changed: insert into printers table
        cur.execute("""
            INSERT INTO printers
            (station_id, name, serial_number, year_purchased, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, data)
        conn.commit()
        cur.close()
        conn.close()
        flash("Printer added successfully.", "success")
        return redirect(url_for('admin.view_printers'))

    return render_template('add_edit_equipment.html', kind='printer', action='Add', station_id=station_id, item=None)


@admin_bp.route('/admin/equipment/<int:equipment_id>/edit_printer', methods=['GET', 'POST'])
def edit_printer(equipment_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    # <-- changed: select printer from printers table
    cur.execute("SELECT * FROM printers WHERE id=%s", (equipment_id,))
    printer = cur.fetchone()

    if not printer:
        flash("Printer not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        # <-- changed: update printers table, including notes
        cur.execute("""
            UPDATE printers SET name=%s, serial_number=%s, year_purchased=%s, status=%s, notes=%s
            WHERE id=%s
        """, (
            request.form.get('printer_name'),
            request.form.get('serial_number'),
            request.form.get('year_purchased'),
            request.form.get('status'),
            request.form.get('notes'),
            equipment_id
        ))
        conn.commit()
        cur.close()
        conn.close()
        flash("Printer updated successfully.", "success")
        return redirect(url_for('admin.view_printers'))


    cur.close()
    conn.close()
    return render_template('add_edit_equipment.html', kind='printer', action='Edit', item=printer)



# ---------------- DELETE EQUIPMENT ----------------
@admin_bp.route('/admin/equipment/<int:equipment_id>/delete', methods=['POST'])
def delete_equipment(equipment_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT station_id FROM equipment WHERE id=%s", (equipment_id,))
    eq = cur.fetchone()
    if not eq:
        flash("Equipment not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    cur.execute("DELETE FROM equipment WHERE id=%s", (equipment_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Equipment deleted successfully.", "success")
    return redirect(url_for('admin.view_station', station_id=eq['station_id']))


# ---------------- VIEW EQUIPMENT ----------------
@admin_bp.route('/admin/equipment/<int:equipment_id>/view_computer')
def view_computer(equipment_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM equipment WHERE id=%s AND type='computer'", (equipment_id,))
    computer = cur.fetchone()
    cur.close()
    conn.close()

    if not computer:
        flash("Computer not found.", "warning")
        return redirect(url_for('admin_dashboard'))

    return render_template('view_computer.html', computer=computer)


@admin_bp.route('/admin/printer/<int:equipment_id>')
def view_printer(equipment_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM printers WHERE id=%s", (equipment_id,))
    printer = cur.fetchone()
    cur.close()
    conn.close()

    if not printer:
        flash("Printer not found.", "warning")
        return redirect(url_for('admin.view_printers'))

    return render_template('single_printer.html', printer=printer)



# ---------------- EDIT STATION ----------------
@admin_bp.route('/admin/station/<int:station_id>/edit', methods=['GET', 'POST'])
def edit_station(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stations WHERE id=%s", (station_id,))
    station = cur.fetchone()

    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        cur.execute("UPDATE stations SET name=%s, location=%s WHERE id=%s", (name, location, station_id))
        conn.commit()
        cur.close()
        conn.close()
        flash("Station updated successfully.", "success")
        return redirect(url_for('admin.admin_dashboard'))

    cur.close()
    conn.close()
    return render_template('add_edit_station.html', action='Edit', station=station)


# ---------------- DELETE STATION ----------------
@admin_bp.route('/admin/station/<int:station_id>/delete', methods=['POST'])
def delete_station(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    # Optional: Delete all equipment under this station first to avoid FK issues
    cur.execute("DELETE FROM equipment WHERE station_id=%s", (station_id,))
    cur.execute("DELETE FROM stations WHERE id=%s", (station_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Station deleted successfully.", "success")
    return redirect(url_for('admin.admin_dashboard'))
# ---------------- MAINTENANCE RECORDS ----------------
@admin_bp.route('/admin/maintenance')
def maintenance_records():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get all maintenance records with station and device info
    cur.execute("""
        SELECT m.*, s.name as station_name, 
               COALESCE(e.name, p.name) as device_name,
               CASE 
                   WHEN m.device_type = 'computer' THEN 'computer'
                   WHEN m.device_type = 'printer' THEN 'printer'
               END as device_type
        FROM maintenance m
        LEFT JOIN stations s ON m.station_id = s.id
        LEFT JOIN equipment e ON m.device_id = e.id AND m.device_type = 'computer'
        LEFT JOIN printers p ON m.device_id = p.id AND m.device_type = 'printer'
        ORDER BY m.date_reported DESC
    """)
    maintenance_records = cur.fetchall()
    
    # Get counts for stats
    cur.execute("SELECT COUNT(*) as total FROM maintenance")
    total_records = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as count FROM maintenance WHERE status = 'resolved'")
    resolved_count = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) as count FROM maintenance WHERE status = 'pending'")
    pending_count = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) as count FROM maintenance WHERE status = 'in_progress'")
    in_progress_count = cur.fetchone()['count']
    
    cur.close()
    conn.close()

    return render_template('maintenance.html', 
                         maintenance_records=maintenance_records,
                         total_records=total_records,
                         resolved_count=resolved_count,
                         pending_count=pending_count,
                         in_progress_count=in_progress_count)

@admin_bp.route('/admin/maintenance/add', methods=['GET', 'POST'])
def add_maintenance():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        device_type = request.form.get('device_type')
        device_id = request.form.get('device_id')
        station_id = request.form.get('station_id')
        issue_description = request.form.get('issue_description')
        technician = request.form.get('technician')
        status = request.form.get('status')
        date_reported = request.form.get('date_reported')
        date_resolved = request.form.get('date_resolved') or None
        
        cur.execute("""
            INSERT INTO maintenance 
            (device_type, device_id, station_id, issue_description, technician, status, date_reported, date_resolved)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (device_type, device_id, station_id, issue_description, technician, status, date_reported, date_resolved))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash("Maintenance record added successfully.", "success")
        return redirect(url_for('admin.maintenance_records'))
    
    # Get stations and devices for dropdowns
    cur.execute("SELECT * FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.execute("SELECT id, name, station_id FROM equipment WHERE type='computer' ORDER BY name")
    computers = cur.fetchall()

    cur.execute("SELECT id, name, station_id FROM printers ORDER BY name")
    printers = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('add_edit_maintenance.html', 
                         action='Add', 
                         record=None,
                         stations=stations,
                         computers=computers,
                         printers=printers)

@admin_bp.route('/admin/maintenance/<int:record_id>/edit', methods=['GET', 'POST'])
def edit_maintenance(record_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM maintenance WHERE id = %s", (record_id,))
    record = cur.fetchone()
    
    if not record:
        flash("Maintenance record not found.", "warning")
        return redirect(url_for('admin.maintenance_records'))
    
    if request.method == 'POST':
        device_type = request.form.get('device_type')
        device_id = request.form.get('device_id')
        station_id = request.form.get('station_id')
        issue_description = request.form.get('issue_description')
        technician = request.form.get('technician')
        status = request.form.get('status')
        date_reported = request.form.get('date_reported')
        date_resolved = request.form.get('date_resolved') or None
        
        cur.execute("""
            UPDATE maintenance SET 
            device_type = %s, device_id = %s, station_id = %s, issue_description = %s, 
            technician = %s, status = %s, date_reported = %s, date_resolved = %s
            WHERE id = %s
        """, (device_type, device_id, station_id, issue_description, technician, 
              status, date_reported, date_resolved, record_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash("Maintenance record updated successfully.", "success")
        return redirect(url_for('admin.maintenance_records'))
    
    # Get stations and devices for dropdowns
    cur.execute("SELECT * FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.execute("SELECT id, name, station_id FROM equipment WHERE type='computer' ORDER BY name")
    computers = cur.fetchall()

    cur.execute("SELECT id, name, station_id FROM printers ORDER BY name")
    printers = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('add_edit_maintenance.html', 
                         action='Edit', 
                         record=record,
                         stations=stations,
                         computers=computers,
                         printers=printers)

@admin_bp.route('/admin/maintenance/<int:record_id>/delete', methods=['POST'])
def delete_maintenance(record_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("DELETE FROM maintenance WHERE id = %s", (record_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    flash("Maintenance record deleted successfully.", "success")
    return redirect(url_for('admin.maintenance_records'))

# ---------------- EQUIPMENT TRANSFER ----------------
@admin_bp.route('/admin/equipment/transfer', methods=['GET', 'POST'])
def transfer_equipment():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        equipment_type = request.form.get('equipment_type')
        from_station_id = request.form.get('from_station_id')
        to_station_id = request.form.get('to_station_id')
        transfer_date = request.form.get('transfer_date')
        transfer_reason = request.form.get('transfer_reason')
        additional_notes = request.form.get('additional_notes')
        
        # Initialize variables for all equipment types
        device_id = None
        equipment_name = ""
        serial_number = None  # Initialize serial_number here
        
        # Handle different equipment types
        if equipment_type in ['computer', 'printer']:
            device_id = request.form.get('device_id')
            
            # Update the device's station
            if equipment_type == 'computer':
                cur.execute("UPDATE equipment SET station_id = %s WHERE id = %s", 
                           (to_station_id, device_id))
            else:  # printer
                cur.execute("UPDATE printers SET station_id = %s WHERE id = %s", 
                           (to_station_id, device_id))
            
            # Get device name for history
            if equipment_type == 'computer':
                cur.execute("SELECT name FROM equipment WHERE id = %s", (device_id,))
            else:
                cur.execute("SELECT name FROM printers WHERE id = %s", (device_id,))
            device_result = cur.fetchone()
            equipment_name = device_result['name'] if device_result else 'Unknown'
            
        else:  # monitor or other
            equipment_name = request.form.get('additional_name')
            serial_number = request.form.get('additional_serial') or None
            device_id = None
        
        # Record transfer in history
        cur.execute("""
            INSERT INTO equipment_transfers 
            (equipment_type, device_id, equipment_name, serial_number, 
             from_station_id, to_station_id, transfer_date, transfer_reason, additional_notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (equipment_type, device_id, equipment_name, serial_number, 
              from_station_id, to_station_id, transfer_date, transfer_reason, additional_notes))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash("Equipment transferred successfully!", "success")
        return redirect(url_for('admin.transfer_history'))
    
    # GET request - load form data
    cur.execute("SELECT * FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.execute("SELECT id, name, station_id FROM equipment WHERE type='computer' ORDER BY name")
    computers = cur.fetchall()
    
    cur.execute("SELECT id, name, station_id FROM printers ORDER BY name")
    printers = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('equipment_transfer.html',
                         stations=stations,
                         computers=computers,
                         printers=printers,
                         today=datetime.now().strftime('%Y-%m-%d'))

@admin_bp.route('/admin/transfers/history')
def transfer_history():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT t.*, 
               s1.name as from_station_name, 
               s2.name as to_station_name
        FROM equipment_transfers t
        LEFT JOIN stations s1 ON t.from_station_id = s1.id
        LEFT JOIN stations s2 ON t.to_station_id = s2.id
        ORDER BY t.transfer_date DESC, t.created_at DESC
    """)
    transfers = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('transfer_history.html', transfers=transfers)
@admin_bp.route('/admin/transfers/<int:transfer_id>/edit', methods=['GET', 'POST'])
def edit_transfer(transfer_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get the transfer record
    cur.execute("""
        SELECT t.*, 
               s1.name as from_station_name, 
               s2.name as to_station_name
        FROM equipment_transfers t
        LEFT JOIN stations s1 ON t.from_station_id = s1.id
        LEFT JOIN stations s2 ON t.to_station_id = s2.id
        WHERE t.id = %s
    """, (transfer_id,))
    transfer = cur.fetchone()
    
    if not transfer:
        flash("Transfer record not found.", "warning")
        return redirect(url_for('admin.transfer_history'))
    
    if request.method == 'POST':
        transfer_date = request.form.get('transfer_date')
        transfer_reason = request.form.get('transfer_reason')
        additional_notes = request.form.get('additional_notes')
        
        # Update the transfer record
        cur.execute("""
            UPDATE equipment_transfers 
            SET transfer_date = %s, transfer_reason = %s, additional_notes = %s
            WHERE id = %s
        """, (transfer_date, transfer_reason, additional_notes, transfer_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash("Transfer record updated successfully!", "success")
        return redirect(url_for('admin.transfer_history'))
    
    # GET request - load form with current data
    cur.close()
    conn.close()

    return render_template('edit_transfer.html', 
                         transfer=transfer,
                         today=datetime.now().strftime('%Y-%m-%d'))

@admin_bp.route('/admin/transfers/<int:transfer_id>/delete', methods=['POST'])
def delete_transfer(transfer_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Delete the transfer record
    cur.execute("DELETE FROM equipment_transfers WHERE id = %s", (transfer_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    flash("Transfer record deleted successfully!", "success")
    return redirect(url_for('admin.transfer_history'))
@admin_bp.route('/admin/computers')
def view_computers():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT e.*, s.name as station_name 
        FROM equipment e 
        LEFT JOIN stations s ON e.station_id = s.id 
        WHERE e.type = 'computer'
        ORDER BY e.id DESC
    """)
    computers = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('view_computers.html', computers=computers)