# app.py
from flask import Flask, render_template, redirect, url_for
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from routes.user_routes import user_bp
from models.db_models import init_db


app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "replace_with_a_real_secret"  # change this

# initialize DB tables 
init_db()

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(user_bp, url_prefix='/user')

@app.route('/')
def index():
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000, debug=True)
