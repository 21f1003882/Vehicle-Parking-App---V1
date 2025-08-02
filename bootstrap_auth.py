from core.extensions import db
from core.models import User, Role, SecretQuestion

def bootstrap_auth(admin_username="admin", admin_email="admin@example.com", admin_password="admin123"):
    # roles
    role_admin = Role.query.filter_by(name="admin").first() or Role(name="admin", description="Administrator")
    role_user  = Role.query.filter_by(name="user").first()  or Role(name="user", description="Regular user")
    db.session.add(role_admin); db.session.add(role_user)

    # secret questions (seed if empty)
    if SecretQuestion.query.count() == 0:
        for t in [
            "What was your first pet's name?",
            "What is your mother's maiden name?",
            "What was the make of your first car?",
            "What is your favorite book?",
            "In what city were you born?",
            "What is the name of your first school?",
            "What is your favorite movie?",
        ]:
            db.session.add(SecretQuestion(text=t))
    db.session.flush()
    sq = SecretQuestion.query.first()

    # admin
    admin = User.query.filter((User.username==admin_username)|(User.email==admin_email)).first()
    if not admin and sq:
        admin = User(username=admin_username, email=admin_email, active=True, secret_question_id=sq.id)
        admin.set_password(admin_password)
        admin.set_secret_answer("admin")
        admin.roles.append(role_admin)
        db.session.add(admin)

    # OFFLINE user (regular user)
    offline = User.query.filter_by(username='offline_user').first()
    if not offline and sq:
        offline = User(username='offline_user', email='offline@example.com', active=True, secret_question_id=sq.id)
        offline.set_password('offline')          # not intended for login; just to satisfy schema
        offline.set_secret_answer('offline')
        offline.roles.append(role_user)
        db.session.add(offline)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error during bootstrap: {e}")