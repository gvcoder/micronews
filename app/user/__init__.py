from flask import Blueprint

user_app = Blueprint('user_app', __name__, template_folder='templates')

from app.user import routes  # noqa: E402, F401
