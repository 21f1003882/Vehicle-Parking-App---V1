# auth.py

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, current_user, login_required
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from flask import current_app
from core.models import User, Role, SecretQuestion
from core.extensions import db
from forms import LoginForm, RegisterForm, ForgotPasswordRequestForm, ResetPasswordForm

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=['GET', 'POST'])
def login_page():
    """Serves the login page and handles form submission."""
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard") if current_user.has_role('admin') else url_for("user_dashboard"))
    
    # Check for a secret key passed from registration
    secret_key_to_show = request.args.get('secret_key')
    
    form = LoginForm()
    if form.validate_on_submit():
        # This block now runs on a valid POST request
        user = User.query.filter(
            (User.username == form.username.data) | (db.func.lower(User.email) == form.username.data.lower())
        ).first()

        if user and user.check_password(form.password.data) and user.active:
            login_user(user, remember=True)
            flash('Login successful. Welcome back!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin_dashboard' if user.has_role('admin') else 'user_dashboard'))
        else:
            flash('Invalid username, email, or password.', 'danger')

    return render_template("login.html", form=form, secret_key_to_show=secret_key_to_show)

@auth_bp.route("/register", methods=['GET', 'POST'])
def register_page():
    """Handles new user creation and redirects to login with the secret key."""
    if current_user.is_authenticated:
        return redirect(url_for("user_dashboard"))
    
    form = RegisterForm()
    form.secret_question_id.choices = [(q.id, q.text) for q in SecretQuestion.query.order_by('text').all()]

    if form.validate_on_submit():
        # This block now runs on a valid POST request
        existing_user = User.query.filter(
            (User.username == form.username.data) | (User.email == form.email.data)
        ).first()

        if existing_user:
            flash('A user with that username or email already exists.', 'warning')
        else:
            user_role = Role.query.filter_by(name='user').one()
            new_user = User(
                username=form.username.data,
                email=form.email.data,
                secret_question_id=form.secret_question_id.data,
                active=True
            )
            new_user.set_password(form.password.data)
            new_user.set_secret_answer(form.secret_answer.data)
            new_user.roles.append(user_role)
            
            db.session.add(new_user)
            db.session.commit()
            
            # --- LOGIC FOR PARTIAL SECRET KEY ---
            # Generate the partial key to show the user
            full_key = new_user.fs_uniquifier
            try:
                # This will extract the middle parts of the UUID
                partial_key = '-'.join(full_key.split('-')[1:-1])
            except IndexError:
                # Fallback for any unexpected format
                partial_key = full_key

            flash('Registration successful! Please save your secret key and log in.', 'success')
            return redirect(url_for('auth.login_page', secret_key=partial_key))

    return render_template("register.html", form=form)
@auth_bp.route("/logout")
@login_required
def logout():
    """Handles user logout for the web session."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/forgot-password", methods=['GET', 'POST'])
def forgot_password_request():
    """Step 1: User submits their email address."""
    form = ForgotPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        # To prevent email enumeration, we show a generic message.
        # But if the user exists, we store their email in the session for the next step.
        if user:
            session['password_reset_email'] = user.email
        
        flash('If an account with that email exists, you may proceed to the next step.', 'info')
        # Redirect to the verification step.
        return redirect(url_for('auth.reset_password_verify'))
        
    return render_template('forgot_password_request.html', form=form)

@auth_bp.route("/reset-password/verify", methods=['GET', 'POST'])
def reset_password_verify():
    """Step 2: User verifies their identity and resets the password."""
    # Get the email from the session. If it's not there, redirect back to step 1.
    email = session.get('password_reset_email')
    if not email:
        flash('Please start the password reset process from the beginning.', 'warning')
        return redirect(url_for('auth.forgot_password_request'))

    user = User.query.filter_by(email=email).first()
    if not user:
        # This case should rarely happen, but it's a good safeguard.
        flash('User not found. Please try again.', 'danger')
        return redirect(url_for('auth.forgot_password_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Check 1: Secret Answer
        is_answer_correct = user.check_secret_answer(form.secret_answer.data)
        # Check 2: Secret Key
    
        is_key_correct = False
        try:
            # Generate the expected partial key from the user's full key
            expected_partial_key = '-'.join(user.fs_uniquifier.split('-')[1:-1])
            # Compare it to the key the user submitted in the form
            is_key_correct = (expected_partial_key == form.secret_key.data)
        except IndexError:
            # Fallback for safety, though it should not happen with UUIDs
            is_key_correct = (user.fs_uniquifier == form.secret_key.data)
     

        if is_answer_correct and is_key_correct:
            user.set_password(form.password.data)
            db.session.commit()
            
            session.pop('password_reset_email', None)
            
            flash('Your password has been reset successfully! You can now log in.', 'success')
            return redirect(url_for('auth.login_page'))
        else:
            flash('The secret answer or secret key is incorrect. Please try again.', 'danger')

    return render_template('reset_password_verify.html', form=form, user=user)