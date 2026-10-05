export type SupportedModel = 'formulaic' | 'meta_label' | 'obi';

export interface ModelDefinition {
  id: SupportedModel;
  name: string;
  badge: string;
  desc: string;
  robot: string;
  envVar: string;
}

export const MODEL_DEFINITIONS: ModelDefinition[] = [
  {
    id: 'formulaic',
    name: 'Formulaic LGBM',
    badge: 'Alpha Factors',
    desc: 'LightGBM model trained on formulaic feature alphas (101-style returns, volatility, moving averages).',
    robot: 'formulaic_lgbm',
    envVar: 'FORMULAIC_MODEL_PATH',
  },
  {
    id: 'meta_label',
    name: 'Meta-label (Triple Barrier)',
    badge: 'TBM De Prado',
    desc: 'Secondary ML filter predicting whether primary signal achieves profit barrier before stop barrier.',
    robot: 'meta_label',
    envVar: 'META_LABEL_MODEL_PATH',
  },
  {
    id: 'obi',
    name: 'Order Book Imbalance (OBI)',
    badge: 'L2 Depth',
    desc: 'High-frequency classifier trained on order book depth imbalances (requires ingested depth data).',
    robot: 'ml_obi',
    envVar: 'ML_OBI_MODEL_PATH',
  },
];
