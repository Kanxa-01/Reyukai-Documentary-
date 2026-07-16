import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', '').replace(
    'postgres://', 'postgresql://', 1
)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

db = SQLAlchemy(app)

STATUS_CHOICES = ['Active', 'Expired', 'Suspended']

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Member(db.Model):
    """Mirrors the 'Members' sheet: S.N, Full Name, Address, Oya No./Oyaname,
    Entrance Date, Hozashu, Jun-Shibicho, Shibicho, Valid upto, Status."""
    __tablename__ = 'members'
    id = db.Column(db.Integer, primary_key=True)  # this IS the S.N shown in the UI
    full_name = db.Column(db.String(150), nullable=False, index=True)
    address = db.Column(db.String(255))

    # Oya = sponsor/mentor. Self-referencing link to another member's S.N.
    # Oyaname is never stored directly -- it's derived from this relationship
    # so it can never drift out of sync with the real member record.
    oya_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=True)
    oya = db.relationship('Member', remote_side=[id], backref='sponsored_members')

    entrance_date = db.Column(db.Date, default=date.today)
    hozashu = db.Column(db.String(150))
    jun_shibicho = db.Column(db.String(150))
    shibicho = db.Column(db.String(150), nullable=False, index=True)
    valid_upto = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), default='Active', index=True)

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def oya_name(self):
        return self.oya.full_name if self.oya else ''


class Receipt(db.Model):
    """Mirrors the 'Recipt' sheet: Receipt No., Member S.N, Full Name,
    Shibicho, Entrance Date, Renewal Date, Status. Full Name/Shibicho/Entrance
    Date are snapshotted at creation time so old receipts stay accurate even
    if the member record changes later."""
    __tablename__ = 'receipts'
    id = db.Column(db.Integer, primary_key=True)
    receipt_no = db.Column(db.String(50), nullable=False, index=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    member = db.relationship('Member', backref='receipts')

    full_name_snapshot = db.Column(db.String(150))
    shibicho_snapshot = db.Column(db.String(150))
    entrance_date_snapshot = db.Column(db.Date)

    renewal_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(30), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['display_name'] = user.display_name
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def dashboard():
    total_members = Member.query.count()
    total_receipts = Receipt.query.count()
    shibicho_counts = db.session.query(
        Member.shibicho, db.func.count(Member.id)
    ).group_by(Member.shibicho).order_by(Member.shibicho).all()
    return render_template(
        'dashboard.html',
        total_members=total_members,
        total_receipts=total_receipts,
        shibicho_counts=shibicho_counts,
    )


# ---------------------------------------------------------------------------
# Member CRUD
# ---------------------------------------------------------------------------

@app.route('/members')
@login_required
def members_list():
    shibicho_filter = request.args.get('shibicho', '')
    status_filter = request.args.get('status', '')
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = Member.query
    if shibicho_filter:
        query = query.filter(Member.shibicho == shibicho_filter)
    if status_filter:
        query = query.filter(Member.status == status_filter)
    if search:
        query = query.filter(Member.full_name.ilike(f'%{search}%'))

    pagination = query.order_by(Member.id).paginate(page=page, per_page=50, error_out=False)
    all_shibichos = [row[0] for row in db.session.query(Member.shibicho).distinct().order_by(Member.shibicho)]

    return render_template(
        'members_list.html',
        members=pagination.items,
        pagination=pagination,
        all_shibichos=all_shibichos,
        current_shibicho=shibicho_filter,
        current_status=status_filter,
        status_choices=STATUS_CHOICES,
        search=search,
    )


@app.route('/api/members/search')
@login_required
def api_members_search():
    """Used by the Oya No. autocomplete on the member form."""
    q = request.args.get('q', '').strip()
    exclude_id = request.args.get('exclude_id', type=int)
    if not q:
        return jsonify([])
    query = Member.query.filter(Member.full_name.ilike(f'%{q}%'))
    if exclude_id:
        query = query.filter(Member.id != exclude_id)
    results = query.order_by(Member.full_name).limit(10).all()
    return jsonify([{'id': m.id, 'full_name': m.full_name, 'shibicho': m.shibicho} for m in results])


@app.route('/members/add', methods=['GET', 'POST'])
@login_required
def member_add():
    if request.method == 'POST':
        member = Member(
            full_name=request.form['full_name'].strip(),
            address=request.form.get('address', '').strip(),
            hozashu=request.form.get('hozashu', '').strip(),
            jun_shibicho=request.form.get('jun_shibicho', '').strip(),
            shibicho=request.form['shibicho'].strip(),
            status=request.form.get('status', 'Active'),
            notes=request.form.get('notes', '').strip(),
        )
        oya_id = request.form.get('oya_id')
        member.oya_id = int(oya_id) if oya_id else None

        entrance_date_str = request.form.get('entrance_date')
        if entrance_date_str:
            member.entrance_date = datetime.strptime(entrance_date_str, '%Y-%m-%d').date()

        valid_upto_str = request.form.get('valid_upto')
        if valid_upto_str:
            member.valid_upto = datetime.strptime(valid_upto_str, '%Y-%m-%d').date()

        db.session.add(member)
        db.session.commit()
        flash(f'Added {member.full_name} (S.N. {member.id}).', 'success')
        return redirect(url_for('members_list'))
    return render_template('member_form.html', member=None)


@app.route('/members/<int:member_id>/edit', methods=['GET', 'POST'])
@login_required
def member_edit(member_id):
    member = Member.query.get_or_404(member_id)
    if request.method == 'POST':
        member.full_name = request.form['full_name'].strip()
        member.address = request.form.get('address', '').strip()
        member.hozashu = request.form.get('hozashu', '').strip()
        member.jun_shibicho = request.form.get('jun_shibicho', '').strip()
        member.shibicho = request.form['shibicho'].strip()
        member.status = request.form.get('status', 'Active')
        member.notes = request.form.get('notes', '').strip()

        oya_id = request.form.get('oya_id')
        member.oya_id = int(oya_id) if oya_id else None

        entrance_date_str = request.form.get('entrance_date')
        if entrance_date_str:
            member.entrance_date = datetime.strptime(entrance_date_str, '%Y-%m-%d').date()

        valid_upto_str = request.form.get('valid_upto')
        member.valid_upto = datetime.strptime(valid_upto_str, '%Y-%m-%d').date() if valid_upto_str else None

        db.session.commit()
        flash(f'Updated {member.full_name}.', 'success')
        return redirect(url_for('members_list'))
    return render_template('member_form.html', member=member)


@app.route('/members/<int:member_id>/delete', methods=['POST'])
@login_required
def member_delete(member_id):
    member = Member.query.get_or_404(member_id)
    if member.sponsored_members:
        flash(f'Cannot delete {member.full_name} -- other members list them as Oya. Reassign those first.', 'error')
        return redirect(url_for('members_list'))
    name = member.full_name
    db.session.delete(member)
    db.session.commit()
    flash(f'Deleted {name}.', 'success')
    return redirect(url_for('members_list'))


@app.route('/members/print')
@login_required
def members_print():
    shibicho_filter = request.args.get('shibicho', '')
    query = Member.query
    if shibicho_filter:
        query = query.filter(Member.shibicho == shibicho_filter)
    members = query.order_by(Member.full_name).all()
    all_shibichos = [row[0] for row in db.session.query(Member.shibicho).distinct().order_by(Member.shibicho)]
    return render_template(
        'members_print.html',
        members=members,
        shibicho=shibicho_filter or 'All Shibichos',
        all_shibichos=all_shibichos,
        printed_on=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )


# ---------------------------------------------------------------------------
# Receipts CRUD (separate tab, linked to Members)
# ---------------------------------------------------------------------------

@app.route('/receipts')
@login_required
def receipts_list():
    shibicho_filter = request.args.get('shibicho', '')
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = Receipt.query
    if shibicho_filter:
        query = query.filter(Receipt.shibicho_snapshot == shibicho_filter)
    if search:
        query = query.filter(
            db.or_(
                Receipt.receipt_no.ilike(f'%{search}%'),
                Receipt.full_name_snapshot.ilike(f'%{search}%'),
            )
        )

    pagination = query.order_by(Receipt.id.desc()).paginate(page=page, per_page=50, error_out=False)
    all_shibichos = [row[0] for row in db.session.query(Member.shibicho).distinct().order_by(Member.shibicho)]

    return render_template(
        'receipts_list.html',
        receipts=pagination.items,
        pagination=pagination,
        all_shibichos=all_shibichos,
        current_shibicho=shibicho_filter,
        search=search,
    )


@app.route('/receipts/add', methods=['GET', 'POST'])
@login_required
def receipt_add():
    if request.method == 'POST':
        member_id = int(request.form['member_id'])
        member = Member.query.get_or_404(member_id)

        receipt = Receipt(
            receipt_no=request.form['receipt_no'].strip(),
            member_id=member.id,
            full_name_snapshot=member.full_name,
            shibicho_snapshot=member.shibicho,
            entrance_date_snapshot=member.entrance_date,
            status=request.form.get('status', 'Active'),
        )
        renewal_date_str = request.form.get('renewal_date')
        if renewal_date_str:
            receipt.renewal_date = datetime.strptime(renewal_date_str, '%Y-%m-%d').date()

        db.session.add(receipt)
        db.session.commit()
        flash(f'Receipt {receipt.receipt_no} added for {member.full_name}.', 'success')
        return redirect(url_for('receipts_list'))
    return render_template('receipt_form.html', receipt=None)


@app.route('/receipts/<int:receipt_id>/edit', methods=['GET', 'POST'])
@login_required
def receipt_edit(receipt_id):
    receipt = Receipt.query.get_or_404(receipt_id)
    if request.method == 'POST':
        receipt.receipt_no = request.form['receipt_no'].strip()
        receipt.status = request.form.get('status', 'Active')
        renewal_date_str = request.form.get('renewal_date')
        if renewal_date_str:
            receipt.renewal_date = datetime.strptime(renewal_date_str, '%Y-%m-%d').date()
        db.session.commit()
        flash(f'Updated receipt {receipt.receipt_no}.', 'success')
        return redirect(url_for('receipts_list'))
    return render_template('receipt_form.html', receipt=receipt)


@app.route('/receipts/<int:receipt_id>/delete', methods=['POST'])
@login_required
def receipt_delete(receipt_id):
    receipt = Receipt.query.get_or_404(receipt_id)
    receipt_no = receipt.receipt_no
    db.session.delete(receipt)
    db.session.commit()
    flash(f'Deleted receipt {receipt_no}.', 'success')
    return redirect(url_for('receipts_list'))


@app.route('/receipts/print')
@login_required
def receipts_print():
    shibicho_filter = request.args.get('shibicho', '')
    query = Receipt.query
    if shibicho_filter:
        query = query.filter(Receipt.shibicho_snapshot == shibicho_filter)
    receipts = query.order_by(Receipt.id).all()
    all_shibichos = [row[0] for row in db.session.query(Member.shibicho).distinct().order_by(Member.shibicho)]
    return render_template(
        'receipts_print.html',
        receipts=receipts,
        shibicho=shibicho_filter or 'All Shibichos',
        all_shibichos=all_shibichos,
        printed_on=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )


# ---------------------------------------------------------------------------
# One-time web setup route (Render free tier has no Shell access)
# Visit /setup/<SETUP_KEY> once to create tables + your first login.
# Remove this route (or change SETUP_KEY) after you've used it.
# ---------------------------------------------------------------------------

SETUP_KEY = os.environ.get('SETUP_KEY', 'change-me-before-deploying')


@app.route('/setup/<key>', methods=['GET', 'POST'])
def one_time_setup(key):
    if key != SETUP_KEY:
        return 'Not found.', 404

    db.create_all()  # safe to run repeatedly -- does nothing if tables already exist

    message = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        if User.query.filter_by(username=username).first():
            message = f'User "{username}" already exists.'
        elif not username or not password:
            message = 'Username and password are required.'
        else:
            user = User(username=username, display_name=display_name or username,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            message = f'User "{username}" created successfully. You can now log in.'

    existing_users = [u.username for u in User.query.all()]
    return f'''
    <html><body style="font-family: sans-serif; max-width: 480px; margin: 60px auto;">
    <h2>One-time Setup</h2>
    <p>Tables created/verified. Existing users: {', '.join(existing_users) or 'none yet'}</p>
    {f"<p style='color: green;'><b>{message}</b></p>" if message else ""}
    <form method="POST">
        <label>Username</label><br>
        <input name="username" required style="width:100%; padding:8px; margin:6px 0;"><br>
        <label>Display Name</label><br>
        <input name="display_name" style="width:100%; padding:8px; margin:6px 0;"><br>
        <label>Password</label><br>
        <input name="password" type="password" required style="width:100%; padding:8px; margin:6px 0;"><br>
        <button type="submit" style="padding:10px 16px; margin-top:10px;">Create User</button>
    </form>
    <p><a href="/login">Go to login</a></p>
    </body></html>
    '''


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@app.cli.command('init-db')
def init_db():
    """Create tables. Run: flask --app app.py init-db"""
    db.create_all()
    print('Tables created.')


@app.cli.command('create-user')
def create_user():
    """Create a login user interactively. Run: flask --app app.py create-user"""
    username = input('Username: ').strip()
    display_name = input('Display name: ').strip()
    password = input('Password: ').strip()
    if User.query.filter_by(username=username).first():
        print('That username already exists.')
        return
    user = User(username=username, display_name=display_name,
                password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    print(f'User "{username}" created.')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
