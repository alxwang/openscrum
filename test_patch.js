const fetch = require('node-fetch') || fetch;
async function go() {
    const res = await fetch('http://127.0.0.1:8000/sessions/ses_0000009c231e890b8Aniw2bOnR', {
        method: 'PATCH',
        body: JSON.stringify({ mode: 'edit' }),
        headers: { 'Content-Type': 'application/json' }
    });
    const text = await res.text();
    console.log(`STATUS: ${res.status}`);
    console.log(`BODY: ${text}`);
}
go().catch(console.error);
