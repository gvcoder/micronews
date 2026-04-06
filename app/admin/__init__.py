from flask import Blueprint

admin_app = Blueprint('admin_app', __name__, template_folder='templates')

from app.admin import routes  # noqa: E402, F401
