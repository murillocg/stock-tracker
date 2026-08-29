import type { LynchCategory, Signal } from './api'

/** Wording shown to a human. The enum values themselves stay untranslated. */
export const SIGNAL_LABEL: Record<Signal, string> = {
  GREEN: 'Meets its category',
  YELLOW: 'Worth a look',
  RED: 'Flagged',
  NEEDS_REVIEW: 'Your call',
  INSUFFICIENT_DATA: 'Not enough data',
  NOT_APPLICABLE: 'Not applicable',
}

export const CATEGORY_LABEL: Record<LynchCategory, string> = {
  FAST_GROWER: 'Fast grower',
  STALWART: 'Stalwart',
  SLOW_GROWER: 'Slow grower',
  CYCLICAL: 'Cyclical',
  TURNAROUND: 'Turnaround',
  ASSET_PLAY: 'Asset play',
}

/** What each category is actually judged on — the reason the label matters. */
export const CATEGORY_BASIS: Record<LynchCategory, string> = {
  FAST_GROWER: 'Judged on PEG and earnings growth.',
  STALWART: 'Judged on P/E, ROE and leverage.',
  SLOW_GROWER: 'Judged on dividend yield and payout ratio.',
  CYCLICAL: 'Judged on P/B — P/E misleads across a cycle. Flagged, never decided.',
  TURNAROUND: 'Judged on debt and margins. Flagged, never decided.',
  ASSET_PLAY: 'Judged on P/B against real assets.',
}
