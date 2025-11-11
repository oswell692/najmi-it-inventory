from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from config import get_db_connection
from werkzeug.security import check_password_hash
import psycopg2.extras

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')  # 'admin' or 'user'
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password) and user['role'] == role:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['station_id'] = user.get('station_id')

            if role == 'admin':
                return redirect(url_for('admin.admin_dashboard'))
            return redirect(url_for('user.user_dashboard'))

        flash("Invalid credentials or role mismatch", "danger")

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
