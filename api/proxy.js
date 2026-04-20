export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).end();

  // Health-check ping — confirm proxy is reachable without calling Anthropic
  if (req.body && req.body._ping) return res.status(200).json({ ok: true });

  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return res.status(500).json({ error: 'ANTHROPIC_API_KEY environment variable is not set' });

  try {
    const body = req.body || {};
    const headers = {
      'Content-Type': 'application/json',
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
    };

    // web_search_20250305 tool type requires the beta header
    const tools = body.tools || [];
    if (tools.some(t => t.type === 'web_search_20250305')) {
      headers['anthropic-beta'] = 'web-search-2025-03-05';
    }

    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    const data = await response.json();
    res.status(response.status).json(data);
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
}
