// Ініціалізація після завантаження DOM
document.addEventListener('DOMContentLoaded', function() {
    // Клонуємо фільтри для мобільної версії
    const filterSidebar = document.querySelector('.filter-sidebar');
    const mobileFiltersBody = document.querySelector('#mobileFilters .offcanvas-body');
    
    if (filterSidebar && mobileFiltersBody) {
        const clonedFilters = filterSidebar.cloneNode(true);
        clonedFilters.classList.remove('filter-sidebar');
        mobileFiltersBody.appendChild(clonedFilters);
        
        // Оновлюємо ID для коректної роботи collapsible елементів
        const mobileCollapses = mobileFiltersBody.querySelectorAll('.collapse');
        mobileCollapses.forEach((collapse, index) => {
            const newId = collapse.id + '-mobile';
            collapse.id = newId;
            
            const trigger = mobileFiltersBody.querySelector(`[data-bs-target="#${collapse.id.replace('-mobile', '')}"]`);
            if (trigger) {
                trigger.setAttribute('data-bs-target', `#${newId}`);
            }
        });
    }
    
    // Автоматична відправка форми при зміні радіо-кнопок
    const filterRadios = document.querySelectorAll('.filter-sidebar .brand-radio, .filter-sidebar .sort-radio');
    filterRadios.forEach(radio => {
        radio.addEventListener('change', function() {
            this.closest('form').submit();
        });
    });
    
    // Зберігаємо стан розкриття фільтрів у localStorage
    const filterHeaders = document.querySelectorAll('.filter-header');
    filterHeaders.forEach(header => {
        const targetId = header.getAttribute('data-bs-target').substring(1);
        const storageKey = `filter-${targetId}-expanded`;
        
        // Встановлюємо початковий стан з localStorage
        const savedState = localStorage.getItem(storageKey);
        if (savedState === 'false') {
            const targetCollapse = document.getElementById(targetId);
            if (targetCollapse) {
                targetCollapse.classList.remove('show');
                header.setAttribute('aria-expanded', 'false');
            }
        }
        
        // Зберігаємо стан при кліку
        header.addEventListener('click', function() {
            const isExpanded = header.getAttribute('aria-expanded') === 'true';
            localStorage.setItem(storageKey, !isExpanded);
        });
    });
});