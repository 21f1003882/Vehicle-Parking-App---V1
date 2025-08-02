from core.extensions import db 
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import uuid
from flask_security import UserMixin, RoleMixin 
from sqlalchemy import UniqueConstraint, and_
from sqlalchemy.orm import foreign

user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer(), db.ForeignKey('user.id'), primary_key=True),
    db.Column('role_id', db.Integer(), db.ForeignKey('role.id'), primary_key=True)
)

class Role(db.Model, RoleMixin):
    """Model for user roles (e.g., Admin, User)."""
    __tablename__ = 'role'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f'<Role {self.name}>'

class SecretQuestion(db.Model):
    """Model to store predefined secret questions for password recovery."""
    __tablename__ = 'secret_question'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255), unique=True, nullable=False)

class User(db.Model, UserMixin):
    """Model for users (Admin and regular Users)."""
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean(), default=True, nullable=False)
    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Relationships
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    secret_question_id = db.Column(db.Integer, db.ForeignKey('secret_question.id'), nullable=False)
    secret_answer_hash = db.Column(db.String(255), nullable=False)
    secret_question = db.relationship('SecretQuestion', backref='users')

    # --- New/Updated Relationships for Parking App ---
    cars = db.relationship('Car', backref='owner', lazy='dynamic', cascade="all, delete-orphan")
    bookings = db.relationship('Booking', backref='user', lazy='dynamic', cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_secret_answer(self, secret_answer):
        """Hashes and stores the secret answer."""
        if secret_answer:
            self.secret_answer_hash = generate_password_hash(secret_answer.lower().strip())

    def check_secret_answer(self, secret_answer):
        """Checks the provided secret answer against the stored hash."""
        if not self.secret_answer_hash:
            return False
        return check_password_hash(self.secret_answer_hash, secret_answer.lower().strip())

    def has_role(self, role_name):
        """Checks if a user has a specific role."""
        return any(role.name == role_name for role in self.roles)

    @property
    def password(self):
        return self.password_hash

    @password.setter
    def password(self, password):
        self.set_password(password)

    def __repr__(self):
        return f'<User {self.username}>'

# --- Car Parking Models ---

class ParkingArea(db.Model):
    __tablename__ = 'parking_area'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    location_description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    price_per_hour = db.Column(db.Float, nullable=False, default=20.0)

    spots = db.relationship(
        'ParkingSpot',
        back_populates='parking_area',
        lazy='dynamic',
        cascade="all, delete-orphan"
    )


class ParkingSpot(db.Model):
    __tablename__ = 'parking_spot'
    id = db.Column(db.Integer, primary_key=True)
    spot_identifier = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='available')
    parking_area_id = db.Column(db.Integer, db.ForeignKey('parking_area.id'), nullable=False)

    parking_area = db.relationship('ParkingArea', back_populates='spots')

    bookings = db.relationship('Booking', back_populates='spot',
                               cascade="all, delete-orphan")
    active_booking = db.relationship(
        'Booking',
        primaryjoin=lambda: and_(
            ParkingSpot.id == foreign(Booking.spot_id),  # disambiguate FK side
            Booking.status == 'active'
        ),
        uselist=False,
        viewonly=True)

    __table_args__ = (UniqueConstraint('spot_identifier', 'parking_area_id', name='_spot_area_uc'),)

    def __repr__(self):
        # now this works because parking_area relationship exists
        return f'<ParkingSpot {self.spot_identifier} in {self.parking_area.name}>'




class Car(db.Model):
    """Model for a user's car."""
    __tablename__ = 'car'
    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20), unique=True, nullable=False)
    make = db.Column(db.String(50), nullable=True)
    model = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(30), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # One-to-Many relationship with Booking
    bookings = db.relationship('Booking', backref='car', lazy='dynamic', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Car {self.license_plate}>'


class Booking(db.Model):
    """Model to record a car being parked in a spot (a parking session)."""
    __tablename__ = 'booking'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    spot_id = db.Column(db.Integer, db.ForeignKey('parking_spot.id'), nullable=False)
    
    start_time = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    total_cost = db.Column(db.Float, nullable=True)

    spot = db.relationship('ParkingSpot', back_populates='bookings')

    @property
    def time_parked(self):
        """Calculates the total time parked for a completed booking."""
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        elif self.start_time:
             # For active bookings, show time elapsed so far
            return datetime.now(timezone.utc) - self.start_time
        return None

    def __repr__(self):
        return f'<Booking Car:{self.car_id} Spot:{self.spot_id} Status:{self.status}>'
