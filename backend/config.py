import os

class Config:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(base_dir, "users.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False