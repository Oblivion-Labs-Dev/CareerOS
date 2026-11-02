/* eslint-disable no-undef -- URL is provided by the Node.js test environment. */

import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import {
  notifyCompletedChange,
  PrecisionTaskCard,
  resolveTaskCardFloatTiming,
  resolveTaskCardStatus,
  type PrecisionTaskCardProps,
} from './precision-task-card';

const sampleProps: PrecisionTaskCardProps = {
  id: 'task-card-prototype',
  title: 'Complete system design exercise',
  completed: false,
  energy: 'medium',
  rarity: 'rare',
  onCompletedChange: () => undefined,
};

const componentStyles = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');

function renderCard(overrides: Partial<PrecisionTaskCardProps> = {}) {
  return renderToStaticMarkup(
    createElement(PrecisionTaskCard, {
      ...sampleProps,
      ...overrides,
    }),
  );
}

describe('PrecisionTaskCard', () => {
  it('renders the exact task title', () => {
    expect(renderCard()).toContain('Complete system design exercise');
  });

  it('shows the Medium energy text', () => {
    const markup = renderCard();

    expect(markup).toContain('>MEDIUM</span>');
    expect(markup).toContain('aria-label="MEDIUM energy, 2 of 3 marks"');
  });

  it('shows two of three energy marks filled', () => {
    const markup = renderCard();

    expect(markup.match(/class="precision-task-card__energy-mark"/g)).toHaveLength(3);
    expect(markup.match(/data-filled="true"/g)).toHaveLength(2);
    expect(markup.match(/data-filled="false"/g)).toHaveLength(1);
  });

  it('exposes a native checkbox', () => {
    expect(renderCard()).toContain('type="checkbox"');
  });

  it('uses the task title in the checkbox accessible label', () => {
    expect(renderCard()).toContain(
      'aria-label="Mark &quot;Complete system design exercise&quot; complete"',
    );
  });

  it('fires the completion callback once with the correct value', () => {
    const onCompletedChange = vi.fn();

    notifyCompletedChange(true, onCompletedChange);

    expect(onCompletedChange).toHaveBeenCalledTimes(1);
    expect(onCompletedChange).toHaveBeenCalledWith(true);
  });

  it('renders the completed state', () => {
    const markup = renderCard({ completed: true });

    expect(markup).toContain('data-completed="true"');
    expect(markup).toContain('checked=""');
    expect(markup).toContain('precision-task-card__completion-liquid');
  });

  it('renders a thick neon-green liquid solution with bubbles when completed', () => {
    const markup = renderCard({ completed: true });

    expect(markup.match(/class="precision-task-card__liquid-bubble"/g)).toHaveLength(7);
    expect(componentStyles).toContain('height: 63%');
    expect(componentStyles).toContain('precision-task-card-neon-liquid-wave');
    expect(componentStyles).toContain('precision-task-card-neon-liquid-caustics');
    expect(componentStyles).toContain('precision-task-card-neon-liquid-bubble');
    expect(componentStyles).toContain('rgba(42, 247, 122, 0.78)');
    expect(componentStyles.lastIndexOf('rgba(42, 247, 122, 0.78)')).toBeGreaterThan(
      componentStyles.lastIndexOf('rgba(125, 39, 195, 0.25)'),
    );
  });

  it('resolves every task status with completion taking priority', () => {
    expect(resolveTaskCardStatus(false, false)).toBe('inactive');
    expect(resolveTaskCardStatus(true, false)).toBe('in-progress');
    expect(resolveTaskCardStatus(true, false, true)).toBe('past-due');
    expect(resolveTaskCardStatus(false, true)).toBe('done');
    expect(resolveTaskCardStatus(true, true, true)).toBe('done');
  });

  it.each([
    [{}, 'in-progress'],
    [{ active: false }, 'inactive'],
    [{ completed: true }, 'done'],
    [{ overdue: true }, 'past-due'],
  ] as const)('renders the %s state without ambient particles', (overrides, status) => {
    const markup = renderCard(overrides);

    expect(markup).toContain('data-task-status="' + status + '"');
    expect(markup).not.toContain('precision-task-card__status-particles');
    expect(componentStyles).not.toContain('precision-task-card-particle-shimmer');
  });

  it('keeps the past-due status label without particles', () => {
    expect(renderCard({ overdue: true })).toContain('Past due');
  });
  it.each([
    ['low', 1],
    ['medium', 2],
    ['high', 3],
  ] as const)('renders the %s energy configuration', (energy, filledMarks) => {
    const markup = renderCard({ energy });

    expect(markup).toContain(`${energy.toUpperCase()} energy, ${filledMarks} of 3 marks`);
    expect(markup.match(/data-filled="true"/g)).toHaveLength(filledMarks);
  });

  it('applies the Rare accent token', () => {
    const markup = renderCard();

    expect(markup).toContain('data-rarity="rare"');
    expect(markup).toContain('--card-accent:#4B8DFF');
  });

  it.each([
    ['common', '#8B949E'],
    ['rare', '#4B8DFF'],
    ['epic', '#D946EF'],
    ['legendary', '#FF8A2B'],
  ] as const)('applies the %s rarity across the card accent layers', (rarity, color) => {
    const markup = renderCard({ rarity });

    expect(markup).toContain('data-rarity="' + rarity + '"');
    expect(markup).toContain('--card-accent:' + color);
    expect(componentStyles).toContain('border-color: var(--card-accent)');
  });

  it.each(['common', 'rare', 'epic', 'legendary'] as const)(
    'renders the %s collectible rarity hardware for every theme',
    (rarity) => {
      const markup = renderCard({ borderTheme: 'celestial', rarity });

      expect(markup).toContain('data-rarity-adornment="' + rarity + '"');
      expect(markup).toContain('precision-task-card__rarity-foil');
      expect(markup).toContain('precision-task-card__rarity-crest');
      expect(markup.match(/precision-task-card__rarity-gems/g)).toHaveLength(1);
      expect(markup).toContain('precision-task-card__rarity-gems"><i></i><i></i><i></i><i></i>');
    },
  );

  it('progresses rarity from matte hardware to a forged animated crown', () => {
    expect(componentStyles).toContain("[data-rarity='common'] .precision-task-card__surface");
    expect(componentStyles).toContain(
      "[data-rarity='rare'] .precision-task-card__rarity-inner-frame",
    );
    expect(componentStyles).toContain("[data-rarity='epic'] .precision-task-card__rarity-foil");
    expect(componentStyles).toContain(
      "[data-rarity='legendary'] .precision-task-card__rarity-crest",
    );
    expect(componentStyles).toContain('precision-rarity-foil-pass');
    expect(componentStyles).toContain('precision-rarity-legendary-lustre');
  });

  it('supports explicit light and dark editorial surfaces', () => {
    expect(renderCard({ colorScheme: 'light' })).toContain('data-color-scheme="light"');
    expect(renderCard({ colorScheme: 'dark' })).toContain('data-color-scheme="dark"');
  });

  it('keeps Electric as the default border theme', () => {
    const markup = renderCard();

    expect(markup).toContain('data-border-theme="electric"');
    expect(markup).toContain('precision-task-card__filter-definitions');
  });

  it('composes the Arcane metal frame with an animated electric perimeter', () => {
    const markup = renderCard({ borderTheme: 'arcane' });

    expect(markup).toContain('data-border-theme="arcane"');
    expect(markup).toContain('precision-task-card__filter-definitions');
    expect(markup).toContain('precision-task-card__arcane-emblem');
  });

  it.each(['holographic', 'ember', 'blueprint'] as const)(
    'renders the %s experimental frame without status particles',
    (borderTheme) => {
      const markup = renderCard({ borderTheme });

      expect(markup).toContain('data-border-theme="' + borderTheme + '"');
      expect(markup).toContain('data-creative-theme="' + borderTheme + '"');
      expect(markup).toContain('precision-task-card__creative-frame');
      expect(markup).not.toContain('precision-task-card__status-particles');
    },
  );

  it.each(['celestial', 'void', 'aurora', 'living-ink'] as const)(
    'renders the collectible %s theme as a full creative frame',
    (borderTheme) => {
      const markup = renderCard({ borderTheme });

      expect(markup).toContain('data-border-theme="' + borderTheme + '"');
      expect(markup).toContain('data-creative-theme="' + borderTheme + '"');
      expect(markup).toContain('precision-task-card__creative-frame');
    },
  );

  it('exposes independent cosmetic layers for mix-and-match loadouts', () => {
    const markup = renderCard({
      borderTheme: 'electric',
      surfaceTheme: 'blueprint',
      completionTheme: 'ember',
      checkboxTheme: 'arcane',
    });

    expect(markup).toContain('data-surface-theme="blueprint"');
    expect(markup).toContain('data-completion-theme="ember"');
    expect(markup).toContain('data-checkbox-theme="arcane"');
    expect(markup).toContain('data-mixed-surface="true"');
    expect(markup).toContain('data-mixed-completion="true"');
    expect(markup).toContain('data-mixed-checkbox="true"');
    expect(componentStyles).toContain("[data-mixed-surface='true'][data-color-scheme='dark']");
  });
  it('keeps the checkbox and completed fill functional under reduced motion', () => {
    const markup = renderCard({ completed: true });

    expect(componentStyles).toContain('@media (prefers-reduced-motion: reduce)');
    expect(componentStyles).toContain(
      ".precision-task-card[data-completed='true'] .precision-task-card__completion-liquid",
    );
    expect(componentStyles).toContain('transform: translateY(0)');
    expect(markup).toContain('type="checkbox"');
  });

  it('keeps every card anchored while varying water-float timing and pointer depth', () => {
    const timing = resolveTaskCardFloatTiming('task-card-prototype');
    const repeatedTiming = resolveTaskCardFloatTiming('task-card-prototype');
    const markup = renderCard();

    expect(timing).toEqual(repeatedTiming);
    expect(timing.durationSeconds).toBeGreaterThanOrEqual(13);
    expect(timing.durationSeconds).toBeLessThan(17);
    expect(timing.delaySeconds).toBeGreaterThan(-8);
    expect(timing.delaySeconds).toBeLessThanOrEqual(0);
    expect(markup).toContain('precision-task-card__ambient-layer');
    expect(markup).toContain('precision-task-card__motion-layer');
    expect(markup).not.toContain('--card-follow-x');
    expect(componentStyles).toContain('precision-task-card-water-float');
    expect(componentStyles).toContain('animation-play-state: paused');
    expect(componentStyles).toContain('translateZ(8px)');
    expect(componentStyles).toContain('rotateX(-1.1deg) rotateY(0.7deg)');
    expect(componentStyles).not.toContain('precision-task-card-zero-gravity');
    expect(componentStyles).not.toContain('translate3d(-5px, 5px, 0)');
  });

  it('constrains long task titles without overflowing the card', () => {
    const longTitle =
      'Complete an exceptionally detailed cross-functional systems architecture review today';
    const markup = renderCard({ title: longTitle });

    expect(markup).toContain(longTitle);
    expect(componentStyles).toContain('overflow-wrap: anywhere');
    expect(componentStyles).toContain('-webkit-line-clamp: 4');
  });
});
