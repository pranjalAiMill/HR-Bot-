from flask import Flask
from mcp_server.routes.leave import leave_bp

from dotenv import load_dotenv

load_dotenv()  

app = Flask(__name__)
app.register_blueprint(leave_bp, url_prefix="/leave")

if __name__ == "__main__":
    app.run(port=9000)
