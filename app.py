from flask import Flask
from config import Config
from models import db
from flask_migrate import Migrate


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate = Migrate(app, db)  # Инициализация миграций

    with app.app_context():
        db.create_all()

    # blueprints

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5005)