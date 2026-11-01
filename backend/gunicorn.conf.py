import os

bind = '0.0.0.0:' + os.getenv('PORT', '10000')
# The current matching loop and socket dispatcher require exactly one process.
workers = 1
worker_class = 'gthread'
threads = 100
preload_app = False
timeout = 60
graceful_timeout = 30
keepalive = 5
# Do not log URLs/query strings (Socket.IO session IDs), tokens or request bodies.
accesslog = None
errorlog = '-'
capture_output = True


def post_worker_init(worker):
    from app.realtime import start_worker
    start_worker(worker.wsgi)
