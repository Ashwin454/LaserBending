import os

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///site.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'dsihshfiushfiuhsiufhnsiufhiufsf')
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 465
    MAIL_USERNAME = 'ashwin.aj4545@gmail.com'
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', 'gclf vkuv odgx jlzj')
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True