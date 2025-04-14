import numpy as np
import joblib
from sklearn.base import BaseEstimator

class DummyModel(BaseEstimator):
    def __init__(self):
        pass

    def fit(self, X, y=None):
        # No training needed, return the model itself
        return self

    def predict(self, X):
        # For each input angle, generate 4 random parameters
        # Scan speed (m/s), Laser power (W), Temperature (°C), No. of scans (integer)
        
        # Here we generate random values for each parameter with realistic ranges
        scan_speed = np.random.uniform(1500, 3000, len(X))  # Scan speed between 0.5 to 5 m/s
        laser_power = np.random.uniform(100, 600, len(X))  # Laser power between 10 to 100 W
        temperature = np.random.uniform(20, 30, len(X))  # Temperature between 20°C to 100°C
        no_of_scans = np.random.randint(1, 16, len(X))  # Number of scans between 5 to 50

        # Return all four parameters as an array of arrays
        return np.vstack([scan_speed, laser_power, temperature, no_of_scans]).T

# Instantiate and use the dummy model
dummy_model = DummyModel()

# Save the dummy model as a pickle file
print("Starting model save process...")
joblib.dump(dummy_model, 'dummy_model.pkl')
print("Dummy model saved as dummy_model.pkl")
