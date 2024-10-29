import base64
import datetime
import json
import os
import flask
import psycopg2
import requests
from flask import jsonify, request
from psycopg2.extras import DictCursor
from utils.db import create_db_connection
from constants.data import  GMAIL_AUTH_ENDPOINT,GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_SCOPES, SALT
import time
from datetime import datetime, timedelta


GMAIL_REDIRECT_URI = 'http://localhost:5174/'
GMAIL_APP_URL = 'https://accounts.google.com/o/oauth2/auth'


def get_gmail_auth_url():
    auth_url = f"{GMAIL_APP_URL}?response_type=code&client_id={GMAIL_CLIENT_ID}&redirect_uri={GMAIL_REDIRECT_URI}&scope={GMAIL_SCOPES}&access_type=offline"
    return auth_url

def token_by_parts(access_token):
    token, encrypted_email = access_token.replace('Bearer ', '').rsplit('.', 1)
    return token, encrypted_email

def decode_email_from_access_token(access_token):
    try:
        token, encrypted_email = token_by_parts(access_token)
        decoded = base64.urlsafe_b64decode(encrypted_email).decode()
        email = decoded[len(SALT):]  
        print(f"Email::: {email}")
        print(f"Access token::: {access_token}")
        return email, token
    except Exception as e:
        print(f"Error decoding token: {str(e)}")
        raise ValueError(f"Invalid token format: {str(e)}")

def encrypt_email_with_token(email, credentials):
    email_bytes = SALT.encode() + email.encode('utf-8')
    encrypted_email = base64.urlsafe_b64encode(email_bytes).decode()
    print(f"Encrypted email: {encrypted_email}")
    credentials['access_token'] = f"{credentials['access_token']}.{encrypted_email}"
    return credentials

def process_code_from_gmail(code):
    print(f"Processing code from Gmail")
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    payload = {
        "grant_type": "authorization_code",
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "redirect_uri": GMAIL_REDIRECT_URI,
        "code": code,
        "access_type": "offline",  
        "prompt": "consent"  
    }

    try:
        response = requests.post(GMAIL_AUTH_ENDPOINT, headers=headers, data=payload)
        response.raise_for_status()
        credentials = response.json()
        print(f"Response: {credentials}") 

        if 'refresh_token' in credentials:
            print(f"Refresh token received: {credentials['refresh_token']}")
        else:
            print("No refresh token received. This might be because the user has already granted permission.")

        if 'access_token' in credentials:
            email = get_gmail_email(credentials['access_token'])
            if email:
                credentials['expiry_date'] = int(time.time()) + credentials['expires_in']
                credentials = encrypt_email_with_token(email, credentials)
                if save_gmail_credentials(credentials, email):
                    return jsonify({
                        'success': True,
                        'code': 200,
                        'token': credentials['access_token'],
                        'email': email
                    }), 200
            else:
                return jsonify({'success': False, 'message': 'Failed to retrieve email', 'code': 500}), 500
        else:
            return jsonify({'success': False, 'message': 'Invalid Credentials', 'code': 401}), 401

    except requests.exceptions.RequestException as e:
        print(f"Error during Gmail authentication: {e}")
        return jsonify({'success': False, 'message': 'Error during authentication', 'code': 500}), 500
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        return jsonify({'success': False, 'message': 'Invalid response from Gmail', 'code': 500}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({'success': False, 'message': 'Unexpected error occurred', 'code': 500}), 500

def check_token_expiration_and_refresh(credentials):
    if 'expiry_date' in credentials and int(time.time()) >= credentials['expiry_date']:
        print("Token has expired. Refreshing...")
        new_credentials = refresh_gmail_token(credentials['refresh_token'])
        if new_credentials:
            return new_credentials
        else:
            print("Failed to refresh token.")
            return None
    return credentials

def get_gmail_credentials(email):
    try:
        conn = create_db_connection()
        print(f"Getting Gmail credentials for {email}")
        credentials = get_user_gmail_credentials(conn, email)
        if credentials is None:
            print(f"No credentials found for {email}")
            return None
        
        credentials = json.loads(credentials['credentials'])
        updated_credentials = check_token_expiration_and_refresh(credentials)
        
        if updated_credentials != credentials:
            save_gmail_credentials(updated_credentials, email)
        
        return updated_credentials
    except Exception as e:
        print(f"Error retrieving Gmail credentials for {email}: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()

def get_gmail_email(access_token):
    
    url = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
    
    headers = {
        'Content-Type': 'application/json',
        "Authorization": f"Bearer {access_token}"
    }
    
    try:
       
        response = requests.get(url, headers=headers)       
 
        if response.status_code == 200:
            
            user_data = response.json()
            
          
            if 'emailAddress' in user_data:
                email = user_data['emailAddress']
                return email
            else:
                print("No email found in the API response")
                return None
        else:
          
            print(f"Failed to retrieve user details: {response.status_code} - {response.text}")
            return None
    
    except requests.exceptions.RequestException as e:
       
        print(f"Error fetching user details: {e}")
        return None
    
def save_gmail_credentials(credentials, email):
    conn = create_db_connection()
    existing_credentials = get_user_gmail_credentials(conn, email)
    try:
        if existing_credentials:
            credentials = json.dumps(credentials)
            update_user_gmail_credentials(conn, email, credentials)
        else:
            insert_user_gmail_credentials(conn, email, credentials)
        return True
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return False
    
def insert_user_gmail_credentials(conn, email, credentials):
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"INSERT INTO \"user_gmail_credentials\" (email, credentials, \"create_date\", \"update_date\") VALUES ('{email}', '{json.dumps(credentials)}', NOW(), NOW())")
            conn.commit()
        print('Database credentials inserted')
    except psycopg2.Error as e:
        print(f"Error inserting user gmail credentials: {e}")
        conn.rollback()
        raise

def update_user_gmail_credentials(conn, email, credentials):
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("UPDATE \"user_gmail_credentials\" SET credentials = %s, \"update_date\" = NOW() WHERE email = %s", (json.dumps(credentials), email))
            conn.commit()
        print('Database credentials updated::::::')
    except psycopg2.Error as e:
        print(f"Error updating user gmail credentials: {e}")
        conn.rollback()
        raise

def get_user_gmail_credentials(conn, email):
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(f"SELECT id, email, credentials, customer_id, usage FROM \"user_gmail_credentials\" WHERE email = '{email}'")
            result = cur.fetchone()
            
        print('Get user gmail credentials Done')
        if result:
            return {
                'id': result['id'],
                'email': result['email'],
                'credentials': result['credentials'],
                'customer_id': result['customer_id'],
                'usage': result['usage']
            }
        return None
    except psycopg2.Error as e:
        print(f"Error getting user gmail credentials: {e}")
        raise

def refresh_gmail_token(refresh_token):
    token_url = GMAIL_AUTH_ENDPOINT
    
    payload = {
        "grant_type": "refresh_token",
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": refresh_token
    }

    try:
        response = requests.post(token_url, data=payload)
        response.raise_for_status()
        new_credentials = response.json()
        
        if 'access_token' in new_credentials:
            new_credentials['refresh_token'] = refresh_token  
            new_credentials['expiry_date'] = int(time.time()) + new_credentials['expires_in']
            
            email = get_gmail_email(new_credentials['access_token'])
            new_credentials = encrypt_email_with_token(email, new_credentials)

            print("Credentials refreshed successfully.")
            return new_credentials
        else:
            print("Gmail Credentials refresh failed.")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Failed to refresh Gmail credentials: {e}")
        return None

def get_gmail_information_from_token(token):
    try:
        url = f"https://api.gmail.com/oauth/v1/access-tokens/{token}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"Failed to get gmail information from token: {e}")
        return None





