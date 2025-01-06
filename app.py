@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    try:
        # Отримуємо дані з форми
        article = request.form.get('article')
        quantity = int(request.form.get('quantity'))
        table_name = request.form.get('table_name')
        user_id = 1  # Заставний користувач

        # Підключення до бази
        conn = get_db_connection()
        cursor = conn.cursor()

        # Знаходимо product_id для артикулу
        cursor.execute("""
            SELECT id
            FROM products
            WHERE article = %s AND table_name = %s
        """, (article, table_name))
        product = cursor.fetchone()

        if not product:
            return render_template('index.html', message="Product not found.")

        product_id = product['id']

        # Перевіряємо, чи товар уже в кошику
        cursor.execute("""
            SELECT id, quantity
            FROM cart
            WHERE user_id = %s AND product_id = %s
        """, (user_id, product_id))
        cart_item = cursor.fetchone()

        if cart_item:
            # Якщо товар уже є в кошику, оновлюємо кількість
            new_quantity = cart_item['quantity'] + quantity
            cursor.execute("""
                UPDATE cart
                SET quantity = %s
                WHERE id = %s
            """, (new_quantity, cart_item['id']))
        else:
            # Якщо товару немає, додаємо його в кошик
            cursor.execute("""
                INSERT INTO cart (user_id, product_id, quantity, added_at)
                VALUES (%s, %s, %s, NOW())
            """, (user_id, product_id, quantity))

        conn.commit()
        return render_template('index.html', message="Product added to cart successfully!")

    except Exception as e:
        return render_template('index.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@app.route('/cart')
def view_cart():
    try:
        user_id = 1  # Заставний користувач
        conn = get_db_connection()
        cursor = conn.cursor()

        # Отримуємо всі товари з кошика
        cursor.execute("""
            SELECT c.id AS cart_id, p.article, p.price, c.quantity, c.product_id
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = %s
        """, (user_id,))
        cart_items = cursor.fetchall()

        return render_template('cart.html', cart_items=cart_items)

    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()

@app.route('/update_cart', methods=['POST'])
def update_cart():
    try:
        cart_id = request.form.get('cart_id')
        quantity = int(request.form.get('quantity'))

        conn = get_db_connection()
        cursor = conn.cursor()

        if quantity > 0:
            # Оновлюємо кількість у кошику
            cursor.execute("""
                UPDATE cart
                SET quantity = %s
                WHERE id = %s
            """, (quantity, cart_id))
        else:
            # Видаляємо товар із кошика, якщо кількість 0
            cursor.execute("""
                DELETE FROM cart
                WHERE id = %s
            """, (cart_id,))

        conn.commit()
        return view_cart()

    except Exception as e:
        return render_template('cart.html', message=f"Error: {str(e)}")
    finally:
        cursor.close()
        conn.close()
