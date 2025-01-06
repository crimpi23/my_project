function search() {
    const query = document.getElementById('search').value;
    fetch(`/search?article=${query}`)
        .then(response => response.json())
        .then(data => {
            const resultsDiv = document.getElementById('results');
            resultsDiv.innerHTML = '';
            data.forEach(product => {
                const productDiv = document.createElement('div');
                productDiv.innerHTML = `<p>${product.article} - ${product.price}</p><button onclick="addToCart(${product.id})">Додати в кошик</button>`;
                resultsDiv.appendChild(productDiv);
            });
        });
}

function addToCart(productId) {
    fetch(`/cart`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            user_id: 1,  // Example user ID, you can replace it with the actual user's ID
            product_id: productId,
            quantity: 1
        })
    })
    .then(response => response.json())
    .then(data => {
        alert('Товар додано до кошика');
    });
}
