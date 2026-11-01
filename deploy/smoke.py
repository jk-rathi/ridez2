"""Exercise the actual image, including migrations, cookies and restart persistence."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.request
import urllib.error


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',default='ridez-render:test')
    parser.add_argument('--port',type=int,default=10081)
    args=parser.parse_args()
    suffix=secrets.token_hex(5)
    name=f'ridez-smoke-{suffix}'
    volume=name+'-data'
    base=f'http://127.0.0.1:{args.port}'
    def docker(*parts,**kwargs):
        return subprocess.run(['docker',*parts],check=True,**kwargs)
    def request(path,body=None,headers=None):
        req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json',**(headers or {})})
        with urllib.request.urlopen(req,timeout=5) as response:
            return response.status,response.read(),response.headers
    def ready():
        for _ in range(60):
            try:
                status,data,_=request('/api/v1/ready')
                if status==200 and json.loads(data)['matching_worker']:return
            except (OSError,urllib.error.HTTPError):pass
            time.sleep(1)
        raise RuntimeError('Container readiness did not succeed')
    with tempfile.TemporaryDirectory() as temp:
        admin_password=secrets.token_urlsafe(24)
        env=Path(temp)/'test.env'
        env.write_text('APP_ENV=production\nDATABASE_URL=sqlite:////var/data/ridez.db\n'
            f'JWT_SECRET={secrets.token_hex(32)}\nUSER_CODE_SECRET={secrets.token_hex(32)}\n'
            'ROUTE_PROVIDER=simulator\nSIMULATOR_ENABLED=1\nTRUST_PROXY_HEADERS=1\n'
            f'BOOTSTRAP_ADMIN=1\nBOOTSTRAP_ADMIN_MOBILE=+12025550125\nBOOTSTRAP_ADMIN_PASSWORD={admin_password}\n')
        env.chmod(0o600)
        try:
            docker('run','-d','--name',name,'--env-file',str(env),'-v',volume+':/var/data',
                '-p',f'127.0.0.1:{args.port}:10000',args.image,stdout=subprocess.DEVNULL)
            ready()
            _,admin,_=request('/api/v1/auth/login',{'mobile':'+12025550125','password':admin_password})
            admin=json.loads(admin)
            assert admin['user']['role']=='admin'
            docker('exec','--user','10001:10001',name,'python','-c',
                "from pathlib import Path; names=[item.split(b'=',1)[0] for item in Path('/proc/1/environ').read_bytes().split(bytes([0]))]; assert not any(key.startswith(b'BOOTSTRAP_ADMIN') for key in names)")
            for path in ('/','/rider/history','/driver/account','/admin/drivers','/test-payment/deployment-check'):
                status,html,_=request(path)
                assert status==200 and b'<div id="root">' in html
            user={'name':'Deployment smoke','mobile':'+919876543210','password':secrets.token_urlsafe(24)}
            _,created,_=request('/api/v1/auth/register',user)
            _,login,headers=request('/api/v1/auth/login',user)
            login=json.loads(login)
            cookie=headers['Set-Cookie'].split(';')[0]
            assert 'HttpOnly' in headers['Set-Cookie'] and 'Secure' in headers['Set-Cookie']
            authorization={'Authorization':'Bearer '+login['access_token']}
            _,quote,_=request('/api/v1/fares/quotes',{'pickup':'Smoke pickup','destination':'Smoke destination','pickup_lat':19.076,'pickup_lng':72.8777},authorization)
            _,booked,_=request('/api/v1/rides',{'quote_id':json.loads(quote)['quote']['id']},authorization)
            ride_id=json.loads(booked)['ride']['id']
            _,cancelled,_=request('/api/v1/rides/'+ride_id+'/cancel',{'reason':'Deployment cancellation check'},authorization)
            assert json.loads(cancelled)['ride']['cancellation']['reason']=='Deployment cancellation check'
            _,data,_=request('/api/v1/workspace',headers=authorization)
            otp=json.loads(data)['trip_otp']
            docker('restart',name,stdout=subprocess.DEVNULL)
            ready()
            _,admin_again,_=request('/api/v1/auth/login',{'mobile':'+12025550125','password':admin_password})
            assert json.loads(admin_again)['user']['id']==admin['user']['id']
            _,data,_=request('/api/v1/workspace',headers=authorization)
            assert json.loads(data)['trip_otp']==otp
            assert json.loads(data)['active_ride'] is None
            assert json.loads(data)['rides'][0]['cancellation']['reason']=='Deployment cancellation check'
            _,renewed,headers=request('/api/v1/auth/refresh',{}, {'Cookie':cookie,'X-Session-Request':'1'})
            renewed=json.loads(renewed)
            assert renewed['user']['id']==json.loads(created)['user']['id']
            cookie=headers['Set-Cookie'].split(';')[0]
            request('/api/v1/auth/logout',{}, {'Cookie':cookie,'X-Session-Request':'1'})
            try:
                request('/api/v1/me',headers={'Authorization':'Bearer '+renewed['access_token']})
                raise AssertionError('Logged-out token was accepted')
            except urllib.error.HTTPError as error:
                assert error.code==401
            print('PASS: production image, startup admin, migrations, frontend, readiness, secure cookies, restart persistence, cancellation and logout')
        finally:
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            subprocess.run(['docker','volume','rm',volume],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
