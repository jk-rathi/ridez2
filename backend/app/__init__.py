import os
import secrets
from pathlib import Path
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv

db = SQLAlchemy()


def create_app(config=None):
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    app = Flask(__name__)
    development = os.getenv('APP_ENV', 'development') == 'development'
    jwt_secret = os.getenv('JWT_SECRET')
    code_secret = os.getenv('USER_CODE_SECRET')
    if development and (not jwt_secret or not code_secret):
        # Persist local secrets so restarts preserve sessions and account-code derivation.
        directory = Path(app.instance_path)
        directory.mkdir(parents=True, exist_ok=True)
        for name in ('jwt', 'codes'):
            path = directory / f'{name}.key'
            try:
                with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as out:
                    out.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        jwt_secret = jwt_secret or (directory / 'jwt.key').read_text()
        code_secret = code_secret or (directory / 'codes.key').read_text()
    app.config.update(SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///ridez.db') if development else os.getenv('DATABASE_URL'), JWT_SECRET=jwt_secret, USER_CODE_SECRET=code_secret, SQLALCHEMY_TRACK_MODIFICATIONS=False)
    if config:
        app.config.update(config)
    app.config.setdefault('TEST_PAYMENTS_ENABLED', os.getenv('TEST_PAYMENTS_ENABLED', '1' if development else '0') == '1')
    app.config.setdefault('SIMULATOR_ENABLED', os.getenv('SIMULATOR_ENABLED', '1' if development else '0') == '1')
    app.config.setdefault('ROUTE_PROVIDER', os.getenv('ROUTE_PROVIDER', 'simulator' if development else 'google'))
    app.config.setdefault('GOOGLE_MAPS_SERVER_KEY', os.getenv('GOOGLE_MAPS_SERVER_KEY', ''))
    if app.config['ROUTE_PROVIDER'] not in ('google', 'simulator'):
        raise RuntimeError('ROUTE_PROVIDER must be google or simulator')
    app.config.setdefault('AUTH_COOKIE_SECURE', not development)
    app.config.setdefault('AUTH_TRUSTED_ORIGINS', [value.strip().rstrip('/') for value in os.getenv('AUTH_TRUSTED_ORIGINS', '').split(',') if value.strip()])
    app.config.setdefault('REFRESH_SESSION_DAYS', 30)
    app.config.setdefault('LOCATION_STALE_SECONDS', 90)
    app.config.setdefault('MATCH_ROUND_SECONDS', 30)
    app.config.setdefault('MATCH_MAX_RADIUS_M', int(os.getenv('MATCH_MAX_RADIUS_M', '5000')))
    if app.config['MATCH_MAX_RADIUS_M'] not in range(500, 10001, 500):
        raise RuntimeError('MATCH_MAX_RADIUS_M must be a multiple of 500 between 500 and 10000')
    required = {'DATABASE_URL':'SQLALCHEMY_DATABASE_URI', 'JWT_SECRET':'JWT_SECRET', 'USER_CODE_SECRET':'USER_CODE_SECRET'}
    missing = [name for name, key in required.items()
               if not app.config.get(key) or (isinstance(app.config[key], str) and not app.config[key].strip())]
    if missing:
        raise RuntimeError('Missing required environment variables: ' + ', '.join(missing)
                           + '. Set these in Render service > Environment (or your runtime environment), then redeploy.')
    if not development:
        for key in ('JWT_SECRET', 'USER_CODE_SECRET'):
            if len(app.config[key]) < 32:
                raise RuntimeError(f'{key} must contain at least 32 characters outside development')
        if app.config['JWT_SECRET'] == app.config['USER_CODE_SECRET']:
            raise RuntimeError('JWT_SECRET and USER_CODE_SECRET must be distinct')
        if app.config['ROUTE_PROVIDER'] == 'google' and not app.config['GOOGLE_MAPS_SERVER_KEY']:
            raise RuntimeError('GOOGLE_MAPS_SERVER_KEY is required for Google routing outside development')
    app.config.setdefault('TRUST_PROXY_HEADERS', os.getenv('TRUST_PROXY_HEADERS', '0') == '1')
    app.config.setdefault('FRONTEND_DIST', str(Path(__file__).resolve().parents[1] / 'frontend_dist'))
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, **app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})}
    if app.config['TRUST_PROXY_HEADERS']:
        from werkzeug.middleware.proxy_fix import ProxyFix
        # Enable only behind Render's trusted, TLS-terminating proxy.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    db.init_app(app)
    Migrate(app, db)
    from .routes import api
    from . import ride_routes, test_payment_routes
    app.register_blueprint(api, url_prefix='/api/v1')
    from .realtime import init_realtime
    init_realtime(app)

    from .web import register_frontend
    register_frontend(app)

    @app.errorhandler(404)
    def missing(_):
        return jsonify(error='Resource not found'), 404

    @app.errorhandler(405)
    def method(_):
        return jsonify(error='Method not allowed'), 405

    @app.cli.command('init-db')
    def init_db():
        """Create local development tables. Production uses versioned migrations."""
        if not development:
            raise RuntimeError('Use flask db upgrade outside development')
        db.create_all()

    import click
    @app.cli.command('check-routing')
    @click.option('--probe',is_flag=True,help='Make one potentially billable request using the exact application route provider.')
    def check_routing(probe):
        """Show safe local configuration diagnostics without displaying a key."""
        from dotenv import dotenv_values
        from .route_provider import compute
        from .services import ApiError
        env_path=Path(__file__).resolve().parents[1] / '.env'
        file_key=dotenv_values(env_path).get('GOOGLE_MAPS_SERVER_KEY') if env_path.exists() else None
        active_key=app.config['GOOGLE_MAPS_SERVER_KEY']
        click.echo(f'Backend folder: {env_path.parent}')
        click.echo(f'Route provider: {app.config["ROUTE_PROVIDER"]}')
        click.echo(f'Server key configured: {bool(active_key)}')
        click.echo(f'Server key matches backend/.env: {bool(active_key and file_key and active_key==file_key)}')
        if not probe:
            click.echo('No Google request made. Add --probe to test the exact application request.')
            return
        try:
            route=compute((19.076,72.8777),(19.086,72.8877),('Diagnostic pickup','Diagnostic destination'))
        except ApiError as error:
            raise click.ClickException(f'Application route probe failed ({error.status}): {error.message}')
        click.echo(f'Application route probe succeeded: provider={route["provider"]}, distance_m={route["distance_m"]}, duration_seconds={route["duration_seconds"]}')

    @app.cli.command('create-admin')
    @click.option('--mobile', prompt=True)
    @click.option('--name', prompt=True)
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(mobile, name, password):
        from .services import register
        register({'mobile': mobile, 'name': name, 'password': password, 'role': 'admin'}, allow_admin=True)
        click.echo('Admin created')

    @app.cli.command('bootstrap-admin')
    def bootstrap_admin_command():
        """Create an admin from runtime settings without exposing a registration API."""
        from .bootstrap import bootstrap_admin
        from .services import ApiError
        try:
            click.echo(bootstrap_admin())
        except ApiError as error:
            raise click.ClickException(error.message)

    return app
