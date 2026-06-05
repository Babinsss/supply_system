from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///supplies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'super_secret_key_change_this_later'

db = SQLAlchemy(app)

# --- DATABASE MODELS ---

class Supply(db.Model):
    __tablename__ = 'supplies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    unit = db.Column(db.String(50), nullable=False) 
    reorder_level = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Supply {self.name}>'

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False) 

    def __repr__(self):
        return f'<User {self.email}>'

class DepartmentRequest(db.Model):
    __tablename__ = 'department_requests'
    id = db.Column(db.Integer, primary_key=True)
    department_name = db.Column(db.String(100), nullable=False)
    requested_by = db.Column(db.String(100), nullable=False)
    supply_id = db.Column(db.Integer, db.ForeignKey('supplies.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    purpose = db.Column(db.String(255), nullable=False) # NEW PURPOSE FIELD
    status = db.Column(db.String(20), default='Pending') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    supply = db.relationship('Supply', backref=db.backref('requests', lazy=True))

    def __repr__(self):
        return f'<Request {self.department_name} - {self.quantity}x>'

# --- ADMIN ROUTES ---

@app.route('/')
def dashboard():
    supplies = Supply.query.all()
    pending_count = DepartmentRequest.query.filter_by(status='Pending').count()
    admin_requests = DepartmentRequest.query.order_by(DepartmentRequest.created_at.desc()).all()
    
    return render_template(
        'dashboard.html', 
        items=supplies, 
        pending_count=pending_count,
        requests=admin_requests
    )

@app.route('/add', methods=['POST'])
def add_item():
    name = request.form.get('name')
    category = request.form.get('category')
    description = request.form.get('description')
    quantity = request.form.get('quantity', type=int)
    unit = request.form.get('unit')
    reorder_level = request.form.get('reorder_level', type=int)

    if not name or quantity is None or not unit or reorder_level is None:
        flash('Name, quantity, unit, and reorder level are required!', 'danger')
        return redirect(url_for('dashboard'))

    new_supply = Supply(
        name=name, category=category, description=description,
        quantity=quantity, unit=unit, reorder_level=reorder_level
    )
    db.session.add(new_supply)
    db.session.commit()
    flash('Item added successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/update/<int:id>', methods=['POST'])
def update_stock(id):
    item = Supply.query.get_or_404(id)
    adjustment = request.form.get('adjustment', type=int)
    
    if adjustment is not None:
        item.quantity += adjustment
        if item.quantity < 0:
            item.quantity = 0
        db.session.commit()
        flash(f'Stock updated successfully for {item.name}!', 'success')
        
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:id>')
def delete_item(id):
    item = Supply.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Item successfully deleted.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/setup-admin')
def setup_admin():
    try:
        existing_admin = User.query.filter_by(email='admin@hospital.com').first()
        if existing_admin:
            return 'Admin account already exists.'

        hashed_password = generate_password_hash('password')
        admin = User(name='Admin', email='admin@hospital.com', password=hashed_password)
        db.session.add(admin)
        db.session.commit()
        return 'SUCCESS! Admin account created. You can now login.'
    except Exception as e:
        db.session.rollback()
        return f'Error: {str(e)}'

@app.route('/process-request/<int:req_id>/<action>')
def process_request(req_id, action):
    req = DepartmentRequest.query.get_or_404(req_id)
    
    if req.status != 'Pending':
        flash('This request has already been processed.', 'warning')
        return redirect(url_for('dashboard'))

    if action == 'approve':
        if req.supply.quantity >= req.quantity:
            req.supply.quantity -= req.quantity 
            req.status = 'Approved'
            flash(f'Request approved. {req.quantity} {req.supply.unit} deducted from {req.supply.name}.', 'success')
        else:
            flash(f'Cannot approve! Not enough stock for {req.supply.name}.', 'danger')
            return redirect(url_for('dashboard'))
            
    elif action == 'deny':
        req.status = 'Denied'
        flash('Request denied. Stock remains unchanged.', 'success')

    db.session.commit()
    return redirect(url_for('dashboard'))

# --- REAL-TIME & PRINT ROUTES ---

@app.route('/api/pending-count')
def pending_count_api():
    count = DepartmentRequest.query.filter_by(status='Pending').count()
    return jsonify({'count': count})

@app.route('/print-request/<int:req_id>')
def print_request(req_id):
    req = DepartmentRequest.query.get_or_404(req_id)
    return render_template('print_template.html', req=req)

# --- DEPARTMENT PORTAL ROUTES ---

@app.route('/portal')
def department_portal():
    available_supplies = Supply.query.filter(Supply.quantity > 0).all()
    return render_template('portal.html', supplies=available_supplies)

@app.route('/submit-request', methods=['POST'])
def submit_request():
    department = request.form.get('department_name')
    person = request.form.get('requested_by')
    supply_id = request.form.get('supply_id', type=int)
    quantity = request.form.get('quantity', type=int)
    purpose = request.form.get('purpose') # CAPTURE NEW FIELD

    if not department or not person or not supply_id or not quantity or not purpose:
        flash('All fields are required to submit a request.', 'danger')
        return redirect(url_for('department_portal'))

    new_request = DepartmentRequest(
        department_name=department,
        requested_by=person,
        supply_id=supply_id,
        quantity=quantity,
        purpose=purpose # SAVE TO DB
    )
    db.session.add(new_request)
    db.session.commit()
    
    flash('Request submitted successfully! ICT will review it shortly.', 'success')
    return redirect(url_for('department_portal'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)