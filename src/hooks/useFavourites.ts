import { useState, useCallback } from "react";

const FAV_KEY = "apkhub.favs.v1";

function loadFavs(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(FAV_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function saveFavs(favs: Set<string>) {
  localStorage.setItem(FAV_KEY, JSON.stringify([...favs]));
}

export function useFavourites() {
  const [favs, setFavs] = useState<Set<string>>(loadFavs);

  const toggle = useCallback((slug: string) => {
    setFavs((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      saveFavs(next);
      return next;
    });
  }, []);

  const isFav = useCallback((slug: string) => favs.has(slug), [favs]);

  return { favs, toggle, isFav, count: favs.size };
}
