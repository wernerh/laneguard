import sqlite3


def connect():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, is_admin INTEGER)")
    conn.execute("INSERT INTO users (name, is_admin) VALUES ('alice', 1), ('bob', 0)")
    return conn


def find_user(conn, name):
    # SEEDED VULN VA-1: SQL built by string concatenation (injection).
    query = "SELECT id, name FROM users WHERE name = '" + name + "'"
    return conn.execute(query).fetchall()
