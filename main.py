from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from models import SessionLocal, User, Product, Order, PriceList

app = FastAPI()

security = HTTPBearer()

app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    user = SessionLocal().query(User).filter(User.token == token).first()
    if not user:
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    return user

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("templates/client.html") as f:
        return f.read()

@app.get("/admin", response_class=HTMLResponse)
def read_admin():
    with open("templates/admin.html") as f:
        return f.read()

@app.post("/orders/", dependencies=[Depends(verify_token)])
def create_order(user_id: int, product_id: int, quantity: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    product = db.query(Product).filter(Product.id == product_id).first()

    if user is None or product is None:
        raise HTTPException(status_code=404, detail="User or Product not found")

    total_price = product.price * quantity
    order = Order(user_id=user_id, product_id=product_id, quantity=quantity, total_price=total_price)

    db.add(order)
    db.commit()
    db.refresh(order)
    return order

@app.get("/users/{user_id}/orders/", dependencies=[Depends(verify_token)])
def read_user_orders(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user.orders

@app.get("/orders/", dependencies=[Depends(verify_token)])
def read_orders(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    return orders

@app.post("/price-lists/", dependencies=[Depends(verify_token)])
def upload_price_list(table_name: str, description: str, db: Session = Depends(get_db)):
    price_list = PriceList(table_name=table_name, description=description)
    db.add(price_list)
    db.commit()
    db.refresh(price_list)
    return price_list

@app.get("/price-lists/", dependencies=[Depends(verify_token)])
def read_price_lists(db: Session = Depends(get_db)):
    price_lists = db.query(PriceList).all()
    return price_lists

@app.post("/users/", dependencies=[Depends(verify_token)])
def create_user(name: str, email: str, db: Session = Depends(get_db)):
    user = User(name=name, email=email, token="some_unique_token")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@app.get("/users/", dependencies=[Depends(verify_token)])
def read_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users

@app.get("/search/")
def search_products(article: str, db: Session = Depends(get_db)):
    results = db.query(Product).filter(Product.article.ilike(f"%{article}%")).all()
    return results
