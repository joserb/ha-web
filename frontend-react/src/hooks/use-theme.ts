import { useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";
const storageKey = "ha-web.theme";

function storedPreference(): ThemePreference {
  const value = localStorage.getItem(storageKey);
  return value === "light" || value === "dark" ? value : "system";
}

function applyTheme(preference: ThemePreference) {
  const systemDark = matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle(
    "dark",
    preference === "dark" || (preference === "system" && systemDark),
  );
  document.documentElement.dataset.theme = preference;
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemePreference>(storedPreference);

  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(theme);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [theme]);

  function setTheme(value: ThemePreference) {
    localStorage.setItem(storageKey, value);
    setThemeState(value);
  }

  return { theme, setTheme };
}
