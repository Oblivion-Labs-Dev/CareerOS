/* eslint-disable no-undef -- Browser globals are provided by the TypeScript DOM library. */

'use client';

import { type CSSProperties, type ChangeEvent, type PointerEvent, useId } from 'react';
import { cn } from './lib/cn';

export type TaskEnergy = 'low' | 'medium' | 'high';
export type TaskRarity = 'common' | 'rare' | 'epic' | 'legendary';
export type TaskCardColorScheme = 'light' | 'dark';
export type TaskCardBorderTheme =
  | 'standard'
  | 'electric'
  | 'arcane'
  | 'holographic'
  | 'ember'
  | 'blueprint'
  | 'celestial'
  | 'void'
  | 'aurora'
  | 'alchemist'
  | 'runic'
  | 'samurai'
  | 'cyberpunk'
  | 'solarpunk'
  | 'frost'
  | 'oceanic'
  | 'storm'
  | 'mechanical'
  | 'dragon-scale'
  | 'stained-glass'
  | 'origami'
  | 'retro-arcade'
  | 'synthwave'
  | 'bioluminescent'
  | 'minimal-luxury'
  | 'living-ink';
export type TaskCardStatus = 'inactive' | 'in-progress' | 'past-due' | 'done';

export interface PrecisionTaskCardProps {
  id: string;
  title: string;
  completed: boolean;
  active?: boolean;
  overdue?: boolean;
  energy: TaskEnergy;
  rarity: TaskRarity;
  onCompletedChange: (completed: boolean) => void;
  colorScheme?: TaskCardColorScheme;
  borderTheme?: TaskCardBorderTheme;
  surfaceTheme?: TaskCardBorderTheme;
  completionTheme?: TaskCardBorderTheme;
  checkboxTheme?: TaskCardBorderTheme;
  className?: string;
}

export const rarityColors: Record<TaskRarity, string> = {
  common: '#8B949E',
  rare: '#4B8DFF',
  epic: '#D946EF',
  legendary: '#FF8A2B',
};

const energyColors: Record<TaskEnergy, string> = {
  low: '#43A68B',
  medium: '#D79A3B',
  high: '#E56855',
};

const filledEnergyMarks: Record<TaskEnergy, number> = {
  low: 1,
  medium: 2,
  high: 3,
};

const themeEyebrowLabels: Record<TaskCardBorderTheme, string> = {
  standard: 'Today',
  electric: 'Today',
  arcane: 'Active task',
  holographic: 'Prism task',
  ember: 'Forge task',
  blueprint: 'System task',
  celestial: 'Star task',
  void: 'Focus event',
  aurora: 'Polar task',
  alchemist: 'Formula task',
  runic: 'Carved task',
  samurai: 'Discipline',
  cyberpunk: 'Data task',
  solarpunk: 'Growth task',
  frost: 'Clear task',
  oceanic: 'Current task',
  storm: 'Storm task',
  mechanical: 'System task',
  'dragon-scale': 'Mythic task',
  'stained-glass': 'Luminous task',
  origami: 'Folded task',
  'retro-arcade': 'Next stage',
  synthwave: 'Night drive',
  bioluminescent: 'Living task',
  'minimal-luxury': 'Priority',
  'living-ink': 'Written task',
};
export function resolveTaskCardStatus(
  active: boolean,
  completed: boolean,
  overdue = false,
): TaskCardStatus {
  if (completed) return 'done';
  if (overdue) return 'past-due';
  return active ? 'in-progress' : 'inactive';
}

export function notifyCompletedChange(
  completed: boolean,
  onCompletedChange: (completed: boolean) => void,
) {
  onCompletedChange(completed);
}

interface PrecisionCardStyle extends CSSProperties {
  '--card-accent': string;
  '--energy-color': string;
  '--card-pointer-x': string;
  '--card-pointer-y': string;
  '--card-tilt-x': string;
  '--card-tilt-y': string;
  '--card-float-delay': string;
  '--card-float-duration': string;
}

export interface TaskCardFloatTiming {
  delaySeconds: number;
  durationSeconds: number;
}

export function resolveTaskCardFloatTiming(id: string): TaskCardFloatTiming {
  let hash = 2166136261;

  for (let index = 0; index < id.length; index += 1) {
    hash = Math.imul(hash ^ id.charCodeAt(index), 16777619) >>> 0;
  }

  return {
    delaySeconds: -((hash % 8000) / 1000),
    durationSeconds: 13 + ((hash >>> 8) % 4000) / 1000,
  };
}

function ElectricBorder({ filterId }: { filterId: string }) {
  return (
    <>
      <svg className="precision-task-card__filter-definitions" aria-hidden="true" focusable="false">
        <defs>
          <filter
            id={filterId}
            x="-30%"
            y="-22%"
            width="160%"
            height="144%"
            colorInterpolationFilters="sRGB"
          >
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.018 0.085"
              numOctaves="5"
              seed="7"
              stitchTiles="stitch"
              result="electric-noise"
            />
            <feOffset in="electric-noise" dx="0" dy="0" result="vertical-forward">
              <animate
                className="precision-task-card__noise-animation"
                attributeName="dy"
                values="-256;256"
                dur="7s"
                repeatCount="indefinite"
              />
            </feOffset>
            <feOffset in="electric-noise" dx="0" dy="0" result="vertical-reverse">
              <animate
                className="precision-task-card__noise-animation"
                attributeName="dy"
                values="256;-256"
                dur="7s"
                repeatCount="indefinite"
              />
            </feOffset>
            <feOffset in="electric-noise" dx="0" dy="0" result="horizontal-forward">
              <animate
                className="precision-task-card__noise-animation"
                attributeName="dx"
                values="-256;256"
                dur="7.6s"
                repeatCount="indefinite"
              />
            </feOffset>
            <feOffset in="electric-noise" dx="0" dy="0" result="horizontal-reverse">
              <animate
                className="precision-task-card__noise-animation"
                attributeName="dx"
                values="256;-256"
                dur="7.6s"
                repeatCount="indefinite"
              />
            </feOffset>
            <feBlend
              in="vertical-forward"
              in2="vertical-reverse"
              mode="color-dodge"
              result="vertical-flow"
            />
            <feBlend
              in="horizontal-forward"
              in2="horizontal-reverse"
              mode="color-dodge"
              result="horizontal-flow"
            />
            <feComposite
              in="vertical-flow"
              in2="horizontal-flow"
              operator="arithmetic"
              k1="0.65"
              k2="0.35"
              k3="0.35"
              k4="0"
              result="circulating-noise"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="circulating-noise"
              scale="18"
              xChannelSelector="R"
              yChannelSelector="B"
            />
          </filter>
        </defs>
      </svg>

      <span className="precision-task-card__aura" aria-hidden="true" />
      <span
        className="precision-task-card__electric-outline precision-task-card__electric-outline--glow-wide"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__electric-outline precision-task-card__electric-outline--glow-tight"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__electric-outline precision-task-card__electric-outline--displaced"
        style={{ filter: `url(#${filterId})` }}
        aria-hidden="true"
      />
      <span
        className="precision-task-card__electric-outline precision-task-card__electric-outline--sharp"
        aria-hidden="true"
      />
    </>
  );
}

function ArcaneFrame() {
  return (
    <>
      <span className="precision-task-card__arcane-aura" aria-hidden="true" />
      <span
        className="precision-task-card__arcane-frame precision-task-card__arcane-frame--outer"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-frame precision-task-card__arcane-frame--inner"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-rail precision-task-card__arcane-rail--top"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-rail precision-task-card__arcane-rail--bottom"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-corner precision-task-card__arcane-corner--top-left"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-corner precision-task-card__arcane-corner--top-right"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-corner precision-task-card__arcane-corner--bottom-left"
        aria-hidden="true"
      />
      <span
        className="precision-task-card__arcane-corner precision-task-card__arcane-corner--bottom-right"
        aria-hidden="true"
      />

      <span className="precision-task-card__arcane-emblem" aria-hidden="true">
        <svg viewBox="0 0 100 112" fill="none">
          <polygon points="50,2 91,27 91,76 50,108 9,76 9,27" className="arcane-emblem__plate" />
          <polygon points="50,13 80,31 80,70 50,94 20,70 20,31" className="arcane-emblem__rim" />
          <polygon points="50,22 72,36 72,65 50,83 28,65 28,36" className="arcane-emblem__gem" />
          <path
            d="M50 22v61M28 36l44 29M72 36 28 65M28 36l22 47 22-47"
            className="arcane-emblem__facet"
          />
          <circle cx="50" cy="50" r="6" className="arcane-emblem__core" />
        </svg>
      </span>

      <span className="precision-task-card__arcane-seal" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </>
  );
}

type CreativeBorderTheme = Exclude<TaskCardBorderTheme, 'electric' | 'arcane'>;

function CreativeFrame({ theme }: { theme: CreativeBorderTheme }) {
  return (
    <span
      className="precision-task-card__creative-frame"
      data-creative-theme={theme}
      aria-hidden="true"
    >
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

function RarityAdornment({ rarity }: { rarity: TaskRarity }) {
  return (
    <span
      className="precision-task-card__rarity-adornment"
      data-rarity-adornment={rarity}
      aria-hidden="true"
    >
      <span className="precision-task-card__rarity-foil" />
      <span className="precision-task-card__rarity-inner-frame" />
      <span className="precision-task-card__rarity-crest">
        <svg viewBox="0 0 48 32" fill="none" focusable="false">
          <path className="rarity-crest__crown" d="M5 24 8 8l10 8 6-13 6 13 10-8 3 16Z" />
          <path className="rarity-crest__facet" d="m12 22 12-15 12 15-12 6Z" />
          <circle className="rarity-crest__core" cx="24" cy="18" r="3.4" />
        </svg>
      </span>
      <span className="precision-task-card__rarity-gems">
        {Array.from({ length: 4 }, (_, index) => (
          <i key={index} />
        ))}
      </span>
      <span className="precision-task-card__rarity-label">{rarity}</span>
    </span>
  );
}
function ArcaneCircuitDiagram() {
  return (
    <svg
      className="precision-task-card__arcane-circuit"
      viewBox="0 0 300 190"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <g className="arcane-circuit__lines">
        <path d="M16 95h38c16 0 19-22 37-22h23" />
        <path d="M16 95h38c16 0 19 22 37 22h23" />
        <path d="M186 72h28c18 0 18-28 36-28h34" />
        <path d="M186 112h32c19 0 18 31 36 31h30" />
        <path d="M150 27v34M150 129v38" />
        <path d="M87 37h18c17 0 18 25 33 25" />
        <path d="M75 154h31c19 0 20-25 34-25" />
        <path d="M214 72v40M252 44v30M252 112v31" />
      </g>
      <g className="arcane-circuit__nodes">
        <circle cx="150" cy="95" r="36" />
        <circle cx="150" cy="95" r="24" />
        <circle cx="150" cy="95" r="9" />
        <rect x="27" y="77" width="30" height="36" rx="7" />
        <rect x="252" y="74" width="32" height="38" rx="6" />
        <rect x="251" y="134" width="34" height="24" rx="5" />
        <circle cx="87" cy="37" r="7" />
        <circle cx="75" cy="154" r="7" />
        <circle cx="252" cy="44" r="12" />
        <circle cx="214" cy="72" r="4" />
        <circle cx="214" cy="112" r="4" />
        <circle cx="150" cy="27" r="4" />
        <circle cx="150" cy="167" r="4" />
      </g>
    </svg>
  );
}
function CompleteCheckbox({
  title,
  completed,
  onChange,
}: {
  title: string;
  completed: boolean;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label
      className="precision-task-card__checkbox-target"
      onClick={(event) => event.stopPropagation()}
    >
      <input
        className="precision-task-card__checkbox-input"
        type="checkbox"
        checked={completed}
        onChange={onChange}
        onClick={(event) => event.stopPropagation()}
        aria-label={`Mark "${title}" complete`}
      />
      <span className="precision-task-card__checkbox-box" aria-hidden="true" />
    </label>
  );
}

function EnergyIndicator({ level }: { level: TaskEnergy }) {
  const filledMarks = filledEnergyMarks[level];
  const visibleLevel = level.toUpperCase();

  return (
    <span
      className="precision-task-card__energy-indicator"
      aria-label={`${visibleLevel} energy, ${filledMarks} of 3 marks`}
    >
      <span className="precision-task-card__energy-value">{visibleLevel}</span>
      <span className="precision-task-card__energy-marks" aria-hidden="true">
        {[0, 1, 2].map((mark) => {
          const filled = mark < filledMarks;
          return (
            <span
              className="precision-task-card__energy-mark"
              data-filled={filled ? 'true' : 'false'}
              key={mark}
            />
          );
        })}
      </span>
    </span>
  );
}

export function PrecisionTaskCard({
  id,
  title,
  completed,
  energy,
  active = true,
  overdue = false,
  rarity,
  onCompletedChange,
  colorScheme = 'dark',
  borderTheme = 'electric',
  surfaceTheme,
  completionTheme,
  checkboxTheme,
  className,
}: PrecisionTaskCardProps) {
  const reactId = useId();
  const filterId = `precision-task-card-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const titleId = `${id}-title`;
  const taskStatus = resolveTaskCardStatus(active, completed, overdue);
  const eyebrowLabel =
    taskStatus === 'done'
      ? 'Task complete'
      : taskStatus === 'past-due'
        ? 'Past due'
        : taskStatus === 'inactive'
          ? 'Inactive task'
          : themeEyebrowLabels[borderTheme];
  const floatTiming = resolveTaskCardFloatTiming(id);
  const style: PrecisionCardStyle = {
    '--card-accent': rarityColors[rarity],
    '--energy-color': energyColors[energy],
    '--card-pointer-x': '50%',
    '--card-pointer-y': '30%',
    '--card-tilt-x': '0deg',
    '--card-tilt-y': '0deg',
    '--card-float-delay': `${floatTiming.delaySeconds}s`,
    '--card-float-duration': `${floatTiming.durationSeconds}s`,
  };

  const resetPointerLighting = (element: HTMLElement) => {
    element.style.setProperty('--card-pointer-x', '50%');
    element.style.setProperty('--card-pointer-y', '30%');
    element.style.setProperty('--card-tilt-x', '0deg');
    element.style.setProperty('--card-tilt-y', '0deg');
  };

  const handlePointerMove = (event: PointerEvent<HTMLElement>) => {
    if (
      event.pointerType === 'touch' ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return;
    }

    const card = event.currentTarget;
    const bounds = card.getBoundingClientRect();
    const normalizedX = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    const normalizedY = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height));

    card.style.setProperty('--card-pointer-x', `${normalizedX * 100}%`);
    card.style.setProperty('--card-pointer-y', `${normalizedY * 100}%`);
    card.style.setProperty('--card-tilt-x', `${(0.5 - normalizedY) * 6}deg`);
    card.style.setProperty('--card-tilt-y', `${(normalizedX - 0.5) * 6}deg`);
  };

  return (
    <article
      className={cn('precision-task-card', className)}
      data-completed={completed ? 'true' : 'false'}
      data-task-status={taskStatus}
      data-rarity={rarity}
      data-color-scheme={colorScheme}
      data-border-theme={borderTheme}
      data-surface-theme={surfaceTheme ?? borderTheme}
      data-completion-theme={completionTheme ?? borderTheme}
      data-checkbox-theme={checkboxTheme ?? borderTheme}
      data-mixed-surface={surfaceTheme && surfaceTheme !== borderTheme ? 'true' : 'false'}
      data-mixed-completion={completionTheme && completionTheme !== borderTheme ? 'true' : 'false'}
      data-mixed-checkbox={checkboxTheme && checkboxTheme !== borderTheme ? 'true' : 'false'}
      aria-labelledby={titleId}
      onPointerMove={handlePointerMove}
      onPointerLeave={(event) => resetPointerLighting(event.currentTarget)}
      style={style}
    >
      <div className="precision-task-card__ambient-layer">
        <div className="precision-task-card__motion-layer">
          <ElectricBorder filterId={filterId} />
          {borderTheme === 'arcane' ? (
            <ArcaneFrame />
          ) : borderTheme !== 'electric' ? (
            <CreativeFrame theme={borderTheme} />
          ) : null}
          <RarityAdornment rarity={rarity} />

          <div className="precision-task-card__surface">
            <span className="precision-task-card__completion-liquid" aria-hidden="true">
              {[0, 1, 2, 3, 4, 5, 6].map((bubble) => (
                <i className="precision-task-card__liquid-bubble" key={bubble} />
              ))}
            </span>
            <header className="precision-task-card__header">
              <span className="precision-task-card__eyebrow" aria-hidden="true">
                {eyebrowLabel}
              </span>

              <CompleteCheckbox
                title={title}
                completed={completed}
                onChange={(event) =>
                  notifyCompletedChange(event.currentTarget.checked, onCompletedChange)
                }
              />
            </header>

            <div className="precision-task-card__body">
              <h2 className="precision-task-card__title" id={titleId}>
                {title}
              </h2>
            </div>

            {borderTheme === 'arcane' || borderTheme === 'blueprint' ? (
              <ArcaneCircuitDiagram />
            ) : null}

            <footer className="precision-task-card__footer">
              <span className="precision-task-card__energy-label">Energy</span>
              <EnergyIndicator level={energy} />
            </footer>
          </div>
        </div>
      </div>
    </article>
  );
}
