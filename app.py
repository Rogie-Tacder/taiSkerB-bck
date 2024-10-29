import os
from flask import Flask, jsonify, request
from service.gmail_tool_call import ask_gmail_api
from service.auth import decode_email_from_access_token, get_gmail_auth_url, get_gmail_credentials, process_code_from_gmail
from service.stripe import cancel_stripe_subscription, process_stripe_payment, retrieve_stripe_product


app = Flask(__name__)

@app.route("/gmail-auth-url", methods=['GET'])
def gmail_auth_url():
    return jsonify(message=get_gmail_auth_url())  

@app.route("/gmail-callback", methods=['GET'])  
def gmail_callback():
    code = request.args.get('code')
    print(f"Received code: {code}") 
    return process_code_from_gmail(code)  

@app.route("/get-gmail-credentials", methods=['GET'])
def get_gmail_credentials_by_email():
    email = request.args.get('email')
    return jsonify(data=get_gmail_credentials(email)) 

@app.route("/ask-gmail", methods=['POST'])
def ask_gmail():
    try:
        data = request.json
        authorization = request.headers.get('x-auth-token')
        if not authorization or not authorization.startswith('Bearer '):
            return jsonify(error="No authorization provided in the request"), 400
        
        if not data:
            return jsonify(error="No JSON data provided"), 400

        message = data.get('message')
        timezone = data.get('timezone')
        chat_history = data.get('chat_history')
        
        if not message:
            return jsonify(error="No message provided in the request"), 400
        
        try:
            email, token = decode_email_from_access_token(authorization)
        except ValueError as ve:
            app.logger.error(f"Error decoding token: {str(ve)}")
            return jsonify(error="Invalid token"), 400
        
        if not email or not token:
            return jsonify(error="Invalid token format"), 400
        
        app.logger.info(f"Decoded email: {email}")
        response, usage = ask_gmail_api(token, message, email, timezone, chat_history)
        return jsonify(data=response, usage=usage), 200
    except Exception as e:
        app.logger.error(f"Error in ask_gmail: {str(e)}", exc_info=True)
        return jsonify(error="An internal server error occurred"), 500

@app.route("/stripe/payment-success", methods=['POST'])
def stripe_payment_process():
    data = request.json
    result = process_stripe_payment(data.get('checkoutSessionId'))
    return jsonify(data={"message": "successfully processed payment", "status": result}), 200

@app.route("/stripe/product", methods=['GET'])
def stripe_product():
    email = request.args.get('email')
    result = retrieve_stripe_product(os.getenv('STRIPE_PRODUCT_ID'), email)
    return jsonify(data=result), 200

@app.route("/stripe/cancel-subscription", methods=['POST'])
def stripe_cancel_subscription():
    data = request.json
    email = data.get('email')
    result = cancel_stripe_subscription(email)
    return jsonify(data={"message": "successfully cancelled subscription", "status": result}), 200