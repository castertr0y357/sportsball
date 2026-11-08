/**
 * Lineup & Rotation Builder - Interactive Client Scripts
 * Handles batting order drag/drop reordering and defensive rotation table sync.
 */
document.addEventListener('DOMContentLoaded', () => {
function moveLineupRow(btn, direction) {
    const row = btn.closest('tr');
    const tbody = row.parentNode;
    if (direction === -1 && row.previousElementSibling) {
        tbody.insertBefore(row, row.previousElementSibling);
    } else if (direction === 1 && row.nextElementSibling) {
        tbody.insertBefore(row.nextElementSibling, row);
    }
    // Reindex order inputs
    const inputs = tbody.querySelectorAll('.lineup-order-input');
    inputs.forEach((input, index) => {
        input.value = index + 1;
    });
    // Brief visual flash to confirm move
    row.style.transition = 'background-color 0.2s';
    const oldBg = row.style.backgroundColor;
    row.style.backgroundColor = 'rgba(59, 130, 246, 0.15)';
    setTimeout(() => { row.style.backgroundColor = oldBg; }, 350);
}

function copyLineupCard() {
    const rows = document.querySelectorAll('#lineupTable tbody tr');
    let text = "{{ team.name }} Lineup vs {{ opponent.name }}\n";
    text += "Date: {{ game.date|date:'D, M d @ g:i A' }} | {{ game.location }}\n";
    text += "--------------------------------------\n";

    let activeCount = 0;
    rows.forEach(row => {
        const orderInput = row.querySelector('.lineup-order-input');
        const nameEl = row.querySelector('strong');
        const posInput = row.querySelector('input[name^="position_"]');
        const presentBox = row.querySelector('input[name^="present_"]');

        if (presentBox && presentBox.checked && nameEl) {
            activeCount++;
            const order = orderInput ? orderInput.value : activeCount;
            const name = nameEl.innerText.trim();
            const pos = posInput && posInput.value.trim() ? ` (${posInput.value.trim()})` : '';
            text += `${order}. ${name}${pos}\n`;
        }
    });

    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            alert("📋 Lineup card copied to clipboard!\nYou can paste it directly into your team group chat or WhatsApp.");
        }).catch(() => {
            prompt("Copy lineup card:", text);
        });
    } else {
        prompt("Copy lineup card:", text);
    }
}


function copyWhatsAppReminder() {
    const text = "⚾ Hey team! Reminder for our upcoming game: {{ team.name }} vs {{ opponent.name }} on {{ game.date|date:'l, M d @ g:i A' }} at {{ game.location }}. Please confirm if you can make it here: " + window.location.origin + "{% url 'game_detail' game.id %}";
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            alert("✓ Copied game reminder to clipboard! Paste it into your team chat or WhatsApp group.");
        });
    } else {
        prompt("Copy this reminder to send to your team:", text);
    }
}

});
