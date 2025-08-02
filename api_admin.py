from flask import Blueprint, request, jsonify
from flask_restful import Api, Resource, reqparse
from flask_jwt_extended import jwt_required, get_jwt
from core.extensions import db
from core.models import User, Car, ParkingArea, ParkingSpot, Booking, SecretQuestion, Role
from datetime import datetime

# This blueprint is for admin-only API operations, protected by JWT
api_admin_bp = Blueprint('api_admin', __name__, url_prefix='/api/admin')
api = Api(api_admin_bp)

# This function runs before any request to this blueprint.
# It ensures the user has a valid JWT and has the 'admin' role.
@api_admin_bp.before_request
@jwt_required()
def before_request_func():
    claims = get_jwt()
    if "admin" not in claims.get("roles", []):
        # Using abort is a clean way to stop the request
        return jsonify({"message": "Administration rights required"}), 403

# --- Resource for Secret Questions ---
class SecretQuestionListAPI(Resource):
    def post(self):
        data = request.get_json()
        if not data or 'text' not in data:
            return {'message': 'Text for secret question is required'}, 400
        
        if SecretQuestion.query.filter_by(text=data['text']).first():
            return {'message': f"Secret question '{data['text']}' already exists"}, 409
            
        new_q = SecretQuestion(text=data['text'])
        db.session.add(new_q)
        db.session.commit()
        return {'id': new_q.id, 'text': new_q.text}, 201

# --- Resource for Users ---
class UserListAPI(Resource):
    def get(self):
        users = User.query.all()
        return jsonify({'users': [{'id': u.id, 'username': u.username, 'email': u.email} for u in users]})

    def post(self):
        data = request.get_json()
        required_fields = ['username', 'email', 'password', 'secret_question_id', 'secret_answer']
        if not all(field in data for field in required_fields):
            return {"message": "Missing required fields"}, 400
        
        if User.query.filter((User.username == data['username']) | (User.email == data['email'])).first():
            return {"message": "Username or email already exists"}, 409

        user_role = Role.query.filter_by(name='user').first()
        if not user_role:
             return {"message": "System error: 'user' role not found."}, 500

        new_user = User(
            username=data['username'], email=data['email'], 
            active=True, secret_question_id=data['secret_question_id']
        )
        new_user.set_password(data['password'])
        new_user.set_secret_answer(data['secret_answer'])
        new_user.roles.append(user_role)
        db.session.add(new_user)
        db.session.commit()
        return {'message': 'User created successfully', 'user_id': new_user.id}, 201

# In api_admin.py, find the ParkingAreaListAPI class

class ParkingAreaListAPI(Resource):
    def get(self):
        # Also return the area_code for any potential use
        areas = ParkingArea.query.all()
        return jsonify({'areas': [{'id': a.id, 'name': a.name, 'code': a.spots.first().spot_identifier.split('-')[0] if a.spots.first() else ''} for a in areas]})

    def post(self):
        data = request.get_json()
        # Add 'area_code' to the list of required fields
        required_fields = ['name', 'location_description', 'price_per_hour', 'num_spots', 'area_code']
        if not all(field in data for field in required_fields):
            return {"message": "Missing required fields (name, location_description, price_per_hour, num_spots, area_code)"}, 400

        area_code = data['area_code'].upper() # Standardize to uppercase

        if ParkingArea.query.filter_by(name=data['name']).first():
            return {'message': f"Parking area with name '{data['name']}' already exists."}, 409
        
        # Check if code is already in use by checking the first spot of other areas
        existing_spot = ParkingSpot.query.filter(ParkingSpot.spot_identifier.startswith(f"{area_code}-")).first()
        if existing_spot:
            return {'message': f"Area code '{area_code}' is already in use."}, 409

        new_area = ParkingArea(
            name=data['name'], location_description=data['location_description'], 
            price_per_hour=float(data['price_per_hour'])
        )
        db.session.add(new_area)
        db.session.flush()

        num_spots = int(data['num_spots'])
        for i in range(1, num_spots + 1):
            # Use the new identifier format
            spot_identifier = f"{area_code}-{i}"
            spot = ParkingSpot(spot_identifier=spot_identifier, parking_area_id=new_area.id, status='available')
            db.session.add(spot)
        
        db.session.commit()
        return {'message': f"Parking area '{new_area.name}' with {num_spots} spots created."}, 201
# --- Resource for Cars ---
class CarListAPI(Resource):
    def get(self):
        cars = Car.query.all()
        return jsonify({'cars': [{'id': c.id, 'license_plate': c.license_plate, 'user_id': c.user_id} for c in cars]})

    def post(self):
        data = request.get_json()
        required_fields = ['license_plate', 'make', 'model', 'color', 'user_id']
        if not all(field in data for field in required_fields):
            return {"message": "Missing required fields"}, 400

        if Car.query.filter_by(license_plate=data['license_plate']).first():
            return {'message': f"Car with license plate '{data['license_plate']}' already exists."}, 409
        
        if not User.query.get(data['user_id']):
            return {'message': f"User with id {data['user_id']} not found."}, 404

        new_car = Car(
            license_plate=data['license_plate'], make=data['make'],
            model=data['model'], color=data['color'], user_id=data['user_id']
        )
        db.session.add(new_car)
        db.session.commit()
        return {'message': 'Car created successfully', 'car_id': new_car.id}, 201

# --- Resource for Bookings ---
class BookingListAPI(Resource):
    def post(self):
        data = request.get_json()
        required_fields = ['user_id', 'car_id', 'spot_id', 'start_time', 'status']
        if not all(field in data for field in required_fields):
            return {"message": "Missing fields"}, 400

        try:
            start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00')) if data.get('end_time') else None
        except ValueError:
            return {'message': 'Invalid datetime format. Use ISO 8601.'}, 400

        new_booking = Booking(
            user_id=data['user_id'], car_id=data['car_id'], spot_id=data['spot_id'],
            start_time=start_time, end_time=end_time, status=data['status'],
            total_cost=float(data['total_cost']) if data.get('total_cost') else None
        )
        
        spot = ParkingSpot.query.get(data['spot_id'])
        if spot and new_booking.status == 'active':
            spot.status = 'occupied'
            
        db.session.add(new_booking)
        db.session.commit()
        return {'message': 'Booking created', 'booking_id': new_booking.id}, 201

# --- Resource for getting spots for an area ---
class ParkingSpotListAPI(Resource):
    def get(self, area_id):
        area = ParkingArea.query.get_or_404(area_id)
        spots = area.spots.all()
        return jsonify({'spots': [{'id': s.id, 'spot_identifier': s.spot_identifier} for s in spots]})



# Register all API resources to the blueprint
api.add_resource(SecretQuestionListAPI, '/secret-questions')
api.add_resource(UserListAPI, '/users')
api.add_resource(ParkingAreaListAPI, '/parking-areas')
api.add_resource(CarListAPI, '/cars')
api.add_resource(BookingListAPI, '/bookings')
api.add_resource(ParkingSpotListAPI, '/parking-areas/<int:area_id>/spots')