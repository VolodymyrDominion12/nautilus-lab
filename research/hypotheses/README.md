# hypotheses/ — артефакти пропозицій

Один виклик моделі = один JSON-файл. Ім'я детерміноване:
`<as-of>-<model>-<sha256 промпту[0..8]>.json`, а повторний виклик з тими самими
входом і моделлю отримує суфікс `-r2`, `-r3`, щоб попередній прогін не зникав.

Файли генерує `scripts/propose_alphas.py`. Руками тут нічого створювати не треба,
крім правки блоку `review`.

## Схема

```jsonc
{
  "version": 1,
  "created_at": "2026-09-15T10:00:00+00:00",
  "model": "deepseek-chat",
  "endpoint_host": "api.deepseek.com",   // хост, без ключів
  "as_of": "2026-09-15",                 // дата відсічення, вказана моделі
  "prompt_file": "research/prompts/01-generate-alphas.md",
  "prompt_sha256": "…",                  // який саме промпт дав цей результат
  "feature_contract": ["ret", "ret_5", "…"],  // 12 ознак FormulaicAlphaEngine
  "count_requested": 5,
  "count_parsed": 5,
  "count_flagged": 1,                    // скількох посилаються на невідомі імена
  "hypotheses": [
    {
      "name": "volume-climax reversal",
      "formula": "-reversal_3 * zscore(volume_ratio)",
      "mechanism": "сплеск обсягу без продовження руху = виснаження агресора",
      "horizon_bars": 5,
      "expected_sign": -1,
      "kill_condition": "IC на OOS < 0 у двох сусідніх фолдах",
      "unknown_identifiers": []
    }
  ],
  "raw_response": "…повна відповідь моделі, для аудиту…",
  "review": {
    "status": "pending",                 // pending | accepted | rejected
    "note": "",
    "gates": { "purged_cv": null, "walk_forward_oos": null, "buy_and_hold_oos": null }
  }
}
```

## Правила рев'ю

| Сигнал в артефакті | Що робити |
|---|---|
| `unknown_identifiers` не порожній | майже завжди вигадана фіча → відкинути або переписати формулу на наявні 12 ознак |
| немає економічного механізму | відкинути: без механізму це підгонка |
| `count_parsed` < `count_requested` | модель не дотримала формату → дивитись `raw_response` |
| `empty` / помилка парсингу | скрипт не створив файл узагалі — це fail closed, а не «нуль гіпотез» |

Заповнений `review` — це і є слід дослідження. Без нього через місяць ти
перевідкриєш ту саму відкинуту ідею.
