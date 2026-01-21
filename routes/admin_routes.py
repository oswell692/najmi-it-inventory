from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from config import get_db_connection
from datetime import datetime, timedelta
import os
import uuid
import json
import socket
from werkzeug.utils import secure_filename
import psycopg2.extras
import time
from flask import current_app
admin_bp = Blueprint('admin', __name__)



def allowed_file(filename):
    """Check if the file has an allowed extension"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper functions for login activities
def get_login_activities(limit=10):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cur.execute("""
        SELECT id, username, computer_name, ip_address, 
               login_time, logout_time, duration, status
        FROM login_activities 
        ORDER BY login_time DESC 
        LIMIT %s
    """, (limit,))
    
    activities = cur.fetchall()
    cur.close()
    conn.close()
    return activities

def get_active_sessions_count():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cur.execute("""
        SELECT COUNT(*) as active_count 
        FROM login_activities 
        WHERE status = 'active'
    """)
    
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result['active_count'] if result else 0

UPLOAD_FOLDER = 'static/uploads/send_items'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@admin_bp.route('/admin/login_activities')
def login_activities():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))
    
    # Get filter parameters
    page = request.args.get('page', 1, type=int)
    per_page = 20
    username_filter = request.args.get('username', '')
    status_filter = request.args.get('status', '')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Build query with filters
    query = """
        SELECT id, username, computer_name, ip_address, 
               login_time, logout_time, duration, status,
               user_agent
        FROM login_activities 
        WHERE 1=1
    """
    params = []
    
    if username_filter:
        query += " AND username ILIKE %s"
        params.append(f"%{username_filter}%")
    
    if status_filter:
        query += " AND status = %s"
        params.append(status_filter)
    
    query += " ORDER BY login_time DESC"
    
    # Get total count for pagination
    count_query = "SELECT COUNT(*) as total FROM login_activities WHERE 1=1"
    count_params = []
    
    if username_filter:
        count_query += " AND username ILIKE %s"
        count_params.append(f"%{username_filter}%")
    
    if status_filter:
        count_query += " AND status = %s"
        count_params.append(status_filter)
    
    cur.execute(count_query, count_params)
    total_count = cur.fetchone()['total']
    
    # Add pagination
    query += " LIMIT %s OFFSET %s"
    params.extend([per_page, (page - 1) * per_page])
    
    cur.execute(query, params)
    all_activities = cur.fetchall()
    
    # Calculate active sessions
    cur.execute("SELECT COUNT(*) as active_count FROM login_activities WHERE status = 'active'")
    active_count_result = cur.fetchone()
    active_sessions_count = active_count_result['active_count'] if active_count_result else 0
    
    cur.close()
    conn.close()
    
    # Calculate total pages
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template('login_activities.html',
                         login_activities=all_activities,
                         active_sessions_count=active_sessions_count,
                         total_activities=total_count,
                         page=page,
                         total_pages=total_pages,
                         username_filter=username_filter,
                         status_filter=status_filter)

# ---------------- ADMIN DASHBOARD ----------------
@admin_bp.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cur.execute("SELECT * FROM stations")
    stations = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) as count FROM equipment WHERE type='computer'")
    computers_count = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) as count FROM printers")
    printers_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM routers")
    routers_count = cur.fetchone()['count']
    
    total_devices = computers_count + printers_count + routers_count
    
    cur.close()
    conn.close()

    # Get login activities
    login_activities = get_login_activities(5)
    active_sessions_count = get_active_sessions_count()

    return render_template('admin_dashboard.html', 
                         stations=stations,
                         computers_count=computers_count,
                         printers_count=printers_count,
                         routers_count=routers_count,
                         total_devices=total_devices,
                         login_activities=login_activities,
                         active_sessions_count=active_sessions_count)

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
        
        item_names = request.form.getlist('item_names[]')
        item_quantities = request.form.getlist('item_quantities[]')
        item_conditions = request.form.getlist('item_conditions[]')
        
        photo_paths = []
        if 'item_photos' in request.files:
            files = request.files.getlist('item_photos')
            for file in files:
                if file and file.filename and allowed_file(file.filename):                    
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    
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
               s.receiving_photos,  
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
    
    received_by = request.form.get('received_by')
    received_date = request.form.get('received_date')
    receive_notes = request.form.get('receive_notes', '')
    
    if not received_by or not received_date:
        flash("Received by and received date are required.", "danger")
        return redirect(url_for('admin.send_items_details', send_id=send_id))
    
    try:
        # Handle file uploads for receiving photos
        receiving_photos = request.files.getlist('receiving_photos')
        photo_paths = []
        
        for photo in receiving_photos:
            if photo and photo.filename:
                # Secure the filename
                filename = secure_filename(photo.filename)
                # Create unique filename
                unique_filename = f"received_{uuid.uuid4()}_{filename}"
                
                # Create uploads directory
                upload_dir = os.path.join('static', 'uploads', 'send_items', 'received')
                os.makedirs(upload_dir, exist_ok=True)
                
                # Save the image
                image_path = os.path.join(upload_dir, unique_filename)
                photo.save(image_path)
                
                # Store relative path WITHOUT json brackets
                relative_path = f"uploads/send_items/received/{unique_filename}"
                photo_paths.append(relative_path)
        
        # Convert photo paths to comma-separated string (NOT JSON)
        photo_paths_str = ','.join(photo_paths) if photo_paths else None
        
        # Get existing photos if any
        cur.execute("SELECT receiving_photos FROM send_items WHERE id = %s", (send_id,))
        existing_record = cur.fetchone()
        existing_photos_str = ""
        
        if existing_record and existing_record['receiving_photos']:
            existing_data = existing_record['receiving_photos']
            
            # Handle both JSON string and comma-separated string
            if existing_data.startswith('[') and existing_data.endswith(']'):
                # It's JSON, parse it
                try:
                    existing_json = json.loads(existing_data)
                    existing_photos_str = ','.join(existing_json)
                except:
                    existing_photos_str = existing_data
            else:
                # It's already comma-separated
                existing_photos_str = existing_data
        
        # Combine existing and new photos
        if existing_photos_str and photo_paths_str:
            all_photos = f"{existing_photos_str},{photo_paths_str}"
        elif existing_photos_str:
            all_photos = existing_photos_str
        else:
            all_photos = photo_paths_str
        
        # Update the database
        cur.execute("""
            UPDATE send_items 
            SET status = 'received',
                received_by = %s,
                received_date = %s,
                receiving_photos = %s,
                notes = CASE 
                    WHEN notes IS NOT NULL AND notes != '' 
                    THEN notes || '\n\n--- RECEIVED ---\nDate: ' || %s || '\nBy: ' || %s || '\nNotes: ' || %s || 
                         CASE WHEN %s IS NOT NULL THEN '\nPhotos attached' ELSE '' END
                    ELSE '--- RECEIVED ---\nDate: ' || %s || '\nBy: ' || %s || '\nNotes: ' || %s || 
                         CASE WHEN %s IS NOT NULL THEN '\nPhotos attached' ELSE '' END
                END
            WHERE id = %s
        """, (
            received_by, 
            received_date, 
            all_photos,
            received_date, received_by, receive_notes, photo_paths_str,
            received_date, received_by, receive_notes, photo_paths_str,
            send_id
        ))
        
        conn.commit()
        
        # Flash message
        if photo_paths:
            flash(f"Items marked as received successfully with {len(photo_paths)} photo(s)!", "success")
        else:
            flash("Items marked as received successfully!", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error marking items as received: {str(e)}", "danger")
        print(f"Error details: {str(e)}")  # For debugging
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
    
    cur.execute("""
        SELECT s.*, 
               s1.name as from_station_name, 
               s2.name as to_station_name,
               s.receiving_photos
        FROM send_items s
        LEFT JOIN stations s1 ON s.from_station_id = s1.id
        LEFT JOIN stations s2 ON s.to_station_id = s2.id
        WHERE s.id = %s
    """, (send_id,))
    send_record = cur.fetchone()
    
    if not send_record:
        flash("Send record not found.", "danger")
        return redirect(url_for('admin.send_items_history'))
    
    # DEBUG: Print what's in the database
    print(f"DEBUG - Record ID: {send_id}")
    print(f"DEBUG - receiving_photos value: {send_record['receiving_photos']}")
    print(f"DEBUG - Type: {type(send_record['receiving_photos'])}")
    
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
        return redirect(url_for('admin.admin_dashboard'))

    cur.execute("SELECT * FROM equipment WHERE station_id=%s AND type='computer'", (station_id,))
    computers = cur.fetchall()

   
    cur.execute("SELECT * FROM printers WHERE station_id=%s", (station_id,))
    printers = cur.fetchall()

    
    cur.execute("SELECT * FROM routers WHERE station_id=%s", (station_id,))
    routers = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('station_dashboard.html', 
                         station=station, 
                         computers=computers, 
                         printers=printers,
                         routers=routers)  

# ---------------- COMPUTERS ----------------
@admin_bp.route('/admin/station/<int:station_id>/add_computer', methods=['GET', 'POST'])
def add_computer(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        # Handle file uploads
        computer_images = request.files.getlist('computer_images')
        image_paths = []
        
        for image in computer_images:
            if image and image.filename:
                # Secure the filename and save the image
                filename = secure_filename(image.filename)
                # Create unique filename to avoid collisions
                unique_filename = f"{uuid.uuid4()}_{filename}"
                # Create uploads directory if it doesn't exist
                upload_dir = os.path.join('static', 'uploads', 'computers')
                os.makedirs(upload_dir, exist_ok=True)
                
                image_path = os.path.join(upload_dir, unique_filename)
                image.save(image_path)
                # Store relative path for web access
                relative_path = f"uploads/computers/{unique_filename}"
                image_paths.append(relative_path)
        
        # Convert list of image paths to JSON string for database storage
        images_json = json.dumps(image_paths) if image_paths else None
        
        data = (
            station_id,
            'computer',
            request.form.get('computer_name'),
            request.form.get('assigned_user'),
            request.form.get('status', 'active'),
            request.form.get('year_purchased'),
            request.form.get('processor'),
            request.form.get('installed_ram'),
            request.form.get('device_id'),
            request.form.get('product_id'),
            request.form.get('serial_number'),
            request.form.get('encryption_type'),
            request.form.get('encryption_key'),
            request.form.get('bios_password'),
            request.form.get('system_type'),
            request.form.get('pen_touch'),
            request.form.get('windows'),
            request.form.get('notes'),
            request.form.get('last_serviced'),
            request.form.get('history'),
            images_json  # Add images to database
        )
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO equipment
            (station_id, type, name, assigned_user, status, year_purchased, processor, ram, device_id, product_id, serial_number, encryption_type, encryption_key, bios_password, system_type, pen_touch, windows, notes, last_serviced, history, images)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
        # Handle file uploads
        computer_images = request.files.getlist('computer_images')
        image_paths = []
        
        # Get existing images from database
        existing_images = []
        if computer['images']:
            try:
                existing_images = json.loads(computer['images'])
            except:
                existing_images = []
        
        # Handle deleted images
        deleted_images_json = request.form.get('deleted_images')
        if deleted_images_json:
            try:
                deleted_images = json.loads(deleted_images_json)
                # Remove deleted images from filesystem
                for image_path in deleted_images:
                    full_path = os.path.join('static', image_path)
                    if os.path.exists(full_path):
                        os.remove(full_path)
                # Remove deleted images from existing images list
                existing_images = [img for img in existing_images if img not in deleted_images]
            except Exception as e:
                print(f"Error processing deleted images: {e}")
        
        # Get kept existing images from form
        kept_existing_images = request.form.getlist('existing_images')
        
        # Process new uploaded images
        for image in computer_images:
            if image and image.filename:
                # Secure the filename and save the image
                filename = secure_filename(image.filename)
                # Create unique filename to avoid collisions
                unique_filename = f"{uuid.uuid4()}_{filename}"
                # Create uploads directory if it doesn't exist
                upload_dir = os.path.join('static', 'uploads', 'computers')
                os.makedirs(upload_dir, exist_ok=True)
                
                image_path = os.path.join(upload_dir, unique_filename)
                image.save(image_path)
                # Store relative path for web access
                relative_path = f"uploads/computers/{unique_filename}"
                image_paths.append(relative_path)
        
        # Combine kept existing images with new images
        all_images = kept_existing_images + image_paths
        images_json = json.dumps(all_images) if all_images else None
        
        cur.execute("""
            UPDATE equipment SET name=%s, assigned_user=%s, status=%s, year_purchased=%s, processor=%s, ram=%s,
            device_id=%s, product_id=%s, serial_number=%s, encryption_type=%s, encryption_key=%s, bios_password=%s, system_type=%s, 
            pen_touch=%s, windows=%s, notes=%s, last_serviced=%s, history=%s, images=%s WHERE id=%s
        """, (
            request.form.get('computer_name'),
            request.form.get('assigned_user'),
            request.form.get('status'),
            request.form.get('year_purchased'),
            request.form.get('processor'),
            request.form.get('installed_ram'),
            request.form.get('device_id'),
            request.form.get('product_id'),
            request.form.get('serial_number'),
            request.form.get('encryption_type'),
            request.form.get('encryption_key'),
            request.form.get('bios_password'),
            request.form.get('system_type'),
            request.form.get('pen_touch'),
            request.form.get('windows'),
            request.form.get('notes'),
            request.form.get('last_serviced'),
            request.form.get('history'),
            images_json,
            equipment_id
        ))
        conn.commit()
        cur.close()
        conn.close()
        flash("Computer updated successfully.", "success")
        return redirect(url_for('admin.view_computers'))

    # For GET request, parse existing images for template
    if computer['images']:
        try:
            # Parse images for template display
            computer_images = json.loads(computer['images'])
            computer['images'] = computer_images
        except:
            computer['images'] = []
    else:
        computer['images'] = []
    
    cur.close()
    conn.close()
    return render_template('add_edit_equipment.html', kind='computer', action='Edit', item=computer)

# ---------------- VIEW ALL PRINTERS ----------------
@admin_bp.route('/admin/printers')
def view_printers():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get all printers with station names
    cur.execute("""
        SELECT p.*, s.name as station_name, s.location 
        FROM printers p 
        LEFT JOIN stations s ON p.station_id = s.id 
        ORDER BY p.id DESC
    """)
    printers = cur.fetchall()
    
    # Get stations for the filter dropdown
    cur.execute("SELECT name FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.close()
    conn.close()

    # Use the correct template name - view_printer.html (singular)
    return render_template('view_printer.html', printers=printers, stations=stations)

@admin_bp.route('/admin/station/<int:station_id>/add_printer', methods=['GET', 'POST'])
def add_printer(station_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        # Handle image uploads for printers
        uploaded_images = []
        
        # Process new image uploads
        if 'printer_images' in request.files:
            files = request.files.getlist('printer_images')
            
            for file in files:
                if file and file.filename:
                    # Validate file is an image
                    if allowed_file(file.filename):
                        # Create uploads directory if it doesn't exist
                        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'printers')
                        os.makedirs(upload_folder, exist_ok=True)
                        
                        # Generate secure filename
                        filename = secure_filename(file.filename)
                        # Add timestamp to make filename unique
                        unique_filename = f"{int(time.time())}_{filename}"
                        file_path = os.path.join(upload_folder, unique_filename)
                        file.save(file_path)
                        
                        # Store relative path for database
                        relative_path = f"uploads/printers/{unique_filename}"
                        uploaded_images.append(relative_path)
        
        # Convert images list to JSON string for database storage
        images_json = json.dumps(uploaded_images) if uploaded_images else None
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Include images in the INSERT statement
        cur.execute("""
            INSERT INTO printers
            (station_id, name, serial_number, year_purchased, status, notes, images)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            station_id,
            request.form.get('printer_name'),
            request.form.get('serial_number'),
            request.form.get('year_purchased'),
            request.form.get('status'),
            request.form.get('notes'),
            images_json
        ))
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
    # Get printer data
    cur.execute("SELECT * FROM printers WHERE id=%s", (equipment_id,))
    printer = cur.fetchone()

    if not printer:
        flash("Printer not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('admin.admin_dashboard'))

    if request.method == 'POST':
        # Get existing images
        existing_images = []
        if printer and printer['images']:
            try:
                existing_images = json.loads(printer['images'])
            except:
                # If images is not valid JSON, treat it as empty
                existing_images = []
        
        # Get existing images from form that are NOT deleted
        form_existing_images = request.form.getlist('existing_images')
        
        # Get deleted images from form
        deleted_images_json = request.form.get('deleted_images', '[]')
        try:
            deleted_images = json.loads(deleted_images_json)
        except:
            deleted_images = []
        
        # Filter out deleted images
        final_existing_images = [img for img in existing_images if img not in deleted_images]
        
        # Handle new image uploads
        uploaded_images = []
        
        if 'printer_images' in request.files:
            files = request.files.getlist('printer_images')
            
            for file in files:
                if file and file.filename:
                    if allowed_file(file.filename):
                        # Create uploads directory if it doesn't exist
                        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'printers')
                        os.makedirs(upload_folder, exist_ok=True)
                        
                        # Generate secure filename
                        filename = secure_filename(file.filename)
                        unique_filename = f"{int(time.time())}_{filename}"
                        file_path = os.path.join(upload_folder, unique_filename)
                        file.save(file_path)
                        
                        # Store relative path for database
                        relative_path = f"uploads/printers/{unique_filename}"
                        uploaded_images.append(relative_path)
        
        # Combine existing (non-deleted) and new images
        all_images = final_existing_images + uploaded_images
        
        # Convert to JSON string for database
        images_json = json.dumps(all_images) if all_images else None
        
        # Delete actual image files from server for deleted images
        for deleted_image in deleted_images:
            try:
                # Construct full path to the image file
                image_path = os.path.join(current_app.root_path, 'static', deleted_image)
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception as e:
                print(f"Error deleting printer image {deleted_image}: {e}")
        
        # Update printer including images
        cur.execute("""
            UPDATE printers SET name=%s, serial_number=%s, year_purchased=%s, 
            status=%s, notes=%s, images=%s
            WHERE id=%s
        """, (
            request.form.get('printer_name'),
            request.form.get('serial_number'),
            request.form.get('year_purchased'),
            request.form.get('status'),
            request.form.get('notes'),
            images_json,
            equipment_id
        ))
        conn.commit()
        cur.close()
        conn.close()
        flash("Printer updated successfully.", "success")
        return redirect(url_for('admin.view_printers'))

    # For GET request, parse images JSON if it exists
    if printer and printer['images']:
        try:
            printer['images'] = json.loads(printer['images'])
        except:
            printer['images'] = []
    else:
        printer['images'] = []
        
    cur.close()
    conn.close()
    return render_template('add_edit_equipment.html', kind='printer', action='Edit', item=printer)

@admin_bp.route('/admin/printer/<int:equipment_id>')
def view_printer(equipment_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    # Join with stations table to get station details
    cur.execute("""
        SELECT p.*, s.name as station_name, s.location 
        FROM printers p 
        LEFT JOIN stations s ON p.station_id = s.id 
        WHERE p.id=%s
    """, (equipment_id,))
    printer = cur.fetchone()
    cur.close()
    conn.close()

    if not printer:
        flash("Printer not found.", "warning")
        return redirect(url_for('admin.view_printers'))

    # Parse images JSON if it exists
    if printer and printer['images']:
        try:
            printer['images'] = json.loads(printer['images'])
        except:
            printer['images'] = []
    else:
        printer['images'] = []

    return render_template('single_printer.html', printer=printer)

@admin_bp.route('/admin/printer/<int:printer_id>/delete', methods=['POST'])
def delete_printer(printer_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get printer data including images
        cur.execute("SELECT images FROM printers WHERE id=%s", (printer_id,))
        printer = cur.fetchone()
        
        if not printer:
            flash("Printer not found.", "warning")
            return redirect(url_for('admin.view_printers'))
        
        # Delete associated image files
        if printer and printer['images']:
            try:
                images = json.loads(printer['images'])
                for image_path in images:
                    try:
                        full_path = os.path.join(current_app.root_path, 'static', image_path)
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except Exception as e:
                        print(f"Error deleting printer image {image_path}: {e}")
            except:
                pass
        
        # Delete the printer from database
        cur.execute("DELETE FROM printers WHERE id=%s", (printer_id,))
        conn.commit()
        flash("Printer deleted successfully.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting printer: {str(e)}", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.view_printers'))

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
        return redirect(url_for('admin.admin_dashboard'))

    cur.execute("DELETE FROM equipment WHERE id=%s", (equipment_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Equipment deleted successfully.", "success")
    return redirect(url_for('admin.view_station', station_id=eq['station_id']))

# ---------------- VIEW EQUIPMENT ----------------
@admin_bp.route('/admin/equipment/<int:equipment_id>')
def view_computer(equipment_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Join with stations table to get station name
    cur.execute("""
        SELECT e.*, s.name as station_name 
        FROM equipment e 
        LEFT JOIN stations s ON e.station_id = s.id 
        WHERE e.id=%s AND e.type='computer'
    """, (equipment_id,))
    
    computer = cur.fetchone()
    
    if not computer:
        flash("Computer not found.", "warning")
        cur.close()
        conn.close()
        return redirect(url_for('admin.admin_dashboard'))

    # Parse images if they exist
    if computer['images']:
        try:
            computer_images = json.loads(computer['images'])
            # Convert computer to dict to make it mutable
            computer_dict = dict(computer)
            computer_dict['images'] = computer_images
            computer = computer_dict
        except:
            # If parsing fails, keep as is or set to empty list
            computer_dict = dict(computer)
            computer_dict['images'] = []
            computer = computer_dict
    else:
        computer_dict = dict(computer)
        computer_dict['images'] = []
        computer = computer_dict

    cur.close()
    conn.close()
    return render_template('view_computer.html', computer=computer)



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
        resolution_details = request.form.get('resolution_details')  # NEW FIELD
        
        # Validate that resolution_details is provided when status is 'resolved'
        if status == 'resolved' and not resolution_details:
            flash("Resolution details are required when status is 'Resolved'.", "danger")
            
            # Get data again for the form
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
        
        cur.execute("""
            INSERT INTO maintenance 
            (device_type, device_id, station_id, issue_description, technician, 
             status, date_reported, date_resolved, resolution_details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (device_type, device_id, station_id, issue_description, technician, 
              status, date_reported, date_resolved, resolution_details))
        
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
        resolution_details = request.form.get('resolution_details')  # NEW FIELD
        
        # Validate that resolution_details is provided when status is 'resolved'
        if status == 'resolved' and not resolution_details:
            flash("Resolution details are required when status is 'Resolved'.", "danger")
            
            # Get data again for the form
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
        
        cur.execute("""
            UPDATE maintenance SET 
            device_type = %s, device_id = %s, station_id = %s, issue_description = %s, 
            technician = %s, status = %s, date_reported = %s, date_resolved = %s,
            resolution_details = %s
            WHERE id = %s
        """, (device_type, device_id, station_id, issue_description, technician, 
              status, date_reported, date_resolved, resolution_details, record_id))
        
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
    
    # Get all computers with station names
    cur.execute("""
        SELECT e.*, s.name as station_name 
        FROM equipment e 
        LEFT JOIN stations s ON e.station_id = s.id 
        WHERE e.type = 'computer'
        ORDER BY e.id DESC
    """)
    computers = cur.fetchall()
    
    # Add this line to get stations for the filter dropdown
    cur.execute("SELECT name FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.close()
    conn.close()

    # Add stations to the template context
    return render_template('view_computers.html', computers=computers, stations=stations)

# Router Management Routes
@admin_bp.route('/admin/routers')
def view_routers():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT r.*, s.name as station_name, s.location
        FROM routers r 
        LEFT JOIN stations s ON r.station_id = s.id 
        ORDER BY r.name
    """)
    routers = cur.fetchall()
    
    cur.execute("SELECT id, name, location FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('view_routers.html', routers=routers, stations=stations)

@admin_bp.route('/admin/add_router', methods=['GET', 'POST'])
def add_router():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, location FROM stations ORDER BY name")
    stations = cur.fetchall()
    cur.close()
    conn.close()

    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            # Handle image uploads
            uploaded_images = []
            
            # Process new image uploads
            if 'router_images' in request.files:
                files = request.files.getlist('router_images')
                
                for file in files:
                    if file and file.filename:
                        # Validate file is an image
                        if allowed_file(file.filename):
                            # Create uploads directory if it doesn't exist
                            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'routers')
                            os.makedirs(upload_folder, exist_ok=True)
                            
                            # Generate secure filename
                            filename = secure_filename(file.filename)
                            # Add timestamp to make filename unique
                            unique_filename = f"{int(time.time())}_{filename}"
                            file_path = os.path.join(upload_folder, unique_filename)
                            file.save(file_path)
                            
                            # Store relative path for database
                            relative_path = f"uploads/routers/{unique_filename}"
                            uploaded_images.append(relative_path)
            
            # Convert images list to JSON string for database storage
            images_json = json.dumps(uploaded_images) if uploaded_images else None
            
            cur.execute("""
                INSERT INTO routers 
                (station_id, name, brand, model, ip_address, serial_number, 
                 username, password, status, purchase_date, notes, images)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request.form.get('station_id'),
                request.form.get('router_name'),
                request.form.get('brand'),
                request.form.get('model'),
                request.form.get('ip_address'),
                request.form.get('serial_number'),
                request.form.get('username'),
                request.form.get('password'),
                request.form.get('status', 'active'),
                request.form.get('purchase_date'),
                request.form.get('notes'),
                images_json
            ))
            
            conn.commit()
            flash("Router added successfully!", "success")
            return redirect(url_for('admin.view_routers'))
            
        except Exception as e:
            conn.rollback()
            flash(f"Error adding router: {str(e)}", "danger")
            import traceback
            traceback.print_exc()
        finally:
            cur.close()
            conn.close()

    return render_template('add_edit_router.html', action='Add', stations=stations)

@admin_bp.route('/admin/router/<int:router_id>/edit', methods=['GET', 'POST'])
def edit_router(router_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get stations for dropdown
    cur.execute("SELECT id, name, location FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    if request.method == 'GET':
        cur.execute("SELECT * FROM routers WHERE id = %s", (router_id,))
        router = cur.fetchone()
        cur.close()
        conn.close()
        
        if not router:
            flash("Router not found.", "warning")
            return redirect(url_for('admin.view_routers'))
        
        # Parse images JSON if it exists
        if router and router['images']:
            try:
                router['images'] = json.loads(router['images'])
            except:
                router['images'] = []
        else:
            router['images'] = []
            
        return render_template('add_edit_router.html', action='Edit', router=router, stations=stations)

    # POST request - update router
    try:
        # Get existing images
        cur.execute("SELECT images FROM routers WHERE id = %s", (router_id,))
        existing_data = cur.fetchone()
        existing_images = []
        
        if existing_data and existing_data['images']:
            try:
                existing_images = json.loads(existing_data['images'])
            except:
                # If images is not valid JSON, treat it as empty
                existing_images = []
        
        # Get existing images from form that are NOT deleted
        form_existing_images = request.form.getlist('existing_images')
        
        # Get deleted images from form
        deleted_images_json = request.form.get('deleted_images', '[]')
        try:
            deleted_images = json.loads(deleted_images_json)
        except:
            deleted_images = []
        
        # Filter out deleted images
        final_existing_images = [img for img in existing_images if img not in deleted_images]
        
        # Handle new image uploads
        uploaded_images = []
        
        if 'router_images' in request.files:
            files = request.files.getlist('router_images')
            
            for file in files:
                if file and file.filename:
                    if allowed_file(file.filename):
                        # Create uploads directory if it doesn't exist
                        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'routers')
                        os.makedirs(upload_folder, exist_ok=True)
                        
                        # Generate secure filename
                        filename = secure_filename(file.filename)
                        unique_filename = f"{int(time.time())}_{filename}"
                        file_path = os.path.join(upload_folder, unique_filename)
                        file.save(file_path)
                        
                        # Store relative path for database
                        relative_path = f"uploads/routers/{unique_filename}"
                        uploaded_images.append(relative_path)
        
        # Combine existing (non-deleted) and new images
        all_images = final_existing_images + uploaded_images
        
        # Convert to JSON string for database
        images_json = json.dumps(all_images) if all_images else None
        
        # Delete actual image files from server for deleted images
        for deleted_image in deleted_images:
            try:
                # Construct full path to the image file
                image_path = os.path.join(current_app.root_path, 'static', deleted_image)
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception as e:
                print(f"Error deleting image {deleted_image}: {e}")
        
        cur.execute("""
            UPDATE routers SET 
            station_id=%s, name=%s, brand=%s, model=%s, ip_address=%s, 
            serial_number=%s, username=%s, password=%s, status=%s, 
            purchase_date=%s, notes=%s, images=%s
            WHERE id=%s
        """, (
            request.form.get('station_id'),
            request.form.get('router_name'),
            request.form.get('brand'),
            request.form.get('model'),
            request.form.get('ip_address'),
            request.form.get('serial_number'),
            request.form.get('username'),
            request.form.get('password'),
            request.form.get('status'),
            request.form.get('purchase_date'),
            request.form.get('notes'),
            images_json,
            router_id
        ))
        
        conn.commit()
        flash("Router updated successfully!", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error updating router: {str(e)}", "danger")
        import traceback
        traceback.print_exc()
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.view_router', router_id=router_id))
@admin_bp.route('/admin/router/<int:router_id>')
def view_router(router_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.*, s.name as station_name, s.location
        FROM routers r 
        LEFT JOIN stations s ON r.station_id = s.id 
        WHERE r.id = %s
    """, (router_id,))
    router = cur.fetchone()
    cur.close()
    conn.close()

    if not router:
        flash("Router not found.", "warning")
        return redirect(url_for('admin.view_routers'))

    # Parse images JSON if it exists
    if router and router['images']:
        try:
            router['images'] = json.loads(router['images'])
        except:
            router['images'] = []
    else:
        router['images'] = []

    return render_template('view_router.html', router=router)

@admin_bp.route('/admin/router/<int:router_id>/delete', methods=['POST'])
def delete_router(router_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # First, get the router's images to delete them from filesystem
        cur.execute("SELECT images FROM routers WHERE id = %s", (router_id,))
        router_data = cur.fetchone()
        
        # Delete associated image files
        if router_data and router_data['images']:
            try:
                images = json.loads(router_data['images'])
                for image_path in images:
                    try:
                        full_path = os.path.join(current_app.root_path, 'static', image_path)
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except Exception as e:
                        print(f"Error deleting image {image_path}: {e}")
            except:
                pass
        
        # Now delete the router from database
        cur.execute("DELETE FROM routers WHERE id = %s", (router_id,))
        conn.commit()
        flash("Router deleted successfully!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error deleting router: {str(e)}", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.view_routers'))

# ==================== ANTIVIRUS MANAGEMENT ====================
@admin_bp.route('/admin/antivirus/<int:antivirus_id>')
def view_antivirus(antivirus_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:     
        cur.execute("""
            SELECT av.*, 
                   COUNT(ea.equipment_id) as assigned_count,
                   STRING_AGG(e.name, ', ') as assigned_equipment_names
            FROM antivirus_software av
            LEFT JOIN equipment_antivirus ea ON av.id = ea.antivirus_id
            LEFT JOIN equipment e ON ea.equipment_id = e.id
            WHERE av.id = %s
            GROUP BY av.id
        """, (antivirus_id,))
        
        antivirus = cur.fetchone()
        
        if not antivirus:
            flash('Antivirus not found.', 'danger')
            return redirect(url_for('admin.antivirus_list'))
        
        cur.execute("""
            SELECT e.*, ea.installed_date, ea.assigned_by
            FROM equipment_antivirus ea
            JOIN equipment e ON ea.equipment_id = e.id
            WHERE ea.antivirus_id = %s
            ORDER BY e.name
        """, (antivirus_id,))
        
        assigned_equipment = cur.fetchall()
        
    except Exception as e:
        print(f"DEBUG: Error fetching antivirus details: {e}")
        flash('Error loading antivirus details.', 'danger')
        return redirect(url_for('admin.antivirus_list'))
    finally:
        cur.close()
        conn.close()
    
    from datetime import date
    today = date.today()
    
    return render_template('antivirus/view.html', 
                         antivirus=antivirus,
                         assigned_equipment=assigned_equipment,
                         today=today,
                         title=f"Antivirus Details - {antivirus['name']}")

@admin_bp.route('/admin/antivirus')
def antivirus_list():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get all antivirus software with equipment assignments
    cur.execute("""
        SELECT av.*, 
               COUNT(ea.equipment_id) as assigned_count,
               STRING_AGG(e.name, ', ') as assigned_equipment
        FROM antivirus_software av
        LEFT JOIN equipment_antivirus ea ON av.id = ea.antivirus_id
        LEFT JOIN equipment e ON ea.equipment_id = e.id
        GROUP BY av.id
        ORDER BY av.name
    """)
    antivirus_list = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('antivirus/list.html', 
                         antivirus_list=antivirus_list, 
                         today=datetime.now().date())

@admin_bp.route('/admin/antivirus/add', methods=['GET', 'POST'])
def antivirus_add():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form['name']
            version = request.form.get('version')
            vendor = request.form.get('vendor')
            activation_key = request.form.get('activation_key')
            activation_date = request.form.get('activation_date')
            expiry_date = request.form.get('expiry_date')
            license_type = request.form.get('license_type')
            notes = request.form.get('notes')
            equipment_id = request.form.get('equipment_id')
            
            print(f"DEBUG: Form data received - Name: {name}, Equipment ID: {equipment_id}")
            
            # Insert new antivirus
            cur.execute("""
                INSERT INTO antivirus_software 
                (name, version, vendor, activation_key, activation_date, expiry_date, license_type, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, version, vendor, activation_key, activation_date, expiry_date, license_type, notes))
            
            result = cur.fetchone()
            print(f"DEBUG: Insert result: {result}")
            
            antivirus_id = result['id']
            print(f"DEBUG: Antivirus ID: {antivirus_id}")
            
            # Assign to the selected computer
            if equipment_id:
                cur.execute("""
                    INSERT INTO equipment_antivirus (equipment_id, antivirus_id, installed_date, assigned_by)
                    VALUES (%s, %s, %s, %s)
                """, (equipment_id, antivirus_id, activation_date, session['user_id']))
            
            conn.commit()
            flash('Antivirus added successfully!', 'success')
            return redirect(url_for('admin.antivirus_list'))
            
        except Exception as e:
            conn.rollback()
            print(f"DEBUG: Full error details: {e}")
            print(f"DEBUG: Error type: {type(e)}")
            flash('Error adding antivirus. Please try again.', 'danger')
            return redirect(url_for('admin.antivirus_list'))
        finally:
            cur.close()
            conn.close()
    
    # GET request - get stations and computers
    cur.execute("SELECT * FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.execute("""
        SELECT id, name, assigned_user, model, station_id
        FROM equipment 
        WHERE type = 'computer' AND status = 'active' 
        ORDER BY name
    """)
    computers = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('antivirus/add.html', stations=stations, computers=computers)

@admin_bp.route('/admin/antivirus/edit/<int:antivirus_id>', methods=['GET', 'POST'])
def edit_antivirus(antivirus_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form['name']
            version = request.form.get('version')
            vendor = request.form.get('vendor')
            activation_key = request.form.get('activation_key')
            activation_date = request.form.get('activation_date')
            expiry_date = request.form.get('expiry_date')
            license_type = request.form.get('license_type')
            notes = request.form.get('notes')
            
            cur.execute("""
                UPDATE antivirus_software 
                SET name = %s, version = %s, vendor = %s, activation_key = %s, 
                    activation_date = %s, expiry_date = %s, license_type = %s, notes = %s
                WHERE id = %s
            """, (name, version, vendor, activation_key, activation_date, expiry_date, license_type, notes, antivirus_id))
            
            conn.commit()
            flash('Antivirus updated successfully!', 'success')
            return redirect(url_for('admin.view_antivirus', antivirus_id=antivirus_id))
            
        except Exception as e:
            conn.rollback()
            print(f"DEBUG: Error updating antivirus: {e}")
            flash('Error updating antivirus. Please try again.', 'danger')
            return redirect(url_for('admin.edit_antivirus', antivirus_id=antivirus_id))
        finally:
            cur.close()
            conn.close()
    
    try:
        cur.execute("SELECT * FROM antivirus_software WHERE id = %s", (antivirus_id,))
        antivirus = cur.fetchone()
        
        if not antivirus:
            flash('Antivirus not found.', 'danger')
            return redirect(url_for('admin.antivirus_list'))
            
    except Exception as e:
        print(f"DEBUG: Error fetching antivirus: {e}")
        flash('Error loading antivirus details.', 'danger')
        return redirect(url_for('admin.antivirus_list'))
    finally:
        cur.close()
        conn.close()
    
    return render_template('antivirus/edit.html', antivirus=antivirus)

@admin_bp.route('/admin/antivirus/<int:antivirus_id>/delete', methods=['POST'])
def delete_antivirus(antivirus_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        
        cur.execute("DELETE FROM equipment_antivirus WHERE antivirus_id = %s", (antivirus_id,))
        cur.execute("DELETE FROM antivirus_notifications WHERE antivirus_id = %s", (antivirus_id,))
        cur.execute("DELETE FROM antivirus_software WHERE id = %s", (antivirus_id,))
        
        conn.commit()
        flash('Antivirus deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting antivirus: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.antivirus_list'))

@admin_bp.route('/admin/antivirus/<int:antivirus_id>/assign', methods=['GET', 'POST'])
def antivirus_assign(antivirus_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        equipment_ids = request.form.getlist('equipment')
        installed_date = request.form['installed_date']
        
        for equipment_id in equipment_ids:
            # Check if already assigned
            cur.execute("SELECT id FROM equipment_antivirus WHERE equipment_id = %s AND antivirus_id = %s", 
                       (equipment_id, antivirus_id))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO equipment_antivirus (equipment_id, antivirus_id, installed_date, assigned_by)
                    VALUES (%s, %s, %s, %s)
                """, (equipment_id, antivirus_id, installed_date, session['user_id']))
        
        conn.commit()
        flash('Antivirus assigned to equipment successfully!', 'success')
        return redirect(url_for('admin.antivirus_list'))
    
    # GET request
    cur.execute("SELECT * FROM antivirus_software WHERE id = %s", (antivirus_id,))
    antivirus = cur.fetchone()
    
    cur.execute("""
        SELECT e.id, e.name, e.assigned_user, e.model, e.processor
        FROM equipment e 
        WHERE e.type = 'computer' 
        AND e.status = 'active' 
        AND e.id NOT IN (
            SELECT equipment_id FROM equipment_antivirus WHERE antivirus_id = %s
        )
        ORDER BY e.name
    """, (antivirus_id,))
    available_equipment = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('antivirus/assign.html', 
                         antivirus=antivirus, 
                         equipment=available_equipment)

@admin_bp.route('/admin/antivirus/check-expiry')
def check_antivirus_expiry():
    """Check for antivirus expiring in 2 months and create notifications"""
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    
    two_months_later = (datetime.now() + timedelta(days=60)).date()
    
    # Find antivirus expiring in 2 months
    cur.execute("""
        SELECT ea.id, av.name, av.expiry_date, e.name as equipment_name, e.id as equipment_id, av.id as antivirus_id
        FROM equipment_antivirus ea
        JOIN antivirus_software av ON ea.antivirus_id = av.id
        JOIN equipment e ON ea.equipment_id = e.id
        WHERE av.expiry_date BETWEEN CURRENT_DATE AND %s
        AND ea.status = 'Active'
        AND av.id NOT IN (
            SELECT antivirus_id FROM antivirus_notifications 
            WHERE notification_type = 'expiry_warning' AND created_at > CURRENT_DATE - INTERVAL '7 days'
        )
    """, (two_months_later,))
    
    expiring_soon = cur.fetchall()
    
    notifications_created = 0
    for item in expiring_soon:
        days_remaining = (item[2] - datetime.now().date()).days
        message = f"Antivirus '{item[1]}' on computer '{item[3]}' expires in {days_remaining} days"
        
        cur.execute("""
            INSERT INTO antivirus_notifications 
            (antivirus_id, equipment_id, message, notification_type, days_remaining)
            VALUES (%s, %s, %s, %s, %s)
        """, (item[5], item[4], message, 'expiry_warning', days_remaining))
        
        notifications_created += 1
    
    conn.commit()
    cur.close()
    conn.close()
    
    flash(f'Checked expiry dates. Created {notifications_created} new notifications.', 'info')
    return redirect(url_for('admin.antivirus_list'))    

@admin_bp.route('/admin/maintenance/<int:record_id>')
def view_maintenance(record_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT m.*, 
               s.name as station_name,
               e.name as device_name,
               e.type as device_type
        FROM maintenance m
        LEFT JOIN stations s ON m.station_id = s.id
        LEFT JOIN equipment e ON m.device_id = e.id
        WHERE m.id = %s
    """, (record_id,))
    
    record = cur.fetchone()
    
    if not record:
        flash("Maintenance record not found.", "danger")
        return redirect(url_for('admin.maintenance_records'))
    
    cur.close()
    conn.close()
    
    return render_template('view_maintenance.html', record=record)

@admin_bp.route('/admin/send_items/<int:send_id>/edit', methods=['GET', 'POST'])
def edit_send_items(send_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get the send record
    cur.execute("""
        SELECT s.*, 
               from_st.name as from_station_name,
               to_st.name as to_station_name
        FROM send_items s
        LEFT JOIN stations from_st ON s.from_station_id = from_st.id
        LEFT JOIN stations to_st ON s.to_station_id = to_st.id
        WHERE s.id = %s
    """, (send_id,))
    
    send_record = cur.fetchone()
    
    if not send_record:
        flash("Send record not found.", "warning")
        return redirect(url_for('admin.send_items_history'))
    
    # Get send items details
    cur.execute("SELECT * FROM send_items_details WHERE send_id = %s", (send_id,))
    send_items = cur.fetchall()
    
    if request.method == 'POST':
        
        sent_by = request.form.get('sent_by')
        send_date = request.form.get('send_date')
        expected_delivery_date = request.form.get('expected_delivery_date') or None
        notes = request.form.get('notes')
        
        
        cur.execute("""
            UPDATE send_items 
            SET sent_by = %s, send_date = %s, 
                expected_delivery_date = %s, notes = %s
            WHERE id = %s
        """, (sent_by, send_date, expected_delivery_date, notes, send_id))
        
        
        if send_record['status'] == 'sent':  
            
            cur.execute("SELECT id FROM send_items_details WHERE send_id = %s", (send_id,))
            existing_ids = [row['id'] for row in cur.fetchall()]
            
            # Get form data for items
            item_ids = request.form.getlist('item_ids[]')
            item_names = request.form.getlist('item_names[]')
            item_quantities = request.form.getlist('item_quantities[]')
            item_conditions = request.form.getlist('item_conditions[]')
            
            # Update or insert items
            for i in range(len(item_names)):
                if i < len(item_ids) and item_ids[i]:  
                    cur.execute("""
                        UPDATE send_items_details 
                        SET item_name = %s, quantity = %s, condition = %s
                        WHERE id = %s AND send_id = %s
                    """, (item_names[i], item_quantities[i], item_conditions[i], 
                          item_ids[i], send_id))
                else:  
                    cur.execute("""
                        INSERT INTO send_items_details 
                        (send_id, item_name, quantity, condition)
                        VALUES (%s, %s, %s, %s)
                    """, (send_id, item_names[i], item_quantities[i], item_conditions[i]))
            
           
            submitted_ids = [int(id) for id in item_ids if id]
            ids_to_delete = [id for id in existing_ids if id not in submitted_ids]
            
            for item_id in ids_to_delete:
                cur.execute("DELETE FROM send_items_details WHERE id = %s", (item_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash("Send record updated successfully.", "success")
        return redirect(url_for('admin.send_items_history'))
    
    
    cur.execute("SELECT * FROM stations ORDER BY name")
    stations = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('edit_send_items.html', 
                         send_record=send_record,
                         send_items=send_items,
                         stations=stations)

@admin_bp.route('/admin/send_items/<int:send_id>/delete', methods=['POST'])
def delete_send_items(send_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    
    cur.execute("SELECT * FROM send_items WHERE id = %s", (send_id,))
    send_record = cur.fetchone()
    
    if not send_record:
        flash("Send record not found.", "warning")
        return redirect(url_for('admin.send_items_history'))
    
    
    cur.execute("DELETE FROM send_items_details WHERE send_id = %s", (send_id,))
    
    
    cur.execute("DELETE FROM send_items WHERE id = %s", (send_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    flash("Send record deleted successfully.", "success")
    return redirect(url_for('admin.send_items_history'))

@admin_bp.route('/admin/transfers/<int:transfer_id>/view')
def view_transfer(transfer_id):
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
        WHERE t.id = %s
    """, (transfer_id,))
    
    transfer = cur.fetchone()
    
    cur.close()
    conn.close()
    
    if not transfer:
        flash("Transfer record not found.", "warning")
        return redirect(url_for('admin.transfer_history'))
    
    return render_template('view_transfer.html', transfer=transfer)

# ==================== STOCK MANAGEMENT ROUTES (PostgreSQL) ====================

def get_notification_data(conn):
    """Helper function to get notification data for any admin page - KEEPS ALL NOTIFICATIONS"""
    cur = None
    try:
        cur = conn.cursor()
        
        
        cur.execute("""
            SELECT id, action, details, user_name, created_at,
                   (created_at > NOW() - INTERVAL '1 hour') as is_unread,
                   CASE 
                       WHEN created_at > NOW() - INTERVAL '1 minute' THEN 'just now'
                       WHEN created_at > NOW() - INTERVAL '1 hour' THEN EXTRACT(MINUTE FROM AGE(NOW(), created_at))::text || ' minutes ago'
                       WHEN created_at > NOW() - INTERVAL '1 day' THEN EXTRACT(HOUR FROM AGE(NOW(), created_at))::text || ' hours ago'
                       ELSE EXTRACT(DAY FROM AGE(NOW(), created_at))::text || ' days ago'
                   END as time_ago
            FROM stock_history 
            ORDER BY created_at DESC 
            LIMIT 100  -- Get more notifications
        """)
        recent_activity = cur.fetchall()
        
        
        cur.execute("SELECT COUNT(*) as unread_count FROM stock_history WHERE created_at > NOW() - INTERVAL '1 hour'")
        unread_result = cur.fetchone()
        unread_notifications_count = unread_result['unread_count'] if unread_result else 0
        
        return recent_activity, unread_notifications_count
        
    except Exception as e:
        print(f"Error in get_notification_data: {e}")
        
        return [], 0
    finally:
        if cur:
            cur.close()

@admin_bp.route('/admin/stock_management')
def stock_management():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        
        item_type = request.args.get('item_type', '')
        status = request.args.get('status', '')
        low_stock = request.args.get('low_stock', '')
        
        
        query = """
            SELECT si.*, 
                   s1.name as sent_to_station_name,
                   s2.name as used_at_station_name
            FROM stock_items si
            LEFT JOIN stations s1 ON si.sent_to_station = s1.id
            LEFT JOIN stations s2 ON si.used_at_station = s2.id
            WHERE 1=1
        """
        params = []
        
        if item_type:
            query += " AND si.item_type = %s"
            params.append(item_type)
        
        if status:
            query += " AND si.status = %s"
            params.append(status)
        
        if low_stock:
            query += " AND si.quantity <= 5"
        
        query += " ORDER BY si.item_name"
        
        cur.execute(query, params)
        stock_items = cur.fetchall()
        
       
        cur.execute("SELECT COUNT(*) as total FROM stock_items")
        result = cur.fetchone()
        total_stock_items = result['total'] if result else 0
        
        cur.execute("SELECT COUNT(*) as toner_count FROM stock_items WHERE item_type = 'Toner'")
        result = cur.fetchone()
        toner_count = result['toner_count'] if result else 0
        
        cur.execute("SELECT COUNT(*) as in_stock_count FROM stock_items WHERE status = 'In Stock'")
        result = cur.fetchone()
        in_stock_count = result['in_stock_count'] if result else 0
        
        cur.execute("SELECT COUNT(*) as low_stock_count FROM stock_items WHERE quantity <= 5")
        result = cur.fetchone()
        low_stock_count = result['low_stock_count'] if result else 0
        
        
        cur.execute("""
            SELECT si.*, s1.name as sent_to_station_name
            FROM stock_items si
            LEFT JOIN stations s1 ON si.sent_to_station = s1.id
            WHERE si.quantity <= 5 
            ORDER BY si.quantity ASC
        """)
        low_stock_items = cur.fetchall()
        
        
        cur.execute("SELECT id, name, location FROM stations ORDER BY name")
        stations = cur.fetchall()
        
       
        try:
            cur.execute("""
                SELECT sh.*, si.item_name 
                FROM stock_history sh 
                LEFT JOIN stock_items si ON sh.stock_item_id = si.id 
                ORDER BY sh.created_at DESC 
                LIMIT 20
            """)
            stock_history = cur.fetchall()
        except Exception:
            stock_history = []
        
       
        recent_activity, unread_notifications_count = get_notification_data(conn)
        
        cur.close()
        conn.close()
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        return render_template(
            'stock_management.html',
            stock_items=stock_items,
            total_stock_items=total_stock_items,
            toner_count=toner_count,
            in_stock_count=in_stock_count,
            low_stock_count=low_stock_count,
            low_stock_items=low_stock_items,
            stock_history=stock_history,
            stations=stations,
            today=today,
            recent_activity=recent_activity,
            unread_notifications_count=unread_notifications_count,
            current_filters={
                'item_type': item_type,
                'status': status,
                'low_stock': low_stock
            }
        )
        
    except Exception as e:
        if cur:
            cur.close()
        if conn:
            conn.close()
        flash(f'Error loading stock management: {str(e)}', 'danger')
        return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/add_stock_item', methods=['POST'])
def add_stock_item():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get form data
        item_name = request.form.get('item_name')
        item_type = request.form.get('item_type')
        quantity = request.form.get('quantity', 1)
        purchase_date = request.form.get('purchase_date') or None
        supplier = request.form.get('supplier')
        model_number = request.form.get('model_number')
        compatible_with = request.form.get('compatible_with')
        notes = request.form.get('notes')
        username = session.get('username', 'Admin')
        
       
        cur.execute("""
            INSERT INTO stock_items 
            (item_name, item_type, quantity, purchase_date, supplier, model_number, compatible_with, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (item_name, item_type, quantity, purchase_date, supplier, model_number, compatible_with, notes))
        
       
        stock_item_id = cur.fetchone()['id']
        
       
        cur.execute("""
            INSERT INTO stock_history (stock_item_id, action, details, user_name, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (stock_item_id, 'Added', f'Added {quantity} {item_name} to stock', username))
        
        conn.commit()
        flash('Stock item added successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error adding stock item: {e}")
        flash(f'Error adding stock item: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.stock_management'))

@admin_bp.route('/admin/update_stock_status', methods=['POST'])
def update_stock_status():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        stock_item_id = request.form.get('stock_item_id')
        status = request.form.get('status')
        send_quantity = int(request.form.get('send_quantity', 1))
        remaining_action = request.form.get('remaining_action', 'keep_in_stock')
        username = session.get('username', 'Admin')
        
       
        if send_quantity < 1:
            flash('Quantity to send must be at least 1.', 'danger')
            return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))
        
        
        cur.execute("""
            SELECT item_name, quantity, status FROM stock_items WHERE id = %s
        """, (stock_item_id,))
        item = cur.fetchone()
        
        if not item:
            flash('Stock item not found.', 'danger')
            return redirect(url_for('admin.stock_management'))
        
        
        if item['quantity'] < send_quantity:
            flash(f'Not enough stock available. Only {item["quantity"]} items in stock.', 'danger')
            return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))
        
        new_quantity = item['quantity'] - send_quantity
        
        if status == 'sent':
            sent_to_station = request.form.get('sent_to_station')
            sent_date = request.form.get('sent_date') or datetime.now().strftime('%Y-%m-%d')
            sent_notes = request.form.get('sent_notes')
            
            if not sent_to_station:
                flash('Please select a station to send to.', 'danger')
                return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))
            
            
            cur.execute("SELECT name FROM stations WHERE id = %s", (sent_to_station,))
            station = cur.fetchone()
            station_name = station['name'] if station else 'Unknown Station'
            
            if remaining_action == 'update_all':
                
                update_query = """
                    UPDATE stock_items 
                    SET status = 'Sent', 
                        sent_to_station = %s, 
                        sent_date = %s, 
                        sent_notes = %s,
                        quantity = 0
                    WHERE id = %s
                """
                params = (sent_to_station, sent_date, sent_notes, stock_item_id)
                
                history_action = 'Sent'
                history_details = f'Sent ALL {item["quantity"]} of {item["item_name"]} to station: {station_name}'
                flash_message = f'All {item["quantity"]} items sent to station successfully!'
                
            else:  
                
                if new_quantity > 0:
                    update_query = """
                        UPDATE stock_items 
                        SET quantity = %s
                        WHERE id = %s
                    """
                    params = (new_quantity, stock_item_id)
                else:
                    
                    update_query = """
                        UPDATE stock_items 
                        SET status = 'Sent', 
                            sent_to_station = %s, 
                            sent_date = %s, 
                            sent_notes = %s,
                            quantity = 0
                        WHERE id = %s
                    """
                    params = (sent_to_station, sent_date, sent_notes, stock_item_id)
                
                history_action = 'Partial Sent'
                history_details = f'Sent {send_quantity} of {item["item_name"]} to station: {station_name}. {new_quantity} items remain in stock.'
                flash_message = f'{send_quantity} item(s) sent successfully! {new_quantity} items remain in stock.'
            
            
            cur.execute(update_query, params)
            
           
            cur.execute("""
                INSERT INTO stock_history (stock_item_id, action, details, user_name, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (stock_item_id, history_action, history_details, username))
            
            flash(flash_message, 'success')
        
        elif status == 'used':
            used_for_printer = request.form.get('used_for_printer')
            used_at_station = request.form.get('used_at_station')
            used_date = request.form.get('used_date') or datetime.now().strftime('%Y-%m-%d')
            usage_notes = request.form.get('usage_notes')
            
            if not used_for_printer or not used_at_station:
                flash('Please fill in printer and station details.', 'danger')
                return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))
            
            
            cur.execute("SELECT name FROM stations WHERE id = %s", (used_at_station,))
            station = cur.fetchone()
            station_name = station['name'] if station else 'Unknown Station'
            
            if remaining_action == 'update_all':
               
                update_query = """
                    UPDATE stock_items 
                    SET status = 'Used', 
                        used_for_printer = %s, 
                        used_at_station = %s, 
                        used_date = %s, 
                        usage_notes = %s,
                        quantity = 0
                    WHERE id = %s
                """
                params = (used_for_printer, used_at_station, used_date, usage_notes, stock_item_id)
                
                history_action = 'Used'
                history_details = f'Used ALL {item["quantity"]} of {item["item_name"]} for printer: {used_for_printer} at station: {station_name}'
                flash_message = f'All {item["quantity"]} items marked as used successfully!'
                
            else:  
                
                if new_quantity > 0:
                    update_query = """
                        UPDATE stock_items 
                        SET quantity = %s
                        WHERE id = %s
                    """
                    params = (new_quantity, stock_item_id)
                else:
                   
                    update_query = """
                        UPDATE stock_items 
                        SET status = 'Used', 
                            used_for_printer = %s, 
                            used_at_station = %s, 
                            used_date = %s, 
                            usage_notes = %s,
                            quantity = 0
                        WHERE id = %s
                    """
                    params = (used_for_printer, used_at_station, used_date, usage_notes, stock_item_id)
                
                history_action = 'Partial Used'
                history_details = f'Used {send_quantity} of {item["item_name"]} for printer: {used_for_printer} at station: {station_name}. {new_quantity} items remain in stock.'
                flash_message = f'{send_quantity} item(s) marked as used successfully! {new_quantity} items remain in stock.'
            
            
            cur.execute(update_query, params)
            
            
            cur.execute("""
                INSERT INTO stock_history (stock_item_id, action, details, user_name, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (stock_item_id, history_action, history_details, username))
            
            flash(flash_message, 'success')
        
        else:
            flash('Invalid status selected.', 'danger')
            return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))
        
        conn.commit()
        
    except ValueError:
        flash('Invalid quantity specified.', 'danger')
        return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))
    except Exception as e:
        conn.rollback()
        print(f"Error updating stock status: {e}")
        flash(f'Error updating stock status: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.view_stock_item', item_id=stock_item_id))

@admin_bp.route('/admin/edit_stock_item', methods=['POST'])
def edit_stock_item():
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        stock_item_id = request.form.get('stock_item_id')
        item_name = request.form.get('item_name')
        item_type = request.form.get('item_type')
        quantity = request.form.get('quantity')
        purchase_date = request.form.get('purchase_date') or None
        supplier = request.form.get('supplier')
        model_number = request.form.get('model_number')
        compatible_with = request.form.get('compatible_with')
        notes = request.form.get('notes')
        username = session.get('username', 'Admin')
        
        # Update stock item
        cur.execute("""
            UPDATE stock_items 
            SET item_name = %s, 
                item_type = %s, 
                quantity = %s, 
                purchase_date = %s, 
                supplier = %s, 
                model_number = %s, 
                compatible_with = %s, 
                notes = %s
            WHERE id = %s
        """, (item_name, item_type, quantity, purchase_date, supplier, 
              model_number, compatible_with, notes, stock_item_id))
        
        # Add to history
        cur.execute("""
            INSERT INTO stock_history (stock_item_id, action, details, user_name, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (stock_item_id, 'Updated', f'Updated {item_name} details', username))
        
        conn.commit()
        flash('Stock item updated successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error updating stock item: {e}")
        flash(f'Error updating stock item: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.stock_management'))

@admin_bp.route('/admin/delete_stock_item/<int:item_id>', methods=['POST'])
def delete_stock_item(item_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
       
        cur.execute("SELECT item_name FROM stock_items WHERE id = %s", (item_id,))
        item = cur.fetchone()
        
        if item:
          
            cur.execute("""
                INSERT INTO stock_history (stock_item_id, action, details, user_name, created_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (item_id, 'Deleted', f'Deleted {item["item_name"]} from stock', session['username']))
        
       
        cur.execute("DELETE FROM stock_items WHERE id = %s", (item_id,))
        
        conn.commit()
        flash('Stock item deleted successfully!', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error deleting stock item: {e}")
        flash(f'Error deleting stock item: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.stock_management'))

@admin_bp.route('/admin/restock_item/<int:item_id>', methods=['POST'])
def restock_item(item_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        additional_quantity = request.form.get('quantity', 1)
        purchase_date = request.form.get('purchase_date')  
        username = session.get('username', 'Admin')
        
        
        cur.execute("SELECT item_name FROM stock_items WHERE id = %s", (item_id,))
        item = cur.fetchone()
        
        if not item:
            flash('Stock item not found.', 'danger')
            return redirect(url_for('admin.stock_management'))
        
       
        cur.execute("""
            UPDATE stock_items 
            SET quantity = quantity + %s, 
                status = 'In Stock'
            WHERE id = %s
        """, (additional_quantity, item_id))
        
        if purchase_date:
            history_details = f'Added {additional_quantity} more {item["item_name"]} to stock (Purchased: {purchase_date})'
        else:
            history_details = f'Added {additional_quantity} more {item["item_name"]} to stock'
        
        # Add to history
        cur.execute("""
            INSERT INTO stock_history (stock_item_id, action, details, user_name, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (item_id, 'Restocked', history_details, username))
        
        conn.commit()
        
        # Flash message with purchase date if provided
        if purchase_date:
            flash(f'Item restocked successfully! {additional_quantity} items added. Purchase date: {purchase_date}', 'success')
        else:
            flash(f'Item restocked successfully! {additional_quantity} items added.', 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error restocking item: {e}")
        flash(f'Error restocking item: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('admin.stock_management'))

@admin_bp.route('/admin/stock_item/<int:item_id>')
def view_stock_item(item_id):
    if session.get('role') != 'admin':
        flash("Access denied.", "danger")
        return redirect(url_for('auth.login'))

    conn = None
    cur = None
    try:
        print("=== DEBUG: Starting view_stock_item ===")
        print(f"DEBUG: item_id = {item_id}")
        print(f"DEBUG: session role = {session.get('role')}")
        
        conn = get_db_connection()
        cur = conn.cursor()
        print("DEBUG: Got database connection")
        
        # Get stock item with station details
        query = """
            SELECT si.*, 
                   s1.name as sent_to_station_name,
                   s2.name as used_at_station_name
            FROM stock_items si
            LEFT JOIN stations s1 ON si.sent_to_station = s1.id
            LEFT JOIN stations s2 ON si.used_at_station = s2.id
            WHERE si.id = %s
        """
        print(f"DEBUG: Executing query: {query}")
        print(f"DEBUG: With param: {item_id}")
        
        cur.execute(query, (item_id,))
        item = cur.fetchone()
        
        print(f"DEBUG: Item fetched: {item}")
        if not item:
            print("DEBUG: Item not found!")
            flash('Stock item not found.', 'danger')
            return redirect(url_for('admin.stock_management'))
        
        
        history_query = """
            SELECT * FROM stock_history 
            WHERE stock_item_id = %s 
            ORDER BY created_at DESC
        """
        print(f"DEBUG: Getting history with query: {history_query}")
        
        cur.execute(history_query, (item_id,))
        history = cur.fetchall()
        print(f"DEBUG: Got {len(history)} history records")
        
        
        cur.execute("SELECT id, name, location FROM stations ORDER BY name")
        stations = cur.fetchall()
        print(f"DEBUG: Got {len(stations)} stations")
        
        
        recent_activity, unread_notifications_count = get_notification_data(conn)
        print(f"DEBUG: Got {len(recent_activity)} recent activities")
        print(f"DEBUG: Unread notifications: {unread_notifications_count}")
        
        cur.close()
        conn.close()
        
        today = datetime.now().strftime('%Y-%m-%d')
        print(f"DEBUG: today = {today}")
        print(f"DEBUG: Rendering template view_stock_item.html")
        print(f"DEBUG: Item keys available: {list(item.keys()) if item else 'No item'}")
        
        return render_template('view_stock_item.html',
                             item=item,
                             history=history,
                             stations=stations,
                             today=today,
                             recent_activity=recent_activity,
                             unread_notifications_count=unread_notifications_count)
        
    except Exception as e:
        print(f"=== DEBUG: ERROR in view_stock_item ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        import traceback
        print("Traceback:")
        traceback.print_exc()
        print(f"=== END DEBUG ===")
        
        if cur:
            cur.close()
        if conn:
            conn.close()
        flash(f'Error viewing stock item: {str(e)}', 'danger')
        return redirect(url_for('admin.stock_management'))


@admin_bp.route('/admin/get_notifications', methods=['GET'])
def get_notifications():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Access denied'}), 403
    
    conn = get_db_connection()
    try:
        recent_activity, unread_notifications_count = get_notification_data(conn)
        
       
        notifications = []
        for activity in recent_activity:
            notifications.append({
                'id': activity['id'],
                'action': activity['action'],
                'details': activity['details'],
                'user_name': activity['user_name'],
                'time_ago': activity['time_ago'],
                'is_unread': activity['is_unread']
            })
        
        return jsonify({
            'notifications': notifications,
            'unread_count': unread_notifications_count
        })
    except Exception as e:
        print(f"Error getting notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()