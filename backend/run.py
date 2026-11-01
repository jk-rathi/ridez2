from app import create_app
from app.realtime import socketio, start_worker
import os

app = create_app()

if __name__ == '__main__':
    start_worker(app)
    # Development server only. One process owns the local socket connections/outbox.
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '5000')), use_reloader=False, allow_unsafe_werkzeug=True)
