# api_auth.py
import re
from flask import Blueprint, request, jsonify
from flask_restful import Api, Resource, reqparse
from flask_jwt_extended import create_access_token

from core.extensions import db, csrf
from core.models import User, Role, SecretQuestion

# This blueprint handles all JSON API requests
api_auth_bp = Blueprint('api_auth', __name__, url_prefix='/api/auth')
api = Api(api_auth_bp)

def is_password_strong(password):
    """Helper function to validate password strength."""
    if len(password) < 6: return False
    if not re.search(r"[A-Z]", password): return False
    if not re.search(r"[0-9]", password): return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password): return False
    return True

class LoginAPI(Resource):
    """API endpoint for user login."""
    method_decorators = [csrf.exempt]
    def post(self):
        data = request.get_json()
        username_or_email = data.get('username')
        password = data.get('password')
        user = User.query.filter((User.username == username_or_email) | (User.email == username_or_email)).first()
        
        if user and user.check_password(password) and user.active:
            additional_claims = {"roles": [role.name for role in user.roles], "username": user.username}
            access_token = create_access_token(identity=user.fs_uniquifier, additional_claims=additional_claims)
            return {'access_token': access_token}, 200
        return {"message": "Invalid credentials or inactive account."}, 401

class SecretQuestionsAPI(Resource):
    """API endpoint to fetch all secret questions."""
    method_decorators = [csrf.exempt]
    def get(self):
        questions = SecretQuestion.query.all()
        return jsonify([{'id': q.id, 'text': q.text} for q in questions])

class RegisterAPI(Resource):
    """API endpoint for new user registration."""
    method_decorators = [csrf.exempt]
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('username', type=str, required=True, help="Username is required")
        parser.add_argument('email', type=str, required=True, help="Email is required")
        parser.add_argument('password', type=str, required=True, help="Password is required")
        parser.add_argument('secret_question_id', type=int, required=True, help="Secret question is required")
        parser.add_argument('secret_answer', type=str, required=True, help="Secret answer is required")
        data = parser.parse_args()

        if User.query.filter((User.username == data['username']) | (User.email == data['email'])).first():
            return {"message": "Username or email already exists"}, 409
        if not is_password_strong(data['password']):
            return {"message": "Password is not strong enough. It needs an uppercase letter, a number, and a special character."}, 400
        if not SecretQuestion.query.get(data['secret_question_id']):
            return {"message": "Invalid secret question selected"}, 400

        user_role = Role.query.filter_by(name='user').first()
        if not user_role:
             return {"message": "System error: 'user' role not found."}, 500

        new_user = User(
            username=data['username'], 
            email=data['email'], 
            active=True, 
            secret_question_id=data['secret_question_id']
        )
        new_user.set_password(data['password'])
        new_user.set_secret_answer(data['secret_answer'])
        new_user.roles.append(user_role)
        db.session.add(new_user)
        db.session.commit()

        secret_key = new_user.fs_uniquifier
        additional_claims = {"roles": ["user"], "username": new_user.username}
        access_token = create_access_token(identity=secret_key, additional_claims=additional_claims)
        
        return {'message': 'Registration successful!', 'secret_key': secret_key, 'access_token': access_token}, 201
    
class ForgotPasswordGetQuestionAPI(Resource):
    """API endpoint for step 1 of password reset."""
    method_decorators = [csrf.exempt]
    def post(self):
        data = request.get_json()
        email = data.get('email')
        user = User.query.filter_by(email=email).first()

        if user and user.secret_question:
            return { 'username': user.username, 'secret_question': user.secret_question.text }, 200
        
        # To prevent user enumeration, we don't return a 404.
        return {'message': 'Details processed.'}, 200

class ForgotPasswordResetAPI(Resource):
    """API endpoint for step 2 of password reset."""
    method_decorators = [csrf.exempt]
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('email', type=str, required=True)
        parser.add_argument('secret_answer', type=str, required=True)
        parser.add_argument('secret_key', type=str, required=True) # This will be the partial key from the user
        parser.add_argument('new_password', type=str, required=True)
        data = parser.parse_args()

        user = User.query.filter_by(email=data['email']).first()
        if not user:
            return {'message': 'Invalid details provided.'}, 400

        try:
            expected_partial_key = '-'.join(user.fs_uniquifier.split('-')[1:-1])
        except IndexError:
            # Fallback if the fs_uniquifier is not a valid UUID format
            return {'message': 'Invalid user key format.'}, 500

        if not user.check_secret_answer(data['secret_answer']) or expected_partial_key != data['secret_key']:
            return {'message': 'Invalid details provided.'}, 400

        if not is_password_strong(data['new_password']):
            return {"message": "Your new password is not strong enough."}, 400

        user.set_password(data['new_password'])
        db.session.commit()
        
        return {'message': 'Password has been reset successfully.'}, 200


api.add_resource(LoginAPI, '/login')
api.add_resource(SecretQuestionsAPI, '/secret-questions')
api.add_resource(RegisterAPI, '/register')
api.add_resource(ForgotPasswordGetQuestionAPI, '/forgot-password/get-question')
api.add_resource(ForgotPasswordResetAPI, '/forgot-password/reset')
