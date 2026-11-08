/**
 * SportsBall Core Application Scripts
 * Manages service worker registration, navigation drawer, theme switching,
 * timezone selector, PWA installation prompts, and online/offline connectivity.
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Service Worker Registration
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').catch(err => {
                console.log('ServiceWorker registration optional:', err);
            });
        });
    }

    // 2. Sidebar Drawer / Toggle
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarCloseBtn = document.getElementById('sidebarCloseBtn');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');

    function toggleSidebar() {
        if (window.innerWidth < 992) {
            document.body.classList.toggle('sidebar-open');
        } else {
            document.body.classList.toggle('sidebar-collapsed');
            try {
                localStorage.setItem('sportsball_sidebar_collapsed', document.body.classList.contains('sidebar-collapsed'));
            } catch(e) {}
        }
    }

    function closeMobileSidebar() {
        document.body.classList.remove('sidebar-open');
    }

    if (sidebarToggle) sidebarToggle.addEventListener('click', toggleSidebar);
    if (sidebarCloseBtn) sidebarCloseBtn.addEventListener('click', closeMobileSidebar);
    if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeMobileSidebar);

    // Restore desktop collapsed state
    try {
        if (localStorage.getItem('sportsball_sidebar_collapsed') === 'true' && window.innerWidth >= 992) {
            document.body.classList.add('sidebar-collapsed');
        }
    } catch(e) {}

    // 3. Account / Settings Dropdown
    const accountDropdownBtn = document.getElementById('accountDropdownBtn');
    const accountDropdownMenu = document.getElementById('accountDropdownMenu');

    if (accountDropdownBtn && accountDropdownMenu) {
        accountDropdownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = accountDropdownMenu.classList.toggle('show');
            accountDropdownBtn.setAttribute('aria-expanded', isOpen);
        });

        document.addEventListener('click', (e) => {
            if (!accountDropdownMenu.contains(e.target) && !accountDropdownBtn.contains(e.target)) {
                accountDropdownMenu.classList.remove('show');
                accountDropdownBtn.setAttribute('aria-expanded', 'false');
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && accountDropdownMenu.classList.contains('show')) {
                accountDropdownMenu.classList.remove('show');
                accountDropdownBtn.setAttribute('aria-expanded', 'false');
                accountDropdownBtn.focus();
            }
        });
    }

    // 4. Theme Switcher (Light / Dark / Auto)
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        try {
            localStorage.setItem('sportsball_theme', theme);
        } catch(e) {}
        document.querySelectorAll('.theme-btn').forEach(btn => {
            if (btn.getAttribute('data-theme-val') === theme) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    const currentTheme = localStorage.getItem('sportsball_theme') || 'system';
    applyTheme(currentTheme);

    document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const theme = btn.getAttribute('data-theme-val');
            applyTheme(theme);
        });
    });

    // 5. Timezone Management
    const timezoneSelect = document.getElementById('userTimezoneSelect');
    const timezonePreview = document.getElementById('timezonePreview');

    function syncTimezoneCookie(tz) {
        const actualTz = (tz === 'auto' || !tz) ? (Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC') : tz;
        document.cookie = 'sportsball_timezone=' + encodeURIComponent(actualTz) + ';path=/;max-age=31536000;SameSite=Lax';
        return actualTz;
    }

    function updateTimezonePreview(tz) {
        if (!timezonePreview) return;
        try {
            const actualTz = (tz === 'auto' || !tz) ? Intl.DateTimeFormat().resolvedOptions().timeZone : tz;
            const nowStr = new Intl.DateTimeFormat('en-US', {
                timeZone: actualTz,
                hour: 'numeric',
                minute: 'numeric',
                second: 'numeric',
                timeZoneName: 'short'
            }).format(new Date());
            timezonePreview.textContent = 'Time: ' + nowStr + ' (' + actualTz + ')';
        } catch(e) {
            timezonePreview.textContent = '';
        }
    }

    const initialTz = localStorage.getItem('sportsball_timezone') || 'auto';
    syncTimezoneCookie(initialTz);

    if (timezoneSelect) {
        timezoneSelect.value = initialTz;
        updateTimezonePreview(initialTz);

        timezoneSelect.addEventListener('change', (e) => {
            const selected = e.target.value;
            try {
                localStorage.setItem('sportsball_timezone', selected);
            } catch(err) {}
            syncTimezoneCookie(selected);
            updateTimezonePreview(selected);
        });
    }

    // 6. PWA Installation Handling
    let deferredInstallPrompt = null;
    const pwaInstallBtn = document.getElementById('pwaInstallBtn');
    const pwaInstallLabel = document.getElementById('pwaInstallLabel');
    const pwaInstallHelp = document.getElementById('pwaInstallHelp');

    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredInstallPrompt = e;
        if (pwaInstallLabel) pwaInstallLabel.textContent = '📲 Install SportsBall App';
    });

    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
        if (pwaInstallLabel) pwaInstallLabel.textContent = '✓ App Installed';
        if (pwaInstallBtn) pwaInstallBtn.disabled = true;
    }

    if (pwaInstallBtn) {
        pwaInstallBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (deferredInstallPrompt) {
                deferredInstallPrompt.prompt();
                const { outcome } = await deferredInstallPrompt.userChoice;
                if (outcome === 'accepted') {
                    if (pwaInstallLabel) pwaInstallLabel.textContent = '✓ App Installed';
                }
                deferredInstallPrompt = null;
            } else if (window.matchMedia('(display-mode: standalone)').matches) {
                alert('SportsBall is already installed on this device.');
            } else {
                const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
                if (isIOS) {
                    if (pwaInstallHelp) {
                        pwaInstallHelp.style.display = 'block';
                        pwaInstallHelp.innerHTML = '📲 <strong>To install on iOS</strong>: Tap the <strong>Share</strong> button (square with arrow up) at the bottom of Safari, then choose <strong>"Add to Home Screen"</strong>.';
                    } else {
                        alert('To install on iPhone/iPad: Tap the Share button in Safari and choose "Add to Home Screen".');
                    }
                } else {
                    alert('To install SportsBall: Open your browser menu (three dots) and select "Install App" or "Add to Home screen".');
                }
            }
        });
    }

    // 7. Live Online/Offline Network Status
    const networkStatusDot = document.getElementById('networkStatusDot');
    const networkStatusText = document.getElementById('networkStatusText');

    function updateNetworkStatus() {
        if (!networkStatusDot || !networkStatusText) return;
        if (navigator.onLine) {
            networkStatusDot.className = 'status-dot';
            networkStatusText.textContent = 'Online';
        } else {
            networkStatusDot.className = 'status-dot offline';
            networkStatusText.textContent = 'Offline (Local)';
        }
    }
    window.addEventListener('online', updateNetworkStatus);
    window.addEventListener('offline', updateNetworkStatus);
    updateNetworkStatus();
});
