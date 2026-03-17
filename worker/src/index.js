const REPO_OWNER = "peter-sciencepark";
const REPO_NAME = "boka";
const ALLOWED_USERS = ["peter", "alexandra"];
const ALLOWED_ORIGIN = "https://peter-sciencepark.github.io";

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

function decodeGithubContent(base64Content) {
  const raw = atob(base64Content.replace(/\n/g, ""));
  const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // PIN auth (all endpoints)
    const pin = request.headers.get("X-Pin") || "";
    if (!pin || pin !== env.PIN) {
      return json({ error: "Fel PIN-kod" }, 401, origin);
    }

    const githubHeaders = {
      Authorization: `token ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github.v3+json",
      "User-Agent": "friskis-schedule-worker",
    };

    // GET /activities — return available activities from config/activities.json
    if (path === "/activities" && request.method === "GET") {
      const githubUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/config/activities.json`;
      const res = await fetch(githubUrl, { headers: githubHeaders });
      if (!res.ok) {
        return json({ activities: [] }, 200, origin);
      }
      const data = await res.json();
      const content = decodeGithubContent(data.content);
      const activities = JSON.parse(content);
      return json({ activities }, 200, origin);
    }

    // /schedule endpoints
    if (path === "/schedule") {
      const user = url.searchParams.get("user");
      if (!user || !ALLOWED_USERS.includes(user)) {
        return json({ error: "Ogiltig användare" }, 400, origin);
      }

      const filePath = `config/${user}.json`;
      const githubUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents/${filePath}`;

      if (request.method === "GET") {
        const res = await fetch(githubUrl, { headers: githubHeaders });
        if (!res.ok) {
          return json({ error: "Kunde inte hämta schema" }, 502, origin);
        }
        const data = await res.json();
        const content = decodeGithubContent(data.content);
        const schedule = JSON.parse(content);
        return json({ schedule, sha: data.sha }, 200, origin);
      }

      if (request.method === "PUT") {
        const body = await request.json();
        if (!Array.isArray(body.schedule) || !body.sha) {
          return json({ error: "Ogiltigt format" }, 400, origin);
        }

        const content = btoa(unescape(encodeURIComponent(
          JSON.stringify(body.schedule, null, 2) + "\n"
        )));

        const res = await fetch(githubUrl, {
          method: "PUT",
          headers: { ...githubHeaders, "Content-Type": "application/json" },
          body: JSON.stringify({
            message: `Uppdatera schema för ${user}`,
            content,
            sha: body.sha,
          }),
        });

        if (!res.ok) {
          const err = await res.json();
          if (res.status === 409) {
            return json({ error: "Schemat ändrades av någon annan. Ladda om sidan." }, 409, origin);
          }
          return json({ error: "Kunde inte spara: " + (err.message || res.status) }, 502, origin);
        }

        const result = await res.json();
        return json({ ok: true, sha: result.content.sha }, 200, origin);
      }
    }

    return json({ error: "Not found" }, 404, origin);
  },
};
