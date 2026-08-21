from app.extensions import db


class Admin(db.Model):
    """
    Administrator entity storing secure credentials for system operators.
    """
    __tablename__ = "admins"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<Admin email='{self.email}'>"
