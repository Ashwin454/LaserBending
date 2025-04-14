import os
import logging
from app import create_app, db  # Adjust import based on your structure

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create the Flask app globally (accessible by Gunicorn)
app = create_app()

# Initialize the database (run once at import time)
with app.app_context():
    db.create_all()  # Create tables if they don't exist
    logger.info("Database tables initialized")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info("Starting server on port %s", port)
    # Use Flask's development server for local testing (Windows)
    app.run(host='0.0.0.0', port=port, debug=False)