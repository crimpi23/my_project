from sqlalchemy import create_engine, Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime

DATABASE_URL = "postgresql://crimpi_parts_user:m9xEi6jMGGtDrtYMh8P3oW3zR6RLFTWn@dpg-cts5hh5umphs73fk5pvg-a/crimpi_parts"
engine = create_engine(DATABASE_URL)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)
    token = Column(String)
    orders = relationship('Order', back_populates='user')

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    article = Column(String)
    table_name = Column(String)
    price = Column(Numeric)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    product_id = Column(Integer, ForeignKey('products.id'))
    quantity = Column(Integer, nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    order_date = Column(DateTime, default=datetime.utcnow)
    user = relationship('User', back_populates='orders')
    product = relationship('Product')

class PriceList(Base):
    __tablename__ = 'price_lists'
    id = Column(Integer, primary_key=True)
    table_name = Column(String)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
