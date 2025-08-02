import os
import functools
import re
from math import ceil
from datetime import datetime, timezone

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import LoginManager, current_user, login_required
from flask_jwt_extended import JWTManager

from sqlalchemy import func, desc
from sqlalchemy.orm import joinedload

from core.extensions import db, csrf
from core.models import User, Role, SecretQuestion, ParkingArea, ParkingSpot, Car, Booking
from forms import ParkingLotForm, CarForm, SearchSpotForm
from auth import auth_bp
from api_auth import api_auth_bp
from api_admin import api_admin_bp
from bootstrap_auth import bootstrap_auth


# ---------------------------
# App & Config
# ---------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-that-you-should-change')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///parking.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["JWT_SECRET_KEY"] = os.environ.get('JWT_SECRET_KEY', 'another-super-secret-key')

# Initialize extensions
db.init_app(app)
csrf.init_app(app)
jwt = JWTManager(app)

# Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(api_auth_bp)
app.register_blueprint(api_admin_bp)

# If your API blueprints accept JSON-only, it's fine to exempt them from CSRF
csrf.exempt(api_auth_bp)
csrf.exempt(api_admin_bp)

# Seed DB once at startup (Flask 3.x no longer has before_first_request)
with app.app_context():
    db.create_all()
    bootstrap_auth()  # creates roles, admin, and offline/walk-in user(s) as defined there


# ---------------------------
# Login Manager
# ---------------------------
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login_page'
login_manager.login_message_category = 'warning'
login_manager.login_message = 'Please log in to access this page.'


@login_manager.user_loader
def load_user(user_id):
    return User.query.filter_by(fs_uniquifier=user_id).first()


# ---------------------------
# Helpers
# ---------------------------
def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.has_role('admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def _now_utc():
    return datetime.now(timezone.utc)

def _complete_booking(booking):
    """Mark booking completed, free the spot, and compute cost."""
    if booking.status == 'completed':
        return
    booking.status = 'completed'
    booking.end_time = datetime.now(timezone.utc)

    start = booking.start_time
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    if booking.spot:
        booking.spot.status = 'available'
        if start:
            price = booking.spot.parking_area.price_per_hour
            hours = (booking.end_time - start).total_seconds() / 3600
            billed_hours = max(1, ceil(hours))
            booking.total_cost = round(billed_hours * price, 2)


# ---------------------------
# Root
# ---------------------------
@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login_page'))
    return redirect(url_for('admin_dashboard' if current_user.has_role('admin') else 'user_dashboard'))


# ---------------------------
# Admin Views
# ---------------------------
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    areas = ParkingArea.query.order_by(ParkingArea.name).all()
    occupancy_data = []
    for area in areas:
        total_spots = area.spots.count()
        occupied_spots = area.spots.filter_by(status='occupied').count()
        occupancy_data.append({
            'area': area,
            'total': total_spots,
            'occupied': occupied_spots,
            'available': total_spots - occupied_spots,
        })
    return render_template('admin_dashboard.html', occupancy_data=occupancy_data)


@app.post('/admin/offline-book')
@login_required
@admin_required
def admin_offline_book():
    """
    JSON endpoint used by the Admin Dashboard 'Offline Booking' form (modal).
    Creates/attaches car to offline user if needed, picks first available spot,
    and starts an ACTIVE booking immediately.
    """
    plate = (request.form.get('license_plate') or '').strip().upper()
    area_id = request.form.get('area_id', type=int)

    if not plate or not area_id:
        return jsonify(ok=False, message="License plate and area are required."), 400

    area = ParkingArea.query.get_or_404(area_id)

    # Find or create car; attach to offline user if not registered
    car = Car.query.filter_by(license_plate=plate).first()
    if not car:
        offline_user = User.query.filter_by(username='offline_user').first()
        if not offline_user:
            return jsonify(ok=False, message="Offline user missing. Run bootstrap."), 500
        car = Car(license_plate=plate, user_id=offline_user.id)
        db.session.add(car)
        db.session.flush()

    # One active/pending booking per car
    existing = Booking.query.filter(
        Booking.car_id == car.id,
        Booking.status.in_(('active', 'pending'))
    ).first()
    if existing:
        return jsonify(ok=False, message="This car already has an active/pending booking."), 400

    # First available spot in area
    spot = ParkingSpot.query.filter_by(
        parking_area_id=area.id, status='available'
    ).order_by(ParkingSpot.spot_identifier.asc()).first()

    if not spot:
        return jsonify(ok=False, message=f"No available spots in {area.name}."), 400

    # Activate immediately
    spot.status = 'occupied'
    booking = Booking(
        user_id=car.user_id,
        car_id=car.id,
        spot_id=spot.id,
        status='active',
        start_time=_now_utc()
    )
    db.session.add(booking)
    db.session.commit()

    return jsonify(
        ok=True,
        plate=plate,
        area_name=area.name,
        spot_identifier=spot.spot_identifier,
        booking_id=booking.id
    )


@app.post('/admin/offline/release/<int:booking_id>')
@login_required
@admin_required
def admin_offline_release(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.status != 'active':
        flash('This booking is not active.', 'warning')
        return redirect(url_for('admin_requests'))

    _complete_booking(b)
    db.session.commit()
    plate = b.car.license_plate if b.car else 'N/A'
    spot  = b.spot.spot_identifier if b.spot else 'N/A'
    flash(f'Released {plate} from {spot}. Cost: ₹{(b.total_cost or 0):.2f}', 'success')
    return redirect(url_for('admin_requests'))

@app.route('/admin/areas/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_area_new():
    form = ParkingLotForm()
    if form.validate_on_submit():
        new_area = ParkingArea(
            name=form.prime_location_name.data,
            location_description=form.address.data,
            price_per_hour=form.price_per_hour.data
        )
        db.session.add(new_area)
        db.session.flush()

        num_spots = form.max_spots.data
        area_code = form.area_code.data.upper()
        for i in range(1, num_spots + 1):
            spot_identifier = f"{area_code}-{i}"
            spot = ParkingSpot(spot_identifier=spot_identifier, parking_area_id=new_area.id, status='available')
            db.session.add(spot)

        db.session.commit()
        flash(f'Parking area "{new_area.name}" with {num_spots} spots created.', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_lot_form.html', form=form, mode='new')


@app.route('/admin/areas/<int:area_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_area_edit(area_id):
    area = ParkingArea.query.get_or_404(area_id)
    form = ParkingLotForm(obj=area)

    if form.validate_on_submit():
        area.name = form.prime_location_name.data
        area.location_description = form.address.data
        area.price_per_hour = form.price_per_hour.data
        db.session.commit()
        flash(f'Parking area "{area.name}" has been updated.', 'success')
        return redirect(url_for('admin_dashboard'))

    form.prime_location_name.data = area.name
    form.address.data = area.location_description
    form.price_per_hour.data = area.price_per_hour
    form.max_spots.data = area.spots.count()
    form.max_spots.render_kw = {'readonly': True}

    return render_template('admin_lot_form.html', form=form, mode='edit', lot=area)


@app.route('/admin/areas/<int:area_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_area_delete(area_id):
    area = ParkingArea.query.get_or_404(area_id)
    if area.spots.filter_by(status='occupied').count() > 0:
        flash('Cannot delete area: it has currently occupied spots.', 'danger')
    else:
        db.session.delete(area)
        db.session.commit()
        flash(f'Parking area "{area.name}" has been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/summary')
@login_required
@admin_required
def admin_summary():
    # high-level stats
    total_areas = ParkingArea.query.count()
    total_spots = ParkingSpot.query.count()
    occupied_spots = ParkingSpot.query.filter_by(status='occupied').count()
    reserved_spots = ParkingSpot.query.filter_by(status='reserved').count()
    available_spots = ParkingSpot.query.filter_by(status='available').count()

    active_bookings = Booking.query.filter_by(status='active').count()
    pending_bookings = Booking.query.filter_by(status='pending').count()
    completed_bookings = Booking.query.filter_by(status='completed').count()

    revenue_total = db.session.query(
        func.coalesce(func.sum(Booking.total_cost), 0.0)
    ).filter(Booking.status == 'completed').scalar() or 0.0

    areas = ParkingArea.query.order_by(ParkingArea.name).all()

    return render_template(
        'admin_summary.html',
        total_areas=total_areas,
        total_spots=total_spots,
        occupied_spots=occupied_spots,
        reserved_spots=reserved_spots,
        available_spots=available_spots,
        active_bookings=active_bookings,
        pending_bookings=pending_bookings,
        completed_bookings=completed_bookings,
        revenue_total=round(revenue_total, 2),
        areas=areas
    )


@app.route('/admin/parking-history')
@login_required
@admin_required
def admin_all_parking():
    all_bookings = (
        Booking.query
        .options(
            joinedload(Booking.user),
            joinedload(Booking.car),
            joinedload(Booking.spot).joinedload(ParkingSpot.parking_area)
        )
        .order_by(Booking.start_time.desc())
        .all()
    )
    return render_template('admin_all_parking.html', bookings=all_bookings)

@app.route('/api/admin/occupancy')
@login_required
@admin_required
def api_admin_occupancy():
    labels, occupied, available = [], [], []
    for area in ParkingArea.query.order_by(ParkingArea.name).all():
        total = area.spots.count()
        occ = area.spots.filter_by(status='occupied').count()
        labels.append(area.name)
        occupied.append(occ)
        available.append(total - occ)
    return jsonify({"labels": labels, "occupied": occupied, "available": available})


@app.route('/api/admin/revenue')
@login_required
@admin_required
def api_admin_revenue():
    labels, totals = [], []
    for area in ParkingArea.query.order_by(ParkingArea.name).all():
        area_spot_ids = [s.id for s in area.spots]
        rev = db.session.query(func.coalesce(func.sum(Booking.total_cost), 0.0)) \
            .filter(Booking.spot_id.in_(area_spot_ids),
                    Booking.status == 'completed').scalar() or 0.0
        labels.append(area.name)
        totals.append(round(rev, 2))
    return jsonify({"labels": labels, "totals": totals})


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    last_parked_subq = db.session.query(
        Booking.user_id,
        func.max(Booking.end_time).label('last_parked_time')
    ).filter(Booking.status == 'completed').group_by(Booking.user_id).subquery()

    users_with_stats = db.session.query(
        User,
        last_parked_subq.c.last_parked_time
    ).outerjoin(last_parked_subq, User.id == last_parked_subq.c.user_id) \
     .order_by(desc(User.created_at)).all()

    users = [u for (u, _last) in users_with_stats]
    return render_template('admin_users.html', users=users)


@app.route('/api/admin/users/<int:user_id>/stats')
@login_required
@admin_required
def api_user_stats(user_id):
    user = User.query.get_or_404(user_id)
    bookings = user.bookings.order_by(desc(Booking.start_time)).all()

    total_spent = db.session.query(func.sum(Booking.total_cost)) \
        .filter(Booking.user_id == user_id, Booking.status == 'completed') \
        .scalar() or 0.0

    bookings_data = []
    for booking in bookings:
        area_name = "N/A"
        spot_identifier = "N/A"
        if booking.spot:
            spot_identifier = booking.spot.spot_identifier
            if booking.spot.parking_area:
                area_name = booking.spot.parking_area.name

        car_plate = booking.car.license_plate if booking.car else "N/A"

        bookings_data.append({
            'area_name': area_name,
            'spot_identifier': spot_identifier,
            'car_plate': car_plate,
            'start_time': booking.start_time.isoformat() if booking.start_time else None,
            'end_time': booking.end_time.isoformat() if booking.end_time else None,
            'status': booking.status,
            'cost': booking.total_cost
        })

    return jsonify({
        'username': user.username,
        'email': user.email,
        'member_since': user.created_at.isoformat(),
        'total_spent': round(total_spent, 2),
        'bookings': bookings_data
    })


@app.route('/admin/search', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_search():
    form = SearchSpotForm(request.form)
    areas = ParkingArea.query.order_by('name').all()
    form.area_id.choices = [(a.id, a.name) for a in areas]

    area_selected = None
    if form.area_id.data:
        area_selected = ParkingArea.query.get(form.area_id.data)
    elif areas:
        area_selected = areas[0]
        form.area_id.data = area_selected.id

    occupied_identifiers, available_identifiers = [], []
    if area_selected:
        spots = area_selected.spots.order_by(ParkingSpot.spot_identifier).all()
        for s in spots:
            (available_identifiers if s.status == 'available' else occupied_identifiers).append(s.spot_identifier)

    spot_result = None
    if request.method == 'POST' and form.validate_on_submit():
        spot_result = ParkingSpot.query.filter_by(
            parking_area_id=area_selected.id,
            spot_identifier=form.spot_identifier.data
        ).first()
        if not spot_result:
            flash(f'Spot "{form.spot_identifier.data}" not found in {area_selected.name}.', 'warning')

    return render_template(
        'admin_search.html',
        form=form,
        area_selected=area_selected,
        available_identifiers=available_identifiers,
        occupied_identifiers=occupied_identifiers,
        spot_result=spot_result,
    )


@app.route('/admin/requests')
@login_required
@admin_required
def admin_requests():
    pendings = Booking.query.filter_by(status='pending') \
                            .order_by(Booking.start_time.asc()).all()

    # show active bookings for the walk-in/offline user accounts
    offline_usernames = ('walkin', 'offline_user')
    offline_active = (
        Booking.query.join(User)
        .filter(Booking.status == 'active', User.username.in_(offline_usernames))
        .order_by(Booking.start_time.asc())
        .all()
    )

    return render_template('admin_requests.html', pendings=pendings, offline_active=offline_active)


@app.route('/api/admin/areas/<int:area_id>/spot-status')
@login_required
@admin_required
def api_admin_area_spot_status(area_id):
    area = ParkingArea.query.get_or_404(area_id)

    occupied_identifiers, available_identifiers = [], []

    first_spot = area.spots.first()
    area_code = first_spot.spot_identifier.split('-')[0] if first_spot else ""

    spots = sorted(
        area.spots,
        key=lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r'([0-9]+)', s.spot_identifier)]
    )

    for spot in spots:
        (available_identifiers if spot.status == 'available' else occupied_identifiers).append(spot.spot_identifier)

    return jsonify({
        'area_name': area.name,
        'area_code': area_code,
        'occupied_identifiers': occupied_identifiers,
        'available_identifiers': available_identifiers
    })


@app.route('/admin/requests/<int:booking_id>/approve', methods=['POST'])
@login_required
@admin_required
def admin_request_approve(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.status != 'pending':
        flash('This request is not pending.', 'warning')
        return redirect(url_for('admin_requests'))
    b.status = 'active'
    b.start_time = _now_utc()
    if b.spot:
        b.spot.status = 'occupied'
    db.session.commit()
    flash(f'Approved: {b.user.username} at {b.spot.spot_identifier}', 'success')
    return redirect(url_for('admin_requests'))


@app.route('/admin/requests/<int:booking_id>/reject', methods=['POST'])
@login_required
@admin_required
def admin_request_reject(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.status != 'pending':
        flash('This request is not pending.', 'warning')
        return redirect(url_for('admin_requests'))
    if b.spot:
        b.spot.status = 'available'
    b.status = 'rejected'
    db.session.commit()
    flash('Request rejected.', 'info')
    return redirect(url_for('admin_requests'))


# ---------------------------
# User Views
# ---------------------------
@app.route('/user')
@login_required
def user_dashboard():
    if current_user.has_role('admin'):
        return redirect(url_for('admin_dashboard'))

    areas = ParkingArea.query.order_by(ParkingArea.name).all()
    user_cars = current_user.cars.all()

    active_bookings = Booking.query.filter_by(user_id=current_user.id, status='active') \
        .order_by(Booking.start_time.desc()).all()
    pending_bookings = Booking.query.filter_by(user_id=current_user.id, status='pending') \
        .order_by(Booking.start_time.desc()).all()

    car_ids_locked = {
        b.car_id for b in Booking.query
        .filter(Booking.user_id == current_user.id, Booking.status.in_(('active', 'pending'))).all()
    }

    return render_template(
        'user_dashboard.html',
        areas=areas,
        cars=user_cars,
        active_bookings=active_bookings,
        pending_bookings=pending_bookings,
        car_ids_locked=car_ids_locked
    )


@app.route('/user/pending/<int:booking_id>/cancel', methods=['POST'])
@login_required
def user_cancel_pending(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.user_id != current_user.id or b.status != 'pending':
        abort(403)
    if b.spot:
        b.spot.status = 'available'
    b.status = 'rejected'
    db.session.commit()
    flash('Request cancelled.', 'info')
    return redirect(url_for('user_dashboard'))


@app.route('/user/cars', methods=['GET', 'POST'])
@login_required
def user_cars():
    form = CarForm()
    if form.validate_on_submit():
        if Car.query.filter_by(license_plate=form.license_plate.data).first():
            flash('A car with this license plate is already registered.', 'warning')
        else:
            new_car = Car(
                license_plate=form.license_plate.data,
                make=form.make.data,
                model=form.model.data,
                color=form.color.data,
                owner=current_user
            )
            db.session.add(new_car)
            db.session.commit()
            flash('New car added successfully!', 'success')
            return redirect(url_for('user_cars'))

    cars = current_user.cars.order_by(Car.license_plate).all()
    return render_template('user_cars.html', cars=cars, form=form)


@app.route('/user/summary')
@login_required
def user_summary():
    total_spent = db.session.query(func.coalesce(func.sum(Booking.total_cost), 0.0)) \
        .filter(Booking.user_id == current_user.id, Booking.status == 'completed') \
        .scalar() or 0.0

    total_sessions = Booking.query.filter_by(user_id=current_user.id, status='completed').count()

    last_5 = Booking.query.filter_by(user_id=current_user.id, status='completed') \
        .order_by(Booking.end_time.desc()).limit(5).all()

    return render_template(
        'user_summary.html',
        total_spent=round(total_spent, 2),
        total_sessions=total_sessions,
        last_5=last_5
    )


@app.route('/user/cars/<int:car_id>/delete', methods=['POST'])
@login_required
def user_car_delete(car_id):
    car = Car.query.get_or_404(car_id)
    if car.owner != current_user:
        abort(403)

    if car.bookings.filter_by(status='active').count() > 0:
        flash('Cannot delete a car that is currently parked.', 'danger')
    else:
        db.session.delete(car)
        db.session.commit()
        flash('Car has been removed.', 'success')
    return redirect(url_for('user_cars'))


@app.route('/user/release/<int:booking_id>', methods=['POST'])
@login_required
def user_release(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        abort(403)

    if booking.status == 'completed':
        flash('This booking has already been completed.', 'warning')
        return redirect(url_for('user_dashboard'))

    # Complete now with timezone-aware times
    booking.status = 'completed'
    booking.end_time = _now_utc()

    start = booking.start_time
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    spot = booking.spot
    if spot and start:
        spot.status = 'available'
        price = spot.parking_area.price_per_hour
        duration_hours = (booking.end_time - start).total_seconds() / 3600
        billed_hours = max(1, ceil(duration_hours))
        booking.total_cost = round(billed_hours * price, 2)

    db.session.commit()
    flash(f'Parking released. Cost: ₹{booking.total_cost:.2f}', 'success')
    return redirect(url_for('user_dashboard'))


@app.route('/api/user/spend')
@login_required
def api_user_spend():
    if current_user.has_role('admin'):
        abort(403)

    rows = Booking.query.filter_by(user_id=current_user.id, status='completed') \
        .order_by(Booking.end_time.desc()).limit(10).all()

    labels = [r.end_time.strftime('%d %b %H:%M') for r in reversed(rows)]
    totals = [round(r.total_cost or 0.0, 2) for r in reversed(rows)]
    return jsonify({"labels": labels, "totals": totals})


@app.route('/user/book', methods=['POST'])
@login_required
def user_book():
    if current_user.has_role('admin'):
        abort(403)

    area_id = request.form.get('area_id', type=int)
    car_id = request.form.get('car_id', type=int)

    if not area_id or not car_id:
        flash('You must select a parking area and a car.', 'danger')
        return redirect(url_for('user_dashboard'))

    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id:
        abort(403)

    existing_for_car = Booking.query.filter(
        Booking.car_id == car_id,
        Booking.status.in_(('active', 'pending'))
    ).first()
    if existing_for_car:
        flash('This car already has an active or pending booking.', 'warning')
        return redirect(url_for('user_dashboard'))

    spot = ParkingSpot.query.filter_by(
        parking_area_id=area_id, status='available'
    ).order_by(ParkingSpot.spot_identifier.asc()).first()

    if not spot:
        flash('Sorry, there are no available spots in this area right now.', 'danger')
        return redirect(url_for('user_dashboard'))

    spot.status = 'reserved'
    b = Booking(user_id=current_user.id, car_id=car_id, spot_id=spot.id, status='pending')
    db.session.add(b)
    db.session.commit()

    flash(f'Request submitted for spot {spot.spot_identifier}. Awaiting admin approval.', 'info')
    return redirect(url_for('user_dashboard'))


@app.route('/user/history')
@login_required
def user_history():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.start_time.desc()).all()
    return render_template('user_history.html', bookings=bookings)


@app.route('/admin/areas/<int:area_id>/view')
@login_required
@admin_required
def admin_area_view(area_id):
    area = ParkingArea.query.get_or_404(area_id)
    spots = area.spots.order_by(ParkingSpot.spot_identifier.asc()).all()
    return render_template('admin_area_view.html', area=area, spots=spots)


# ---------------------------
# Main Execution
# ---------------------------
if __name__ == '__main__':
    app.run(debug=True, port=5001)