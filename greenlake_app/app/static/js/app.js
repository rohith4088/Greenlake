document.addEventListener('DOMContentLoaded', () => {
    const navItems = document.querySelectorAll('.nav-item');
    const contentArea = document.getElementById('contentArea');
    const pageTitle = document.getElementById('pageTitle');
    const configModal = document.getElementById('configModal');
    const openConfigBtn = document.getElementById('openConfig');
    const closeConfigBtn = document.querySelector('.close');
    const configForm = document.getElementById('configForm');

    // Navigation
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            if (item.dataset.target) {
                e.preventDefault();
                navItems.forEach(nav => nav.classList.remove('active'));
                item.classList.add('active');
                const target = item.dataset.target;
                loadContent(target);
            }
        });
    });

    // Content Loading
    async function loadContent(target) {
        contentArea.innerHTML = '<p>Loading...</p>';
        pageTitle.innerText = target.charAt(0).toUpperCase() + target.slice(1);

        try {
            if (target === 'dashboard') {
                contentArea.innerHTML = `
                    <div class="welcome-card">
                        <h3>Dashboard Overview</h3>
                        <p>Select Devices, Subscriptions or Users to view data.</p>
                    </div>
                `;
            } else if (target === 'devices') {
                const res = await fetch('/api/devices');
                if (!res.ok) throw new Error('Failed to fetch devices');
                const data = await res.json();
                renderTable(data, ['serialNumber', 'model', 'status', 'sub_status', 'sub_end']);
            } else if (target === 'subscriptions') {
                const res = await fetch('/api/subscriptions');
                if (!res.ok) throw new Error('Failed to fetch subscriptions');
                const data = await res.json();
                renderTable(data, ['key', 'tier', 'status', 'start_date', 'end_date']);
            } else if (target === 'users') {
                const res = await fetch('/api/users');
                if (!res.ok) throw new Error('Failed to fetch users');
                const data = await res.json();
                renderTable(data, ['username', 'email', 'userStatus', 'role']);
            }
        } catch (error) {
            contentArea.innerHTML = `<div class="card" style="border-color: red; color: red;">Error: ${error.message}. <br>Please check your configuration.</div>`;
        }
    }

    // Helper to render tables
    function renderTable(data, columns) {
        if (!data || data.length === 0) {
            contentArea.innerHTML = '<p>No data found.</p>';
            return;
        }

        let table = '<div class="card"><table><thead><tr>';
        columns.forEach(col => {
            table += `<th>${col.toUpperCase()}</th>`;
        });
        table += '</tr></thead><tbody>';

        data.forEach(row => {
            table += '<tr>';
            columns.forEach(col => {
                // handle nested objects if necessary, simple for now
                table += `<td>${row[col] || '-'}</td>`;
            });
            table += '</tr>';
        });

        table += '</tbody></table></div>';
        contentArea.innerHTML = table;
    }

    // Modal Handling
    openConfigBtn.onclick = () => configModal.style.display = 'block';
    closeConfigBtn.onclick = () => configModal.style.display = 'none';
    window.onclick = (event) => {
        if (event.target == configModal) {
            configModal.style.display = 'none';
        }
    }

});
