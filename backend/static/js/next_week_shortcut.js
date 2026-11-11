// Kalendar oynasidagi "Kecha | Bugun | Ertaga" qatoriga "Keyingi hafta"
// (kelayotgan dushanba) tugmasini qo'shadi.
(function () {
    function addNextWeekLink(shortcuts) {
        if (shortcuts.dataset.nextWeek) return;
        const box = shortcuts.closest('[id^="calendarbox"]');
        if (!box) return;
        const num = box.id.replace('calendarbox', '');
        shortcuts.dataset.nextWeek = '1';

        shortcuts.appendChild(document.createTextNode(' | '));
        const link = document.createElement('a');
        link.href = '#';
        link.textContent = 'Keyingi hafta';
        link.addEventListener('click', function (e) {
            e.preventDefault();
            if (!window.DateTimeShortcuts) return;
            const day = DateTimeShortcuts.now().getDay(); // 0 = yakshanba
            const offset = ((8 - day) % 7) || 7;          // keyingi dushanbagacha
            DateTimeShortcuts.handleCalendarQuickLink(num, offset);
        });
        shortcuts.appendChild(link);
    }

    function scan() {
        document.querySelectorAll('.calendar-shortcuts').forEach(addNextWeekLink);
    }

    document.addEventListener('DOMContentLoaded', function () {
        scan();
        new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
    });
    window.addEventListener('load', scan);
})();
