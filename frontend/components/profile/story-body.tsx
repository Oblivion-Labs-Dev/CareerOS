/** Render a corpus story's body as readable prose.
 *
 * The bodies were written as Markdown in a chat window, so they arrive full of
 * `##` headings, `>` quote markers and `**bold**` runs. Printed verbatim that
 * punctuation is most of what the eye lands on, and a seventeen-thousand
 * character story becomes unreadable — which is the whole reason the corpus
 * was never shown anywhere.
 *
 * This is deliberately a small subset of Markdown rather than a dependency:
 * headings, quotes, rules, bullets, bold and inline code are everything the
 * corpus actually uses (checked against all 63 bodies), and rendering to React
 * nodes rather than to HTML means no `dangerouslySetInnerHTML` and so no way
 * for story text to inject markup.
 */
import type { ReactNode } from "react";

/** Split one line into bold / code / plain runs. */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    if (match[1] !== undefined) nodes.push(<strong key={`${keyPrefix}-b${index}`}>{match[1]}</strong>);
    else nodes.push(<code key={`${keyPrefix}-c${index}`}>{match[2]}</code>);
    cursor = match.index + match[0].length;
    index += 1;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

type Styles = Record<string, string>;

export function renderStoryBody(body: string, styles: Styles): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = body.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];
  let quote: string[] = [];
  let bullets: string[] = [];
  let key = 0;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(" ").trim();
    paragraph = [];
    if (text) out.push(<p key={`p${key++}`} className={styles.bodyParagraph}>{inline(text, `p${key}`)}</p>);
  };
  const flushQuote = () => {
    if (quote.length === 0) return;
    // Quote markers in these stories wrap the spoken STAR answer, which is one
    // block of speech rather than several one-line quotations; blank marker
    // lines inside it are paragraph breaks, not separate quotes.
    const paragraphs = quote.join("\n").split(/\n\s*\n/).map((part) => part.replace(/\s+/g, " ").trim()).filter(Boolean);
    quote = [];
    if (paragraphs.length === 0) return;
    out.push(
      <blockquote key={`q${key++}`} className={styles.bodyQuote}>
        {paragraphs.map((part, index) => <p key={index}>{inline(part, `q${key}-${index}`)}</p>)}
      </blockquote>,
    );
  };
  const flushBullets = () => {
    if (bullets.length === 0) return;
    const items = [...bullets];
    bullets = [];
    out.push(
      <ul key={`u${key++}`} className={styles.bodyList}>
        {items.map((item, index) => <li key={index}>{inline(item, `u${key}-${index}`)}</li>)}
      </ul>,
    );
  };
  const flushAll = () => {
    flushParagraph();
    flushQuote();
    flushBullets();
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    const quoted = /^>\s?(.*)$/.exec(line);
    const bullet = /^\s*[-*•]\s+(.+)$/.exec(line);

    if (heading) {
      flushAll();
      const level = Math.min(heading[1].length, 3);
      const text = heading[2].trim();
      if (text) {
        out.push(
          <p key={`h${key++}`} className={level === 1 ? styles.bodyH1 : level === 2 ? styles.bodyH2 : styles.bodyH3}>
            {inline(text, `h${key}`)}
          </p>,
        );
      }
      continue;
    }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushAll();
      out.push(<hr key={`r${key++}`} className={styles.bodyRule} />);
      continue;
    }
    if (quoted) {
      flushParagraph();
      flushBullets();
      quote.push(quoted[1]);
      continue;
    }
    if (bullet) {
      flushParagraph();
      flushQuote();
      bullets.push(bullet[1].trim());
      continue;
    }
    if (!line.trim()) {
      // A blank line ends a paragraph or list, but not a quote: quoted blocks
      // in these stories separate their own paragraphs with empty "> " lines.
      flushParagraph();
      flushBullets();
      continue;
    }
    flushQuote();
    paragraph.push(line.trim());
  }
  flushAll();
  return out;
}

/** Strip the conversational preamble some bodies begin with.
 *
 * Several stories were pasted into a chat and still carry the instruction that
 * came with them ("I will paste you everything I worked on … keep everything
 * but in better words -") ahead of the first heading. It is not part of the
 * story and reads as nonsense at the top of the page, so it is dropped when
 * the body clearly starts somewhere later.
 */
export function trimStoryPreamble(body: string): string {
  const firstHeading = body.search(/(^|\n)#{1,3}\s/);
  if (firstHeading <= 0) return body;
  const preamble = body.slice(0, firstHeading);
  // Only a short, lower-case-ish lead-in is treated as chatter; a genuine
  // opening paragraph before the first heading is left alone.
  if (preamble.length > 400 || !/\b(paste|structure this|keep ev|i'?ll|i will)\b/i.test(preamble)) return body;
  return body.slice(firstHeading).replace(/^\n+/, "");
}
