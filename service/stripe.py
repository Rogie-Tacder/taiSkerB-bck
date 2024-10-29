
import datetime
import json
import os
import stripe
import psycopg2
from service.auth import get_user_gmail_credentials
from utils.db import create_db_connection
from psycopg2.extras import DictCursor

# Initialize Stripe with your secret key
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def process_stripe_payment(session_id):
    try:
        data = retrieve_stripe_payment_intent(session_id)
        result = save_stripe_payment_data(data)
        return True
    except stripe.error.StripeError as e:
        print(f"Stripe error occurred: {str(e)}")
        return {"error": "An error occurred while processing the payment"}
    except Exception as e:
        print(f"Unexpected error occurred: {str(e)}")
        return {"error": "An unexpected error occurred"}

def retrieve_stripe_payment_intent(session_id):
    return stripe.checkout.Session.retrieve(
        session_id
    )

def retrieve_stripe_product(product_id, email):
    product =  stripe.Product.retrieve(
        product_id
    )
    
    price = stripe.Price.retrieve(
        product.default_price
    )
    subscription_status, subscription_usage = retrieve_customer_subscription_status(email)
    return {
        "price": price.unit_amount / 100,
        "subscription_status": subscription_status,
        "subscription_usage": subscription_usage
    }

def save_stripe_payment_data(data):
    conn = create_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            customer_email = data['customer_details']['email']
            customer_name = data['customer_details']['name']
            amount_total = data['amount_total']
            currency = data['currency']
            payment_status = data['payment_status']
            subscription_id = data['subscription']
            session_id = data['id']
            created_at = data['created']
            stripe_customer_id = data['customer']
            invoice_id = data.get('invoice')
            payment_intent_id = data.get('payment_intent')

            # Update user_hubspot_credentials with customer_id
            cur.execute(
                """
                UPDATE user_gmail_credentials
                SET customer_id = %s
                WHERE email = %s
                RETURNING id
                """,
                (stripe_customer_id, customer_email)
            )
            user_id = cur.fetchone()

            if not user_id:
                raise Exception(f"User with email {customer_email} not found in user_hubspot_credentials")

            # Insert or update the subscription record
            cur.execute(
                """
                INSERT INTO subscriptions
                (customer_id, stripe_subscription_id, stripe_customer_id, status, created_at, amount, currency, stripe_session_id, stripe_payment_intent_id, stripe_invoice_id, metadata)
                VALUES (%s, %s, %s, %s, to_timestamp(%s), %s, %s, %s, %s, %s, %s)
                ON CONFLICT (stripe_subscription_id) DO UPDATE
                SET status = EXCLUDED.status,
                    amount = EXCLUDED.amount,
                    updated_at = CURRENT_TIMESTAMP,
                    stripe_session_id = EXCLUDED.stripe_session_id,
                    stripe_payment_intent_id = EXCLUDED.stripe_payment_intent_id,
                    stripe_invoice_id = EXCLUDED.stripe_invoice_id,
                    metadata = EXCLUDED.metadata
                RETURNING id
                """,
                (stripe_customer_id, subscription_id, stripe_customer_id, payment_status, created_at, amount_total, currency, session_id, payment_intent_id, invoice_id, json.dumps(data))
            )

            subscription_record_id = cur.fetchone()[0]

            conn.commit()
            return subscription_record_id

    except (Exception, psycopg2.Error) as error:
        print("Error in save_stripe_payment_data:", error)
        if conn:
            conn.rollback()
        raise

    finally:
        if conn:
            conn.close()


def retrieve_customer_subscription_status(email):
    try:
        conn = create_db_connection()
        customer = get_user_gmail_credentials(conn, email)
        if not customer or 'customer_id' not in customer:
            print(f"No valid customer found for email: {email}")
            return 'inactive', 0

        invoices = stripe.Invoice.list(
            customer=customer['customer_id'],
        ) if customer['customer_id'] else []

        subscription_status = 'inactive'

        subscriptions = stripe.Subscription.list(
            customer=customer['customer_id'],
        ) if customer['customer_id'] else []

        current_month = datetime.datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for invoice in invoices:
            if invoice.paid and invoice.created >= int(current_month.timestamp()) and len(subscriptions.get('data')) > 0:
                subscription_status = 'active'
                break
        return subscription_status, customer['usage']
    except stripe.error.StripeError as e:
        print(f"Stripe error occurred: {str(e)}")
        raise
    except ValueError as e:
        print(f"Value error occurred: {str(e)}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()

def cancel_stripe_subscription(email):
    try:
        conn = create_db_connection()
        customer = get_user_gmail_credentials(conn, email)
        if not customer or 'customer_id' not in customer:
            raise ValueError(f"No valid customer found for email: {email}") 
        subscriptions = stripe.Subscription.list(
            customer=customer['customer_id'],
        )

        if not subscriptions:
            raise ValueError(f"No active subscription found for email: {email}")
        
        is_subscription_cancelled = False
        for sub in subscriptions:
            result = stripe.Subscription.cancel(sub.get('id'))
            print("result:::", result)
            is_subscription_cancelled = True
        
        return is_subscription_cancelled
    except stripe.error.StripeError as e:
        print(f"Stripe error occurred: {str(e)}")
        raise
    except ValueError as e:
        print(f"Value error occurred: {str(e)}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        raise


