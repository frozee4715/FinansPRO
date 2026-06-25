// Flash mesajlarını 4 saniye sonra otomatik kapat
document.addEventListener('DOMContentLoaded', function () {
    const box = document.getElementById('flashes');
    if (box) {
        setTimeout(function () {
            Array.from(box.children).forEach(function (el) {
                el.style.transition = 'opacity .4s, transform .4s';
                el.style.opacity = '0';
                el.style.transform = 'translateX(20px)';
            });
            setTimeout(function () { box.remove(); }, 450);
        }, 4000);
    }

    // Silme işlemleri için onay
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        el.addEventListener('submit', function (e) {
            if (!confirm(el.getAttribute('data-confirm'))) e.preventDefault();
        });
    });

    // Karanlık / açık mod değiştirme
    const toggle = document.getElementById('themeToggle');
    if (toggle) {
        const sync = function () {
            const dark = document.documentElement.getAttribute('data-theme') === 'dark';
            toggle.textContent = dark ? '☀️' : '🌙';
            if (window.twemoji) twemoji.parse(toggle, { folder: 'svg', ext: '.svg' });
        };
        sync();
        toggle.addEventListener('click', function () {
            const dark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (dark) {
                document.documentElement.removeAttribute('data-theme');
                try { localStorage.setItem('theme', 'light'); } catch (e) {}
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                try { localStorage.setItem('theme', 'dark'); } catch (e) {}
            }
            sync();
        });
    }
});
