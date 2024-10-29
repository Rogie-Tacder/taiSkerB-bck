from typing import Final
from dotenv import load_dotenv
import os
load_dotenv()
# Sa HUBSPOT na sya na constants
# HUBSPOT_APP_ID: Final[str] = '3550755'
# HUBSPOT_SCOPES: Final[str] = "crm.objects.line_items.read%20crm.objects.carts.write%20crm.objects.line_items.write%20crm.objects.carts.read%20crm.objects.subscriptions.read%20crm.objects.orders.write%20oauth%20crm.objects.owners.read%20crm.objects.commercepayments.read%20crm.objects.orders.read%20crm.objects.invoices.read%20account-info.security.read%20crm.objects.leads.read%20crm.objects.leads.write%20crm.objects.users.read%20tickets%20crm.objects.contacts.write%20e-commerce%20crm.objects.marketing_events.read%20accounting%20crm.objects.marketing_events.write%20crm.objects.companies.write%20crm.lists.write%20crm.objects.companies.read%20crm.lists.read%20crm.objects.deals.read%20crm.objects.deals.write%20crm.objects.quotes.write%20crm.objects.contacts.read%20crm.objects.quotes.read&optional_scope=business_units_view.read%20business-intelligence"
# HUBSPOT_AUTH_ENPOINT: Final[str] = 'https://api.hubapi.com/oauth/v1/token'
# HUBSPOT_API_URL: Final[str] = 'https://api.hubapi.com/'
SALT: Final[str] = 'sVcjG4voQY8SD4dKTwdiN3s1aK2VEbi2'


# Kani sa Gmail constants  \(-.-)/
GMAIL_REDIRECT_URI: Final[str] = 'http://localhost:5174/'
GMAIL_AUTH_ENDPOINT: Final[str] = 'https://oauth2.googleapis.com/token'
GMAIL_AUTH_URL = 'https://accounts.google.com/o/oauth2/auth' 
GMAIL_CLIENT_ID: Final[str] = os.getenv('GMAIL_CLIENT_ID')
GMAIL_CLIENT_SECRET: Final[str]= os.getenv('GMAIL_CLIENT_SECRET')
GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
