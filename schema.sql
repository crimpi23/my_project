CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    password VARCHAR(200) NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE
);

CREATE TABLE price_lists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    article VARCHAR(80) NOT NULL,
    price FLOAT NOT NULL,
    price_list_id INTEGER REFERENCES price_lists(id) ON DELETE CASCADE
);
