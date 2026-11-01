"""Make a consistent SQLite backup without stopping the application."""
import argparse
import os
from pathlib import Path
import sqlite3
from sqlalchemy.engine import make_url

parser=argparse.ArgumentParser()
parser.add_argument('destination',help='New backup file, e.g. /var/data/backups/ridez-backup.db')
args=parser.parse_args()
url=make_url(os.environ.get('DATABASE_URL',''))
if url.get_backend_name()!='sqlite' or not url.database or url.database==':memory:':
    raise SystemExit('This backup command requires a file-backed SQLite database')
source=Path(url.database).resolve()
destination=Path(args.destination).resolve()
if not source.is_file() or destination==source or destination.exists():
    raise SystemExit('Source must exist and destination must be a new file')
destination.parent.mkdir(parents=True,exist_ok=True)
# Exclusive creation prevents overwriting an existing backup.
fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as original:
    with sqlite3.connect(destination) as backup:
        original.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise SystemExit('Backup integrity check failed')
print('Backup created and integrity checked')
