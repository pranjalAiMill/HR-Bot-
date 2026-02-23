from flask import Flask
from mcp_server.routes.leave import leave_bp
from mcp_server.routes.timesheet import timesheet_bp

from utils.db_loader import build_db
from dotenv import load_dotenv

load_dotenv()

build_db()

app = Flask(__name__)
app.register_blueprint(leave_bp, url_prefix="/leave")
app.register_blueprint(timesheet_bp,  url_prefix="/timesheet")

if __name__ == "__main__":
    app.run(port=9000)