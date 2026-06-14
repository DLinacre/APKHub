import type { AppRecord } from "../data/seedData";

function tokenize(s: string): string[] {
  return (s || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

export class SearchIndex {
  private map = new Map<string, Set<number>>();

  build(apps: AppRecord[]) {
    this.map.clear();
    apps.forEach((app, i) => {
      const text = [
        app.name,
        app.owner,
        app.description,
        ...(app.topics || []),
        app.language,
        app.category,
      ].join(" ");
      const toks = tokenize(text);
      const seen = new Set(toks);
      seen.forEach((t) => {
        if (!this.map.has(t)) this.map.set(t, new Set());
        this.map.get(t)!.add(i);
      });
    });
  }

  search(q: string, apps: AppRecord[]): number[] {
    const terms = tokenize(q);
    if (!terms.length) return apps.map((_, i) => i);

    let result: Set<number> | null = null;

    terms.forEach((term, ti) => {
      const isLast = ti === terms.length - 1;
      let postings = this.map.get(term);

      if (!postings && isLast) {
        postings = new Set();
        for (const [tok, idx] of this.map) {
          if (tok.startsWith(term)) {
            for (const x of idx) postings.add(x);
          }
        }
      }

      if (!postings) postings = new Set();

      result =
        result === null
          ? new Set(postings)
          : new Set([...result].filter((x) => postings!.has(x)));
    });

    const ranked = [...(result || [])].sort((a, b) => {
      const score = (app: AppRecord) => {
        const n = (app.name || "").toLowerCase();
        let s = 0;
        terms.forEach((t) => {
          if (n.startsWith(t)) s += 3;
          else if (n.includes(t)) s += 1;
        });
        return s + Math.log10((app.stars || 0) + 1) * 0.5;
      };
      return score(apps[b]) - score(apps[a]);
    });

    return ranked;
  }
}
