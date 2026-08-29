const MOFA_TRAVEL_ALARM_URL =
  "https://apis.data.go.kr/1262000/TravelAlarmService0404/getTravelAlarm0404List";

function trimOrNull(value) {
  if (value === undefined || value === null) {
    return null;
  }
  const trimmed = String(value).trim();
  return trimmed ? trimmed : null;
}

function positiveInteger(value, field, fallback, max) {
  const raw = trimOrNull(value);
  if (!raw) {
    return fallback;
  }
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${field} must be a positive integer.`);
  }
  const parsed = Number(raw);
  if (parsed < 1 || parsed > max) {
    throw new Error(`${field} must be between 1 and ${max}.`);
  }
  return parsed;
}

function normalizeMofaTravelAlarmQuery(query = {}) {
  const normalized = {
    page: positiveInteger(query.page, "page", 1, 100000),
    perPage: positiveInteger(query.perPage ?? query.per_page, "perPage", 10, 100),
    countryNm: trimOrNull(query.countryNm ?? query.country_nm),
    countryIsoAlp2: trimOrNull(query.countryIsoAlp2 ?? query.country_iso_alp2)
  };

  if (normalized.countryIsoAlp2 && !/^[A-Za-z]{2}$/.test(normalized.countryIsoAlp2)) {
    throw new Error("country_iso_alp2 must be a two-letter ISO code.");
  }
  normalized.countryIsoAlp2 = normalized.countryIsoAlp2?.toUpperCase() || null;
  if (normalized.countryNm && normalized.countryIsoAlp2) {
    throw new Error("Provide either country_nm or country_iso_alp2, not both.");
  }
  return Object.fromEntries(
    Object.entries(normalized).filter(([, value]) => value !== null)
  );
}

async function proxyMofaTravelAlarmRequest({
  query,
  serviceKey,
  fetchImpl = global.fetch
}) {
  if (!serviceKey) {
    return {
      statusCode: 503,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({
        error: "upstream_not_configured",
        message: "DATA_GO_KR_API_KEY is not configured on the proxy server."
      })
    };
  }

  const url = new URL(MOFA_TRAVEL_ALARM_URL);
  url.searchParams.set("serviceKey", serviceKey);
  url.searchParams.set("page", String(query.page));
  url.searchParams.set("perPage", String(query.perPage));
  url.searchParams.set("returnType", "JSON");
  if (query.countryNm) {
    url.searchParams.set("cond[country_nm::EQ]", query.countryNm);
  }
  if (query.countryIsoAlp2) {
    url.searchParams.set("cond[country_iso_alp2::EQ]", query.countryIsoAlp2);
  }

  const response = await fetchImpl(url, {
    headers: {
      accept: "application/json",
      "user-agent": "k-skill-proxy/mofa-travel-safety"
    },
    signal: AbortSignal.timeout(20000)
  });
  return {
    statusCode: response.status,
    contentType: response.headers.get("content-type") || "application/json; charset=utf-8",
    body: await response.text()
  };
}

module.exports = {
  MOFA_TRAVEL_ALARM_URL,
  normalizeMofaTravelAlarmQuery,
  proxyMofaTravelAlarmRequest
};
