const token = "pmHW6oRtXWIZY3UBdpMobcaxyAR9ElAUh8mFsHrJFv44xTRSsqcBxmKQFDPKgJBr";

function fetchProtected(route) {
    return fetch(route, {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    }).then(response => response.json());
}

// Приклад завантаження даних прайс-листів
function loadPriceLists() {
    fetchProtected('/price-lists/')
        .then(data => {
            const contentDiv = document.getElementById('content');
            contentDiv.innerHTML = JSON.stringify(data, null, 2);
        })
        .catch(error => console.error('Error:', error));
}

document.addEventListener("DOMContentLoaded", loadPriceLists);
