import os
import psycopg2
from psycopg2.extras import DictCursor

def create_db_connection():
    db_host = os.environ['DB_HOST']
    db_user = os.environ['DB_USER']
    db_pass = os.environ['DB_PASS']
    db_name = os.environ['DB_NAME']
    db_port = os.environ.get('DB_PORT', '5432')  # Default PostgreSQL port
    
    conn = psycopg2.connect(
        host=db_host,
        user=db_user,
        password=db_pass,
        dbname=db_name,
        port=db_port
    )
    return conn