import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    conn = psycopg2.connect(
        "postgresql://neondb_owner:npg_KVdAX3LTU8Dc@ep-square-shadow-agb2xqf6-pooler.c-2.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
        cursor_factory=RealDictCursor  
    )
    return conn

