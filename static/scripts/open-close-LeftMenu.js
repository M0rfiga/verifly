const menuOpenBtn = document.getElementById('open-left-menu');
const menuCloseBtn = document.getElementById('close-left-menu');
const leftMenu = document.getElementById('left-menu');

if (menuOpenBtn && leftMenu) {
    menuOpenBtn.addEventListener('click', () => {
        leftMenu.classList.toggle('active');
    });
}

if (menuCloseBtn && leftMenu) {
    menuCloseBtn.addEventListener('click', () => {
        leftMenu.classList.remove('active');
    });
}