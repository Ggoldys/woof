let lastUpdateTime = null;

document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM fully loaded and script running");
    fetchData();
    setInterval(fetchData, 10000); // каждые 10 секунд
});

function fetchData() {
    console.log("⏰ fetchData called at", new Date().toLocaleTimeString());

    const el = document.getElementById('lastUpdated');
   // if (el) el.textContent = "Updating data...";

    fetch('/api/summary')
        .then(response => {
            if (!response.ok) throw new Error('Network error');
            return response.json();
        })
        .then(data => {
            console.log("✅ Data received:", data);
            updateUI(data);
            lastUpdateTime = new Date();
            updateLastUpdatedTime();
        })
        .catch(error => {
            console.error('❌ Error in fetchData:', error);
            const el = document.getElementById('lastUpdated');
            if (el) el.textContent =
                `Error updating data (last success: ${lastUpdateTime ? lastUpdateTime.toLocaleString() : 'never'})`;
        });
}

function updateLastUpdatedTime() {
    if (!lastUpdateTime) return;

    const options = {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    };

    document.getElementById('lastUpdated').textContent =
        `Last updated: ${lastUpdateTime.toLocaleString(undefined, options)}`;
}

function updateUI(data) {
    // Обработка обычных билетов
    const regularSummary = {};
    let regularTotal = 0;

    data.ticket_transfers.forEach(transfer => {
        if (!regularSummary[transfer.sender]) {
            regularSummary[transfer.sender] = 0;
        }
        regularSummary[transfer.sender] += transfer.amount;
        regularTotal += transfer.amount;
    });

    const sortedRegular = Object.entries(regularSummary)
        .sort((a, b) => b[1] - a[1]);

    // Обработка HODL билетов
    let hodlTotal = 0;
    const hodlTickets = data.hodl_tickets || {}; // Добавляем проверку на существование

    const sortedHodl = Object.entries(hodlTickets)
        .sort((a, b) => b[1] - a[1]);

    // Правильно считаем общее количество HODL билетов
    sortedHodl.forEach(([_, tickets]) => {
        hodlTotal += tickets;
    });

    // Обновляем суммы (добавляем проверки)
    document.getElementById('regularTotal').textContent = regularTotal > 0 ? regularTotal.toString() : "0";
    document.getElementById('hodlTotal').textContent = hodlTotal > 0 ? hodlTotal.toString() : "0";

    // Заполняем таблицы
    fillTable('#regularTable tbody', sortedRegular, true);
    fillTable('#hodlTable tbody', sortedHodl, false);
}

// Новая функция для заполнения таблиц
function fillTable(selector, data, isRegular) {
    const table = document.querySelector(selector);
    table.innerHTML = '';

    data.forEach(([address, tickets]) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${address}</td>
            <td>${isRegular ? tickets.toString() : tickets}</td>
        `;
        table.appendChild(row);
    });
}