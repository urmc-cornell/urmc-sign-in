// Small, inline extension of the existing dashboard's Google Sheet importer.
(() => {
    const byId = id => document.getElementById(id);
    const message = text => { byId('member-sheet-message').textContent = text; };
    const node = (tag, text) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; return element; };
    let loaded, rows = [], busy = false;

    function suggested(header, columns) {
        const title = header.toLowerCase().trim().replace(/[?*]/g, '');
        if (['email', 'email address', 'netid', 'net id'].includes(title)) return 'netid';
        if (['name', 'full name'].includes(title)) return 'full_name';
        if (columns.includes(title)) return title;
        if (title.includes('linkedin')) return 'linkedin_url';
        if (title.includes('headshot')) return title.includes('second') ? 'secondary_headshot_url' : 'headshot_url';
        return '';
    }

    async function request(action, data) {
        const response = await fetch('/member_sheet/' + action, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...data, token: loaded?.token})
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not process the sheet.');
        return result;
    }

    async function run(text, task) {
        if (busy) return;
        busy = true;
        showLoading(text);
        try { await task(); } catch (error) { message('Error: ' + error.message); }
        finally { busy = false; byId('loading-overlay').classList.remove('active'); updateCount(); }
    }

    function checks() { return [...byId('member-sheet-rows').querySelectorAll('input[type="checkbox"]')]; }
    function updateCount() {
        const available = checks().filter(check => !check.disabled);
        const count = available.filter(check => check.checked).length;
        byId('member-sheet-update').disabled = busy || !count;
        byId('member-sheet-update').textContent = `Update Selected People (${count})${loaded ? ' — ' + loaded.env.toUpperCase() : ''}`;
        const uniqueCount = new Set(available.map(check => check.dataset.netid)).size;
        byId('member-sheet-all').checked = count > 0 && count === uniqueCount;
        byId('member-sheet-all').indeterminate = count > 0 && count < uniqueCount;
    }

    byId('eboard-sheet').addEventListener('submit', event => {
        event.preventDefault();
        run('Loading sheet headers…', async () => {
            // Hide stale mappings/selections even if loading a different source fails.
            byId('member-sheet-mapping').hidden = true;
            byId('member-sheet-people').hidden = true;
            loaded = await request('load', {sheet_id: byId('member-sheet-id').value,
                tab: byId('member-sheet-tab-label').hidden ? null : byId('member-sheet-tab').value});
            const tabs = byId('member-sheet-tab'); tabs.replaceChildren();
            loaded.tabs.forEach(title => { const option = node('option', title); option.value = title; tabs.append(option); });
            tabs.value = loaded.tab; byId('member-sheet-tab-label').hidden = false;
            const body = byId('member-sheet-columns'); body.replaceChildren();
            const targets = ['netid', ...loaded.columns];
            if (loaded.columns.includes('first_name') && loaded.columns.includes('last_name')) targets.push('full_name');
            const used = new Set();
            loaded.headers.forEach(header => {
                const tr = node('tr'); tr.append(node('td', header || '(unnamed column)'));
                const cell = node('td'), select = node('select');
                select.setAttribute('aria-label', 'Map ' + (header || 'unnamed column'));
                const ignore = node('option', 'Ignore'); ignore.value = ''; select.append(ignore);
                targets.forEach(target => { const option = node('option', target === 'full_name' ? 'Full name → first_name + last_name' : target); option.value = target; select.append(option); });
                const suggestion = suggested(header, targets);
                select.value = used.has(suggestion) ? '' : suggestion;
                if (select.value) used.add(select.value);
                select.onchange = () => { byId('member-sheet-people').hidden = true; };
                cell.append(select); tr.append(cell); body.append(tr);
            });
            byId('member-sheet-mapping').hidden = false;
            message(`Loaded ${loaded.tab}. Map columns, then click Show People. Target: ${loaded.env}.`);
        });
    });

    byId('member-sheet-id').oninput = () => {
        byId('member-sheet-tab-label').hidden = true;
        byId('member-sheet-mapping').hidden = true;
        byId('member-sheet-people').hidden = true;
    };
    byId('member-sheet-tab').onchange = () => {
        byId('member-sheet-mapping').hidden = true;
        byId('member-sheet-people').hidden = true;
        message('Click Load Sheet to load this tab.');
    };

    byId('member-sheet-show').onclick = () => run('Reading mapped people…', async () => {
        const mapping = [...byId('member-sheet-columns').querySelectorAll('select')].map(select => select.value);
        const result = await request('map', {mapping}); rows = result.rows;
        const fields = [...new Set(rows.flatMap(row => Object.keys(row.values)))];
        const head = node('tr'); ['Select', 'Sheet row', 'NetID', ...fields, 'Result'].forEach(title => head.append(node('th', title)));
        byId('member-sheet-head').replaceChildren(head);
        const body = byId('member-sheet-rows'); body.replaceChildren();
        rows.forEach(row => {
            const tr = node('tr'), cell = node('td'), check = node('input'); check.type = 'checkbox';
            check.value = row.index; check.dataset.netid = row.netid; check.disabled = !!row.error;
            check.setAttribute('aria-label', `Select ${row.netid || 'invalid response'} row ${row.sheet_row}`);
            check.onchange = () => { if (check.checked) checks().forEach(other => { if (other !== check && other.dataset.netid === check.dataset.netid) other.checked = false; }); updateCount(); };
            cell.append(check); tr.append(cell, node('td', row.sheet_row), node('td', row.netid));
            fields.forEach(field => tr.append(node('td', Array.isArray(row.values[field]) ? row.values[field].join(', ') : row.values[field] || '—')));
            const status = node('td', row.error || 'Ready'); status.id = `sheet-row-result-${row.index}`; tr.append(status); body.append(tr);
        });
        byId('member-sheet-people').hidden = false;
        message('Select the people to update. Only the mapped, nonblank fields shown below will be saved.');
    });

    byId('member-sheet-all').onchange = event => {
        const latest = new Map(); checks().forEach(check => { check.checked = false; if (!check.disabled) latest.set(check.dataset.netid, check); });
        if (event.target.checked) latest.forEach(check => { check.checked = true; });
        updateCount();
    };
    byId('member-sheet-update').onclick = () => run('Updating selected people…', async () => {
        const selected = checks().filter(check => check.checked && !check.disabled).map(check => Number(check.value));
        const result = await request('apply', {selected});
        result.results.forEach(row => {
            byId(`sheet-row-result-${row.index}`).textContent = row.ok ? 'Updated' : row.error;
            const check = checks().find(check => Number(check.value) === row.index);
            if (row.ok) checks().forEach(other => { if (other.dataset.netid === check.dataset.netid) { other.checked = false; other.disabled = true; } });
        });
        const successes = result.results.filter(row => row.ok).length;
        message(`Updated ${successes} people in ${loaded.env}. ${result.results.length - successes} failed; see their Result column.`);
    });
    toggleEboardSource('sheet');
})();
