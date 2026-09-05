"use client";

import { use, useEffect, useState } from "react";
import { fetchPublicPortfolio, type PublicPortfolio } from "@/lib/settings-api";

export default function PublicPortfolioPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [portfolio, setPortfolio] = useState<PublicPortfolio | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    void fetchPublicPortfolio(slug)
      .then((data) => { if (!cancelled) setPortfolio(data); })
      .catch(() => { if (!cancelled) setPortfolio(null); });
    return () => { cancelled = true; };
  }, [slug]);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        color: "var(--text)",
        display: "flex",
        justifyContent: "center",
        padding: "48px 20px",
      }}
    >
      <div style={{ width: "100%", maxWidth: "680px" }}>
        {portfolio === undefined ? (
          <p style={{ color: "var(--text-secondary)" }}>Loading…</p>
        ) : portfolio === null ? (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <h1 style={{ fontSize: "1.25rem", marginBottom: "8px" }}>This portfolio isn&apos;t public</h1>
            <p style={{ color: "var(--text-secondary)" }}>
              Either it doesn&apos;t exist, or its owner hasn&apos;t made it public yet.
            </p>
          </div>
        ) : (
          <article>
            <header style={{ marginBottom: "32px" }}>
              <h1 style={{ fontSize: "2rem", margin: "0 0 4px" }}>{portfolio.name || "Career profile"}</h1>
              {portfolio.headline ? (
                <p style={{ fontSize: "1.05rem", color: "var(--accent)", margin: "0 0 4px" }}>{portfolio.headline}</p>
              ) : null}
              <p style={{ color: "var(--text-secondary)", margin: 0, fontSize: "0.9rem" }}>
                {[portfolio.location, portfolio.yearsExperience ? `${portfolio.yearsExperience} yrs experience` : null]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </header>

            {portfolio.skills.length > 0 ? (
              <section style={{ marginBottom: "32px" }}>
                <h2 style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-secondary)", marginBottom: "10px" }}>
                  Skills
                </h2>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                  {portfolio.skills.map((skill) => (
                    <span
                      key={skill}
                      style={{
                        padding: "4px 10px",
                        borderRadius: "999px",
                        background: "var(--card)",
                        border: "1px solid var(--border)",
                        fontSize: "0.8rem",
                      }}
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </section>
            ) : null}

            {portfolio.experience.length > 0 ? (
              <section style={{ marginBottom: "32px" }}>
                <h2 style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-secondary)", marginBottom: "10px" }}>
                  Experience
                </h2>
                <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                  {portfolio.experience.map((item, i) => (
                    <div key={`${item.company}-${i}`} style={{ display: "flex", justifyContent: "space-between", gap: "12px", borderBottom: "1px solid var(--border)", paddingBottom: "10px" }}>
                      <div>
                        <strong>{item.title}</strong>
                        <div style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>{item.company}</div>
                      </div>
                      <span style={{ color: "var(--text-secondary)", fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                        {item.startDate}{item.endDate ? ` – ${item.endDate}` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {portfolio.accomplishments.length > 0 ? (
              <section>
                <h2 style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-secondary)", marginBottom: "10px" }}>
                  Selected work
                </h2>
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {portfolio.accomplishments.map((acc, i) => (
                    <div
                      key={`${acc.company}-${i}`}
                      style={{ padding: "14px 16px", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "12px" }}
                    >
                      <div style={{ fontWeight: 600 }}>{acc.project || acc.company}</div>
                      {acc.company && acc.project ? (
                        <div style={{ color: "var(--text-secondary)", fontSize: "0.8rem", marginBottom: "6px" }}>{acc.company}</div>
                      ) : null}
                      {acc.summary ? <p style={{ margin: 0, color: "var(--text-secondary)" }}>{acc.summary}</p> : null}
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </article>
        )}
      </div>
    </main>
  );
}
