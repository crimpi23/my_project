console.log('Header.js loading...'); // Для перевірки завантаження

document.addEventListener('DOMContentLoaded', function() {
    console.log('Header.js loaded and DOM ready'); // Для перевірки
    
    // Мобільне меню
    const mobileMenuBtn = document.querySelector('.mobile-menu-btn');
    const mobileMenu = document.querySelector('.mobile-menu');
    
    console.log('Mobile menu button found:', !!mobileMenuBtn);
    console.log('Mobile menu found:', !!mobileMenu);
    
    if (mobileMenuBtn && mobileMenu) {
        console.log('Adding click event to mobile menu button');
        
        mobileMenuBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Mobile menu button clicked!'); // ЦЕ МАЄ З'ЯВИТИСЯ
            
            // Перемикаємо класи
            this.classList.toggle('active');
            mobileMenu.classList.toggle('active');
            document.body.classList.toggle('menu-open');
            
            console.log('Menu classes after toggle:', {
                buttonActive: this.classList.contains('active'),
                menuActive: mobileMenu.classList.contains('active'),
                bodyMenuOpen: document.body.classList.contains('menu-open')
            });
        });
        
        // Закриття меню при кліку на посилання
        const menuLinks = mobileMenu.querySelectorAll('.mobile-nav-link');
        console.log('Found menu links:', menuLinks.length);
        
        menuLinks.forEach(link => {
            link.addEventListener('click', function() {
                console.log('Menu link clicked, closing menu');
                mobileMenu.classList.remove('active');
                mobileMenuBtn.classList.remove('active');
                document.body.classList.remove('menu-open');
            });
        });
        
        // Закриття меню при кліку поза ним
        document.addEventListener('click', function(event) {
            const isClickInsideMenu = mobileMenu.contains(event.target);
            const isClickMenuButton = mobileMenuBtn.contains(event.target);
            
            if (mobileMenu.classList.contains('active') && !isClickInsideMenu && !isClickMenuButton) {
                console.log('Clicked outside menu, closing');
                mobileMenu.classList.remove('active');
                mobileMenuBtn.classList.remove('active');
                document.body.classList.remove('menu-open');
            }
        });
        
    } else {
        console.error('Mobile menu elements not found!');
        console.log('Available elements with mobile classes:', {
            mobileMenuBtns: document.querySelectorAll('.mobile-menu-btn').length,
            mobileMenus: document.querySelectorAll('.mobile-menu').length
        });
    }
    
    // Закриття меню при зміні розміру екрану
    window.addEventListener('resize', function() {
        if (window.innerWidth > 991) {
            if (mobileMenu && mobileMenu.classList.contains('active')) {
                console.log('Screen resized to desktop, closing mobile menu');
                mobileMenu.classList.remove('active');
                if (mobileMenuBtn) {
                    mobileMenuBtn.classList.remove('active');
                }
                document.body.classList.remove('menu-open');
            }
        }
    });
    
    // Offcanvas меню
    const burger = document.querySelector('.burger-btn');
    const menu = document.getElementById('mobileMenu'); // offcanvas variant
    const inlineMenu = document.querySelector('.mobile-menu.d-lg-none'); // перший (inline) якщо хочеш теж ховати
    const backdrop = document.querySelector('.mobile-menu-backdrop');
    const closeBtn = document.querySelector('.close-mobile-menu');

    function openMenu() {
        menu.classList.add('open');
        document.body.style.overflow = 'hidden';
    }
    function closeMenu() {
        menu.classList.remove('open');
        document.body.style.overflow = '';
    }

    if (burger) {
        burger.addEventListener('click', () => {
            if (menu.classList.contains('open')) {
                closeMenu();
            } else {
                openMenu();
            }
        });
    }
    if (closeBtn) closeBtn.addEventListener('click', closeMenu);
    if (backdrop) backdrop.addEventListener('click', closeMenu);

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && menu.classList.contains('open')) closeMenu();
    });
    
    // ========== КАТАЛОГ В МОБІЛЬНОМУ МЕНЮ ==========
    const mobileCatalogBtn = document.getElementById('mobileCatalogBtn');
    const mobileCatalogMenu = document.getElementById('mobileCatalogMenu');
    
    if (mobileCatalogBtn && mobileCatalogMenu) {
        mobileCatalogBtn.addEventListener('click', () => {
            mobileCatalogBtn.classList.toggle('open');
            mobileCatalogMenu.classList.toggle('show');
        });
        
        // Розкриття підменю категорій 1 рівня (ТІЛЬКИ всередині mobileCatalogMenu)
        mobileCatalogMenu.querySelectorAll('.mobile-cat-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                btn.classList.toggle('open');
                const subMenu = btn.closest('.mobile-cat-item').querySelector('.mobile-cat-sub');
                if (subMenu) subMenu.classList.toggle('open');
            });
        });
        
        // Розкриття підменю категорій 2 рівня (ТІЛЬКИ всередині mobileCatalogMenu)
        mobileCatalogMenu.querySelectorAll('.mobile-cat-toggle-l2').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                btn.classList.toggle('open');
                const subMenu = btn.closest('.mobile-cat-sub-item').querySelector('.mobile-cat-sub-l3');
                if (subMenu) subMenu.classList.toggle('open');
            });
        });
    }
});