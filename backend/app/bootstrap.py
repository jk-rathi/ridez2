"""Explicit startup-only admin creation for hosts without an interactive shell."""
import os
from . import repositories as users
from .services import ApiError, normalize, register


def bootstrap_admin():
    fields={key:os.environ.get('BOOTSTRAP_ADMIN_'+key.upper(),'') for key in ('mobile','password')}
    missing=['BOOTSTRAP_ADMIN_'+key.upper() for key,value in fields.items() if not value.strip()]
    if missing:
        raise ApiError('Missing admin bootstrap settings: '+', '.join(missing))
    mobile=normalize(fields['mobile'])
    existing=users.by_mobile(mobile)
    if existing:
        if existing.role!='admin':
            raise ApiError('Bootstrap mobile belongs to a rider or driver. Choose an unused mobile number; accounts are never promoted by bootstrap.')
        if existing.status!='active':
            raise ApiError('Existing admin is not active. Bootstrap does not reactivate accounts.')
        return 'Admin already exists; existing name and password are unchanged.'
    register({'name':os.environ.get('BOOTSTRAP_ADMIN_NAME','Admin'),'mobile':mobile,
              'password':fields['password'],'role':'admin'},allow_admin=True)
    return 'Bootstrap admin created successfully.'
