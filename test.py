# attempt to display local currency based on user location

import re
import json
from urllib import request

from forex_python.converter import CurrencyRates
c = CurrencyRates()

# fetch country code - alpha2
url = 'http://ipinfo.io/json'
response = request.urlopen(url)
data = json.load(response)
country=data['country']

# search for currency



print(c.convert('USD', 'AOA', 10))



print(country)