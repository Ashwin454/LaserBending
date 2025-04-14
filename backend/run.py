import os
import logging
from app import create_app, db  # Import db directly from app

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    logger.info("Starting server on port %s", port)
    with app.app_context():
        db.create_all()  # Create tables
    app.run(host='0.0.0.0', port=port, debug=False)