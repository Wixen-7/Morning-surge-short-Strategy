import os
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

API_KEY = os.getenv('KITE_API_KEY')
ACCESS_TOKEN = os.getenv('KITE_ACCESS_TOKEN')
print('KITE_API_KEY set:', bool(API_KEY))
print('KITE_ACCESS_TOKEN set:', bool(ACCESS_TOKEN))
if not API_KEY or not ACCESS_TOKEN:
    print('Credentials missing; aborting.')
else:
    try:
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(ACCESS_TOKEN)
        instruments = kite.instruments('NSE')
        print('Connected OK; instruments fetched:', len(instruments))
    except TokenException as e:
        print('TokenException:', e)
    except Exception as e:
        print(type(e).__name__ + ':', e)
