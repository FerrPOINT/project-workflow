(() => {
  if (typeof window === "undefined") return;
  const existing = window.PdlcThemePreference || window.SdlcThemePreference;
  if (existing) {
    window.PdlcThemePreference = window.SdlcThemePreference = existing;
    return;
  }
  // While legacy builds are supported, their cookie remains authoritative.
  // Dual writes keep both generations consistent without a second preference store.
  const cookieNames = ["sdlc-ui-theme", "pdlc-ui-theme"];
  const eventNames = ["sdlc-ui-theme-change", "pdlc-ui-theme-change"];
  const valid = (value) => ["dark", "gray", "light"].includes(value);
  let sessionTheme;
  let platformDefault = null;
  let notificationVersion = 0;
  let emitting = false;

  function shared() {
    try {
      for (const name of cookieNames) {
        const cookie = document.cookie
          .split(";")
          .map((value) => value.trim())
          .find((value) => value.startsWith(name + "="));
        const value = cookie?.slice(name.length + 1);
        if (valid(value)) return value;
      }
    } catch {
      /* Cookies may be blocked. */
    }
  }

  function read(legacyKey = "theme", fallback = platformDefault ?? "dark") {
    if (valid(sessionTheme)) return sessionTheme;
    const preference = shared();
    if (preference) return preference;
    try {
      const value = localStorage.getItem(legacyKey);
      if (valid(value)) return value;
    } catch {
      /* Keep theme controls usable without storage. */
    }
    return valid(fallback) ? fallback : "dark";
  }

  function setPlatformDefault(value) {
    const next = valid(value) ? value : null;
    if (platformDefault === next) return;
    platformDefault = next;
    // Use the existing notification channel without persisting or replacing a choice.
    window.dispatchEvent(new Event("pdlc-ui-theme-change"));
  }

  function set(value, legacyKey = "theme") {
    if (!valid(value)) return;
    sessionTheme = value;
    try {
      for (const name of cookieNames)
        document.cookie =
          name +
          "=" +
          value +
          "; Path=/; Max-Age=31536000; SameSite=Lax" +
          (location.protocol === "https:" ? "; Secure" : "");
    } catch {
      /* The current window retains the selection. */
    }
    if (shared() === value) sessionTheme = undefined;
    try {
      localStorage.setItem(legacyKey, value);
    } catch {
      /* The shared cookie remains authoritative. */
    }
    notificationVersion++;
    emitting = true;
    try {
      for (const name of eventNames) window.dispatchEvent(new Event(name));
    } finally {
      emitting = false;
    }
  }

  function subscribe(listener) {
    let delivered = -1;
    const preferenceChanged = () => {
      if (emitting && delivered === notificationVersion) return;
      delivered = notificationVersion;
      listener();
    };
    const change = (event) => {
      if (
        [...(event.changed || []), ...(event.deleted || [])].some((cookie) =>
          cookieNames.includes(cookie.name),
        )
      ) {
        sessionTheme = undefined;
        listener();
      }
    };
    const visible = () => {
      if (document.visibilityState === "visible") listener();
    };
    window.cookieStore?.addEventListener("change", change);
    for (const name of eventNames)
      window.addEventListener(name, preferenceChanged);
    window.addEventListener("focus", listener);
    window.addEventListener("pageshow", listener);
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.cookieStore?.removeEventListener("change", change);
      for (const name of eventNames)
        window.removeEventListener(name, preferenceChanged);
      window.removeEventListener("focus", listener);
      window.removeEventListener("pageshow", listener);
      document.removeEventListener("visibilitychange", visible);
    };
  }

  window.PdlcThemePreference = window.SdlcThemePreference = {
    read,
    set,
    setPlatformDefault,
    subscribe,
  };
})();
