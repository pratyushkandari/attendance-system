from app.extensions import db


class Admin(db.Model):
    """
    Administrator entity storing secure credentials for system operators.

    Attributes:
        id: Primary key surrogate integer.
        email: Unique login email identity.
        password: Salted scrypt hash from Werkzeug's ``generate_password_hash``.
    """
    __tablename__ = "admins"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)

    def __repr__(self) -> str:
        return f"<Admin email='{self.email}'>"

