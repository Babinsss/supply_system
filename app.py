import uuid
import json
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///supplies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'super_secret_key_change_this_later'

db = SQLAlchemy(app)

# --- Helper Function for Philippine Time (UTC+8) ---
def get_pht_time():
    return datetime.utcnow() + timedelta(hours=8)

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
    created_at = db.Column(db.DateTime, default=get_pht_time)
    updated_at = db.Column(db.DateTime, default=get_pht_time, onupdate=get_pht_time)

class DepartmentRequest(db.Model):
    __tablename__ = 'department_requests'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(50), nullable=False)
    department_name = db.Column(db.String(100), nullable=False)
    requested_by = db.Column(db.String(100), nullable=False)
    supply_id = db.Column(db.Integer, db.ForeignKey('supplies.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='Pending') 
    created_at = db.Column(db.DateTime, default=get_pht_time)
    supply = db.relationship('Supply', backref=db.backref('requests', lazy=True))

# --- ADMIN ROUTES ---
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    supplies = Supply.query.all()
    all_requests = DepartmentRequest.query.order_by(DepartmentRequest.created_at.desc()).all()
    
    # Group the requests by batch_id so they appear as one transaction
    grouped_batches = {}
    for req in all_requests:
        if req.batch_id not in grouped_batches:
            grouped_batches[req.batch_id] = {
                'batch_id': req.batch_id,
                'created_at': req.created_at,
                'department_name': req.department_name,
                'requested_by': req.requested_by,
                'status': req.status,
                'items': []
            }
        grouped_batches[req.batch_id]['items'].append(req)
    
    requests_to_display = list(grouped_batches.values())
    pending_count = len([b for b in requests_to_display if b['status'] == 'Pending'])
    
    return render_template('dashboard.html', items=supplies, requests=requests_to_display, pending_count=pending_count)

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
        if item.quantity < 0: item.quantity = 0
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

# --- STOCKCARD WITH MONTHLY FILTER & BALANCES ---
@app.route('/stockcard/<int:item_id>')
def stockcard(item_id):
    item = Supply.query.get_or_404(item_id)
    
    # 1. Determine the selected month (default to current month in PHT)
    month_filter = request.args.get('month', get_pht_time().strftime('%Y-%m'))
    
    # 2. Fetch ALL approved releases to accurately calculate running balances
    all_releases = DepartmentRequest.query.filter_by(
        supply_id=item_id, 
        status='Approved'
    ).order_by(DepartmentRequest.created_at.desc()).all()
    
    # 3. Calculate backward running balances based on current actual stock
    current_bal = item.quantity
    for release in all_releases:
        release.running_balance = current_bal
        current_bal += release.quantity
        
    # 4. Filter to only show transactions for the selected month
    monthly_releases = [r for r in all_releases if r.created_at.strftime('%Y-%m') == month_filter]
    
    # 5. Determine "Balance Forwarded" (the starting balance BEFORE this month's transactions)
    older_releases = [r for r in all_releases if r.created_at.strftime('%Y-%m') < month_filter]
    if older_releases:
        balance_forwarded = older_releases[0].running_balance
    else:
        balance_forwarded = current_bal # If no older transactions, starting balance is the original full amount
        
    # 6. Generate a list of available months for the dropdown selector
    available_months = sorted(list(set(r.created_at.strftime('%Y-%m') for r in all_releases)), reverse=True)
    if month_filter not in available_months:
        available_months.insert(0, month_filter)
        
    available_months_formatted = []
    for m in available_months:
        date_obj = datetime.strptime(m, '%Y-%m')
        available_months_formatted.append({
            'value': m,
            'label': date_obj.strftime('%B %Y').upper()
        })
        
    current_month_label = datetime.strptime(month_filter, '%Y-%m').strftime('%B %Y').upper()
    
    return render_template(
        'stockcard.html', 
        item=item, 
        releases=monthly_releases, 
        month_filter=month_filter, 
        available_months=available_months_formatted,
        current_month_label=current_month_label,
        balance_forwarded=balance_forwarded
    )

@app.route('/process-batch/<batch_id>/<action>', methods=['GET', 'POST'])
def process_batch(batch_id, action):
    batch_reqs = DepartmentRequest.query.filter_by(batch_id=batch_id).all()
    
    if not batch_reqs:
        flash('Request not found.', 'danger')
        return redirect(url_for('dashboard'))

    if batch_reqs[0].status != 'Pending':
        flash('This request has already been processed.', 'warning')
        return redirect(url_for('dashboard'))

    if action == 'approve':
        # Check if the admin modified quantities via the modal form
        if request.method == 'POST':
            for req in batch_reqs:
                adj_qty = request.form.get(f'qty_{req.id}', type=int)
                if adj_qty is not None:
                    req.quantity = adj_qty 

        # Verify stock for ALL items before approving anything
        for req in batch_reqs:
            if req.supply.quantity < req.quantity:
                flash(f'Cannot approve! Not enough stock for {req.supply.name}. You tried to release {req.quantity} but only have {req.supply.quantity}.', 'danger')
                return redirect(url_for('dashboard'))
        
        # Deduct quantities and approve the batch
        for req in batch_reqs:
            req.supply.quantity -= req.quantity
            req.status = 'Approved'
        flash('Bulk request approved and stock updated!', 'success')
            
    elif action == 'deny':
        for req in batch_reqs:
            req.status = 'Denied'
        flash('Bulk request denied. Stock remains unchanged.', 'success')

    db.session.commit()
    return redirect(url_for('dashboard'))

# --- REAL-TIME & PORTAL ROUTES ---
@app.route('/api/pending-count')
def pending_count_api():
    pending_batches = db.session.query(DepartmentRequest.batch_id).filter_by(status='Pending').distinct().all()
    return jsonify({'count': len(pending_batches)})

@app.route('/portal')
def department_portal():
    available_supplies = Supply.query.filter(Supply.quantity > 0).all()
    return render_template('portal.html', supplies=available_supplies)

@app.route('/submit-request', methods=['POST'])
def submit_request():
    dept = request.form.get('department_name')
    person = request.form.get('requested_by')
    purpose = request.form.get('purpose')
    cart_json = request.form.get('cart_data', '[]')
    
    try:
        cart_data = json.loads(cart_json)
    except json.JSONDecodeError:
        cart_data = []

    if not cart_data:
        flash('Please add items to your cart before submitting.', 'danger')
        return redirect(url_for('department_portal'))

    batch_id = str(uuid.uuid4())
    for item in cart_data:
        new_req = DepartmentRequest(
            batch_id=batch_id, department_name=dept, requested_by=person,
            supply_id=int(item['id']), quantity=int(item['qty']), purpose=purpose
        )
        db.session.add(new_req)
        
    db.session.commit()
    flash('Your bulk request has been successfully submitted to ICT.', 'success')
    return redirect(url_for('department_portal'))

@app.route('/print-bulk/<batch_id>')
def print_bulk(batch_id):
    batch_requests = DepartmentRequest.query.filter_by(batch_id=batch_id).all()
    if not batch_requests:
        return "Batch not found", 404
    return render_template('print_template.html', batch_requests=batch_requests)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)