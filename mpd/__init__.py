import os
from flask import Flask
from authlib.integrations.flask_client import OAuth


oauth = OAuth()


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='sdfsdfsdf',
        DATABASE=os.path.join(app.instance_path, 'mpd.sqlite'),
        OAUTH_ID='',
        OAUTH_SECRET='',
    )
    app.config.from_pyfile('config.py', silent=True)
    os.makedirs(app.instance_path, exist_ok=True)

    from . import db
    db.init_app(app)
    from . import party
    app.register_blueprint(party.papp)

    oauth.register(
        'openstreetmap',
        api_base_url='https://api.openstreetmap.org/api/0.6/',
        access_token_url='https://www.openstreetmap.org/oauth2/token',
        authorize_url='https://www.openstreetmap.org/oauth2/authorize',
        client_id=app.config['OAUTH_ID'],
        client_secret=app.config['OAUTH_SECRET'],
        client_kwargs={'scope': 'read_prefs'},
    )
    oauth.init_app(app)

    return app
