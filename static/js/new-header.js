// ============================================
// AUTOGROUPEU HEADER - ANTI-FLICKER SOLUTION
// Principle: Heights NEVER change, only opacity
// This prevents scroll position recalculation loops
// ============================================

console.log('Anti-flicker header.js loading...');

document.addEventListener('DOMContentLoaded', function() {
    console.log('Header initialization started');
    
    const mainHeader = document.querySelector('.main-header');
    
    if (!mainHeader) {
        console.error('Main header element not found!');
        return;
    }
    
    // ============================================
    // SCROLL DETECTION - Anti-stroboscope hysteresis
    // ============================================
    
    let isCompact = false;
    let latestScrollY = window.scrollY || 0;
    let rafScheduled = false;
    const COMPACT_ENTER_THRESHOLD = 160;
    const COMPACT_EXIT_THRESHOLD = 80;

    const setCompactState = (compact) => {
        isCompact = compact;
        if (compact) {
            mainHeader.classList.add('is-compact');
            document.body.classList.add('header-compact');
            console.log('Header → COMPACT');
        } else {
            mainHeader.classList.remove('is-compact');
            document.body.classList.remove('header-compact');
            console.log('Header → EXPANDED');
        }
    };
    
    const applyScrollState = () => {
        rafScheduled = false;
        const scrollY = latestScrollY;

        if (!isCompact && scrollY >= COMPACT_ENTER_THRESHOLD) {
            setCompactState(true);
        } else if (isCompact && scrollY <= COMPACT_EXIT_THRESHOLD) {
            setCompactState(false);
        }

        if (scrollY > 10) {
            mainHeader.classList.add('is-sticky');
        } else {
            mainHeader.classList.remove('is-sticky');
        }
    };

    const handleScroll = () => {
        latestScrollY = window.scrollY || 0;
        if (rafScheduled) return;
        rafScheduled = true;
        window.requestAnimationFrame(applyScrollState);
    };
    
    // Use passive listener for performance
    window.addEventListener('scroll', handleScroll, { passive: true });
    
    // Initial check
    applyScrollState();
    
    console.log('Scroll listener attached');
    
    // ============================================
    // MOBILE MENU TOGGLE
    // ============================================
    
    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    const mobileMenu = document.getElementById('mobileMenu');
    const closeMobileMenu = document.getElementById('closeMobileMenu');
    const mobileMenuBackdrop = document.getElementById('mobileMenuBackdrop');

    const closeMobileMenuPanel = () => {
        if (!mobileMenu) return;
        mobileMenu.classList.remove('open');
        document.body.classList.remove('menu-open');
    };

    const openMobileMenuPanel = () => {
        if (!mobileMenu) return;
        // Даємо змогу іншим оверлеям закритися перед відкриттям меню
        document.dispatchEvent(new CustomEvent('mobileMenu:opening'));
        mobileMenu.classList.add('open');
        document.body.classList.add('menu-open');
    };

    // Коли відкриваються нижні drawer-и, верхнє меню має закриватися
    document.addEventListener('mobileDrawers:opening', closeMobileMenuPanel);
    
    if (mobileMenuToggle && mobileMenu) {
        mobileMenuToggle.addEventListener('click', function(e) {
            e.preventDefault();
            if (mobileMenu.classList.contains('open')) {
                closeMobileMenuPanel();
            } else {
                openMobileMenuPanel();
            }
            console.log('Mobile menu toggled');
        });
    }
    
    if (closeMobileMenu && mobileMenu) {
        closeMobileMenu.addEventListener('click', function(e) {
            e.preventDefault();
            closeMobileMenuPanel();
            console.log('Mobile menu closed');
        });
    }
    
    // Close on backdrop click
    if (mobileMenuBackdrop) {
        mobileMenuBackdrop.addEventListener('click', function() {
            closeMobileMenuPanel();
            console.log('Mobile menu closed (backdrop)');
        });
    }
    
    // Mobile catalog toggle
    const mobileCatalogBtn = document.getElementById('mobileCatalogBtn');
    const mobileCatalogMenu = document.getElementById('mobileCatalogMenu');
    
    if (mobileCatalogBtn && mobileCatalogMenu) {
        mobileCatalogBtn.addEventListener('click', function(e) {
            e.preventDefault();
            mobileCatalogMenu.classList.toggle('open');
            const arrow = this.querySelector('.mobile-cat-arrow');
            if (arrow) {
                arrow.style.transform = mobileCatalogMenu.classList.contains('open') ? 'rotate(180deg)' : '';
            }
        });
    }
    
    // Mobile category toggle
    document.querySelectorAll('.mobile-cat-toggle').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const parent = this.closest('.mobile-cat-item');
            const submenu = parent.querySelector('.mobile-cat-sub');
            if (submenu) {
                submenu.classList.toggle('open');
                const icon = this.querySelector('i');
                if (icon) {
                    icon.style.transform = submenu.classList.contains('open') ? 'rotate(180deg)' : '';
                }
            }
        });
    });
    
    // Mobile level 2 toggle
    document.querySelectorAll('.mobile-cat-toggle-l2').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const parent = this.closest('.mobile-cat-sub-item');
            const submenu = parent.querySelector('.mobile-cat-sub-l3');
            if (submenu) {
                submenu.classList.toggle('open');
                const icon = this.querySelector('i');
                if (icon) {
                    icon.style.transform = submenu.classList.contains('open') ? 'rotate(180deg)' : '';
                }
            }
        });
    });
    
    // Клік по батьківській категорії → розгортає підменю (не навігує)
    document.querySelectorAll('.mobile-cat-parent-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const header = this.closest('.mobile-cat-header');
            const toggle = header && header.querySelector('.mobile-cat-toggle, .mobile-cat-toggle-l2');
            if (toggle) toggle.click();
        });
    });

    // Close menu when clicking on link
    document.querySelectorAll('.mobile-menu-content a').forEach(link => {
        link.addEventListener('click', function() {
            // Close after short delay to allow navigation
            setTimeout(() => {
                closeMobileMenuPanel();
            }, 100);
        });
    });
    
    // Close mobile menu on window resize (above mobile breakpoint)
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768 && mobileMenu && mobileMenu.classList.contains('open')) {
            closeMobileMenuPanel();
            console.log('Mobile menu closed on resize');
        }
    });
    
    // ============================================
    // MODAL HANDLERS (VIN, Help, Service)
    // ============================================

    // ============================================
    // MOBILE BOTTOM DRAWERS (fallback handlers)
    // ============================================
    const bottomNavCatalog = document.getElementById('bottomNavCatalog');
    const bottomNavAccount = document.getElementById('bottomNavAccount');
    const mobileCatalogDrawer = document.getElementById('mobileCatalogDrawer');
    const mobileAccountDrawer = document.getElementById('mobileAccountDrawer');
    const mobileDrawerBackdrop = document.getElementById('mobileDrawerBackdrop');

    const closeBottomDrawers = () => {
        mobileCatalogDrawer?.classList.remove('open');
        mobileAccountDrawer?.classList.remove('open');
        mobileDrawerBackdrop?.classList.remove('open');
        document.body.classList.remove('drawer-open');
        bottomNavCatalog?.setAttribute('aria-expanded', 'false');
        bottomNavAccount?.setAttribute('aria-expanded', 'false');
    };

    closeBottomDrawers();

    const openBottomDrawer = (type) => {
        if (!mobileCatalogDrawer || !mobileAccountDrawer || !mobileDrawerBackdrop) return;
        closeMobileMenuPanel();
        document.dispatchEvent(new CustomEvent('mobileDrawers:opening'));
        if (type === 'catalog') {
            mobileCatalogDrawer.classList.add('open');
            mobileAccountDrawer.classList.remove('open');
            bottomNavCatalog?.setAttribute('aria-expanded', 'true');
            bottomNavAccount?.setAttribute('aria-expanded', 'false');
        } else {
            mobileAccountDrawer.classList.add('open');
            mobileCatalogDrawer.classList.remove('open');
            bottomNavAccount?.setAttribute('aria-expanded', 'true');
            bottomNavCatalog?.setAttribute('aria-expanded', 'false');
        }
        mobileDrawerBackdrop.classList.add('open');
        document.body.classList.add('drawer-open');
    };

    if (bottomNavCatalog) {
        bottomNavCatalog.addEventListener('click', function(e) {
            e.preventDefault();
            if (mobileCatalogDrawer?.classList.contains('open')) {
                closeBottomDrawers();
                return;
            }
            openBottomDrawer('catalog');
        });
    }

    if (bottomNavAccount) {
        bottomNavAccount.addEventListener('click', function(e) {
            e.preventDefault();
            if (mobileAccountDrawer?.classList.contains('open')) {
                closeBottomDrawers();
                return;
            }
            openBottomDrawer('account');
        });
    }

    mobileDrawerBackdrop?.addEventListener('click', closeBottomDrawers);
    document.addEventListener('mobileMenu:opening', closeBottomDrawers);
    document.querySelectorAll('.mobile-drawer-close').forEach((btn) => {
        btn.addEventListener('click', closeBottomDrawers);
    });

    document.querySelectorAll('.mobile-bottom-drawer a').forEach((link) => {
        link.addEventListener('click', function() {
            setTimeout(closeBottomDrawers, 50);
        });
    });

    // Активна вкладка нижнього меню
    const currentPath = window.location.pathname;
    if (currentPath.includes('/public_cart') || currentPath.includes('/cart')) {
        document.getElementById('bottomNavCart')?.classList.add('active');
    } else if (currentPath.includes('/user') || currentPath.includes('/profile') || currentPath.includes('/login') || currentPath.includes('/register')) {
        bottomNavAccount?.classList.add('active');
    } else if (currentPath === '/' || currentPath.match(/^\/(sk|en|pl)\/?$/)) {
        bottomNavCatalog?.classList.add('active');
    }
    
    function closeAllModals() {
        ['vinModalOverlay', 'helpModalOverlay', 'serviceModalOverlay'].forEach(modalId => {
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.classList.remove('d-flex');
                modal.classList.add('d-none');
            }
        });
        document.body.classList.remove('modal-open');
    }
    
    const openModal = (modalId) => {
        closeAllModals(); // Close any other open modals
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('d-none');
            modal.classList.add('d-flex');
            document.body.classList.add('modal-open');
            console.log(`Modal ${modalId} opened`);
        }
    };
    
    const closeModal = (modalId) => {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('d-flex');
            modal.classList.add('d-none');
            document.body.classList.remove('modal-open');
            console.log(`Modal ${modalId} closed`);
        }
    };
    
    // VIN Modal
    document.querySelectorAll('[data-open-vin-modal]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            openModal('vinModalOverlay');
        });
    });
    
    // Help Modal
    document.querySelectorAll('[data-open-help-modal]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            openModal('helpModalOverlay');
        });
    });
    
    // Service Modal
    document.querySelectorAll('[data-open-service-modal]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            openModal('serviceModalOverlay');
        });
    });
    
    // Close buttons
    const closeButtons = {
        'closeVinModal': 'vinModalOverlay',
        'closeHelpModal': 'helpModalOverlay',
        'closeServiceModal': 'serviceModalOverlay'
    };
    
    Object.entries(closeButtons).forEach(([btnId, modalId]) => {
        const btn = document.getElementById(btnId);
        if (btn) {
            btn.addEventListener('click', () => closeModal(modalId));
        }
    });
    
    // Close modals on backdrop click or ESC key
    ['vinModalOverlay', 'helpModalOverlay', 'serviceModalOverlay'].forEach(modalId => {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeModal(modalId);
                }
            });
        }
    });
    
    // Close modals on ESC key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeAllModals();
        }
    });

    // ============================================
    // ORDER DETAILS MODAL
    // ============================================
    const orderModalOverlay = document.getElementById('orderModalOverlay');
    const orderModalContent = document.getElementById('orderModalContent');

    function openOrderModal(orderUrl) {
        if (!orderModalOverlay || !orderModalContent) return;
        orderModalContent.innerHTML = '<div class="order-modal-loading"><div class="spinner-border text-primary" role="status" style="width:2rem;height:2rem;"></div></div>';
        orderModalOverlay.classList.remove('d-none');
        orderModalOverlay.classList.add('d-flex');
        document.body.classList.add('modal-open');

        fetch(orderUrl, { credentials: 'same-origin' })
            .then(r => {
                if (!r.ok) throw new Error(r.status);
                return r.text();
            })
            .then(html => { orderModalContent.innerHTML = html; })
            .catch(() => {
                orderModalContent.innerHTML = '<div class="p-3 text-danger">Error loading order details.</div>';
            });
    }

    function closeOrderModal() {
        if (!orderModalOverlay) return;
        orderModalOverlay.classList.remove('d-flex');
        orderModalOverlay.classList.add('d-none');
        document.body.classList.remove('modal-open');
    }

    document.getElementById('closeOrderModal')?.addEventListener('click', closeOrderModal);

    orderModalOverlay?.addEventListener('click', function(e) {
        if (e.target === orderModalOverlay) closeOrderModal();
    });

    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.btn-view-order');
        if (!btn) return;
        e.preventDefault();
        const orderUrl = btn.dataset.orderUrl;
        if (orderUrl) openOrderModal(orderUrl);
    });

    // Include order modal in ESC close
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && orderModalOverlay && !orderModalOverlay.classList.contains('d-none')) {
            closeOrderModal();
        }
    }, { once: false });
    
    // ============================================
    // WISHLIST BUTTONS
    // ============================================
    
    document.querySelectorAll('.product-wishlist').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            btn.classList.toggle('active');
            console.log('Wishlist toggled');
        });
    });
    
    // ============================================
    // CART BADGE UPDATE
    // ============================================
    
    window.updateCartBadge = function(count) {
        const cartBadge = document.getElementById('cart-badge');
        if (cartBadge) {
            if (count > 0) {
                cartBadge.textContent = count;
                cartBadge.style.display = 'flex';
            } else {
                cartBadge.style.display = 'none';
            }
        }

        const bottomBadge = document.getElementById('bottomCartBadge');
        if (bottomBadge) {
            if (count > 0) {
                bottomBadge.textContent = count;
                bottomBadge.style.display = '';
            } else {
                bottomBadge.style.display = 'none';
            }
        }
    };
    
    console.log('Header initialization complete - ANTI-FLICKER MODE ACTIVE');
});
