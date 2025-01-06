<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search Results</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <header>
        <nav>
            <a href="{{ url_for('home') }}">Головна</a>
            <a href="{{ url_for('search') }}">Пошук</a>
        </nav>
    </header>

    <main>
        <h1>Search Results</h1>
        <form action="{{ url_for('search') }}" method="get">
            <input type="text" name="query" placeholder="Enter article" value="{{ query }}">
            <button type="submit">Search</button>
        </form>

        {% if error %}
            <p class="error">{{ error }}</p>
        {% elif results %}
            <ul>
                {% for product in results %}
                    <li>{{ product.article }} - {{ product.price }} €</li>
                {% endfor %}
            </ul>
        {% else %}
            <p>No results found for '{{ query }}'.</p>
        {% endif %}
    </main>
</body>
</html>
