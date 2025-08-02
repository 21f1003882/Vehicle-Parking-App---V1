# forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, IntegerField, SelectField, TextAreaField, FloatField
from wtforms.validators import DataRequired, Length, Email, EqualTo, NumberRange, ValidationError

class LoginForm(FlaskForm):
    """Form for users to login."""
    username = StringField('Username or Email', validators=[DataRequired(), Length(min=3, max=120)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class RegisterForm(FlaskForm):
    """Form for new users to register."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters long.')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match.')
    ])
    secret_question_id = SelectField('Secret Question', coerce=int, validators=[DataRequired()])
    secret_answer = StringField('Secret Answer', validators=[DataRequired(), Length(min=2, max=100)])
    submit = SubmitField('Create Account')

class ParkingLotForm(FlaskForm):
    """Form for admins to create or edit a parking area (lot)."""
    prime_location_name = StringField('Area Name', validators=[DataRequired(), Length(max=100)])
    area_code = StringField('Area Code (3 Letters)', validators=[DataRequired(), Length(min=3, max=3, message="Code must be exactly 3 letters.")])
    address = TextAreaField('Location Description', validators=[DataRequired(), Length(max=255)])
    price_per_hour = FloatField('Price per Hour (₹)', validators=[DataRequired(), NumberRange(min=0, message="Price must be a positive number.")])
    max_spots = IntegerField('Number of Spots', validators=[
        DataRequired(),
        NumberRange(min=1, max=1000, message='Must be between 1 and 1000.')
    ])
    submit = SubmitField('Save Area')

    def validate_area_code(self, area_code):
        """Custom validator to ensure area code is all letters."""
        if not area_code.data.isalpha():
            raise ValidationError('Area code must contain only letters.')

class CarForm(FlaskForm):
    """Form for users to add a new car."""
    license_plate = StringField('License Plate', validators=[DataRequired(), Length(min=3, max=20)])
    make = StringField('Make (e.g., Tata)', validators=[DataRequired(), Length(max=50)])
    model = StringField('Model (e.g., Nexon)', validators=[DataRequired(), Length(max=50)])
    color = StringField('Color', validators=[DataRequired(), Length(max=30)])
    submit = SubmitField('Add Car')

class ForgotPasswordRequestForm(FlaskForm):
    """Form for Step 1: User enters their email."""
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    submit = SubmitField('Continue')

class ResetPasswordForm(FlaskForm):
    """Form for Step 2: User verifies details and sets a new password."""
    secret_answer = StringField('Your Secret Answer', validators=[DataRequired()])
    secret_key = StringField('Your Secret Key', validators=[DataRequired()])
    password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters long.')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match.')
    ])
    submit = SubmitField('Reset Password')

class SearchSpotForm(FlaskForm):
    """Form for admin to search for a specific spot."""
    area_id = SelectField('Parking Area', coerce=int, validators=[DataRequired()])
    spot_identifier = StringField('Spot Identifier (e.g., PMC-5)', validators=[DataRequired()])
    submit = SubmitField('Search')

