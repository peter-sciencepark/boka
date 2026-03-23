const ALLOWED_USERS = ["peter", "alexandra"];
const ALLOWED_ORIGIN = "https://peter-sciencepark.github.io";

// Rate limiting: max failed PIN attempts per IP
const MAX_FAILURES = 5;
const LOCKOUT_SECONDS = 900; // 15 min

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin === ALLOWED_ORIGIN ? ALLOWED_ORIGIN : "",
    "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Pin",
  };
}

function json(data, status = 200, origin = "") {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
  });
}

async function checkRateLimit(ip, kv) {
  const key = `fail:${ip}`;
  const val = await kv.get(key);
  return val ? parseInt(val, 10) >= MAX_FAILURES : false;
}

async function recordFailure(ip, kv) {
  const key = `fail:${ip}`;
  const val = await kv.get(key);
  const failures = val ? parseInt(val, 10) : 0;
  await kv.put(key, String(failures + 1), { expirationTtl: LOCKOUT_SECONDS });
}

async function clearFailures(ip, kv) {
  await kv.delete(`fail:${ip}`);
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";

    // Rate limit check
    const blocked = await checkRateLimit(ip, env.RATE_LIMIT);
    if (blocked) {
      return json({ error: "För många misslyckade försök. Vänta 15 minuter." }, 429, origin);
    }

    // PIN auth
    const pin = request.headers.get("X-Pin") || "";
    if (!pin || pin !== env.PIN) {
      await recordFailure(ip, env.RATE_LIMIT);
      return json({ error: "Fel PIN-kod" }, 401, origin);
    }
    await clearFailures(ip, env.RATE_LIMIT);

    // GET /activities
    if (path === "/activities" && request.method === "GET") {
      const raw = await env.DATA.get("activities");
      const activities = raw ? JSON.parse(raw) : [];
      return json({ activities }, 200, origin);
    }

    // PUT /activities
    if (path === "/activities" && request.method === "PUT") {
      const body = await request.json();
      if (!Array.isArray(body.activities)) {
        return json({ error: "Ogiltigt format" }, 400, origin);
      }
      await env.DATA.put("activities", JSON.stringify(body.activities));
      return json({ ok: true }, 200, origin);
    }

    // Validate user param for bookings/schedule
    function getUser() {
      const user = url.searchParams.get("user");
      if (!user || !ALLOWED_USERS.includes(user)) return null;
      return user;
    }

    // GET /bookings?user=xxx
    if (path === "/bookings" && request.method === "GET") {
      const user = getUser();
      if (!user) return json({ error: "Ogiltig användare" }, 400, origin);
      const raw = await env.DATA.get(`bookings:${user}`);
      const bookings = raw ? JSON.parse(raw) : [];
      return json({ bookings }, 200, origin);
    }

    // PUT /bookings?user=xxx
    if (path === "/bookings" && request.method === "PUT") {
      const user = getUser();
      if (!user) return json({ error: "Ogiltig användare" }, 400, origin);
      const body = await request.json();
      if (!Array.isArray(body.bookings)) {
        return json({ error: "Ogiltigt format" }, 400, origin);
      }
      await env.DATA.put(`bookings:${user}`, JSON.stringify(body.bookings));
      return json({ ok: true }, 200, origin);
    }

    // /schedule endpoints
    if (path === "/schedule") {
      const user = getUser();
      if (!user) return json({ error: "Ogiltig användare" }, 400, origin);

      if (request.method === "GET") {
        const raw = await env.DATA.get(`schedule:${user}`);
        const schedule = raw ? JSON.parse(raw) : [];
        return json({ schedule }, 200, origin);
      }

      if (request.method === "PUT") {
        const body = await request.json();
        if (!Array.isArray(body.schedule)) {
          return json({ error: "Ogiltigt format" }, 400, origin);
        }
        await env.DATA.put(`schedule:${user}`, JSON.stringify(body.schedule));
        return json({ ok: true }, 200, origin);
      }
    }

    return json({ error: "Not found" }, 404, origin);
  },
};
