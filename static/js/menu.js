document.addEventListener('DOMContentLoaded', function() {
    // Знаходимо всі кнопки розгортання
    const expandButtons = document.querySelectorAll('.expand-btn');
    
    expandButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // Переключаємо активний стан кнопки
            this.classList.toggle('active');
            
            // Знаходимо підменю
            const submenu = this.closest('.menu-item-header')
                              .nextElementSibling;
            
            if (submenu && submenu.classList.contains('submenu')) {
                submenu.classList.toggle('show');
                
                // Прокручуємо до відкритого підменю
                if (submenu.classList.contains('show')) {
                    setTimeout(() => {
                        submenu.scrollIntoView({ 
                            behavior: 'smooth', 
                            block: 'nearest' 
                        });
                    }, 300);
                }
            }
        });
    });
    
    // Закриваємо всі підменю при кліку поза меню
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.vertical-menu')) {
            document.querySelectorAll('.submenu.show').forEach(submenu => {
                submenu.classList.remove('show');
            });
            document.querySelectorAll('.expand-btn.active').forEach(btn => {
                btn.classList.remove('active');
            });
        }
    });
});