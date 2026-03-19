document.addEventListener('DOMContentLoaded', function() {
    // Мобільне меню - шукаємо різні варіанти назв класів
    const mobileMenuBtn = document.querySelector('.burger-btn') || document.querySelector('.mobile-menu-btn');
    const mobileMenu = document.querySelector('.mobile-menu');
    const closeMenuBtn = document.querySelector('.close-mobile-menu');
    const backdrop = document.querySelector('.mobile-menu-backdrop');
    
    console.log('Mobile menu button found:', !!mobileMenuBtn);
    console.log('Mobile menu found:', !!mobileMenu);
    console.log('Close button found:', !!closeMenuBtn);
    
    if (mobileMenuBtn && mobileMenu) {
        console.log('Adding click event to mobile menu button');
        
        // Функція для відкриття/закриття меню
        function toggleMenu() {
            mobileMenuBtn.classList.toggle('active');
            mobileMenu.classList.toggle('open');
            document.body.classList.toggle('menu-open');
            
            console.log('Menu toggled:', {
                buttonActive: mobileMenuBtn.classList.contains('active'),
                menuOpen: mobileMenu.classList.contains('open')
            });
        }
        
        // Функція для закриття меню
        function closeMenu() {
            mobileMenuBtn.classList.remove('active');
            mobileMenu.classList.remove('open');
            document.body.classList.remove('menu-open');
        }
        
        mobileMenuBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('Mobile menu button clicked!');
            toggleMenu();
        });
        
        // Закриття меню кнопкою X
        if (closeMenuBtn) {
            closeMenuBtn.addEventListener('click', function(e) {
                e.preventDefault();
                console.log('Close button clicked');
                closeMenu();
            });
        }
        
        // Закриття меню при кліку на backdrop
        if (backdrop) {
            backdrop.addEventListener('click', function() {
                console.log('Backdrop clicked');
                closeMenu();
            });
        }
        
        // Закриття меню при кліку на посилання
        const menuLinks = mobileMenu.querySelectorAll('a');
        console.log('Found menu links:', menuLinks.length);
        
        menuLinks.forEach(link => {
            // Не закриваємо при кліку на мовні кнопки, бо вони переходять на іншу сторінку
            link.addEventListener('click', function(e) {
                // Якщо це не toggle кнопка категорій
                if (!this.closest('.mobile-cat-toggle') && !this.closest('.mobile-cat-toggle-l2')) {
                    console.log('Menu link clicked');
                    // Не закриваємо відразу, даємо перейти за посиланням
                }
            });
        });
        
        // Закриття меню при кліку поза ним
        document.addEventListener('click', function(event) {
            const isClickInsideMenu = mobileMenu.contains(event.target);
            const isClickMenuButton = mobileMenuBtn.contains(event.target);
            
            if (mobileMenu.classList.contains('open') && !isClickInsideMenu && !isClickMenuButton) {
                console.log('Clicked outside menu, closing');
                closeMenu();
            }
        });
        
    } else {
        console.error('Mobile menu elements not found!');
        console.log('Available elements with mobile classes:', {
            burgerBtns: document.querySelectorAll('.burger-btn').length,
            mobileMenuBtns: document.querySelectorAll('.mobile-menu-btn').length,
            mobileMenus: document.querySelectorAll('.mobile-menu').length
        });
    }
    
    // Закриття меню при зміні розміру екрану
    window.addEventListener('resize', function() {
        if (window.innerWidth > 991) {
            if (mobileMenu && mobileMenu.classList.contains('open')) {
                console.log('Screen resized to desktop, closing mobile menu');
                mobileMenu.classList.remove('open');
                if (mobileMenuBtn) {
                    mobileMenuBtn.classList.remove('active');
                }
                document.body.classList.remove('menu-open');
                document.body.style.overflow = '';
            }
        }
    });
    
    // Закриття меню по Escape
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && mobileMenu && mobileMenu.classList.contains('open')) {
            mobileMenu.classList.remove('open');
            if (mobileMenuBtn) mobileMenuBtn.classList.remove('active');
            document.body.classList.remove('menu-open');
            document.body.style.overflow = '';
        }
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

    // ===================================================
    // HEADER STICKY - FIXED HEIGHT (NO FLICKERING)
    // ===================================================
    // Key: Header height never changes, only opacity fades
    // This prevents scroll position changes that cause flickering
    
    const mainHeader = document.querySelector('.main-header');
    
    const toggleSticky = () => {
        if (!mainHeader) return;
        const scrollY = window.scrollY;
        
        // Add sticky shadow when scrolled
        mainHeader.classList.toggle('is-sticky', scrollY > 10);
        
        // Fade out top bar and nav at 100px
        // No height change = no scroll jump = no flickering
        mainHeader.classList.toggle('is-compact', scrollY > 100);
    };
    
    // Initialize on load
    toggleSticky();
    
    // Optimized scroll handler with RAF
    let ticking = false;
    window.addEventListener('scroll', () => {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                toggleSticky();
                ticking = false;
            });
            ticking = true;
        }
    }, { passive: true });

    const vinModalOverlay = document.getElementById('vinModalOverlay');
    document.querySelectorAll('[data-open-vin-modal]').forEach(btn => {
        btn.addEventListener('click', () => {
            if (vinModalOverlay) {
                vinModalOverlay.classList.remove('d-none');
                document.body.style.overflow = 'hidden';
            }
        });
    });

    const helpModalOverlay = document.getElementById('helpModalOverlay');
    document.querySelectorAll('[data-open-help-modal]').forEach(btn => {
        btn.addEventListener('click', () => {
            if (helpModalOverlay) {
                helpModalOverlay.classList.remove('d-none');
                document.body.style.overflow = 'hidden';
            }
        });
    });

    const serviceModalOverlay = document.getElementById('serviceModalOverlay');
    document.querySelectorAll('[data-open-service-modal]').forEach(btn => {
        btn.addEventListener('click', () => {
            if (serviceModalOverlay) {
                serviceModalOverlay.classList.remove('d-none');
                document.body.style.overflow = 'hidden';
            }
        });
    });
});