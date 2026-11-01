"""Serve the Vite build from the same origin as HTTP and Socket.IO APIs."""
from pathlib import Path
from flask import jsonify, send_from_directory, request
from werkzeug.exceptions import NotFound


def register_frontend(app):
    def frontend(path='index.html'):
        root = Path(app.config['FRONTEND_DIST'])
        if not root.is_dir():
            return jsonify(error='Frontend build is not installed'), 404
        if path.split('/')[0] in ('api', 'socket.io') or any(part.startswith('.') for part in path.split('/')):
            return jsonify(error='Resource not found'), 404
        try:
            response = send_from_directory(root, path)
        except NotFound:
            if path in ('login', 'register') or path.split('/')[0] in ('rider', 'driver', 'admin', 'test-payment'):
                response = send_from_directory(root, 'index.html')
            else:
                return jsonify(error='Resource not found'), 404
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if path.startswith('assets/') else 'no-cache'
        return response

    app.add_url_rule('/', 'frontend_index', frontend, methods=['GET'])
    app.add_url_rule('/<path:path>', 'frontend_page', frontend, methods=['GET'])

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer' if request.path.startswith('/test-payment/') else 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(self)'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response
