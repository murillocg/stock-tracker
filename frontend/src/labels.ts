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
